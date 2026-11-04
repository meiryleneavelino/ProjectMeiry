# Horus e treinamento federado no Scattered Directive

Diagramas e explicacao dos componentes, inclusive monitoracao, estao na
[arquitetura atual](arquitetura-atual.md).

## Escopo

Esta adaptacao reutiliza os servicos Go do Scattered Directive. Nao substitui
seu fluxo VFL/TTP, os notebooks FABRIC, os datasets de energia ou o frontend
original em `web/`. A nova interface esta em `horus-sandbox-frontend/`.

O fluxo integrado ao Horus e horizontal: regressao logistica com FedAvg,
dados sinteticos locais de UVA, VU e TUDELFT. Integrar a interface ao treinamento
vertical de energia e implantar esse fluxo no FABRIC ainda sao trabalhos separados.
As outras telas do Horus continuam usando dados demonstrativos, exceto a
validacao de algoritmos e a tela Ledger, que usam o ledger Hyperledger Fabric
de governanca ([ledger Fabric e SAST local](ledger-fabric-e-sast-local.md)).
O inicio de treino pela governanca grava `TrainingStarted` nesse ledger.

## Arquitetura

```text
Horus -> API Gateway -> sidecar/RabbitMQ -> policy-enforcer
                                      -> orchestrator -> agentes Go
      -> coordenador Python -> agentes -> Jobs trainer + sidecar
      -> agregacao FedAvg -> modelo global -> download autorizado
```

- `training-system`: gateway, policy-enforcer, orchestrator e coordenador.
- `core`: RabbitMQ e tres membros do etcd da aplicacao.
- `uva`, `vu`, `tudelft`: agente permanente com sidecar e Jobs por rodada.
- Cada trainer monta apenas seu dataset, em modo somente leitura.
- A aprovacao exige todas as organizacoes, dataset, algoritmo e computeToData.
- A autorizacao e revalidada entre rodadas e antes do download do modelo.
- O protocolo adiciona campos opcionais; `Request` e as rotas VFL sao mantidos.

## Requisitos

Docker Desktop em execucao, Node.js 18+ e Python 3. O projeto inclui suas
proprias ferramentas Docker CLI, kind, kubectl e Helm 4. Na raiz de
Scattered-Directive, criar o container de ferramentas com:

```bash
bash dev.sh
```

O launcher constroi `scattered-dev-tools:local` e inicia `dynamos-dev`, montando
apenas esta pasta em `/workspace/Scattered-Directive`, o kubeconfig e o socket
Docker. Depois da primeira construcao pode-se usar `bash dev.sh --no-rebuild`.
Os comandos Helm usam `--force-conflicts`; nao dependem de arquivos da raiz antiga.

Os comandos abaixo sao executados na raiz de `Scattered-Directive/` no Mac.
Se esta pasta for montada diretamente em `/workspace`, configure antes:

```bash
export SCATTERED_CONTAINER_ROOT=/workspace
```

O padrao e `/workspace/Scattered-Directive`. `DYNAMOS_DEV_CONTAINER` e `DOCKER_BIN`
permitem selecionar outro container de ferramentas e executavel Docker.
O launcher tambem respeita `SCATTERED_CONTAINER_ROOT`.

Com 4 CPUs e 8 GB no Docker, os tres clusters simultaneos causaram saturacao
e timeouts. Para a validacao desta adaptacao, os containers dos clusters
`dynamos-control-plane` e `dynamos-training-control-plane` foram parados com
autorizacao, sem exclusao de containers, volumes ou dados. Evite iniciar os
tres juntos sem aumentar os recursos do Docker.

## Executar

Preparar imagens, cluster, dados sinteticos e verificacao de isolamento:

```bash
python3 configuration/federated-training/manage.py setup
```

O cluster e `kind-scattered-training`. As imagens sao
`scattered-federated-training:local` e `scattered-integrated-services:local`.
O comando nao implanta no cluster original nem no `kind-dynamos-training`.
Credenciais proprias ficam em `configuration/federated-training/.local/`,
ignorada pelo Git; nao copiar as credenciais da instalacao anterior.

