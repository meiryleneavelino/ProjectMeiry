package main

import (
	"context"
	"crypto/hmac"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"net/http"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"sync"
	"time"

	pb "github.com/Jorrit05/DYNAMOS/pkg/proto"
	"github.com/Jorrit05/DYNAMOS/pkg/training"
	"github.com/google/uuid"
	clientv3 "go.etcd.io/etcd/client/v3"
	batchv1 "k8s.io/api/batch/v1"
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/resource"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
)

var trainingStateMutex sync.Mutex

func maintainTrainingRegistration() {
	var leaseID clientv3.LeaseID
	ticker := time.NewTicker(5 * time.Second)
	defer ticker.Stop()
	for {
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		if leaseID != 0 {
			if _, err := etcdClient.KeepAliveOnce(ctx, leaseID); err != nil {
				leaseID = 0
			}
		}
		if leaseID == 0 {
			if lease, err := etcdClient.Grant(ctx, 20); err == nil {
				leaseID = lease.ID
			}
		}
		if leaseID != 0 {
			encoded, _ := json.Marshal(agentConfig)
			if _, err := etcdClient.Put(ctx, "/agents/online/"+serviceName, string(encoded), clientv3.WithLease(leaseID)); err != nil {
				logger.Sugar().Warnw("Training agent registration failed; retrying", "organization", serviceName)
			}
		}
		cancel()
		<-ticker.C
	}
}

type trainingRound struct {
	RunID         string                 `json:"run_id"`
	RoundNumber   int                    `json:"round_number"`
	LocalEpochs   int                    `json:"local_epochs"`
	Model         map[string]interface{} `json:"model"`
	Authorization string                 `json:"authorization"`
}

type localModelUpdate struct {
	Coefficients   []float64 `json:"coefficients"`
	Intercept      float64   `json:"intercept"`
	Samples        int       `json:"samples"`
	Accuracy       float64   `json:"accuracy"`
	ValidationLoss float64   `json:"validation_loss"`
}

type trainingRoundState struct {
	Status string            `json:"status"`
	Token  string            `json:"token,omitempty"`
	Update *localModelUpdate `json:"update,omitempty"`
}

func trainingStatePath(name string) string {
	return filepath.Join("/state", "rounds", name+".json")
}

func writeTrainingState(name string, state trainingRoundState) error {
	path := trainingStatePath(name)
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		return err
	}
	encoded, _ := json.Marshal(state)
	if err := os.WriteFile(path+".tmp", encoded, 0600); err != nil {
		return err
	}
	return os.Rename(path+".tmp", path)
}

func validTrainingRoundName(name string) bool {
	parts := strings.Split(name, "-")
	if len(parts) != 3 || parts[0] != "training" || len(parts[1]) != 16 || len(parts[2]) < 2 {
		return false
	}
	for _, character := range parts[1] {
		if !strings.ContainsRune("0123456789abcdef", character) {
			return false
		}
	}
	return slices.Contains([]string{"r1", "r2", "r3", "r4", "r5", "r6", "r7", "r8", "r9", "r10"}, parts[2])
}

func validateLocalUpdate(update localModelUpdate) error {
	if len(update.Coefficients) != 4 || update.Samples < 1 || update.Samples > 10000 ||
		update.Accuracy < 0 || update.Accuracy > 1 || update.ValidationLoss < 0 || update.ValidationLoss > 100 {
		return errors.New("invalid local model update")
	}
	for _, value := range append(append([]float64{}, update.Coefficients...), update.Intercept, update.Accuracy, update.ValidationLoss) {
		if math.IsNaN(value) || math.IsInf(value, 0) || math.Abs(value) > 1000000 {
			return errors.New("invalid local model value")
		}
	}
	return nil
}

func handleTrainingResult(message *pb.MicroserviceCommunication) error {
	name := message.Metadata["round_name"]
	if !validTrainingRoundName(name) || message.Data == nil {
		return errors.New("invalid training result")
	}
	trainingStateMutex.Lock()
	defer trainingStateMutex.Unlock()
	var state trainingRoundState
	encoded, err := os.ReadFile(trainingStatePath(name))
	if err != nil || json.Unmarshal(encoded, &state) != nil || state.Status != "pending" ||
		!hmac.Equal([]byte(state.Token), []byte(message.Metadata["result_token"])) {
		return errors.New("unknown or consumed training result capability")
	}
	encoded, _ = json.Marshal(message.Data.AsMap())
	var update localModelUpdate
	decoder := json.NewDecoder(strings.NewReader(string(encoded)))
	decoder.DisallowUnknownFields()
	if decoder.Decode(&update) != nil || validateLocalUpdate(update) != nil {
		return errors.New("invalid training result fields")
	}
	logger.Sugar().Infow("Training result received through DYNAMOS sidecar", "organization", serviceName, "round", name)
	return writeTrainingState(name, trainingRoundState{Status: "completed", Update: &update})
}

