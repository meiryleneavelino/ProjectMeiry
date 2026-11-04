# Guia de testes do Prontuário FHIR, etapa por etapa

Este guia parte de **tudo desligado** e mostra, para cada etapa do módulo
`horus-fhir`, o que digitar, o que deve aparecer e o que fazer se não
aparecer. A explicação da arquitetura está em
[fhir-consentimento.md](fhir-consentimento.md).

> **Importante:** para testar a parte FHIR **não é preciso** ligar o cluster
> kind, o treino nem a governança. Bastam o Docker Desktop, a pilha
> `horus-fhir` e o front-end. Deixar o kind desligado ainda libera ≈3 GB de
> memória.

## 0. Preparação (uma vez por terminal)

Abra o **Docker Desktop** e espere o ícone ficar verde. Depois, em cada
terminal:

```bash
cd "/Users/meiryleneavelino/Desktop/TUDelft/desenvolvimento/Projeto Meiry/horus-fhir"
D=/Applications/Docker.app/Contents/Resources/bin/docker
T=$(cat .local/api-token 2>/dev/null)
api() { curl -s -H "Authorization: Bearer $T" -H "Content-Type: application/json" "$@"; }
```

- `T` é o token da API do PEP. Ele é criado no primeiro `start` e não muda
  depois.
- `api` é só um atalho para o `curl` já com o token.

**Confira que não há clusters kind ligados.** Eles disputam CPU e memória, e
com eles o HAPI pode levar mais de 20 minutos para subir, ou nem subir:

```bash
"$D" ps --format '{{.Names}}' | grep control-plane
"$D" stop $("$D" ps --format '{{.Names}}' | grep control-plane)
```

O primeiro comando lista os clusters; se aparecer algum (por exemplo
`dynamos-control-plane`, `dynamos-training-control-plane` ou
`scattered-training-control-plane`), o segundo os para. Eles voltam com
`docker start <nome>`; o `stop` não apaga nada. O `tools.py start` também
avisa quando encontra clusters ligados.

Antes de começar, confira também que nada antigo está ocupando as portas:

```bash
lsof -nP -iTCP:8099 -sTCP:LISTEN    # vazio = livre (8099 é o PEP)
lsof -nP -iTCP:5175 -sTCP:LISTEN    # vazio = livre (5175 é o front)
```

Tempos aproximados de cada etapa:

| Etapa | Comando | Tempo |
|---|---|---|
| 1 | `tools.py start` | 1 a 2 min (o HAPI é lento para subir) |
| 2 | `tools.py deploy-cc` | ≈1 min |
| 4 | `scenario.py --reset` | 3 a 4 min (recria tudo antes) |
| 6 | `tools.py test` | ≈4 min |
| 6 | `tools.py bench` | ≈8 min |

**Não interrompa** esses comandos com Ctrl+C. Alguns ficam vários minutos sem
imprimir nada, e isso é normal.

---

## Etapa 1: infraestrutura (Fabric novo + HAPI FHIR)

### Subir

```bash
python3 tools.py start
```

**Esperado** (o aviso só aparece se o kind estiver ligado):

```
WARNING: other environments are running ... (not stopped by this tool)
1/5 CAs (fhir-ca.hospital, fhir-ca.lab)
2/5 identities (nodes + personas adm-001, pat-001, phy-001, phy-002, lab-001)
3/5 orderer and peers
4/5 channel fhir-channel
5/5 HAPI FHIR R4 (first start takes 1-2 minutes)
Ready: FHIR 4.0.1 at fhir-hapi:8080 (internal only), channel fhir-channel up.
```

Se o chaincode já tinha sido implantado (existe `.local/fabric.json`), o
`start` também sobe o chaincode, o gateway e a API e imprime
`fhir-gateway (internal) and fhir-api (PEP, http://127.0.0.1:8099) are up`.

### Testar

```bash
python3 tools.py status
python3 tools.py test-infra
```

**Esperado:**
- todos os contêineres `fhir-*` estão `Up`; o `fhir-hapi-init` aparece como
  `Exited (0)`, o que é normal;
