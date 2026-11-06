# O que mudou nos projetos-base (Scattered Directive, DYNAMOS e ExtremeXP)

Este documento resume o que o Horus **aproveitou**, **alterou** e
**acrescentou** em cada projeto que serviu de base. A referência é o último
commit do autor original do Scattered Directive: `028b9c2` (03/12/2025,
`DYNAMOS-UVA/Scattered-Directive`, branch `main`). Tudo o que está aqui foi
conferido comparando esse commit com o código atual.

## Resumo em uma tabela

| Projeto-base | O que é | O que fiz |
|---|---|---|
| **Scattered Directive** | Automação que instala o DYNAMOS no testbed FABRIC, mais o workload VFL/TTP de energia. | **Nada do original foi apagado ou reescrito.** Acrescentei um ambiente local (kind) para treino federado horizontal, com chart, scripts e coordenador próprios. |
| **DYNAMOS** (pasta `go/`) | Marketplace de dados: api-gateway, policy-enforcer, orchestrator, agentes e sidecars, ligados por RabbitMQ. | **Pequenas mudanças aditivas** (≈100 linhas em 13 arquivos) para aceitar um novo tipo de pedido, `mlTrainingRequest`. Todas ficam desligadas se `TRAINING_ENABLED` não for `true`. A lógica nova está em arquivos novos (≈860 linhas). |
| **ExtremeXP** (`extremexp_accesscontrol/`) | Controle de acesso ABAC com Keycloak e contratos Solidity (PAP, PIP, PDP) na Hyperledger Besu. | **Não alterei nada** e não executo o código. Aproveitei o **modelo conceitual** PAP / PIP / PDP, reimplementado em Hyperledger Fabric no módulo FHIR. |

Os módulos `horus-governance/`, `horus-fhir/` e `horus-sandbox-frontend/` são
novos: não vêm de nenhuma das bases.

---

## 1. Scattered Directive

### Aproveitado sem mudança

- Notebooks e scripts do testbed **FABRIC** (`fabric/`). Atenção: é o
  testbed de pesquisa FABRIC, não o Hyperledger Fabric.
- Workload **VFL / Shared Execution via TTP**: `VFL_*.py`,
  `house_energy_consumption/` e o caminho VFL dentro do orchestrator.
- Charts originais (`charts/agents`, `api-gateway`, `core`, `orchestrator`,
  `namespaces`, `thirdparty`...), `configuration/` original, `python/`
  original, `proto-files/` (exceto 3 campos, ver DYNAMOS), `web/`, `scripts/`,
  `docs/papers` e `docs/slides`.

Tudo isso continua no repositório, mas o Horus não aciona esse código.

### Acrescentado

| Caminho | Para quê |
|---|---|
| `charts/federated-training/` | Chart Helm do treino local: os serviços DYNAMOS em `training-system` e `core`, um agente por organização (UVA, VU, TUDELFT), NetworkPolicies e limites de recursos. |
| `configuration/federated-training/` | `manage.py` (setup, verify, forward), configuração do kind, Dockerfiles e testes do ambiente. |
| `python/federated-training/` | **training-coordinator** (FastAPI): FedAvg de regressão logística (`SGDClassifier`), rodadas, métricas e modelo final. Dados sintéticos deterministas. |
| `dev.sh` | Sobe o container `dynamos-dev`, com kind, kubectl e Helm. |
| `docs/` (novos `.md` e diagramas) | Guias, arquitetura, passo a passo e diagramas draw.io. |
| `readme.MD` | Seções novas sobre o Horus. O texto original foi mantido. |

### Não trazido para o repositório novo

`.devcontainer/`, `.github/`, `.gitattributes` e o `.gitignore` da raiz. São
metadados do repositório original; não há código nem regra de negócio
neles.

---

## 2. DYNAMOS (código Go em `go/` e `proto-files/`)

### Regra seguida

O comportamento original do DYNAMOS não mudou. Cada alteração entra num
**desvio condicional**: só age quando o pedido é do tipo `mlTrainingRequest`,
ou quando a variável `TRAINING_ENABLED=true` está ligada. Pedidos antigos
(por exemplo, `sqlDataRequest` e o VFL) seguem exatamente o mesmo caminho de
antes.

