"""horus-fhir operator CLI (stage 1: local infrastructure).

  python3 tools.py start | stop | status | down | reset-demo
  python3 tools.py test-infra       # FHIR metadata + channel height on both peers
  python3 tools.py test-isolation   # snapshot others, start, test, down, compare
  python3 tools.py deploy-cc        # stage 2: build, install, approve, commit fhir-abac
  python3 tools.py test-cc          # stage 2: committed definition, identities, refused write
  python3 tools.py build            # stage 3: rebuild fhir-gateway + fhir-api images and restart them
  python3 tools.py test-api         # stage 3: unit tests + one call per endpoint (writes to the ledger)
  python3 tools.py test             # stage 6: Go + pytest unit (image) + reset-demo + pytest integration (Mac)
  python3 tools.py bench            # stage 6: scenario --reset, measurements, reset + scenario again

Only resources of the compose project "horus-fhir" are touched: containers and
volumes named fhir-*, the network horus-fhir-net and this folder's .local/.
No prune, no command against another folder or the kind cluster.
"""
import argparse
import base64
import gzip
import hashlib
import io
import json
import os
import platform
import tarfile
import secrets
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOCAL = ROOT / ".local"
PROJECT = "horus-fhir"
CHANNEL = "fhir-channel"
NETWORK = "horus-fhir-net"
DOCKER_APP = Path("/Applications/Docker.app/Contents/Resources/bin/docker")
DOCKER = str(DOCKER_APP) if DOCKER_APP.exists() else (shutil.which("docker") or "docker")
CHAINCODE = "fhir-abac"
CC_VERSION = "0.1.0"
CC_IMAGE = f"{CHAINCODE}:{CC_VERSION}"
ENDORSEMENT = "AND('HospitalMSP.peer','LabMSP.peer')"
FABRIC_JSON = LOCAL / "fabric.json"
CHAINCODES = ["fhir-cc-hospital", "fhir-cc-lab"]
SERVICES = ["fhir-gateway", "fhir-api"]
API = "http://127.0.0.1:8099"
FABRIC = ["fhir-orderer0", "fhir-peer0-hospital", "fhir-peer0-lab"]
CAS = ["fhir-ca-hospital", "fhir-ca-lab"]
NEIGHBORS = {"scattered-training-control-plane": "kind cluster (training + horus-governance ledger)",
             "horus-governance-api": "horus-governance API", "dynamos-dev": "dynamos-dev tools"}


def run(*args, capture=False, check=True, env=None, cwd=None):
    result = subprocess.run(list(args), text=True, capture_output=capture, cwd=cwd,
                            env={**os.environ, **env} if env else None)
    if check and result.returncode != 0:
        if capture:
            sys.stderr.write(result.stdout + result.stderr)
        raise SystemExit(f"failed: {' '.join(args[:6])}...")
    return result


def fabric_state():
    return json.loads(FABRIC_JSON.read_text()) if FABRIC_JSON.exists() else None


def compose(*args, **kwargs):
    """Always passes the deployed package IDs, so chaincode containers keep theirs."""
    state = fabric_state() or {}
    env = {f"FHIR_CC_ID_{org.upper()}": package for org, package in state.get("packageIds", {}).items()}
    return run(DOCKER, "compose", "-p", PROJECT, "-f", str(ROOT / "compose.yaml"), *args, env=env, **kwargs)


def ensure_secrets():
    """CA bootstrap passwords: generated once, only in .local (git-ignored)."""
    folder = LOCAL / "ca"
    folder.mkdir(parents=True, exist_ok=True)
    for path in (folder / "hospital.password", folder / "lab.password", LOCAL / "gateway-token", LOCAL / "api-token"):
        if not path.exists():
            path.write_text(secrets.token_hex(24))
            path.chmod(0o600)


def tools(command, capture=True, check=True):
    return compose("run", "--rm", "--no-deps", "fhir-tools", "bash", "-c", command, capture=capture, check=check)