- os dois peers estão na **mesma altura** do `fhir-channel`;
- o `test-infra` imprime três `OK`:
  - `GET /fhir/metadata`;
  - `peer channel getinfo` nos dois peers;
  - nenhuma porta publicada.

**Opcional, teste de não interferência:**

```bash
python3 tools.py test-isolation
```

Ele liga a rede FHIR, testa, desliga e compara tudo o que está **fora** dela.
Deve terminar com:

```
OK non-interference: containers, volumes, networks and kind pods outside horus-fhir are identical
```

Esse teste **termina com a rede FHIR desligada e apagada**. Depois dele, rode
`python3 tools.py start` e `python3 tools.py deploy-cc`.

### Observar

```bash
"$D" ps --filter label=com.docker.compose.project=horus-fhir --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
"$D" logs --tail 20 fhir-peer0.hospital
```

Na coluna `Ports`, só o `fhir-api` mostra `127.0.0.1:8099->8000/tcp`.

---

## Etapa 2: chaincode `fhir-abac` (PAP, PIP e PDP)

### Implantar (1ª vez, ou depois de `down`)

```bash
python3 tools.py deploy-cc
```

**Esperado:**

```
1/5 test + build fhir-abac:0.1.0 (offline, scratch image)
2/5 package + install on both peers (sequence 1)
3/5 chaincode containers fhir-cc.hospital, fhir-cc.lab
4/5 approve for HospitalMSP and LabMSP
    approvals: {'HospitalMSP': True, 'LabMSP': True}
5/5 commit (endorsed by both peers)
Deployed fhir-abac 0.1.0 sequence 1; saved .local/fabric.json
fhir-gateway (internal) and fhir-api (PEP, http://127.0.0.1:8099) are up
```

Se já estiver implantado, os passos 4 e 5 mostram
`already committed at sequence 1`.

### Testar

```bash
python3 tools.py test-cc
(cd chaincode && GOPROXY=off GOFLAGS=-mod=mod go test ./... -v 2>&1 | grep -E "^(--- |ok)")
```

**Esperado do `test-cc`** (9 linhas `OK`):
- a política de endosso decodificada como
  `2 out of [HospitalMSP.peer, LabMSP.peer] (AND)`;
- `WhoAmI` de cada persona com o papel certo, por exemplo
  `{"id":"pat-001","msp":"HospitalMSP","role":"patient"}`;
- `PAP:CreatePolicy as phy-001 refused ... height unchanged`.

**Esperado do `go test`:** 13 linhas `--- PASS`. Entre elas:
`TestPermitAnaExamA`, `TestDenyOtherExam`, `TestDenyOtherPhysician`,
`TestDenyExpired`, `TestDenyRevoked`, `TestDenyResourceWithoutPolicy` e
`TestOnlyThePatientWritesConsent`.

---

## Etapa 3: middleware com o PEP (API em 127.0.0.1:8099)

### Testar automaticamente

```bash
python3 tools.py test-api
python3 tools.py reset-demo     # este teste grava na ledger; limpe depois
```

**Esperado do `test-api`:** 15 linhas `OK`. Entre elas:
- `200 PERMIT` para a Ana no exame A;
- `403 NO_CONSENT` para a Ana no exame B;
- `403 WRONG_GRANTEE` para o Bruno no exame A;
- `tampered Observation in FHIR -> ... PEP refuses 403 HASH_MISMATCH`;
- `only fhir-api (127.0.0.1:8099) is published`.

### Testar à mão, um endpoint por vez

Faça isto num canal **limpo**, depois de `python3 tools.py reset-demo`.
Rode `T=$(cat .local/api-token)` de novo se for um terminal novo.

```bash
api http://127.0.0.1:8099/status | python3 -m json.tool
```

Esperado: `"fhir": {"ok": true, "fhirVersion": "4.0.1"}` e
`"chain": {"ok": true, "height": 4}`.

