# horus-fhir

Full explanation, in Portuguese:
[docs/fhir-consentimento.md](../docs/fhir-consentimento.md).

Exam access control with patient consent: HL7 FHIR R4 (HAPI) plus ABAC
(PEP / PDP / PAP / PIP) on a **new, separate** Hyperledger Fabric network.
It shares nothing with the horus-governance ledger in the kind cluster.
All data is fictitious; no clinical data goes on-chain.

## Stage 1: local infrastructure

| Container | Role |
| --- | --- |
| `fhir-ca.hospital`, `fhir-ca.lab` | Fabric CA 1.5.22, one per organization |
| `fhir-orderer0.hospital` | The only Raft orderer, owned by HospitalMSP |
| `fhir-peer0.hospital`, `fhir-peer0.lab` | Fabric 2.5.16 peers |
| `fhir-hapi` | HAPI FHIR `v8.0.0`, R4, H2 in volume `fhir-hapi-data` |

- Network: `horus-fhir-net`.
- Volumes: `fhir-*`.
- Channel: `fhir-channel`. Writes need both organizations (MAJORITY of two).
- Ports: **none on the host.** FHIR is reachable only inside the network.
  Stage 3 adds the PEP as the only entry point.

Identities carry `role` in the certificate. The enrollment IDs are pseudonyms,
because the signer's certificate is stored in every block:

| ID | Organization | Role | Persona |
| --- | --- | --- | --- |
| `adm-001` | HospitalMSP | `admin` | policy administrator |
| `pat-001` | HospitalMSP | `patient` | João |
| `phy-001` | HospitalMSP | `physician` | Dra. Ana |
| `phy-002` | HospitalMSP | `physician` | Dr. Bruno |
| `lab-001` | LabMSP | `lab` | Laboratório |

Credentials live in `.local/wallet/`, node material in `.local/crypto/`, and
CA passwords in `.local/ca/`. All of `.local/` is git-ignored.

```bash
python3 tools.py start           # warns if kind/governance are running, never stops them
python3 tools.py status
python3 tools.py test-infra      # /fhir/metadata, channel height on both peers, no host ports
python3 tools.py test-isolation  # snapshot others -> start -> test -> down -> compare
python3 tools.py stop | down | reset-demo
```

`down` removes only the project's `fhir-*` containers and volumes (including
their anonymous volumes), `horus-fhir-net` and `.local/{crypto,wallet,channel,ca}`.
It refuses to run if the project contains anything without the `fhir-` prefix.

## Stage 2: chaincode `fhir-abac` (PAP / PIP / PDP)

There is one chaincode with three contracts. Functions are named
`<Component>:<Name>`, and the PDP reads the PAP and the PIP only through
reader interfaces. The code is in `chaincode/abac`, and
`chaincode/cmd/fhir-abac` runs it as a chaincode-as-a-service server.

| Component | Functions | Who may write |
| --- | --- | --- |
| PAP | `CreatePolicy`, `UpdatePolicy`, `GetPolicy`, `ListPolicies`, `BindResource(resource:<id> or label:<L>)`, `GetPolicyForResource` | `role=admin` (HospitalMSP) |
| PIP | `PutConsent`, `RevokeConsent`, `GetConsent`, `GetConsentFor`, `ListConsents` | `role=patient`, only for themselves |
| PIP | `PutResource(reportId, serviceRequestId, patientPseudo, reportHash, label, labId)`, `GetResource`, `ListResources` | `role=lab` (LabMSP), immutable |
| PDP | `RequestAccess(reportId, action)` (submit, records the decision, denials too), `GetDecision` | any member |

Other functions: `ListEvents` (audit index) and `WhoAmI`.

How it decides:

- **Roles.** Every role is pinned to its MSP: `admin`, `patient` and
  `physician` come from HospitalMSP, `lab` from LabMSP.