def warn_neighbors():
    names = run(DOCKER, "ps", "--format", "{{.Names}}", capture=True).stdout.split()
    running = [name for name in NEIGHBORS if name in names]
    if running:
        stats = run(DOCKER, "stats", "--no-stream", "--format", "{{.Name}} {{.MemUsage}}", *running, capture=True, check=False).stdout
        print("WARNING: other environments are running and share Docker's memory (not stopped by this tool):")
        for line in stats.strip().splitlines():
            name = line.split()[0]
            print(f"  - {name} ({NEIGHBORS.get(name, '')}): {' '.join(line.split()[1:])}")
        print("  The FHIR stack needs about 1.4 GB more. Stop them yourself if Docker runs out of memory.")


def hapi_ready(timeout=300):
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = tools("curl -fsS -m 5 http://fhir-hapi:8080/fhir/metadata", check=False)
        if result.returncode == 0:
            return json.loads(result.stdout)
        time.sleep(5)
    raise SystemExit("HAPI FHIR did not answer /fhir/metadata in time: docker logs fhir-hapi")


def start():
    warn_neighbors()
    ensure_secrets()
    for folder in ("crypto", "wallet", "channel"):
        (LOCAL / folder).mkdir(parents=True, exist_ok=True)
    print("1/5 CAs (fhir-ca.hospital, fhir-ca.lab)")
    compose("up", "-d", "--wait", *CAS)
    print("2/5 identities (nodes + personas adm-001, pat-001, phy-001, phy-002, lab-001)")
    for org in ("hospital", "lab"):
        compose("run", "--rm", "--no-deps", "fhir-enroll", org)
    print("3/5 orderer and peers")
    compose("up", "-d", "--wait", *FABRIC)
    print(f"4/5 channel {CHANNEL}")
    tools("bash /network/scripts/channel.sh", capture=False)
    print("5/5 HAPI FHIR R4 (first start takes 1-2 minutes)")
    compose("up", "-d", "fhir-hapi")
    metadata = hapi_ready()
    if fabric_state():
        compose("up", "-d", *CHAINCODES)
        print(f"chaincode {CHAINCODE} {fabric_state()['version']} containers started (already deployed)")
        services_up()
    print(f"Ready: FHIR {metadata.get('fhirVersion')} at fhir-hapi:8080 (internal only), channel {CHANNEL} up.")


def heights():
    script = (f"for org in hospital lab; do msp=$([ $org = hospital ] && echo HospitalMSP || echo LabMSP); "
              f"CORE_PEER_LOCALMSPID=$msp CORE_PEER_MSPCONFIGPATH=/local/crypto/$org/admin/msp "
              f"CORE_PEER_ADDRESS=fhir-peer0.$org:7051 CORE_PEER_TLS_ENABLED=true "
              f"CORE_PEER_TLS_ROOTCERT_FILE=/local/crypto/$org/public/msp/tlscacerts/ca.pem "
              f"peer channel getinfo -c {CHANNEL} 2>/dev/null | sed -n 's/^Blockchain info: /'$org' /p'; done")
    info = {}
    for line in tools(script).stdout.strip().splitlines():
        org, raw = line.split(" ", 1)
        info[org] = json.loads(raw)
    return info


def status():
    compose("ps", "-a", "--format", "table {{.Name}}\t{{.Status}}", capture=False)
    try:
        for org, item in heights().items():
            print(f"fhir-peer0.{org}: {CHANNEL} height {item['height']}")
    except SystemExit:
        print(f"{CHANNEL}: not reachable (network stopped?)")


def guarded_resources():
    """Every container/volume of the project must carry the fhir- prefix."""
    label = f"label=com.docker.compose.project={PROJECT}"
    containers = run(DOCKER, "ps", "-a", "--filter", label, "--format", "{{.Names}}", capture=True).stdout.split()
    volumes = run(DOCKER, "volume", "ls", "--filter", label, "--format", "{{.Name}}", capture=True).stdout.split()
    foreign = [name for name in containers + volumes if not name.startswith("fhir-")]
    if foreign:
        raise SystemExit(f"refusing: project {PROJECT} has unexpected resources {foreign}")
    return containers, volumes