```bash
# Passo 0: Admin grava a política no PAP
api -X POST "http://127.0.0.1:8099/admin/policies?as=adm-001" -d '{}' | python3 -m json.tool | head -20
# Passo 1: Dra. Ana pede os exames (só FHIR)
api -X POST "http://127.0.0.1:8099/service-requests?as=phy-001" | python3 -m json.tool
# Passo 2: João consente só a Ana, só o exame A, 30 dias
api -X POST "http://127.0.0.1:8099/consents?as=pat-001" -d '{"serviceRequestId":"sr-001","grantee":"phy-001","days":30}' | python3 -m json.tool
# Passo 3: Laboratório grava os resultados A e B
api -X POST "http://127.0.0.1:8099/lab/results?as=lab-001" -d '{"serviceRequestId":"sr-001"}' | python3 -m json.tool
api -X POST "http://127.0.0.1:8099/lab/results?as=lab-001" -d '{"serviceRequestId":"sr-002"}' | python3 -m json.tool
```

Em cada resposta, confira `txId` e `blockNumber`: a altura sobe a cada
gravação. Agora pegue os IDs dos laudos e faça os acessos (passos 4 e 5):

```bash
A=$(api http://127.0.0.1:8099/results | python3 -c "import json,sys; print([r['id'] for r in json.load(sys.stdin) if r['serviceRequestId']=='sr-001'][-1])")
B=$(api http://127.0.0.1:8099/results | python3 -c "import json,sys; print([r['id'] for r in json.load(sys.stdin) if r['serviceRequestId']=='sr-002'][-1])")
echo "A=$A B=$B"

api -o /dev/null -w "Ana -> A: HTTP %{http_code}\n"   "http://127.0.0.1:8099/reports/$A?as=phy-001"   # 200
api -o /dev/null -w "Ana -> B: HTTP %{http_code}\n"   "http://127.0.0.1:8099/reports/$B?as=phy-001"   # 403
api -o /dev/null -w "Bruno -> A: HTTP %{http_code}\n" "http://127.0.0.1:8099/reports/$A?as=phy-002"   # 403
api "http://127.0.0.1:8099/reports/$B?as=phy-001" | python3 -m json.tool | head -12   # "reason": "NO_CONSENT", sem "resource"
```

Para auditar e verificar (passo 6):

```bash
api http://127.0.0.1:8099/audit | python3 -c "import json,sys; [print(e['source'], e['name'], e.get('txId','')[:12]) for e in json.load(sys.stdin)]"
api "http://127.0.0.1:8099/verify/report/$A" | python3 -m json.tool     # "match": true
```

Duas provas de que **o FHIR não é acessível sem passar pelo PEP**:

```bash
curl -s -m 2 http://127.0.0.1:8090/fhir/metadata || echo "8090 fechada: OK"
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8099/status   # 401 sem token
```

---

## Etapa 4: cenário de ponta a ponta

```bash
python3 scenario.py --reset            # 3-4 min: primeiro limpa e recria tudo, depois roda
python3 scenario.py --reset --revoke   # o mesmo, com o extra da revogação
```

Logo depois de `reset-demo (canal e FHIR limpos)…`, o script fica **minutos
sem imprimir nada**. É normal: ele está recriando a rede. Depois imprime os
passos 0 a 6 e um resumo.

**Esperado no final:**

```
━━ Resumo
   OK  PERMIT         tx …  bloco 10
   OK  NO_CONSENT     tx …  bloco 11
   OK  WRONG_GRANTEE  tx …  bloco 12
   OK  REVOKED        tx …  bloco 14      (só com --revoke)
   altura final do fhir-channel: 13 (ou 15 com --revoke)
   evidência completa: .local/scenario-last.json
```

Depois do comando, `echo $?` deve dar `0`, o que significa que todas as
decisões foram as esperadas. Nos passos 4 e 5 aparece o **rastro da
decisão**: PEP → PDP → PIP (atributos do recurso) → PAP (política) → regras →
PIP (consentimento) → decisão → conferência do hash.

---

## Etapa 5: telas no front-end

### Ligar o front

