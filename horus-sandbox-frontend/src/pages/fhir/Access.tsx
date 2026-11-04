import { useEffect, useState } from "react";
import { ClipboardList, Eye, Route } from "lucide-react";
import Panel from "@/components/Panel";
import FhirUnavailable from "@/components/fhir/FhirUnavailable";
import DecisionTrace from "@/components/fhir/DecisionTrace";
import { useFhir } from "@/components/fhir/FhirLayout";
import { ErrorLine, PageTitle, RoleHint, input, primary, secondary, useAction, useFhirData } from "@/components/fhir/common";
import { fhirApi, postFhir } from "@/data/fhir";
import type { AccessOutcome, ResultItem, ServiceRequestItem } from "@/types/fhir";

export default function FhirAccess() {
  const { persona, unavailable } = useFhir();
  const orders = useFhirData<ServiceRequestItem[]>("/service-requests");
  const results = useFhirData<ResultItem[]>("/results");
  const [report, setReport] = useState("");
  const [outcome, setOutcome] = useState<{ value: AccessOutcome; reportId: string; persona: string } | null>(null);
  const action = useAction();
  const registered = (results.data ?? []).filter(item => item.onChain);
  useEffect(() => { if (!report && registered.length) setReport(registered[0].id); }, [registered, report]);
  if (unavailable) return <FhirUnavailable />;

  const order = async () => { if (await action.run(() => postFhir(`/service-requests?as=${persona?.id}`))) orders.reload(); };
  const open = async () => {
    if (!persona) return;
    const value = await action.run(() => fhirApi<AccessOutcome>(`/reports/${report}?as=${persona.id}`));
    if (value) setOutcome({ value, reportId: report, persona: persona.id });
  };
  const decision = outcome?.value;

  return (
    <div>
      <PageTitle title="Acesso ao exame" subtitle="Toda leitura passa pelo PEP. Ele pede a decisão ao PDP (transação no fhir-channel), confere o hash e só então entrega — ou nega com o motivo." />
      <Panel title="Pedidos de exame (passo 1)" icon={<ClipboardList size={16} />}
        right={<button className={secondary} disabled={action.busy} onClick={order}>Solicitar exames A e B</button>}>
        <RoleHint persona={persona} expected="physician" who="um médico (Dra. Ana)" />
        {!orders.data?.length && <div className="text-sm text-ink-faint">Nenhum pedido ainda. Com a persona Dra. Ana, clique em “Solicitar exames A e B”.</div>}
        <ul className="m-0 flex list-none flex-wrap gap-2 p-0">
          {(orders.data ?? []).map(item => (
            <li key={item.id} className="rounded-lg border border-line px-3 py-1.5 text-[12.5px]">
              <b>{item.exam}</b> · {item.id} · solicitante {item.requester} · <span className="text-ink-faint">só FHIR, sem registro na ledger</span>
            </li>
          ))}
        </ul>
      </Panel>
      <Panel title="Abrir exame" icon={<Eye size={16} />}>
        <RoleHint persona={persona} expected="physician" who="um médico" />
        <div className="grid gap-3 md:grid-cols-[1fr_auto] md:items-end">
          <label className="text-[12.5px] text-ink-muted">Exame (DiagnosticReport registrado no PIP)
            <select className={input} value={report} onChange={event => setReport(event.target.value)}>
              {!registered.length && <option value="">nenhum resultado registrado</option>}
              {registered.map(item => <option key={item.id} value={item.id}>{item.exam} · {item.id}</option>)}
            </select>
          </label>
          <button className={primary} disabled={action.busy || !report || !persona} onClick={open}>
            {action.busy ? "Consultando PDP…" : `Abrir como ${persona?.label ?? "—"}`}
          </button>
        </div>
        <ErrorLine text={action.error} />
      </Panel>
      {decision && outcome && (
        <>
          <div className={`mb-4.5 rounded-card border px-5 py-4 ${decision.permitted ? "border-status-green/40 bg-status-greenSoft" : "border-status-red/40 bg-status-redSoft"}`}>
            <div className={`font-serif text-[24px] font-bold ${decision.permitted ? "text-status-green" : "text-status-red"}`}>
              {decision.permitted ? "PERMITIDO" : "NEGADO"}
            </div>
            <div className="text-[13px] text-ink">
              {decision.permitted ? "O PEP entregou o exame (hash conferido)." : <>Motivo: <b>{decision.reason}</b>. O conteúdo não foi entregue.</>}
              {" "}HTTP {decision.httpStatus} · {outcome.persona} · {decision.ledger} · bloco {decision.blockNumber ?? "—"} ·
              PDP {decision.timings.pdpSubmitMs ?? "—"} ms (endosso {decision.timings.fabric?.endorseMs ?? "—"} · commit {decision.timings.fabric?.commitMs ?? "—"})
            </div>
          </div>
          <Panel title="Rastro da decisão: PEP → PDP → PAP → PIP → decisão" icon={<Route size={16} />}>
            {decision.policy.policyId && (
              <div className="mb-3 text-[12.5px] text-ink-muted">
                Política <b>{decision.policy.policyId}</b> v{decision.policy.policyVersion} · hash <span className="font-mono">{decision.policy.policyHash?.slice(0, 16)}…</span>
              </div>
            )}
            <DecisionTrace outcome={decision} reportId={outcome.reportId} persona={outcome.persona} />
          </Panel>
          {decision.permitted && decision.resource && (
            <Panel title={`Exame: ${decision.resource.diagnosticReport.code?.text ?? decision.resource.diagnosticReport.id}`} icon={<Eye size={16} />}>
              <div className="mb-2 text-[12px] text-ink-faint">
                DiagnosticReport {decision.resource.diagnosticReport.id} · {decision.resource.diagnosticReport.status} ·
                rótulo {decision.resource.diagnosticReport.meta?.security?.map(item => item.code).join(", ")} · dados fictícios
              </div>
              <table className="w-full text-left text-[13px]">
                <thead className="text-ink-faint"><tr><th className="py-1.5">Observation</th><th>Resultado</th></tr></thead>
                <tbody>
                  {decision.resource.observations.map(item => (
                    <tr key={item.id} className="border-t border-line">
                      <td className="py-2">{item.code?.coding?.[0]?.display ?? item.code?.coding?.[0]?.code}</td>
                      <td className="font-semibold">{item.valueQuantity ? `${item.valueQuantity.value} ${item.valueQuantity.unit}` : item.valueString}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Panel>
          )}
        </>
      )}
    </div>
  );
}