def down():
    ensure_secrets()  # compose validates the secret files even for "down"
    containers, volumes = guarded_resources()
    print(f"Removing containers {containers or '-'} and volumes {volumes or '-'} of project {PROJECT}")
    compose("--profile", "tools", "down", "--volumes", "--remove-orphans")
    for folder in ("crypto", "wallet", "channel", "ca", "cc"):
        shutil.rmtree(LOCAL / folder, ignore_errors=True)
    FABRIC_JSON.unlink(missing_ok=True)
    print("Removed .local/crypto, wallet, channel, ca, cc and fabric.json (credentials are invalid without the CA volumes).")


def test_infra():
    metadata = hapi_ready(timeout=30)
    assert metadata.get("resourceType") == "CapabilityStatement" and metadata.get("fhirVersion") == "4.0.1", metadata
    print(f"OK GET /fhir/metadata: CapabilityStatement, FHIR {metadata['fhirVersion']}")
    info = heights()
    assert set(info) == {"hospital", "lab"}, info
    assert len({item["currentBlockHash"] for item in info.values()}) == 1, info
    for org, item in info.items():
        print(f"OK peer channel getinfo {CHANNEL} on fhir-peer0.{org}: height {item['height']}")
    published = run(DOCKER, "ps", "--filter", f"label=com.docker.compose.project={PROJECT}",
                    "--format", "{{.Names}} {{.Ports}}", capture=True).stdout
    assert "0.0.0.0" not in published and "127.0.0.1" not in published, published
    print("OK no FHIR/Fabric port is published on the host")


def snapshot():
    """State of everything that is NOT horus-fhir."""
    state = {"containers": {}, "volumes": [], "networks": {}, "pods": {}}
    ids = run(DOCKER, "ps", "-aq", capture=True).stdout.split()
    own = set()  # anonymous volumes of fhir-* containers (image VOLUME declarations)
    for item in json.loads(run(DOCKER, "inspect", *ids, capture=True).stdout) if ids else []:
        name = item["Name"].lstrip("/")
        if name.startswith("fhir-"):
            own.update(mount.get("Name") for mount in item.get("Mounts", []) if mount.get("Type") == "volume")
        else:
            state["containers"][name] = [item["Id"][:12], item["State"]["Status"], item["State"]["StartedAt"]]
    state["volumes"] = sorted(v for v in run(DOCKER, "volume", "ls", "--format", "{{.Name}}", capture=True).stdout.split()
                              if not v.startswith("fhir-") and v not in own)
    for line in run(DOCKER, "network", "ls", "--format", "{{.Name}} {{.ID}}", capture=True).stdout.splitlines():
        name, network_id = line.split()
        if name != NETWORK:
            state["networks"][name] = network_id
    pods = run(DOCKER, "exec", "dynamos-dev", "kubectl", "--context", "kind-scattered-training", "get", "pods", "-A",
               "-o", "json", capture=True, check=False)
    if pods.returncode == 0:
        for pod in json.loads(pods.stdout)["items"]:
            owners = [owner["kind"] for owner in pod["metadata"].get("ownerReferences", [])]
            if "Job" in owners:
                continue  # short-lived Jobs come and go on their own
            restarts = sum(c.get("restartCount", 0) for c in pod.get("status", {}).get("containerStatuses", []))
            state["pods"][f"{pod['metadata']['namespace']}/{pod['metadata']['name']}"] = [pod["metadata"]["uid"], restarts]
    return state