func createLocalTrainingJob(ctx context.Context, request trainingRound, name, token string) error {
	namespace := strings.ToLower(serviceName)
	if clientSet == nil {
		clientSet = getKubeClient()
	}
	input, _ := json.Marshal(map[string]interface{}{
		"run_id": request.RunID, "round_number": request.RoundNumber, "local_epochs": request.LocalEpochs,
		"model": request.Model, "name": name, "callback_token": token,
	})
	configMap, err := clientSet.CoreV1().ConfigMaps(namespace).Create(ctx, &corev1.ConfigMap{
		ObjectMeta: metav1.ObjectMeta{Name: name, Labels: map[string]string{"app": "federated-training"}},
		Data:       map[string]string{"request.json": string(input)},
	}, metav1.CreateOptions{})
	if err != nil {
		return err
	}
	falseValue, trueValue := false, true
	userID := int64(10001)
	deadline, cleanup, retries := int64(180), int32(600), int32(0)
	security := &corev1.SecurityContext{AllowPrivilegeEscalation: &falseValue, ReadOnlyRootFilesystem: &trueValue,
		Capabilities: &corev1.Capabilities{Drop: []corev1.Capability{"ALL"}}}
	job := &batchv1.Job{ObjectMeta: metav1.ObjectMeta{Name: name, Labels: map[string]string{"app": "federated-training", "role": "worker"}},
		Spec: batchv1.JobSpec{BackoffLimit: &retries, ActiveDeadlineSeconds: &deadline, TTLSecondsAfterFinished: &cleanup,
			Template: corev1.PodTemplateSpec{ObjectMeta: metav1.ObjectMeta{
				Labels:      map[string]string{"app": "federated-training", "role": "worker"},
				Annotations: map[string]string{"linkerd.io/inject": "disabled"}},
				Spec: corev1.PodSpec{RestartPolicy: corev1.RestartPolicyNever, AutomountServiceAccountToken: &falseValue,
					SecurityContext: &corev1.PodSecurityContext{RunAsNonRoot: &trueValue, RunAsUser: &userID, FSGroup: &userID,
						SeccompProfile: &corev1.SeccompProfile{Type: corev1.SeccompProfileTypeRuntimeDefault}},
					Containers: []corev1.Container{
						{Name: "trainer", Image: os.Getenv("TRAINER_IMAGE"), ImagePullPolicy: corev1.PullIfNotPresent,
							Args: []string{"trainer"}, SecurityContext: security,
							Env: []corev1.EnvVar{{Name: "ORGANIZATION", Value: serviceName}, {Name: "DYNAMOS_INTEGRATED", Value: "true"}},
							Resources: corev1.ResourceRequirements{Requests: corev1.ResourceList{corev1.ResourceCPU: resource.MustParse("100m"), corev1.ResourceMemory: resource.MustParse("128Mi")},
								Limits: corev1.ResourceList{corev1.ResourceCPU: resource.MustParse("500m"), corev1.ResourceMemory: resource.MustParse("512Mi")}},
							VolumeMounts: []corev1.VolumeMount{{Name: "dataset", MountPath: "/data", ReadOnly: true},
								{Name: "input", MountPath: "/input", ReadOnly: true}, {Name: "temporary", MountPath: "/tmp"}}},
						{Name: "sidecar", Image: os.Getenv("TRAINING_SIDECAR_IMAGE"), ImagePullPolicy: corev1.PullIfNotPresent,
							Command: []string{"/app/sidecar"}, SecurityContext: security,
							Env: []corev1.EnvVar{{Name: "TEMPORARY_JOB", Value: "true"}, {Name: "AMQ_USER", Value: "normal_user"},
								{Name: "OC_AGENT_HOST", Value: "collector.core.svc.cluster.local:55678"},
								{Name: "AMQ_PASSWORD", ValueFrom: &corev1.EnvVarSource{SecretKeyRef: &corev1.SecretKeySelector{
									LocalObjectReference: corev1.LocalObjectReference{Name: "rabbit"}, Key: "password"}}}}},
					},
					Volumes: []corev1.Volume{
						{Name: "dataset", VolumeSource: corev1.VolumeSource{PersistentVolumeClaim: &corev1.PersistentVolumeClaimVolumeSource{ClaimName: "training-data", ReadOnly: true}}},
						{Name: "input", VolumeSource: corev1.VolumeSource{ConfigMap: &corev1.ConfigMapVolumeSource{LocalObjectReference: corev1.LocalObjectReference{Name: name}}}},
						{Name: "temporary", VolumeSource: corev1.VolumeSource{EmptyDir: &corev1.EmptyDirVolumeSource{SizeLimit: quantityPointer("32Mi")}}},
					},
				}},
		}}
	created, err := clientSet.BatchV1().Jobs(namespace).Create(ctx, job, metav1.CreateOptions{})
	if err != nil {
		clientSet.CoreV1().ConfigMaps(namespace).Delete(ctx, name, metav1.DeleteOptions{})
		return err
	}
	configMap.OwnerReferences = []metav1.OwnerReference{{APIVersion: "batch/v1", Kind: "Job", Name: name, UID: created.UID}}
	_, err = clientSet.CoreV1().ConfigMaps(namespace).Update(ctx, configMap, metav1.UpdateOptions{})
	return err
}

