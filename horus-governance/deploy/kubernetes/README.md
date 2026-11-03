# Future organization-local analysis Jobs

Stage (a) runs and tests Docker containers only. The template is NOT installed
by tools.py and does not change the existing training cluster.

Organization/image/namespace mapping lives in ../../config/organizations.json.
The future trusted worker must validate and substitute NAMESPACE, ORGANIZATION,
JOB_NAME, INPUT_CONFIGMAP and IMAGE_REFERENCE; use an immutable registry digest
for IMAGE_REFERENCE. Never interpolate submitted code into this template, an
image, a shell command, or a filename.

The trusted worker will create an input ConfigMap with one submission.py key,
containing already validated normalized UTF-8 text. The fixed shell command
only redirects this file into the trusted analyzer's stdin. The submitted file
is never executed or imported. ConfigMap size constraints mean the future
adapter must account for Kubernetes object overhead or choose another input
transport; accepting 1 MB at the API does not guarantee a 1 MB ConfigMap fits.
Attach ownership/cleanup to the input object and protect access to its contents.

The template supplies non-root execution, a read-only root filesystem, a
read-only input, disabled service-account token, dropped capabilities,
no privilege escalation, seccomp, CPU/memory/tmp limits and a Job deadline.
NetworkPolicy denies both ingress and egress for analysis Pods. The cluster
must enforce NetworkPolicy (the existing sandbox uses Cilium).

Kubernetes has no portable per-container pids-limit field in a Pod manifest.
The future deployment must configure and verify a suitable kubelet podPidsLimit
or equivalent runtime/admission policy before claiming the Docker 128-process
limit is reproduced. emptyDir also does not by itself guarantee the Docker
tmpfs noexec mount option. This template alone is not a verified replacement
for the tested Docker isolation. No Kubernetes transport is implemented yet.

No training PVC, dataset, API token, cloud credential or Docker socket should
be mounted in an analysis Pod. The API/worker must treat parse failures,
resource limits, timeouts, missing results and image mismatches as errors,
never as approval. Do not deploy the template before those controls exist.