A preparacao valida e reutiliza um dataset existente sem sobrescrever o arquivo.
Se um Job `training-seed` falhar por prazo durante a primeira inicializacao,
investigue seus logs antes de recriar somente esse Job. Arquivos incompletos
ou invalidos sao rejeitados; nao apague o volume para contornar essa verificacao.

Em outro terminal, expor apenas o gateway em localhost:

```bash
python3 configuration/federated-training/manage.py forward
```

Iniciar o Horus em outro terminal:

```bash
npm --prefix horus-sandbox-frontend ci
npm --prefix horus-sandbox-frontend run dev -- --strictPort
```

Abrir <http://127.0.0.1:5175/training>. O proxy local usa a API em
`http://127.0.0.1:8096/api/v1/ml` e injeta o token no servidor Vite,
nao no bundle do navegador. O coordenador nao e exposto diretamente.

Selecionar UVA/VU/TUDelft, tres rodadas e duas epocas locais. O download so e
liberado apos conclusao e nova autorizacao. Cancelar remove os Jobs rastreados.

Consultar recursos ou repetir a verificacao de isolamento:

```bash
python3 configuration/federated-training/manage.py status
python3 configuration/federated-training/manage.py verify
```

## Validar

Testes locais, sem cluster:

```bash
python3 -m unittest discover -s configuration/federated-training -p 'test_manage.py' -v
python3 -m venv /tmp/scattered-training-venv
/tmp/scattered-training-venv/bin/pip install -r python/federated-training/requirements.txt
/tmp/scattered-training-venv/bin/python -m unittest discover -s python/federated-training -p 'test_*.py' -v
cd go
go test ./pkg/training ./cmd/agent ./cmd/api-gateway ./cmd/orchestrator ./cmd/policy-enforcer ./cmd/sidecar
cd ..
npm --prefix horus-sandbox-frontend run build
```

Com setup concluido, port-forward ativo e nenhuma execucao pela interface:

```bash
python3 configuration/federated-training/test_integrated.py
```

Esse teste altera temporariamente o acordo sintetico de TUDELFT e o restaura
em blocos `finally`. Verifica negacao antes de criar Jobs, tres organizacoes,
tres rodadas, trainer/sidecar, resultados via RabbitMQ e revogacao. Se o processo
for morto abruptamente, conferir o acordo antes de voltar a usar a interface.

## Limites e verificacao desta adaptacao

Em 29/10/2026, o setup e a verificacao de isolamento passaram no cluster
`kind-scattered-training`. O teste integrado completou tres rodadas com UVA,
VU e TUDELFT, verificou trainer/sidecar, resultados via RabbitMQ, download do
modelo global e negacao antes da execucao e apos revogacao. A execucao em curso
tambem parou na revalidacao de politica. O Horus mostrou isolamento verificado
e a execucao concluida com download habilitado.

Dez testes Python de modelo/servico, dois testes do gerenciador, testes Go,
build do Horus e lint do chart passaram. Os relatorios locais ficam em
`configuration/federated-training/.local/isolation-report.json`,
`integration-report.json` e `training-report.json`. Isso valida o sandbox
horizontal, nao a integracao VFL/TTP ou a implantacao FABRIC.

Os dados sao sinteticos. Nao ha secure aggregation, differential privacy, OIDC,
TLS de producao nem isolamento contra administradores do cluster. Atualizacoes
de modelo e metricas nao sao garantias de privacidade. Revogacao e aplicada nas
fronteiras de revalidacao, nao interrompe imediatamente um trainer em execucao.
O deployment FABRIC original nao e atualizado pelo gerenciador local.

## Estrutura apos a limpeza

A pasta-pai da workspace contem somente `Scattered-Directive/`. Os arquivos
do projeto antigo, incluindo seu repositorio Git, foram movidos para
`~/.Trash/DYNAMOS-antigo-2026-10-29`, sem alterar o repositorio Git deste projeto.
Os dois clusters antigos continuam parados e preservados; o cluster ativo e
`kind-scattered-training`. A limpeza de arquivos nao descartou seus volumes.

Depois dessa limpeza, o proxy Horus respondeu HTTP 200 e o teste integrado
passou novamente: tres organizacoes, tres rodadas, modelo global, sidecars,
RabbitMQ e revogacao. As ferramentas agora sao construidas inteiramente a partir
de `configuration/federated-training/Dockerfile.tools` deste projeto.