def test_isolation():
    before = snapshot()
    print(f"Snapshot: {len(before['containers'])} containers, {len(before['volumes'])} volumes, "
          f"{len(before['networks'])} networks, {len(before['pods'])} kind pods (not horus-fhir)")
    start()
    test_infra()
    down()
    after = snapshot()
    differences = [key for key in before if before[key] != after[key]]
    for key in differences:
        print(f"DIFFERENT {key}:")
        old, new = before[key], after[key]
        if isinstance(old, dict):
            for name in sorted(set(old) | set(new)):
                if old.get(name) != new.get(name):
                    print(f"  {name}: {old.get(name)} -> {new.get(name)}")
        else:
            print(f"  removed {sorted(set(old) - set(new))} added {sorted(set(new) - set(old))}")
    if differences:
        raise SystemExit("isolation test FAILED")
    print("OK non-interference: containers, volumes, networks and kind pods outside horus-fhir are identical")


# ---------------------------------------------------------------- stage 2

def org_env(org, identity=None):
    """peer CLI environment for the peer of <org>: the org admin, or a wallet
    persona (its MSP comes from the persona, not from the peer it talks to)."""
    msp = "HospitalMSP" if org == "hospital" else "LabMSP"
    msp_dir = f"/local/crypto/{org}/admin/msp"
    if identity:
        msp = json.loads((LOCAL / "wallet" / identity / "identity.json").read_text())["msp"]
        msp_dir = f"/local/wallet/{identity}/msp"
    return (f"CORE_PEER_LOCALMSPID={msp} CORE_PEER_MSPCONFIGPATH={msp_dir} CORE_PEER_ADDRESS=fhir-peer0.{org}:7051 "
            f"CORE_PEER_TLS_ENABLED=true CORE_PEER_TLS_ROOTCERT_FILE=/local/crypto/{org}/public/msp/tlscacerts/ca.pem")


ORDERER_ARGS = "-o fhir-orderer0.hospital:7050 --tls --cafile /local/crypto/hospital/public/msp/tlscacerts/ca.pem"
BOTH_PEERS = " ".join(f"--peerAddresses fhir-peer0.{org}:7051 --tlsRootCertFiles /local/crypto/{org}/public/msp/tlscacerts/ca.pem"
                      for org in ("hospital", "lab"))


def deterministic_tgz(files):
    """tar.gz with fixed timestamps and owners, so the package ID never changes."""
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb", mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode="w", format=tarfile.USTAR_FORMAT) as archive:
            for name, data in files:
                info = tarfile.TarInfo(name)
                info.size, info.mtime, info.mode, info.uid, info.gid = len(data), 0, 0o644, 0, 0
                archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def build_chaincode():
    """Go tests, static linux binary from the local module cache (offline), scratch image."""
    source = ROOT / "chaincode"
    go_env = {"GOPROXY": "off", "GOFLAGS": "-mod=mod", "GOSUMDB": "off", "CGO_ENABLED": "0"}
    run("go", "test", "./...", "-count=1", cwd=source, env=go_env)
    arch = run(DOCKER, "info", "--format", "{{.Architecture}}", capture=True).stdout.strip()
    goarch = {"aarch64": "arm64", "arm64": "arm64", "x86_64": "amd64"}.get(arch, platform.machine())
    run("go", "build", "-trimpath", "-ldflags=-s -w", "-o", "build/fhir-abac", "./cmd/fhir-abac", cwd=source,
        env={**go_env, "GOOS": "linux", "GOARCH": goarch})
    run(DOCKER, "build", "-q", "-t", CC_IMAGE, str(source), capture=True)


def committed():
    result = tools(f"{org_env('hospital')} peer lifecycle chaincode querycommitted -C {CHANNEL} -n {CHAINCODE} -O json",
                   check=False)
    return json.loads(result.stdout) if result.returncode == 0 else None


