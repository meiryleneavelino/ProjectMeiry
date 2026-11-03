# Horus governance: SAST, API, catalog and local ledger

Stages (a) through (d) provide offline Semgrep, server-side reviewer selection,
persistent deduplication/catalog, a SQLite hash-chain ledger and the Horus UI.
See the [project structure and testing guide](../docs/governanca-estrutura-e-testes.md).

For startup of the whole system and end-to-end observation, use the
[complete Horus guide](../docs/HORUS_GUIA_COMPLETO.md).

The training API on 8096 and protected go/, python/, charts/, configuration/
and fabric/ directories have not been modified by this governance integration.
Governance is here; frontend changes are in horus-sandbox-frontend/.

## Start governance

With Docker Desktop, SAST images and the existing training gateway available,
run from this directory:

```bash
python3 tools.py build
python3 tools.py start
python3 tools.py status
```

The API binds localhost:8097. The existing Vite server on 5175 injects its
local token for /governance-api. Only the trusted worker has a Docker socket.
Both services share .local/ and use the launcher user's UID/GID. On Linux,
Docker socket group access is configurable via HORUS_DOCKER_GID.
`python3 tools.py stop` stops governance without deleting persistent files.

The API reads the existing training token through a read-only mount. It starts
the built-in through an authenticated bridge; status/cancel/download continue
through the existing training proxy. Direct clients of 8096 are not audited
automatically by this local ledger. Configure server identity in
config/settings.example.json and restart governance after editing it.
This is a local bearer-token sandbox, not multi-user production login.

## Run locally

Docker Desktop and Python 3.10+ are required. The host runner uses only the
Python standard library; no host Semgrep installation is required.
From the Scattered-Directive directory:

```bash
cd horus-governance
python3 tools.py build
python3 tools.py analyze --organization UVA --file examples/clean.py
python3 tools.py analyze --organization VU --file examples/unsafe.py
```

Expected: clean.py is approved with score 100 and no findings. unsafe.py is
rejected with score 0, detecting eval, pickle.loads, subprocess, a network
import and a deliberately fake token. Do not execute or import unsafe.py.
Only submit it to tools.py, which treats it as text.

To analyze pasted text from stdin:

```bash
python3 tools.py analyze --organization UVA --stdin
```

Paste Python text, then finish input with Ctrl+D. Files must end in .py or
.txt. Invalid UTF-8, binary control characters, empty/whitespace-only input,
invalid Python syntax, and inputs over 1,048,576 bytes are rejected. The
scanner uses a generated temporary directory and a fixed submission.py name;
the original filename is never mounted or executed inside the container.
Changing only CRLF/CR line endings to LF does not change the normalized hash.
Other whitespace is preserved. UTF-8 BOM is not normalized away and can fail
the Python syntax check.

Successful analysis has exit status 0 even when the policy decision is
rejected; read report.decision. Infrastructure/input/parse errors have exit
status 2 and no approval. Do not infer approval solely from process exit code.

## Images and configuration

The build produces:

- horus-sast-base:local: common analyzer, local rules and standard policy.
- horus-sast-uva:local: UVA organization identity.
- horus-sast-vu:local: VU organization identity.
- horus-sast-tudelft:local: TUDELFT organization identity.

The base pins Semgrep 1.145.0 by multi-platform OCI digest, supporting native
arm64 and amd64. No remote rules or registry configuration is fetched during
analysis. Initial Docker image downloads require internet at build time.
Semgrep metrics and version checks are disabled. Suppression comments such as
nosemgrep do not suppress the governance findings.

config/organizations.json maps organizations to images and future namespaces.
The CLI allows explicit analyzer selection for operator tests only. The API
performs the reviewer lottery and researcher-organization exclusion on the
server. The frontend cannot choose the reviewer or override identity.
Submitted algorithms may enter the catalog but cannot be executed.

config/policy.json is shared by all organizations. sast/rules.yaml is a local
Semgrep configuration stored in JSON syntax (also valid YAML), so both the
trusted analyzer and Semgrep read precisely the same rule definitions.
Rebuild all images after changing policy, rules, or analyzer code.

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
high findings and score >=70. Low-severity counts are supported; the current
rule set uses high and medium. A medium finding alone does not necessarily
reject the script. Fixed messages never include matched credential values.

