# Horus — Federated Learning Sandbox (front-end skeleton)

Esqueleto de front-end em **React + TypeScript + Vite + Tailwind CSS**, com o Dashboard já
funcional (dados mock) e as demais telas do sistema (Novo Job, Meus Jobs, Autorizações, Ledger,
Modelos, Dados & Datasets, Segurança, Relatórios, Configurações) já roteadas como stubs prontos
para você preencher.

## Scattered Directive

A rota `/training` esta conectada ao treinamento horizontal DYNAMOS; as outras
telas usam dados demonstrativos. O VFL/TTP original ainda nao e disparado pelo
Horus. Consulte o [guia de operacao](../docs/horus-federated-training.md) para
preparar o cluster separado e expor o gateway na porta 8096.

## Como rodar

Pré-requisito: Node.js 18+ instalado.

```bash
npm install
npm run dev
```

Abra http://127.0.0.1:5175/training no navegador. O Visual Studio Code detecta o projeto normalmente ao
abrir esta pasta (`code .`); recomenda-se instalar a extensão **ESLint** e a **Tailwind CSS
IntelliSense**.

Outros scripts:

```bash
npm run build     # build de produção em dist/
npm run preview   # serve o build de produção localmente
```

## Estrutura

```
src/
  components/        componentes reutilizáveis (StatCard, Panel, JobsTable, ...)
    charts/          gráficos (Recharts)
  data/mock.ts        dados de exemplo — ÚNICO lugar a trocar por chamadas reais de API
  pages/              uma página por rota (Dashboard.tsx é a mais completa)
  types/index.ts      tipos que espelham o contrato do back-end
  App.tsx             layout + rotas (react-router-dom)
  main.tsx            entrypoint
```

## Como conectar as demais telas ao back-end real

Fora de `/training`, `src/data/mock.ts` exporta arrays estáticos. Quando o back-end (PIP/PDP/PEP/PAP + ledger)
existir, o padrão recomendado é:

1. Trocar cada `export const mockX = [...]` por uma função assíncrona, ex.:

   ```ts
   export async function fetchJobs(): Promise<TrainingJob[]> {
     const res = await fetch("/api/jobs");
     if (!res.ok) throw new Error("Falha ao buscar jobs");
     return res.json();
   }
   ```

2. Instalar `@tanstack/react-query` e trocar o uso direto do array mock, dentro dos componentes de
   página, por `useQuery({ queryKey: ["jobs"], queryFn: fetchJobs })`.
3. Os componentes de apresentação (`JobsTable`, `AuthorizationsPanel`, etc.) não precisam mudar —
   eles já recebem os dados via props tipadas.

## Stack e porquê

- **React + TypeScript**: tipagem forte para os contratos de Job/Authorization/LedgerEvent que
  vêm do back-end de smart contracts.
- **Vite**: dev server rápido, build moderno.
- **Tailwind CSS**: tokens de cor da marca Horus já configurados em `tailwind.config.js`
  (`navy`, `gold`, `violet`, `status.*`) — evite cores soltas fora desses tokens.
- **Recharts**: gráficos declarativos, idiomáticos em React.
- **lucide-react**: ícones outline consistentes com o resto da UI.
- **react-router-dom**: uma rota por item do menu lateral.
