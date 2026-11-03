import hashlib
import json
import time
from uuid import uuid4

from manage import CONTEXT, LOCAL, kubectl, set_gate


PROBE = r'''
import hashlib,json,os,socket
from pathlib import Path
dataset=Path('/data/dataset.csv')
assert dataset.is_file(), 'Local dataset is missing'
try:
    Path('/data/write-probe').write_text('forbidden')
except PermissionError:
    pass
except OSError as error:
    assert error.errno == 30, 'Unexpected write failure'
else:
    raise AssertionError('Dataset is writable')
assert not Path('/var/run/secrets/kubernetes.io/serviceaccount/token').exists(), 'API token is mounted'
assert sorted(path.name for path in Path('/data').iterdir()) == ['dataset.csv'], 'Unexpected mounted data'
with socket.create_connection((os.environ['LOCAL_AGENT'],8080),timeout=10):
    pass
for host,port in [(os.environ['OTHER_AGENT'],8080),(os.environ['SINK'],8081),(os.environ['API_IP'],443)]:
    try:
        connection=socket.create_connection((host,port),timeout=3)
    except (TimeoutError,ConnectionError,OSError):
        continue
    connection.close()
    raise AssertionError('Forbidden connection succeeded: '+host)
print(json.dumps({'read_local':True,'write_denied':True,'no_api_token':True,
                  'other_organization_denied':True,'egress_denied':True,
                  'dataset_hash':hashlib.sha256(dataset.read_bytes()).hexdigest()}))
'''


def verify():
    set_gate(False)
    suffix = uuid4().hex[:8]
    sink_name = f"isolation-sink-{suffix}"
    seed = json.loads(kubectl("get", "job/training-seed", "-n", "uva", "-o", "json", capture=True))
    security = seed["spec"]["template"]["spec"]["securityContext"]
    image = seed["spec"]["template"]["spec"]["containers"][0]["image"]
    container_security = seed["spec"]["template"]["spec"]["containers"][0]["securityContext"]
    created = []
    report = {"context": CONTEXT, "verified_at": time.time(), "organizations": {}}
    try:
        sink = {"apiVersion": "v1", "kind": "Pod", "metadata": {"name": sink_name, "namespace": "training-system"},
                "spec": {"automountServiceAccountToken": False, "restartPolicy": "Never", "securityContext": security,
                         "containers": [{"name": "sink", "image": image, "imagePullPolicy": "IfNotPresent",
                                         "command": ["python", "-m", "http.server", "8081"],
                                         "securityContext": container_security,
                                         "readinessProbe": {"tcpSocket": {"port": 8081}}}]}}
        kubectl("create", "-f", "-", input_data=json.dumps(sink))
        created.append(("pod", sink_name, "training-system"))
        kubectl("wait", "--for=condition=Ready", f"pod/{sink_name}", "-n", "training-system", "--timeout=120s")
        sink_ip = json.loads(kubectl("get", f"pod/{sink_name}", "-n", "training-system", "-o", "json", capture=True))["status"]["podIP"]
        api_ip = json.loads(kubectl("get", "svc/kubernetes", "-n", "default", "-o", "json", capture=True))["spec"]["clusterIP"]
        control_name = f"isolation-control-{suffix}"
        control = {"apiVersion": "batch/v1", "kind": "Job", "metadata": {"name": control_name, "namespace": "training-system"},
                   "spec": {"backoffLimit": 0, "activeDeadlineSeconds": 90, "template": {"spec": {
                       "automountServiceAccountToken": False, "restartPolicy": "Never", "securityContext": security,
                       "containers": [{"name": "control", "image": image, "imagePullPolicy": "IfNotPresent",
                                       "command": ["python", "-c", f"import socket; socket.create_connection(('{sink_ip}',8081),timeout=10).close()"],
                                       "securityContext": container_security}]}}}}
        kubectl("create", "-f", "-", input_data=json.dumps(control))
        created.append(("job", control_name, "training-system"))
        kubectl("wait", "--for=condition=complete", f"job/{control_name}", "-n", "training-system", "--timeout=120s")
        for namespace, other_namespace in (("uva", "vu"), ("vu", "tudelft"), ("tudelft", "uva")):
            name = f"isolation-probe-{suffix}"
            local_ip = json.loads(kubectl("get", "svc/training-agent", "-n", namespace, "-o", "json", capture=True))["spec"]["clusterIP"]
            other_ip = json.loads(kubectl("get", "svc/training-agent", "-n", other_namespace, "-o", "json", capture=True))["spec"]["clusterIP"]
            probe = {"apiVersion": "batch/v1", "kind": "Job", "metadata": {"name": name, "namespace": namespace},
                     "spec": {"backoffLimit": 0, "activeDeadlineSeconds": 90, "template": {
                         "metadata": {"labels": {"app": "federated-training", "role": "worker"}},
                         "spec": {"automountServiceAccountToken": False, "restartPolicy": "Never", "securityContext": security,
                                  "containers": [{"name": "probe", "image": image, "imagePullPolicy": "IfNotPresent",
                                                  "command": ["python", "-c", PROBE], "securityContext": container_security,
                                                  "env": [{"name": "LOCAL_AGENT", "value": local_ip},
                                                          {"name": "OTHER_AGENT", "value": other_ip},
                                                          {"name": "SINK", "value": sink_ip}, {"name": "API_IP", "value": api_ip}],
                                                  "volumeMounts": [{"name": "dataset", "mountPath": "/data", "readOnly": True}]}],
                                  "volumes": [{"name": "dataset", "persistentVolumeClaim": {"claimName": "training-data", "readOnly": True}}]}}}}
            kubectl("create", "-f", "-", input_data=json.dumps(probe))
            created.append(("job", name, namespace))
            kubectl("wait", "--for=condition=complete", f"job/{name}", "-n", namespace, "--timeout=120s")
            output = kubectl("logs", f"job/{name}", "-n", namespace, capture=True)
            report["organizations"][namespace] = json.loads(output)
            for resource, target_namespace in (("persistentvolumeclaims", other_namespace), ("secrets", namespace)):
                answer = kubectl("auth", "can-i", "get", resource, "-n", target_namespace,
                                 "--as", f"system:serviceaccount:{namespace}:training-agent", capture=True, check=False)
                if answer != "no":
                    raise RuntimeError(f"Unexpected agent permission: {namespace} -> {resource}")
            print(f"{namespace.upper()}: local read OK; write, cross-organization network and API access denied")
        hashes = {entry["dataset_hash"] for entry in report["organizations"].values()}
        if len(hashes) != 3:
            raise RuntimeError("Organizations do not have distinct datasets")
        report["status"] = "passed"
        LOCAL.mkdir(parents=True, exist_ok=True)
        (LOCAL / "isolation-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        set_gate(True)
        print("Isolation verified; training enabled. No raw dataset was exported.")
    finally:
        for kind, name, namespace in reversed(created):
            kubectl("delete", kind, name, "-n", namespace, "--ignore-not-found", "--wait=false", check=False)


if __name__ == "__main__":
    verify()