### Arquivos originais alterados

| Serviço | Arquivo | Mudança |
|---|---|---|
| Contrato de mensagens | `proto-files/rabbitMQ.proto` (+ `rabbitMQ.pb.go` regenerado) | Novo campo `training` (`google.protobuf.Struct`) em 3 mensagens: pedido de aprovação, resposta de validação e pedido de composição. |
| API comum | `go/pkg/api/http.go` | Campo `allowedAlgorithms` na relação usuário ↔ organização. |
| api-gateway | `cmd/api-gateway/main.go` | Registra a rota `/ml/` se `TRAINING_ENABLED`. |
| policy-enforcer | `cmd/policy-enforcer/generate_validation_response.go` | Para treino, cada organização confere tipo de pedido, dataset, **algoritmo permitido** e arquétipo. Se **uma** organização negar, o treino inteiro é negado. |
| orchestrator | `cmd/orchestrator/composition_request.go` | Para treino: arquétipo fixo `computeToData`, sem passar por `chooseArchetype`, e `JobName` = UUID novo. |
| orchestrator | `cmd/orchestrator/manage_jobs.go` | Valida a aprovação do treino antes de compor. Suporta a **revalidação** a cada rodada (`_ml_revalidate`), o que permite revogar no meio do treino. |
| agente | `cmd/agent/main.go`, `register_agent.go`, `consume.go`, `incoming_microservice_communication.go` | Rotas `/rounds` e `/health`, registro do agente de treino no etcd, tratamento de `mlTrainingRequest`. O cliente Kubernetes passa a ser criado no `main()`, não mais na declaração da variável. |
| sidecar | `cmd/sidecar/main.go`, `rabbit_ms_chain.go`, `rabbit_send.go` | Num Job temporário (`TEMPORARY_JOB`), o sidecar encerra depois de publicar o resultado, para o Job poder concluir. Envio de `mlTrainingRequest` com tempo máximo de 10 s. |

### Arquivos novos em `go/`

| Arquivo | Conteúdo |
|---|---|
| `pkg/training/training.go` | Tipo `Request` do treino, validação e `AllowedBy`. **Grant assinado (HMAC)** por execução, com `Sign` e `Verify`. |
| `cmd/api-gateway/training.go` | Endpoints `/ml/*`: inicia o treino (passando pelo policy-enforcer e pelo orchestrator), acompanha, cancela, baixa o modelo e faz proxy ao coordenador. |
| `cmd/orchestrator/training.go` | `validateTrainingApproval`: exige que **todas** as organizações escolhidas autorizem. |
| `cmd/agent/training.go` | Cria o **Job Kubernetes trainer + sidecar** de cada rodada, com dados locais `readOnly`, e valida a atualização local antes de devolvê-la. |
| `*_test.go` (5 arquivos) | Testes das partes acima. |

### Fluxo de treino

```
Horus → api-gateway /ml → policy-enforcer (cada organização autoriza o algoritmo)
      → orchestrator (computeToData, UUID) → agentes UVA/VU/TUDELFT
      → Job trainer + sidecar por rodada (dado não sai da organização)
      → atualização local via RabbitMQ → training-coordinator (FedAvg) → modelo global
```

---

## 3. ExtremeXP (`extremexp_accesscontrol/`)

### Situação

É um repositório próprio (submódulo Git, `extremexp-HORIZON/extremexp_accesscontrol`).
**Não foi alterado**: as únicas diferenças locais são arquivos `.DS_Store`
do macOS. Nenhum código dele é executado pelo Horus.

### Aproveitado: o modelo ABAC

O módulo FHIR (`horus-fhir/chaincode`) segue a mesma divisão de
responsabilidades do ExtremeXP, reimplementada em Go para o Hyperledger
Fabric:

| ExtremeXP (Solidity, Besu) | Horus FHIR (`fhir-abac`, Fabric) |
|---|---|
| `PAP.registerResource` / `registerPolicy` | `PAP:CreatePolicy`, `UpdatePolicy` e `BindResource` (política JSON declarativa) |
| `PIP.addResource(uri, contentHash)` | `PIP:PutResource(reportId, ..., reportHash, ...)` (hash SHA-256 do JSON canônico) |
| `PIP` (papel e grupo do usuário) | Atributo `role` no certificado da Fabric CA, preso ao MSP da organização |
| `PDP.evaluateRequest` | `PDP:RequestAccess` (nega por padrão, grava o motivo e emite um evento) |
| `SamplePolicy` (papel, horário, IP, local) | Regras da política: papel, organização, rótulo, consentimento, prazo e revogação |
| `KeycloakLogs` | `AuditEvent` FHIR com o txId e o índice de eventos `evt:` na ledger |
| (não existe) | **Consentimento** do paciente (`PutConsent` e `RevokeConsent`) |

### Não aproveitado, e por quê

1. **Governança SAST:** os contratos respondem "este usuário pode acessar
   este recurso?". A governança precisa provar "a organização sorteada
   analisou este código com as regras acordadas", que é outra pergunta.
2. **Sem controle de quem escreve:** qualquer conta pode chamar
   `PDP.setPAP/setPIP`, sobrescrever `registerResource` ou dar a si mesma um
   papel. Em confiança zero, isso não serve. No `fhir-abac`, cada função
   confere o papel e o MSP de quem assina, e o endosso exige Hospital **e**
   Lab.
3. **Infraestrutura:** a rede Besu não está no repositório (o código espera
   `localhost:8555`), e há gas e blocos periódicos. O Fabric já traz
   identidade por organização.
4. **Keycloak / login real:** fica para o futuro. No diagrama de contexto, ele
   aparece como "Provedor de identidade", fora do MVP.

---

## 4. O que é totalmente novo

| Módulo | Resumo |
|---|---|
| `horus-sandbox-frontend/` | Front-end Horus (React, Vite, Tailwind). Telas reais: Training, Ledger e Prontuário (FHIR). As demais telas são demonstrativas. |
| `horus-governance/` | Governança zero-trust: Fabric `horus-governance` (UVA, VU e TUDELFT), commit-reveal, sorteio da revisora, Semgrep num Job sem rede, relatório assinado e auditoria por re-execução. |
| `horus-fhir/` | Prontuário com consentimento: HAPI FHIR, PEP (FastAPI), chaincode `fhir-abac` e uma rede Fabric **separada** (Hospital + Lab), toda em Docker. |

---

## 5. Frases prontas para explicar

- "Usei o **Scattered Directive** como base de infraestrutura e não removi
  nada dele. O VFL/TTP e o FABRIC continuam lá. Acrescentei um ambiente local
  em kind para treino federado horizontal."
- "No **DYNAMOS**, criei um novo tipo de pedido, `mlTrainingRequest`, que
  percorre o mesmo caminho do marketplace: gateway → policy-enforcer →
  orchestrator → agentes. As mudanças nos arquivos originais são pequenas e
  condicionais. O resto está em arquivos novos, com testes."
- "Cada organização autoriza explicitamente o **algoritmo**. A autorização é
  revalidada a cada rodada, e o dado nunca sai da organização: o treino roda
  num Job dentro do namespace dela."
- "Do **ExtremeXP** aproveitei o modelo ABAC PAP / PIP / PDP. Reimplementei
  esse modelo no Hyperledger Fabric porque os contratos originais não
  controlam quem pode escrever, o que é essencial num cenário de confiança
  zero."

## Como conferir

Rode a partir da raiz do `Projeto Meiry`:

```bash
mkdir -p /tmp/upstream
git -C ../DYNAMOS_TUDelft_Test/Scattered-Directive archive 028b9c2 | tar -x -C /tmp/upstream
diff -rq /tmp/upstream . -x .git -x node_modules -x .DS_Store -x __pycache__ -x .venv -x .local
diff /tmp/upstream/go/cmd/orchestrator/manage_jobs.go go/cmd/orchestrator/manage_jobs.go
```