- **Policies.** A policy is declarative JSON interpreted by the PDP. The rule
  types are `subjectRole`, `subjectMsp`, `resourceLabel` and `consent`. The
  `consent` checks are `exists`, `grantee`, `patient`, `active` and `notExpired`.
- **Resolution.** A binding to the resource wins over a binding to its
  security label. With no binding, the answer is deny.
- **Denial reasons.** `UNKNOWN_RESOURCE`, `NO_POLICY`, `ACTION_NOT_ALLOWED`,
  `NOT_PHYSICIAN`, `WRONG_ROLE`, `WRONG_ORGANIZATION`, `LABEL_MISMATCH`,
  `NO_CONSENT`, `WRONG_GRANTEE`, `PATIENT_MISMATCH`, `REVOKED`, `EXPIRED`.
- **Expiry.** `validUntil` is checked against the transaction timestamp,
  never a local clock.
- **Hash checks.** The PEP compares content hashes; the chaincode never
  reads FHIR.

```bash
(cd chaincode && GOPROXY=off GOFLAGS=-mod=mod go test ./... -v)
python3 tools.py deploy-cc   # go test, offline build, scratch image fhir-abac:0.1.0,
                             # install, approve (both orgs), commit with AND(HospitalMSP.peer, LabMSP.peer)
python3 tools.py test-cc     # committed definition + decoded policy, queries on both peers,
                             # WhoAmI per persona, a refused write leaves the height unchanged
```

`deploy-cc` writes `.local/fabric.json`: channel, chaincode, version,
sequence, package IDs and endorsement policy. The package is deterministic,
so a rerun keeps the same package IDs. `reset-demo` runs down, start and
deploy-cc.

## Stage 3: middleware with the PEP (FastAPI) and fhir-gateway (Go)

```
Mac 127.0.0.1:8099 -> fhir-api (PEP; bearer token in .local/api-token)
                        |- fhir_client.py   -> fhir-hapi:8080 (internal only)
                        '- fabric_client.py -> fhir-gateway:8080 (internal, Fabric Gateway SDK, wallet)
```

Identity is **simulated**: `?as=<persona>` selects which wallet certificate
signs. This is not authentication (future: SMART on FHIR or Keycloak).

| Endpoint | Signs as | ABAC |
| --- | --- | --- |
| `POST /admin/policies` (`?update=true`) | `adm-001` | PAP `CreatePolicy` / `UpdatePolicy` |
| `POST /consents` / `POST /consents/{id}/revoke` | `pat-001` | FHIR `Consent`, then PIP `PutConsent` / `RevokeConsent` (FHIR status becomes `inactive`) |
| `POST /lab/results` | `lab-001`, then `adm-001` | FHIR Bundle (Observation, DiagnosticReport with `meta.security`, Provenance), then PIP `PutResource` and PAP `BindResource` |
| `GET /reports/{id}?as=…` | the persona | **PEP**, see below |
| `GET /consents`, `/results`, `/policies`, `/audit`, `/verify/{report\|consent}/{id}`, `/transactions/{tx}`, `/personas`, `/status` | - | queries for the front end |

What the PEP does for `GET /reports/{id}`:

1. It submits `PDP:RequestAccess`, so the decision is recorded on-chain.
2. Only on PERMIT, it reads the report from FHIR and compares two hashes:
   - the SHA-256 of the DiagnosticReport together with its Observations;
   - the PIP's `reportHash`.
3. It answers 200 with the resource, or 403 with only the reason. A wrong
   hash gives 403 `HASH_MISMATCH`.
4. In both cases it creates an `AuditEvent` with the Fabric tx ID and block.

The hashes use canonical JSON (sorted keys, UTF-8, no whitespace) of the
resource as read back from HAPI. The fields `meta.versionId`, `lastUpdated`,
`source` and `text` are left out. Exam identifiers on-chain are opaque
(`sr-001`, `dr-…`, `consent-…`).