def deploy_cc():
    print(f"1/5 test + build {CC_IMAGE} (offline, scratch image)")
    build_chaincode()
    current = committed()
    sequence = 1 if not current else current["sequence"] + (current["version"] != CC_VERSION)
    print(f"2/5 package + install on both peers (sequence {sequence})")
    label, packages = f"{CHAINCODE}_{CC_VERSION}", {}
    for org in ("hospital", "lab"):
        connection = json.dumps({"address": f"fhir-cc.{org}:9999", "dial_timeout": "10s", "tls_required": False}).encode()
        metadata = json.dumps({"type": "ccaas", "label": label}).encode()
        package = deterministic_tgz([("metadata.json", metadata),
                                     ("code.tar.gz", deterministic_tgz([("connection.json", connection)]))])
        folder = LOCAL / "cc" / org
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "package.tgz").write_bytes(package)
        packages[org] = f"{label}:{hashlib.sha256(package).hexdigest()}"
        installed = tools(f"{org_env(org)} peer lifecycle chaincode queryinstalled -O json", check=False).stdout
        if packages[org] not in installed:
            tools(f"{org_env(org)} peer lifecycle chaincode install /local/cc/{org}/package.tgz")
    state = {"channel": CHANNEL, "chaincode": CHAINCODE, "version": CC_VERSION, "sequence": sequence,
             "packageIds": packages, "endorsementPolicy": ENDORSEMENT, "image": CC_IMAGE}
    FABRIC_JSON.write_text(json.dumps(state, indent=2) + "\n")
    print("3/5 chaincode containers fhir-cc.hospital, fhir-cc.lab")
    compose("up", "-d", "--force-recreate", *CHAINCODES)
    definition = (f"-C {CHANNEL} -n {CHAINCODE} -v {CC_VERSION} --sequence {sequence} "
                  f"--signature-policy \"{ENDORSEMENT}\"")
    if current and current["sequence"] == sequence:
        print(f"4/5 + 5/5 already committed at sequence {sequence}")
    else:
        print("4/5 approve for HospitalMSP and LabMSP")
        for org in ("hospital", "lab"):
            tools(f"{org_env(org)} peer lifecycle chaincode approveformyorg {ORDERER_ARGS} {definition} "
                  f"--package-id {packages[org]} --waitForEvent")
        readiness = tools(f"{org_env('hospital')} peer lifecycle chaincode checkcommitreadiness {definition} -O json").stdout
        print(f"    approvals: {json.loads(readiness)['approvals']}")
        print("5/5 commit (endorsed by both peers)")
        tools(f"{org_env('hospital')} peer lifecycle chaincode commit {ORDERER_ARGS} {definition} {BOTH_PEERS} --waitForEvent")
    state["committed"] = committed()
    FABRIC_JSON.write_text(json.dumps(state, indent=2) + "\n")
    print(f"Deployed {CHAINCODE} {CC_VERSION} sequence {sequence}; saved .local/fabric.json")
    services_up()


def query(org, identity, function, *args):
    payload = json.dumps({"Args": [function, *args]}).replace("'", "'\\''")
    result = tools(f"{org_env(org, identity)} peer chaincode query -C {CHANNEL} -n {CHAINCODE} -c '{payload}'", check=False)
    return result.returncode, (result.stdout if result.returncode == 0 else result.stderr).strip()


