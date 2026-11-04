import { FileLock2, Link as LinkIcon, ScrollText } from "lucide-react";
import Panel from "@/components/Panel";
import StatCard from "@/components/StatCard";
import FhirUnavailable from "@/components/fhir/FhirUnavailable";
import { useFhir } from "@/components/fhir/FhirLayout";
import { ErrorLine, PageTitle, RoleHint, TxLine, primary, useAction, useFhirData } from "@/components/fhir/common";
import { formatDate, postFhir } from "@/data/fhir";
import type { PolicyCatalog } from "@/types/fhir";

export default function FhirPolicies() {
  const { persona, unavailable } = useFhir();
  const catalog = useFhirData<PolicyCatalog>("/policies");
  const action = useAction();
  if (unavailable) return <FhirUnavailable />;

  const create = async () => { if (await action.run(() => postFhir(`/admin/policies?as=${persona?.id}`, {}))) catalog.reload(); };
  const policies = catalog.data?.policies ?? [];
  const bindings = catalog.data?.bindings ?? [];

  return (
    <div>
      <PageTitle title="Políticas (PAP)" subtitle="Regras declarativas em JSON, interpretadas pelo PDP. Trocar a política não exige reimplantar o chaincode. Sem política associada, a decisão é NEGAR." />
      <div className="mb-4.5 grid gap-3 sm:grid-cols-2">
        <StatCard title="Políticas" value={policies.length} footnote="gravadas no PAP (fhir-channel)" icon={<ScrollText size={16} className="text-navy-950" />} iconBg="#f1dcae" />
        <StatCard title="Recursos associados" value={bindings.length} footnote="resource:<id> ou label:<rótulo>" icon={<LinkIcon size={16} className="text-white" />} iconBg="#4b3f9e" />
      </div>
      {!policies.some(item => item.policyId === "ConsentRequiredPolicy") && (
        <Panel title="Passo 0: cadastrar ConsentRequiredPolicy" icon={<FileLock2 size={16} />}>
          <RoleHint persona={persona} expected="admin" who="o Administrador de políticas" />
          <button className={primary} disabled={action.busy} onClick={create}>{action.busy ? "Gravando…" : "Cadastrar política"}</button>
          <ErrorLine text={action.error} />
        </Panel>
      )}
      <ErrorLine text={catalog.error} />
      {policies.map(policy => (
        <Panel key={policy.policyId} title={`${policy.policyId} · v${policy.version}`} icon={<ScrollText size={16} />}>
          {policy.description && <div className="mb-2 text-[13px] text-ink-muted">{policy.description}</div>}
          <div className="mb-2 text-[12.5px]">Ações: <b>{policy.actions.join(", ")}</b> · todas as regras precisam valer:</div>
          <ul className="mb-3 ml-4 list-disc text-[12.5px]">
            {policy.rules.map((rule, index) => (
              <li key={index}><span className="font-mono">{rule.type}</span> {rule.value ? `= ${rule.value}` : `[${rule.checks?.join(", ")}]`}</li>
            ))}
          </ul>
          <div className="font-mono text-[11px] text-ink-faint">hash {policy.policyHash}</div>
          <TxLine txId={policy.txId}>por {policy.updatedBy} em {formatDate(policy.updatedAt)} ·</TxLine>
          <div className="mt-3 text-[12.5px] font-semibold text-ink">Recursos associados</div>
          <ul className="m-0 mt-1 flex list-none flex-col gap-1 p-0 text-[12.5px]">
            {bindings.filter(item => item.policyId === policy.policyId).map(item => (
              <li key={item.target} className="flex flex-wrap gap-2">
                <span className="font-mono">{item.target}</span>
                <span className="text-ink-faint">por {item.boundBy} · {formatDate(item.boundAt)} · tx {item.txId.slice(0, 12)}…</span>
              </li>
            ))}
            {!bindings.some(item => item.policyId === policy.policyId) && <li className="text-ink-faint">nenhum</li>}
          </ul>
        </Panel>
      ))}
    </div>
  );
}