```bash
python3 tools.py build      # offline Go build of fhir-gateway; fhir-api from pinned requirements.lock
python3 tools.py test-api   # unit tests, then one call per endpoint (PERMIT, NO_CONSENT, WRONG_GRANTEE),
                            # a tampered Observation (HASH_MISMATCH) and the PEP-bypass check
python3 tools.py reset-demo # clean channel and FHIR again (test-api writes to the ledger)
```

## Stage 4: end-to-end scenario

`scenario.py` uses only the Python standard library and talks only to the
PEP API. It runs steps 0 to 6 of the specification:

| Step | Who | What | ABAC |
| --- | --- | --- | --- |
| 0 | Admin | Policy | PAP |
| 1 | Dra. Ana | Orders exams A and B (`POST /service-requests`) | FHIR only |
| 2 | João | Consent | PIP |
| 3 | Laboratory | Results A and B, label R | PIP + PAP |
| 4 | Dra. Ana | Opens exam A | PERMIT |
| 5 | Dra. Ana | Opens exam B | DENY `NO_CONSENT` |
| extra | Dr. Bruno | Opens exam A | DENY `WRONG_GRANTEE` |
| 6 | PEP | Each AuditEvent with its on-chain tx, checked as VALID in its block | — |

For every step it prints the FHIR IDs, the ABAC component, the tx ID, the
block and the decision. For every access it also prints the decision trace:
PEP → PDP → PAP (policy) → PIP (attributes) → decision.

```bash
python3 scenario.py --reset            # clean channel + FHIR first
python3 scenario.py --reset --revoke   # extra: João revokes, Dra. Ana gets REVOKED
python3 scenario.py                    # on top of the current state (reuses the policy)
```

The exit status is 0 only if every decision is the expected one. The full
evidence (trace, timings, tx IDs, blocks) is in `.local/scenario-last.json`.

## Stage 5: front end (horus-sandbox-frontend)

The FHIR screens are a separate sidebar section, **"Prontuário (FHIR)"**.
The changes to existing files are additions only: a block in `Sidebar.tsx`,
one `<Route path="/fhir">` in `App.tsx`, and the `/fhir-api` proxy in
`vite.config.ts`, which sends the token from `horus-fhir/.local/api-token`
server-side.

| Route | Screen |
| --- | --- |
| `/fhir/consent` | João grants or revokes consent (Consent in FHIR, hash and attributes in the PIP) |
| `/fhir/lab` | The lab sends results (label R or N); "Verificar hash" per result |
| `/fhir/access` | Step 1 (orders), then open an exam: **PERMITIDO** with the Observations or **NEGADO** with the reason, plus the decision trail PEP → PDP → PAP → PIP → decision |
| `/fhir/policies` | PAP policies (rules, version, hash) and their bound resources; step 0 button |
| `/fhir/audit` | On-chain events plus off-chain AuditEvents, with "Verificar hash" and "Verificar tx" |

A bar at the top of every FHIR screen holds the persona selector (Admin,
João, Laboratório, Dra. Ana, Dr. Bruno), "Ledger: Fabric fhir-channel" and a
note that the identity is simulated.

If the PEP API is down, the FHIR screens show "serviço FHIR indisponível"
and the sandbox screens keep working. The FHIR screens never call
`/governance-api` or `/training-api`, so the reverse also holds. Code is in
`src/components/fhir/`, `src/pages/fhir/`, `src/data/fhir.ts` and
`src/types/fhir.ts`.

## Stage 6: tests, measurements and documentation

```bash
python3 tools.py test    # Go tests, pytest unit tests in fhir-api:0.1.0-test (no network),
                         # reset-demo, pytest integration tests from the Mac (.venv, pinned pytest)
python3 tools.py bench   # scenario --reset, measurements (app/bench.py inside fhir-api plus
                         # the PEP round trip from the Mac), then a clean scenario again
```

Results are written to `.local/bench-<timestamp>.json` and
`.local/bench-last.md`. The tables are in the "Medições" section of
`docs/fhir-consentimento.md`.
