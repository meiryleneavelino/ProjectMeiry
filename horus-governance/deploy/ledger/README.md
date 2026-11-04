# Horus ledger deployment (Hyperledger Fabric 2.5)

`setup.py` and `chart/` deploy one Fabric organization per namespace (`uva`,
`vu`, `tudelft`) into the existing `kind-scattered-training` cluster. The
namespaces come from the training chart; this chart only adds Pods, Services,
PVCs, ConfigMaps, RBAC and NetworkPolicies labeled `app=horus-ledger`.

Explanation of every step (Portuguese):
[docs/ledger-fabric-e-sast-local.md](../../../docs/ledger-fabric-e-sast-local.md).

## Per organization

| Object | Purpose |
| --- | --- |
| `ledger-ca` (Deployment, Service `ca`, PVC `ledger-ca`) | Fabric CA 1.5.22 with TLS; bootstrap password from Secret `ledger-ca-bootstrap`. |
| `ledger-enroll` (Job, `files/enroll.sh`) | Registers/enrolls peer0, orderer0, orgadmin, sast-agent (+ researcher in tudelft) into PVC `ledger-crypto`; writes `/crypto/public`. |
| `orderer0` | Raft consenter, channel participation API on 7053 (mutual TLS). |
| `peer0` | LevelDB state, gateway enabled, chaincode-as-a-service builder. Readiness uses TCP 7051 because `/healthz` checks a Docker daemon. |
| `ledger-admin` | fabric-tools console with only the admin identity and public material. |
| `horus-chaincode` | Rendered only once the package ID for that organization is known. |
| `horus-sast-agent` | ServiceAccount + Role (ConfigMaps, Jobs, pods, pods/log in its namespace). |
| `horus-ledger-gateway` | Only for the organization with `researcher: true`. |

Each Pod mounts only its own identity via `subPath`. All ledger PVCs carry
`helm.sh/resource-policy: keep`.

NetworkPolicies: peers/orderers accept 7050/7051/7053 only from ledger
components in the three namespaces; the CA only from its enrollment Job; the
chaincode only from its own peer; analysis Pods (`app=horus-sast`) get no
ingress and no egress; the agent may reach the API server.

## setup.py steps

1. Build `horus-ledger:local` and the analyzer images (skip with `--skip-build`).
2. Compute the agreed configuration (`.local/ledger/governance.json`).
3. Load images into kind (multi-platform images are exported for the local
   platform and imported with `ctr`; images already on the node are skipped).
4. Create `ledger-ca-bootstrap` per namespace and `ledger-gateway-token`.
5. Helm install CA, enrollment, orderer, peer and admin console.
6. Collect `/crypto/public` from every organization (refused if a key is found).
7. Generate the genesis block in the researcher organization's console.
8. `osnadmin channel join` per orderer; wait for three active consenters.
9. `peer channel join` per peer.
10. Build a deterministic ccaas package per organization, install it (or reuse
    the package ID that organization already approved) and start the chaincode.
11. `approveformyorg` per organization; commit with MAJORITY endorsement.
12. `InitConfig`: each organization's chaincode compares it to its own copy.
13. Start agents and gateway; cross-check heights, block hashes and configuration.

Re-running is safe. Channel/chaincode settings: channel `horus-governance`,
chaincode `horus-governance` version 1.0 sequence 1, BatchTimeout 1 s,
MaxMessageCount 10, application capability V2_5.

## Commands (from `horus-governance/`)

```bash
python3 tools.py ledger setup [--skip-build]
python3 tools.py ledger forward [--background]
python3 tools.py ledger verify
python3 tools.py ledger status
python3 tools.py ledger down [--purge]
```

The chart is copied into the `dynamos-dev` container with `docker cp` before
`helm upgrade`, so it works whichever checkout that container mounts.
`HORUS_KIND_CLUSTER` and `DYNAMOS_DEV_CONTAINER` override the defaults.