O front precisa ser **desta pasta** (Projeto Meiry), porque só ela tem a
seção nova. Num terminal próprio, a partir da raiz do projeto:

```bash
cd "/Users/meiryleneavelino/Desktop/TUDelft/desenvolvimento/Projeto Meiry"
npm --prefix horus-sandbox-frontend run dev -- --strictPort
```

Esperado: `Local: http://127.0.0.1:5175/`. Deixe este terminal aberto.

Em outro terminal, confira o proxy do FHIR:

```bash
curl -s http://127.0.0.1:5175/fhir-api/status
```

Esperado: um JSON com `"ledger":"Fabric fhir-channel"`. Se der erro, veja a
seção [Problemas comuns](#problemas-comuns).

### Roteiro de cliques (num canal limpo: `python3 tools.py reset-demo`)

Abra **http://127.0.0.1:5175/fhir/policies**. No menu à esquerda aparece o
bloco **"PRONTUÁRIO (FHIR)"**. No topo da página fica a barra **Persona** e
"Ledger: Fabric fhir-channel · altura N".

| # | Persona (barra do topo) | Tela | Ação | Deve aparecer |
|---|---|---|---|---|
| 0 | **Administrador de políticas** | Políticas (PAP) | "Cadastrar política" | Cartão `ConsentRequiredPolicy · v1`, com as regras e o hash |
| 1 | **Dra. Ana** | Acesso ao exame | "Solicitar exames A e B" | Exame A (`sr-001`) e Exame B (`sr-002`) na lista de pedidos |
| 2 | **João (paciente)** | Consentimento | Exame A · Dra. Ana · 30 dias → "Consentir" | Faixa verde "Consent … gravado no PIP", com a tx e o bloco; a linha aparece na tabela como `active` |
| 3 | **Laboratório** | Laboratório | Pedido Exame A · R → "Enviar resultado"; depois Exame B · R | Faixa verde com o DiagnosticReport, o hash, PIP e PAP; dois resultados na tabela; "Verificar hash" → "hash confere" |
| 4 | **Dra. Ana** | Acesso ao exame | Exame A → "Abrir como Dra. Ana" | **PERMITIDO**, com o rastro PEP → PDP → PAP → PIP e a tabela do hemograma |
| 5 | **Dra. Ana** | Acesso ao exame | Exame B → "Abrir" | **NEGADO**, motivo **NO_CONSENT**, sem conteúdo |
| extra | **Dr. Bruno** | Acesso ao exame | Exame A → "Abrir" | **NEGADO**, motivo **WRONG_GRANTEE** |
| 6 | qualquer | Auditoria | "Verificar hash" e "Verificar tx" | Os contadores (on-chain, AuditEvents, permitidos, negados) e `hash confere` / `tx: VALID · bloco N` |
| revogação | **João (paciente)** | Consentimento | "Revogar" | Status na ledger muda para `revoked`; a Dra. Ana passa a receber **NEGADO (REVOKED)** no exame A |

Se você já rodou `scenario.py`, os passos 0 a 3 já estão feitos. Vá direto
para o passo 4.

Se escolher uma persona "errada" para a tela, aparece um aviso amarelo, mas o
envio continua liberado. Assim dá para ver a **recusa vinda do chaincode**,
por exemplo a Dra. Ana tentando consentir.

### Teste de indisponibilidade (opcional)

```bash
"$D" stop fhir-api      # as telas FHIR mostram "serviço FHIR indisponível"; /training e Dashboard continuam
"$D" start fhir-api     # clique em "Tentar de novo" na faixa vermelha
```

---

## Etapa 6: testes automáticos e medições

```bash
python3 tools.py test     # ≈4 min
```

**Esperado:**

```
OK Go tests (chaincode PAP/PIP/PDP, gateway)
17 passed …
OK pytest unit tests of the middleware (in fhir-api:0.1.0-test, no network)
reset-demo: integration tests need a clean channel and FHIR
20 passed …
OK pytest integration tests (from the Mac).
```

Os testes de integração precisam de canal limpo, e por isso o comando faz
`reset-demo` sozinho.

```bash
python3 tools.py bench    # ≈8 min; deixa um cenário limpo no fim
cat .local/bench-last.md
```

**Esperado:** três tabelas:
1. `RequestAccess`: total ≈1 s, quase tudo "espera do commit";
2. consultas ao PAP e ao PIP: ≈1 a 2 ms;
3. vazão: ≈1, 5 e 180 pedidos/s com concorrência 1, 5 e 10.

---

## Desligar

```bash
python3 tools.py stop    # para os contêineres; dados, ledger e credenciais ficam
# ou
python3 tools.py down    # apaga TUDO que é fhir- (rede, volumes, credenciais); depois exige start + deploy-cc
```

O front para com **Ctrl+C** no terminal do `npm run dev`.

Para voltar depois de um `stop`:

```bash
python3 tools.py start
```

Ele sobe tudo de novo, inclusive o chaincode, o gateway e a API, porque o
`.local/fabric.json` existe.

---

## Problemas comuns

| Sintoma | Causa | O que fazer |
|---|---|---|
| Tela FHIR com a faixa vermelha **"serviço FHIR indisponível"** | O `fhir-api` (8099) não está rodando | `python3 tools.py status`. Se o `fhir-api` não aparecer: `python3 tools.py start`; se ainda faltar, `python3 tools.py deploy-cc` |
| Menu sem o bloco **"Prontuário (FHIR)"**, ou `/fhir/access` em branco | O front está rodando a partir de **outra pasta** (por exemplo `DYNAMOS_TUDelft_Test/Scattered-Directive`), que não tem a seção nova | `lsof -a -p $(lsof -t -iTCP:5175 -sTCP:LISTEN) -d cwd` mostra a pasta. Pare esse front (Ctrl+C no terminal dele) e suba a partir de `Projeto Meiry` |
| `curl 127.0.0.1:5175/fhir-api/status` dá erro, mas `api http://127.0.0.1:8099/status` funciona | O front foi iniciado antes do proxy novo existir | Reinicie o `npm run dev` |
| `curl: (7) Failed to connect to 127.0.0.1 port 8099` | A pilha FHIR está desligada, ou foi feito `down` | `python3 tools.py start` e, se preciso, `python3 tools.py deploy-cc` |
| `{"detail":"invalid API token"}` | Faltou o token no `curl` | Use o atalho `api` da preparação (`T=$(cat .local/api-token)`) |
| `scenario.py` "travado" depois de `reset-demo …` | Ele está recriando a rede (3-4 min) | Espere; não aperte Ctrl+C |
| `scenario.py` termina com `ERRO` num acesso | O canal tem dados de testes anteriores (por exemplo outro consentimento) | Rode com `--reset` |
| `HAPI FHIR did not answer /fhir/metadata in time` | **Docker sem CPU ou memória**, quase sempre por clusters kind ligados (inclusive os antigos `dynamos-control-plane` e `dynamos-training-control-plane`). Nos logs do HAPI aparecem `Thread starvation` e intervalos de vários minutos | 1. `"$D" stats --no-stream`; 2. `"$D" stop $("$D" ps --format '{{.Names}}' \| grep control-plane)`; 3. `"$D" restart fhir-hapi`; 4. `python3 tools.py start` |
| `failed: …compose… secret file … does not exist` | `.local` foi apagado à mão | `python3 tools.py start` recria os segredos |
| Lista de consentimentos ou resultados "atrasada" | Cache de busca do HAPI | Já tratado (`no-cache`); clique em atualizar, ou mude de tela e volte |

## Onde ficam as evidências

| Arquivo | Conteúdo |
|---|---|
| `horus-fhir/.local/scenario-last.json` | Último cenário: IDs, txIds, blocos, rastros e tempos |
| `horus-fhir/.local/bench-*.json` e `bench-last.md` | Medições |
| `horus-fhir/.local/fabric.json` | Canal, chaincode, versão, sequência e package IDs |
| Tela `/fhir/audit` | Linha do tempo on-chain + off-chain, com verificação |
