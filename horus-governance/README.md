# Horus governance: zero-trust SAST, Fabric ledger, catalog and API

Submitted algorithms are analyzed as text and are never executed. Since
03/11/2026 no single party has to be trusted for that analysis:

1. The researcher's submission is a transaction on a Hyperledger Fabric
   channel run by UVA, VU and TUDELFT. The researcher's organization comes
   from the researcher's X.509 certificate.
2. The eligible organizations (selected ones minus the researcher's) draw the
   reviewer together with commit-reveal inside the chaincode.
3. The drawn organization's `sast-agent` runs Semgrep in an ephemeral,
   network-less Kubernetes Job **in its own namespace** and records the report
   signed with its own Fabric identity.
4. The chaincode accepts the report only from the drawn organization, with the
   agreed rules, policy, Semgrep version and analyzer image digest, and only if
   counts, score, decision and reasons match its own recomputation.
5. The other eligible organizations re-run the deterministic analysis and
   record an audit; a different report hash marks the submission as disputed.

The step-by-step explanation (in Portuguese) is
[docs/ledger-fabric-e-sast-local.md](../docs/ledger-fabric-e-sast-local.md);
the complete project guide is [docs/HORUS_GUIA_COMPLETO.md](../docs/HORUS_GUIA_COMPLETO.md).
The training API (8096) and the protected go/, python/, charts/, configuration/
and fabric/ directories are not modified by governance.

## Layout

| Path | Content |
| --- | --- |
| `app/` | FastAPI service: input validation, ledger client, catalog, training bridge. |
| `ledger/` | Go module, one binary with three modes: `chaincode`, `agent`, `gateway`. |
| `ledger/governance/` | Chaincode rules (pure Go, tested in memory). |
| `ledger/internal/agent/` | Organization-local SAST agent and its Kubernetes Job runner. |
| `ledger/internal/httpgw/` | Researcher gateway used by the Python API. |
| `deploy/ledger/` | Helm chart and idempotent `setup.py` for the Fabric network. |
| `sast/` | Rules, policy contracts, the analyzer (runs inside the Job), image build and operator CLI runner. |
| `config/` | Policy, organizations (image, namespace, MSP), displayed identity. |
| `tests/` | Python tests with an in-memory ledger stand-in, plus gated SAST and live tests. |

## Start

Prerequisites: Docker Desktop, the `dynamos-dev` tools container and the
`kind-scattered-training` cluster from the training setup.

```bash
python3 tools.py build                     # analyzer images
python3 tools.py ledger setup              # Fabric network, chaincode, agents, gateway
python3 tools.py ledger forward --background   # gateway on 127.0.0.1:8098
python3 tools.py start                     # API on 127.0.0.1:8097
python3 tools.py ledger verify             # same height, hash and config on all peers
```

`ledger setup` is idempotent; `--skip-build` reuses existing images.
`ledger down` removes the ledger Pods and keeps data; `ledger down --purge`
deletes the ledger history and identities. `tools.py start` only starts the
API; no governance container mounts the Docker socket any more
(`--remove-orphans` removes the old worker container).

The API reads the training token read-only and the gateway token from
`.local/ledger/gateway-token`. This is a local bearer-token sandbox, not
multi-user production login. The researcher's Fabric key lives in the gateway
Pod in the `tudelft` namespace (sandbox simplification).

## Analysis isolation (Kubernetes Job)

| Control | Value |
| --- | --- |
| Where | Namespace of the drawn organization, created by that organization's agent. |
| Network | NetworkPolicy with no ingress and no egress (no DNS, no API server). |
| User | UID/GID 20001, used by no other workload. |
| Processes | `ulimit -u 128` (per UID, hence the dedicated UID). |
| Filesystem | Read-only root, in-memory `/tmp` (128 MiB), read-only input. |
| Privileges | All capabilities dropped, no privilege escalation, seccomp RuntimeDefault, PodSecurity `restricted`. |
| Resources | 1 CPU, 768 MiB, 150 s deadline, no retries. |
| Credentials | No service-account token, Secrets, datasets or Docker socket. |
| Image | `imagePullPolicy: Never`; the digest reported by the kubelet must be the agreed one. |
| Cleanup | Job and ConfigMap deleted by the agent; TTL as a fallback. |

The agent's Role allows only ConfigMaps, Jobs and reading Pod logs in its own
namespace. Submissions are limited to 900 KiB so the code fits one ConfigMap.

## Operator CLI analysis (outside the ledger)

`tools.py analyze` still runs the analyzer image in local Docker for operator
checks (for example, comparing the three organization images). It records
nothing on the ledger.

```bash
python3 tools.py analyze --organization UVA --file examples/clean.py
python3 tools.py analyze --organization VU --file examples/unsafe.py
```

Expected: clean.py approved with score 100 and no findings; unsafe.py
rejected with score 0 (eval, pickle.loads, subprocess, a network import and a
deliberately fake token). Do not execute or import unsafe.py. Exit status 0
means the analysis completed, even if rejected; errors exit with 2.

## Images and agreed configuration

The build produces `horus-sast-base:local` and one image per organization
(`horus-sast-uva|vu|tudelft:local`, differing only in `HORUS_ORGANIZATION`).
Semgrep 1.145.0 is pinned by OCI digest; no remote rules are fetched during
analysis. `ledger/Dockerfile` builds `horus-ledger:local` and runs the Go tests.

`ledger setup` writes the agreed configuration to
`.local/ledger/governance.json` and to a ConfigMap in every organization:
members and MSPs, `rules_hash`, `policy_hash`, Semgrep version, each
organization's analyzer image digest, rule severities/messages, policy and the
600 s draw timeout. Rebuilding analyzer images changes their digests and
therefore the configuration; the ledger refuses a different configuration
(sandbox: `ledger down --purge` and `ledger setup`).

## Rules and policy

| Rule | Severity | Detection |
| --- | --- | --- |
| horus.dynamic-code | high | eval, exec and compile, including recognized aliases. |
| horus.pickle-deserialization | high | pickle.load and pickle.loads. |
| horus.unsafe-yaml | high | yaml.load without explicit SafeLoader/CSafeLoader, unsafe_load and full_load. |
| horus.process-execution | high | subprocess calls and os command/process APIs. |
| horus.network-import | medium | socket, requests, urllib, http, httpx and aiohttp imports. |
| horus.file-write-path | high | Common open/Path write APIs, dynamic modes and low-level os.open with a destination not statically under /tmp. |
| horus.unresolved-file-write | high | Object write APIs and low-level os.write whose destination cannot be proven from the call. |
| horus.hardcoded-secret | high | Credential-like assignments/dictionary fields with nonempty literal values. |

Score is max(0, 100 - 25*high - 10*medium - 2*low). Approval requires zero
high findings and score >= 70. Suppression comments such as nosemgrep do not
suppress the governance findings. Static analysis is not proof of safety.

## Report

The analyzer prints a canonical-JSON envelope: `report` (schema version,
code/rules/policy hashes, Semgrep version, score, counts, sorted findings with
fixed messages, decision, reasons), `report_hash` and `provenance`. The report
contains no timestamps, paths, snippets or organization identity, so all three
organization images produce the same `report_hash` for the same input. That
determinism is what makes audits by re-execution possible. The agent hashes
the raw `report` bytes exactly as printed; nothing is re-serialized.

## Tests

```bash
(cd ledger && go test ./...)
python3 -m venv .venv && .venv/bin/pip install -r requirements.lock
.venv/bin/python -m unittest discover -s tests -v
HORUS_SAST_DOCKER_TESTS=1 .venv/bin/python -m unittest discover -s tests -v
HORUS_GOV_LIVE_TESTS=1 .venv/bin/python -m unittest tests.test_live -v
```

Go tests cover the chaincode rules, three agents against the real chaincode in
memory (including a dishonest reviewer caught by the audit and a retried
infrastructure failure) and the gateway. Python tests use `tests/fake_ledger.py`.
The live test needs the ledger, the gateway forward, the API and Vite (or
`HORUS_GOV_LIVE_API`/`HORUS_GOV_LIVE_TOKEN` to call an API directly). Set
`HORUS_GOV_LIVE_TRAINING=1` only to request a real three-round Kubernetes run.

## Known limits

All three organizations share one kind cluster administered by one person;
the design is the production one, real isolation needs one cluster per
organization. Raft orderers tolerate crashes, not malice; MAJORITY endorsement
with three organizations does not stop a two-organization collusion. A
signature proves who recorded a report, not that Semgrep ran; audits cover
that when another honest eligible organization exists. Previous SQLite ledger
events were not migrated. See section 11 of the ledger document for the full
list.