Static analysis is not proof of safety: Python reflection, obfuscation,
indirect calls, external dependencies and dynamic destinations can evade
these rules or yield conservative false positives. A 100 score means no
findings under this exact rule set, not permission to execute outside a
future reviewed sandbox. No submitted dependency is imported or installed.

## Isolation

tools.py creates one temporary container and removes it in a finally block.
It inspects and executes the immutable image ID, not a mutable tag selected
after launch. No submitted host file/directory, dataset or socket is mounted.

- --network none; no analysis service ports.
- Non-root UID/GID 10001, read-only root filesystem.
- All capabilities dropped, no-new-privileges enabled.
- 768 MiB memory, no additional swap, one CPU, at most 128 processes.
- /tmp tmpfs: 128 MiB, noexec, nosuid and nodev.
- Scanner subprocess timeout and outer container deadline; errors fail closed.

The only subprocesses launched for submitted text are the trusted Semgrep
binary and its static-analysis engine. A trusted ast.parse syntax check
creates an AST, never a running user program. No eval/exec/import of submitted
code occurs. The Python interpreter runs isolated from user import paths.
Do not mount the Docker socket inside an analyzer; any future worker with
Docker access remains a trusted, privileged operational boundary.

The Kubernetes template and its unimplemented controls are described in
[deploy/kubernetes/README.md](deploy/kubernetes/README.md). It was not applied.

## Report and image provenance

stdout contains a JSON envelope:

```json
{
  "report": {
    "schema_version": 1,
    "code_hash": "sha256",
    "rules_hash": "sha256-of-exact-rules-bytes",
    "policy_hash": "sha256-of-canonical-policy",
    "semgrep_version": "1.145.0",
    "score": 100,
    "counts": {"high": 0, "medium": 0, "low": 0},
    "findings": [],
    "decision": "approved",
    "reasons": ["No high-severity findings and security score meets policy."]
  },
  "report_hash": "sha256-of-canonical-report",
  "provenance": {
    "organization": "UVA",
    "image": "horus-sast-uva:local",
    "image_id": "sha256:local-docker-image-id",
    "repository_digests": [],
    "digest": "sha256:digest",
    "digest_kind": "docker_image_id"
  }
}
```

Each finding has rule_id, line, column, severity and a fixed message. Findings
are sorted by line, column, rule ID, severity and message. The report contains
no timestamps, temporary paths, snippets, organization or image identity.
The report hash excludes provenance, so different organization images produce
the same report/hash for the same normalized text/rules/policy/engine.

Canonical JSON uses sorted keys, compact separators, UTF-8, no ASCII escaping
and no NaN/Infinity. Report hashes have no sha256: prefix. When a repository
digest is available it is recorded; otherwise the local Docker image
ID is explicitly labeled docker_image_id, not misrepresented as a
registry manifest digest. Provenance is intended for future ledger events.

verify_report(report, expected_hash) detects changes relative to a trusted
expected hash. The API compares the stored report against CodeAnalyzed in the
verified local ledger. No Besu/blockchain backend has been activated.

The persistent API deduplicates normalized code hashes, including concurrent
queued/running requests. Re-running the operator CLI deliberately starts a
fresh analysis for determinism tests; it does not register catalog entries.

## Tests and acceptance gate

```bash
python3 -m unittest discover -s tests -p test_sast.py -v
HORUS_SAST_DOCKER_TESTS=1 python3 -m unittest discover -s tests -p test_sast.py -v
```

The first command runs contract tests and explicitly skips Docker tests.
The second runs all tests against real offline Semgrep containers after
tools.py build. Tests cover binary/UTF-8/size rejection, normalization,
scoring, tampered reports, all required categories, selected aliases,
redaction, suppression resistance, safe YAML/static /tmp destinations,
traversal, invalid syntax, non-execution, effective Docker isolation and
identical reports from all three organizations for both supplied examples.

To run all backend tests:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.lock
HORUS_SAST_DOCKER_TESTS=1 .venv/bin/python -m unittest discover -s tests -v
```

Set HORUS_GOV_LIVE_TESTS=1 to include tests against the running API/worker/Vite.
Set HORUS_GOV_LIVE_TRAINING=1 only to request a real three-round Kubernetes run.
Ledger tampering tests use temporary databases, never the active ledger.
Local tx_id values are not blockchain transaction hashes.