def test_cc():
    state = fabric_state()
    assert state, "run deploy-cc first"
    for org in ("hospital", "lab"):
        text = tools(f"{org_env(org)} peer lifecycle chaincode querycommitted -C {CHANNEL} -n {CHAINCODE} -O json").stdout
        info = json.loads(text)
        policy = base64.b64decode(info["validation_parameter"])
        assert info["approvals"] == {"HospitalMSP": True, "LabMSP": True}, info
        assert b"HospitalMSP" in policy and b"LabMSP" in policy, policy
        print(f"OK fhir-peer0.{org}: {CHAINCODE} {info['version']} sequence {info['sequence']}, approvals {info['approvals']}, "
              f"endorsement policy names HospitalMSP and LabMSP")
    decoded = tools("echo '" + base64.b64encode(policy).decode() + "' | base64 -d > /tmp/p && "
                    "configtxlator proto_decode --type protos.ApplicationPolicy --input /tmp/p", check=False)
    if decoded.returncode == 0:
        rule = json.loads(decoded.stdout)["signature_policy"]["rule"]["n_out_of"]
        assert rule["n"] == 2 and len(rule["rules"]) == 2, rule
        print("OK endorsement policy decoded: 2 out of [HospitalMSP.peer, LabMSP.peer] (AND)")
    answers = {org: query(org, "phy-001", "PAP:ListPolicies") for org in ("hospital", "lab")}
    assert all(code == 0 for code, _ in answers.values()) and answers["hospital"] == answers["lab"], answers
    print(f"OK PAP:ListPolicies on both peers: {answers['hospital'][1]}")
    for identity, org, role in (("pat-001", "hospital", "patient"), ("phy-001", "hospital", "physician"),
                                ("adm-001", "hospital", "admin"), ("lab-001", "lab", "lab")):
        code, text = query(org, identity, "WhoAmI")
        assert code == 0 and json.loads(text)["role"] == role, text
        print(f"OK WhoAmI as {identity}: {text}")
    before = heights()["hospital"]["height"]
    invoke = tools(f"{org_env('hospital', 'phy-001')} peer chaincode invoke {ORDERER_ARGS} -C {CHANNEL} -n {CHAINCODE} "
                   f"{BOTH_PEERS} -c '{json.dumps({'Args': ['PAP:CreatePolicy', 'Open', '{}']})}'", check=False)
    after = heights()["hospital"]["height"]
    assert invoke.returncode != 0 and "forbidden: requires role=admin" in invoke.stderr and before == after, invoke.stderr
    print(f"OK PAP:CreatePolicy as phy-001 refused at endorsement (forbidden), height unchanged ({after})")


# ---------------------------------------------------------------- stage 3

def image_exists(name):
    return run(DOCKER, "image", "inspect", name, capture=True, check=False).returncode == 0


def services_up(rebuild=False):
    """fhir-gateway (Go, offline build, scratch) and fhir-api (FastAPI PEP)."""
    ensure_secrets()
    if rebuild or not image_exists("fhir-gateway:0.1.0"):
        source = ROOT / "gateway"
        go_env = {"GOPROXY": "off", "GOFLAGS": "-mod=mod", "GOSUMDB": "off", "CGO_ENABLED": "0"}
        run("go", "test", "./...", "-count=1", cwd=source, env=go_env)
        arch = run(DOCKER, "info", "--format", "{{.Architecture}}", capture=True).stdout.strip()
        run("go", "build", "-trimpath", "-ldflags=-s -w", "-o", "build/fhir-gateway", ".", cwd=source,
            env={**go_env, "GOOS": "linux", "GOARCH": {"aarch64": "arm64", "x86_64": "amd64"}.get(arch, "arm64")})
        run(DOCKER, "build", "-q", "-t", "fhir-gateway:0.1.0", str(source), capture=True)
    if rebuild or not image_exists("fhir-api:0.1.0"):
        run(DOCKER, "build", "-q", "-t", "fhir-api:0.1.0", str(ROOT / "middleware"), capture=True)
    compose("up", "-d", "--wait", "--force-recreate" if rebuild else "--no-recreate", *SERVICES)
    print(f"fhir-gateway (internal) and fhir-api (PEP, {API}) are up")


