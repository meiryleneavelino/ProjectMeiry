# Scattered Directive

## Complete Horus Guide

Start with the [complete code, testing and observation guide](docs/HORUS_GUIA_COMPLETO.md)
for the current local Horus implementation: architecture, file map, startup,
SAST, ledger, real federated training, tests, monitoring and recovery limits.

Welcome to Scattered Directive. This is an automated and reproducible framework to deploy the digital data marketplace
platform [DYNAMOS](https://github.com/Jorrit05/DYNAMOS) on the [FABRIC](https://portal.fabric-testbed.net) Research
Infrastructure.

Scattered Directive automates the entire setup, from requesting nodes to configuring and deploying DYNAMOS with the
relevant relations to the nodes all defined. This allows researchers and developers (you!) to utilise DYNAMOS without
any hassle.

To prove our implementation of Scattered Directive, we utilised it to implement a Vertical Federated Learning workload,
creating a new archetype to support shared execution of the global model training on a trusted third party. This
archetype is aptly named *Shared Execution via TTP*.

## Horus and Local Federated Training

The local DYNAMOS training integration is now available inside this directory:
Horus, the Go gateway/policy-enforcer/orchestrator/agents, trainer-sidecar Jobs,
RabbitMQ, application etcd, and a separate Kubernetes sandbox.

See [the operation guide](docs/horus-federated-training.md) for setup, tests,
architecture, and limitations. The existing FABRIC notebooks and VFL/TTP
workload are preserved. The Horus training screen currently runs horizontal
FedAvg on synthetic data, not the energy VFL/TTP workload.

See [the current architecture](docs/arquitetura-atual.md) for rendered diagrams,
component responsibilities, the execution sequence, and the exact monitoring
status. Prometheus/Grafana/Jaeger are not installed in the current sandbox.

For a complete live walkthrough, follow the
[step-by-step observation guide](docs/passo-a-passo-observar-treinamento.md):
watch Pods and Jobs, correlate run IDs, inspect sidecars, authorization,
storage, networking, broker state, metrics, cancellation and final artifacts.

From this directory, start the self-contained tools with `bash dev.sh` before
following the operation guide. No files from the previous parent project are
required for the local horizontal training workflow.

## Horus Governance (zero trust)

Submitted algorithms are never executed. Their governance follows a
zero-trust model: no organization, and not the Horus server, has to be
trusted on its own.

- A Hyperledger Fabric 2.5 channel (`horus-governance`) is run by UVA, VU and
  TUDELFT inside their own namespaces: one CA, peer, Raft orderer, chaincode
  and SAST agent per organization.
- The eligible organizations draw the reviewer together (commit-reveal in the
  chaincode); the researcher's organization comes from the researcher's certificate and is
  excluded.
- The drawn organization runs Semgrep in an ephemeral, network-less Kubernetes
  Job in its own namespace and records the report signed with its identity.
  The chaincode checks the signer, rules, policy, image digest and recomputes
  the score.
- The other eligible organizations re-run the deterministic analysis; a
  different report hash marks the submission as disputed.

Start with `python3 tools.py ledger setup` in `horus-governance/`. See
[the ledger, step by step (Portuguese)](docs/ledger-fabric-e-sast-local.md),
[governance setup](horus-governance/README.md) and the
[project structure, usage tests and monitoring guide](docs/governanca-estrutura-e-testes.md).
The `extremexp_accesscontrol` contracts are not used (see section 12 of the
ledger document). Note: the `fabric/` folder is the FABRIC testbed, unrelated
to Hyperledger Fabric.

## Running and testing everything

To start and test all three parts (training, governance and FHIR), follow
[docs/como-rodar-e-testar-tudo.md](docs/como-rodar-e-testar-tudo.md) (in
Portuguese).

The full architecture is in
[docs/diagrams/drawio/horus-arquitetura-completa.drawio](docs/diagrams/drawio/horus-arquitetura-completa.drawio),
with three pages: overview, FHIR module, and how to run and test.

## Horus FHIR: consent-based exam access (separate Fabric network)

`horus-fhir/` adds controlled access to exam results, based on patient
consent. It uses HL7 FHIR R4 resources (HAPI) and ABAC in the XACML style:

- **PEP:** a middleware that sits in front of FHIR and enforces decisions.
- **PDP, PAP and PIP:** chaincode contracts.

It runs on a **new, separate Hyperledger Fabric network** (`fhir-channel`,
with HospitalMSP and LabMSP). Clinical data stays in FHIR; the ledger holds
only pseudonymous IDs, hashes, deadlines and decisions. All data is
fictitious. The FHIR screens are the "Prontuário (FHIR)" section of the
Horus front end.

- Explanation, in Portuguese:
  [docs/fhir-consentimento.md](docs/fhir-consentimento.md) (architecture,
  FHIR ↔ contract mapping, how to run and observe, tests, measurements,
  limitations).
- Commands: [horus-fhir/README.md](horus-fhir/README.md).

## Setup

Practically everything is automated. The only thing you need to do is open the FABRIC Jupyter Notebook, clone this
repository into there, open `fabric/dynamos.ipynb` configure the preferred configuration of nodes and execute.
