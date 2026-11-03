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

## Horus Governance

The governance API/worker adds offline organization-local Semgrep analysis,
server-side reviewer selection, a validated algorithm catalog and a local
SQLite hash-chain ledger. Submitted algorithms are never executed. The
existing built-in training path remains unchanged behind an audited bridge.

See [governance setup](horus-governance/README.md) and the
[project structure, usage tests and monitoring guide](docs/governanca-estrutura-e-testes.md).
The real Ledger screen is at `/ledger`; the training screen includes code
submission/results. Besu is a future adapter, not an active blockchain backend.

## Setup

Practically everything is automated. The only thing you need to do is open the FABRIC Jupyter Notebook, clone this
repository into there, open `fabric/dynamos.ipynb` configure the preferred configuration of nodes and execute.