func quantityPointer(value string) *resource.Quantity {
	quantity := resource.MustParse(value)
	return &quantity
}

func trainingRoundsHandler(writer http.ResponseWriter, request *http.Request) {
	if token := os.Getenv("API_TOKEN"); token == "" || !hmac.Equal([]byte(request.Header.Get("Authorization")), []byte("Bearer "+token)) {
		http.Error(writer, "authentication required", http.StatusUnauthorized)
		return
	}
	ctx, cancel := context.WithTimeout(request.Context(), 30*time.Second)
	defer cancel()
	if request.URL.Path == "/rounds" && request.Method == http.MethodPost {
		var parameters trainingRound
		decoder := json.NewDecoder(http.MaxBytesReader(writer, request.Body, 65536))
		decoder.DisallowUnknownFields()
		if decoder.Decode(&parameters) != nil {
			http.Error(writer, "invalid training round", http.StatusBadRequest)
			return
		}
		grant, err := training.Verify(parameters.Authorization, os.Getenv("TRAINING_SIGNING_KEY"))
		if err != nil || grant.RunID != parameters.RunID || !slices.Contains(grant.Request.Organizations, serviceName) ||
			parameters.RoundNumber < 1 || parameters.RoundNumber > grant.Request.Rounds || parameters.LocalEpochs != grant.Request.LocalEpochs {
			http.Error(writer, "round does not match authorized training", http.StatusForbidden)
			return
		}
		runID, err := uuid.Parse(parameters.RunID)
		if err != nil {
			http.Error(writer, "invalid run ID", http.StatusBadRequest)
			return
		}
		name := fmt.Sprintf("training-%s-r%d", strings.ReplaceAll(runID.String(), "-", "")[:16], parameters.RoundNumber)
		composition, err := getCompositionRequest(grant.User, grant.RunID)
		if err != nil || composition == nil || composition.ArchetypeId != "computeToData" || composition.RequestType != training.RequestType {
			http.Error(writer, "DYNAMOS composition is not ready", http.StatusConflict)
			return
		}
		trainingStateMutex.Lock()
		defer trainingStateMutex.Unlock()
		if _, err := os.Stat(trainingStatePath(name)); err == nil {
			http.Error(writer, "round already exists", http.StatusConflict)
			return
		}
		token := uuid.NewString()
		if err := writeTrainingState(name, trainingRoundState{Status: "pending", Token: token}); err != nil ||
			createLocalTrainingJob(ctx, parameters, name, token) != nil {
			writeTrainingState(name, trainingRoundState{Status: "failed"})
			http.Error(writer, "could not create local training Job", http.StatusInternalServerError)
			return
		}
		writer.Header().Set("Content-Type", "application/json")
		writer.WriteHeader(http.StatusAccepted)
		json.NewEncoder(writer).Encode(map[string]string{"name": name, "namespace": strings.ToLower(serviceName)})
		return
	}
	name := strings.TrimPrefix(request.URL.Path, "/rounds/")
	if !validTrainingRoundName(name) {
		http.NotFound(writer, request)
		return
	}
	if clientSet == nil {
		clientSet = getKubeClient()
	}
	if request.Method == http.MethodDelete {
		foreground := metav1.DeletePropagationForeground
		clientSet.BatchV1().Jobs(strings.ToLower(serviceName)).Delete(ctx, name, metav1.DeleteOptions{PropagationPolicy: &foreground})
		writer.Header().Set("Content-Type", "application/json")
		json.NewEncoder(writer).Encode(map[string]string{"status": "cancelled"})
		return
	}
	if request.Method != http.MethodGet {
		writer.WriteHeader(http.StatusMethodNotAllowed)
		return
	}
	trainingStateMutex.Lock()
	defer trainingStateMutex.Unlock()
	var state trainingRoundState
	encoded, err := os.ReadFile(trainingStatePath(name))
	if err != nil || json.Unmarshal(encoded, &state) != nil {
		http.NotFound(writer, request)
		return
	}
	job, err := clientSet.BatchV1().Jobs(strings.ToLower(serviceName)).Get(ctx, name, metav1.GetOptions{})
	if err != nil {
		http.NotFound(writer, request)
		return
	}
	if job.Status.Failed > 0 {
		state.Status = "failed"
	} else if state.Status == "completed" && job.Status.Succeeded == 0 {
		state.Status = "running"
	}
	state.Token = ""
	writer.Header().Set("Content-Type", "application/json")
	json.NewEncoder(writer).Encode(state)
}
