package agent

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"regexp"
	"time"

	batchv1 "k8s.io/api/batch/v1"
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/resource"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/kubernetes"
	"k8s.io/client-go/rest"
)

// KubeRunner creates one ephemeral analysis Job per run in the agent's own
// namespace. The Role bound to the agent only allows ConfigMaps, Jobs and
// reading Pod logs there; it cannot reach other organizations' namespaces.
type KubeRunner struct {
	Client    kubernetes.Interface
	Namespace string
	Image     string
	Timeout   time.Duration
}

func NewKubeRunner(namespace, image string) (*KubeRunner, error) {
	config, err := rest.InClusterConfig()
	if err != nil {
		return nil, err
	}
	client, err := kubernetes.NewForConfig(config)
	if err != nil {
		return nil, err
	}
	return &KubeRunner{Client: client, Namespace: namespace, Image: image, Timeout: 3 * time.Minute}, nil
}

var digestPattern = regexp.MustCompile(`sha256:[0-9a-f]{64}`)

// analyzerUID is used by no other workload. RLIMIT_NPROC (ulimit -u) counts all
// processes of a UID on the node, so a UID shared with other pods (10001 is used
// by the training services) would exhaust the limit before Semgrep starts.
const analyzerUID = int64(20001)

func pointer[T any](value T) *T { return &value }

// job mirrors deploy/kubernetes/sast-job.yaml.template, plus a per-UID process
// limit (ulimit -u) because Kubernetes has no per-container pids-limit field.
func (r *KubeRunner) job(name, configMap string) *batchv1.Job {
	labels := map[string]string{"app": "horus-sast", "horus-ledger/analysis": name}
	return &batchv1.Job{
		ObjectMeta: metav1.ObjectMeta{Name: name, Namespace: r.Namespace, Labels: labels},
		Spec: batchv1.JobSpec{
			BackoffLimit: pointer(int32(0)), ActiveDeadlineSeconds: pointer(int64(150)),
			TTLSecondsAfterFinished: pointer(int32(300)),
			Template: corev1.PodTemplateSpec{
				ObjectMeta: metav1.ObjectMeta{Labels: labels},
				Spec: corev1.PodSpec{
					AutomountServiceAccountToken: pointer(false), EnableServiceLinks: pointer(false),
					RestartPolicy: corev1.RestartPolicyNever,
					SecurityContext: &corev1.PodSecurityContext{
						RunAsNonRoot: pointer(true), RunAsUser: pointer(analyzerUID), RunAsGroup: pointer(analyzerUID),
						FSGroup: pointer(analyzerUID), SeccompProfile: &corev1.SeccompProfile{Type: corev1.SeccompProfileTypeRuntimeDefault},
					},
					Containers: []corev1.Container{{
						Name: "analyzer", Image: r.Image, ImagePullPolicy: corev1.PullNever,
						Command: []string{"/bin/sh", "-c"},
						Args:    []string{"ulimit -u 128 && exec python3 -I /opt/horus/sast/analyze.py < /input/submission.py"},
						SecurityContext: &corev1.SecurityContext{
							Privileged: pointer(false), AllowPrivilegeEscalation: pointer(false),
							ReadOnlyRootFilesystem: pointer(true),
							Capabilities:           &corev1.Capabilities{Drop: []corev1.Capability{"ALL"}},
						},
						Resources: corev1.ResourceRequirements{
							Requests: corev1.ResourceList{corev1.ResourceCPU: resource.MustParse("100m"), corev1.ResourceMemory: resource.MustParse("256Mi")},
							Limits:   corev1.ResourceList{corev1.ResourceCPU: resource.MustParse("1"), corev1.ResourceMemory: resource.MustParse("768Mi")},
						},
						VolumeMounts: []corev1.VolumeMount{{Name: "input", MountPath: "/input", ReadOnly: true},
							{Name: "temporary", MountPath: "/tmp"}},
					}},
					Volumes: []corev1.Volume{
						{Name: "input", VolumeSource: corev1.VolumeSource{ConfigMap: &corev1.ConfigMapVolumeSource{
							LocalObjectReference: corev1.LocalObjectReference{Name: configMap}, DefaultMode: pointer(int32(0o444))}}},
						{Name: "temporary", VolumeSource: corev1.VolumeSource{EmptyDir: &corev1.EmptyDirVolumeSource{
							Medium: corev1.StorageMediumMemory, SizeLimit: pointer(resource.MustParse("128Mi"))}}},
					},
				},
			},
		},
	}
}

func (r *KubeRunner) Run(ctx context.Context, codeHash string, code []byte) ([]byte, string, error) {
	suffix := make([]byte, 3)
	if _, err := rand.Read(suffix); err != nil {
		return nil, "", err
	}
	name := fmt.Sprintf("horus-sast-%s-%s", codeHash[:12], hex.EncodeToString(suffix))
	labels := map[string]string{"app": "horus-sast-input", "horus-ledger/analysis": name}
	configMaps, jobs := r.Client.CoreV1().ConfigMaps(r.Namespace), r.Client.BatchV1().Jobs(r.Namespace)
	cleanup := func() {
		background := metav1.DeletePropagationBackground
		_ = jobs.Delete(context.Background(), name, metav1.DeleteOptions{PropagationPolicy: &background})
		_ = configMaps.Delete(context.Background(), name, metav1.DeleteOptions{})
	}
	defer cleanup()
	if _, err := configMaps.Create(ctx, &corev1.ConfigMap{ObjectMeta: metav1.ObjectMeta{Name: name, Labels: labels},
		Data: map[string]string{"submission.py": string(code)}}, metav1.CreateOptions{}); err != nil {
		return nil, "", fmt.Errorf("create input: %w", err)
	}
	if _, err := jobs.Create(ctx, r.job(name, name), metav1.CreateOptions{}); err != nil {
		return nil, "", fmt.Errorf("create job: %w", err)
	}
	deadline := time.Now().Add(r.Timeout)
	for {
		job, err := jobs.Get(ctx, name, metav1.GetOptions{})
		if err == nil && (job.Status.Succeeded > 0 || job.Status.Failed > 0) {
			break
		}
		if time.Now().After(deadline) {
			return nil, "", errors.New("analysis job did not finish in time")
		}
		select {
		case <-ctx.Done():
			return nil, "", ctx.Err()
		case <-time.After(time.Second):
		}
	}
	pods, err := r.Client.CoreV1().Pods(r.Namespace).List(ctx, metav1.ListOptions{LabelSelector: "job-name=" + name})
	if err != nil || len(pods.Items) != 1 {
		return nil, "", errors.New("analysis pod not found")
	}
	pod := pods.Items[0]
	if len(pod.Status.ContainerStatuses) != 1 || pod.Status.ContainerStatuses[0].State.Terminated == nil {
		return nil, "", errors.New("analysis container did not terminate normally")
	}
	digest := digestPattern.FindString(pod.Status.ContainerStatuses[0].ImageID)
	stream, err := r.Client.CoreV1().Pods(r.Namespace).GetLogs(pod.Name, &corev1.PodLogOptions{Container: "analyzer"}).Stream(ctx)
	if err != nil {
		return nil, "", fmt.Errorf("read analyzer output: %w", err)
	}
	defer stream.Close()
	output, err := io.ReadAll(io.LimitReader(stream, 4<<20))
	return output, digest, err
}