def api(method, path, body=None, expect=(200,)):
    import urllib.error
    import urllib.request
    token = (LOCAL / "api-token").read_text().strip()
    request = urllib.request.Request(API + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            code, data = response.status, json.loads(response.read() or b"null")
    except urllib.error.HTTPError as error:
        code, data = error.code, json.loads(error.read() or b"null")
    assert code in expect, f"{method} {path}: HTTP {code} {data}"
    return data


def test_api():
    unit = run(DOCKER, "run", "--rm", "--network", "none", "--entrypoint", "python", "fhir-api:0.1.0",
               "-m", "unittest", "discover", "-s", "tests", capture=True, check=False)
    assert unit.returncode == 0, unit.stderr
    print(f"OK middleware unit tests: {unit.stderr.strip().splitlines()[-1]}")
    status = api("GET", "/status")
    assert status["fhir"]["ok"] and status["chain"]["ok"], status
    print(f"OK /status: FHIR {status['fhir']['fhirVersion']}, {status['ledger']} height {status['chain']['height']}")
    assert len(api("GET", "/personas")["personas"]) == 5
    policies = api("GET", "/policies")
    if not any(item["policyId"] == "ConsentRequiredPolicy" for item in policies["policies"]):
        created = api("POST", "/admin/policies?as=adm-001", {})
        print(f"OK POST /admin/policies (PAP) tx {created['txId'][:12]} block {created['blockNumber']}")
    api("POST", "/admin/policies?as=phy-001", {}, expect=(403,))
    print("OK POST /admin/policies as phy-001 -> 403 (PAP refuses)")
    api("POST", "/service-requests?as=phy-001")
    print("OK POST /service-requests as phy-001 (step 1, FHIR only)")
    consent = api("POST", "/consents?as=pat-001", {"serviceRequestId": "sr-001", "grantee": "phy-001", "days": 30})
    print(f"OK POST /consents (PIP) {consent['fhir']['id']} tx {consent['txId'][:12]} block {consent['blockNumber']}")
    api("POST", "/consents?as=phy-001", {"serviceRequestId": "sr-001", "grantee": "phy-001"}, expect=(403,))
    print("OK POST /consents as phy-001 -> 403")
    reports = {}
    for request_id in ("sr-001", "sr-002"):
        result = api("POST", "/lab/results?as=lab-001", {"serviceRequestId": request_id})
        reports[request_id] = result["fhir"]["diagnosticReport"]
        print(f"OK POST /lab/results {request_id}: {reports[request_id]} PIP block {result['pip']['blockNumber']}, "
              f"PAP block {result['pap']['blockNumber']}")
    a, b = reports["sr-001"], reports["sr-002"]
    checks = [("phy-001", a, 200, "PERMIT"), ("phy-001", b, 403, "NO_CONSENT"), ("phy-002", a, 403, "WRONG_GRANTEE")]
    for persona, report, code, reason in checks:
        outcome = api("GET", f"/reports/{report}?as={persona}", expect=(code,))
        assert outcome["reason"] == reason and outcome["auditEventId"], outcome
        assert ("resource" in outcome) == (code == 200), outcome
        steps = " -> ".join(dict.fromkeys(step["component"] for step in outcome["decisionTrace"]))
        print(f"OK GET /reports/{report}?as={persona}: {code} {reason}, tx {outcome['txId'][:12]} block "
              f"{outcome['blockNumber']}, trace PEP -> {steps}, AuditEvent {outcome['auditEventId']}, "
              f"PDP {outcome['timings']['pdpSubmitMs']} ms")
    assert api("GET", f"/verify/report/{a}")["match"] and api("GET", f"/verify/consent/{consent['fhir']['id']}")["match"]
    print("OK /verify/report and /verify/consent: on-chain hash matches FHIR")
    timeline = api("GET", "/audit")
    names = {item["name"] for item in timeline}
    assert {"PolicyCreated", "ConsentGranted", "ResourceRegistered", "ResourceBound", "AccessDecision", "AuditEvent"} <= names, names
    print(f"OK /audit: {len(timeline)} entries (on-chain + off-chain)")
    # Tamper with an Observation directly in FHIR (inside the network): the PEP must refuse it.
    observation = api("GET", f"/reports/{a}?as=phy-001")["resource"]["observations"][0]
    tampered = {key: value for key, value in observation.items() if key != "meta"}
    tampered["meta"] = {"security": observation["meta"]["security"]}
    tampered["valueQuantity"]["value"] = 99.9
    tools("curl -fsS -X PUT -H 'Content-Type: application/fhir+json' "
          f"--data '{json.dumps(tampered)}' http://fhir-hapi:8080/fhir/Observation/{observation['id']} -o /dev/null")
    outcome = api("GET", f"/reports/{a}?as=phy-001", expect=(403,))
    assert outcome["reason"] == "HASH_MISMATCH" and "resource" not in outcome, outcome
    assert not api("GET", f"/verify/report/{a}")["match"]
    print("OK tampered Observation in FHIR -> PDP permits, PEP refuses 403 HASH_MISMATCH, /verify shows mismatch")
    published = run(DOCKER, "ps", "--filter", f"label=com.docker.compose.project={PROJECT}", "--format", "{{.Names}} {{.Ports}}",
                    capture=True).stdout
    exposed = [line for line in published.splitlines() if "->" in line]
    assert len(exposed) == 1 and exposed[0].startswith("fhir-api ") and "127.0.0.1:8099" in exposed[0], exposed
    import socket
    with socket.socket() as probe:
        probe.settimeout(1)
        assert probe.connect_ex(("127.0.0.1", 8090)) != 0
    print("OK only fhir-api (127.0.0.1:8099) is published; FHIR is not reachable from the Mac (PEP cannot be bypassed)")


# ---------------------------------------------------------------- stage 6

def venv_python():
    python = ROOT / ".venv" / "bin" / "python"
    if not python.exists():
        run(sys.executable, "-m", "venv", str(ROOT / ".venv"))
        run(str(python), "-m", "pip", "install", "-q", "--no-deps", "-r", str(ROOT / "requirements-dev.lock"))
    return str(python)


def test_all():
    go_env = {"GOPROXY": "off", "GOFLAGS": "-mod=mod", "GOSUMDB": "off"}
    for module in ("chaincode", "gateway"):
        run("go", "test", "./...", "-count=1", cwd=ROOT / module, env=go_env)
    print("OK Go tests (chaincode PAP/PIP/PDP, gateway)")
    run(DOCKER, "build", "-q", "--target", "test", "-t", "fhir-api:0.1.0-test", str(ROOT / "middleware"), capture=True)
    run(DOCKER, "run", "--rm", "--network", "none", "fhir-api:0.1.0-test")
    print("OK pytest unit tests of the middleware (in fhir-api:0.1.0-test, no network)")
    print("reset-demo: integration tests need a clean channel and FHIR")
    down()
    start()
    deploy_cc()
    run(venv_python(), "-m", "pytest", "-q", "-p", "no:cacheprovider", str(ROOT / "tests"), cwd=ROOT)
    print("OK pytest integration tests (from the Mac). Run reset-demo or scenario.py --reset for a clean demo.")


def bench():
    run(sys.executable, str(ROOT / "scenario.py"), "--reset", capture=True)
    run(sys.executable, str(ROOT / "bench.py"), cwd=ROOT)
    print("Leaving a clean demo: scenario.py --reset")
    run(sys.executable, str(ROOT / "scenario.py"), "--reset", capture=True)


def main():
    parser = argparse.ArgumentParser(description="horus-fhir local infrastructure")
    parser.add_argument("action", choices=("start", "stop", "status", "down", "reset-demo", "test-infra",
                                               "test-isolation", "deploy-cc", "test-cc", "build", "test-api",
                                               "test", "bench"))
    action = parser.parse_args().action
    if action == "start":
        start()
    elif action == "stop":
        ensure_secrets()
        compose("--profile", "tools", "stop")
    elif action == "status":
        ensure_secrets()
        status()
    elif action == "down":
        down()
    elif action == "reset-demo":
        down()
        start()
        deploy_cc()
    elif action == "deploy-cc":
        deploy_cc()
    elif action == "test-cc":
        test_cc()
    elif action == "build":
        services_up(rebuild=True)
    elif action == "test-api":
        test_api()
    elif action == "test":
        test_all()
    elif action == "bench":
        bench()
    elif action == "test-infra":
        test_infra()
    else:
        test_isolation()


if __name__ == "__main__":
    main()
