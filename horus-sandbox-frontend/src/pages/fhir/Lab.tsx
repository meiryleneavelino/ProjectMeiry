import { useState } from "react";
import { FlaskConical, ShieldCheck } from "lucide-react";
import Panel from "@/components/Panel";
import FhirUnavailable from "@/components/fhir/FhirUnavailable";
import { useFhir } from "@/components/fhir/FhirLayout";
import { ErrorLine, PageTitle, RoleHint, TxLine, input, primary, secondary, useAction, useFhirData } from "@/components/fhir/common";
import { fhirApi, formatDate, postFhir, shortHash } from "@/data/fhir";
import type { Receipt, ResultItem, ServiceRequestItem, Verification } from "@/types/fhir";

interface LabResult {
  fhir: { diagnosticReport: string; observations: string[]; provenance: string };
  reportHash: string;
  pip: Receipt;
  pap: Receipt;
}

export default function FhirLab() {
  const { persona, unavailable } = useFhir();
  const orders = useFhirData<ServiceRequestItem[]>("/service-requests");
  const results = useFhirData<ResultItem[]>("/results");
  const [request, setRequest] = useState("sr-001");
  const [label, setLabel] = useState("R");
  const [last, setLast] = useState<LabResult | null>(null);
  const [checks, setChecks] = useState<Record<string, Verification>>({});
  const action = useAction();
  if (unavailable) return <FhirUnavailable />;

  const send = async () => {
    const result = await action.run(() => postFhir<LabResult>(`/lab/results?as=${persona?.id}`, { serviceRequestId: request, securityLabel: label }));
    if (result) { setLast(result); results.reload(); }
  };
  const verify = async (id: string) => {
    const result = await action.run(() => fhirApi<Verification>(`/verify/report/${id}`));
    if (result) setChecks(current => ({ ...current, [id]: result }));
  };

  return (
    <div>
      <PageTitle title="Laboratório" subtitle="O resultado (Observation, DiagnosticReport com meta.security e Provenance) fica no FHIR. O PIP recebe o hash e o rótulo; o PAP liga o laudo à política." />
      <Panel title="Enviar resultado" icon={<FlaskConical size={16} />}>
        <RoleHint persona={persona} expected="lab" who="Laboratório" />
        <div className="grid gap-3 md:grid-cols-[1fr_200px_auto] md:items-end">
          <label className="text-[12.5px] text-ink-muted">Pedido
            <select className={input} value={request} onChange={event => setRequest(event.target.value)}>
              {(orders.data ?? []).map(item => <option key={item.id} value={item.id}>{item.exam} · {item.id}</option>)}
            </select>
          </label>
          <label className="text-[12.5px] text-ink-muted">Rótulo de segurança
            <select className={input} value={label} onChange={event => setLabel(event.target.value)}>
              <option value="R">R · restrito</option>
              <option value="N">N · normal (sem política: negado por padrão)</option>
            </select>
          </label>
          <button className={primary} disabled={action.busy || !orders.data?.length} onClick={send}>
            {action.busy ? "Enviando…" : "Enviar resultado"}
          </button>
        </div>
        <div className="mt-2 text-[11.5px] text-ink-faint">Valores fictícios gerados pelo middleware. Para N, só um laudo ligado a uma política pode ser aberto.</div>
        <ErrorLine text={action.error} />
        {last && (
          <div className="mt-3 rounded-lg bg-status-greenSoft px-3 py-2 text-[12.5px] text-status-green">
            DiagnosticReport {last.fhir.diagnosticReport} + {last.fhir.observations.length} Observation(s) + {last.fhir.provenance} · hash {shortHash(last.reportHash, 16)}
            <TxLine txId={last.pip.txId} block={last.pip.blockNumber}>PIP:PutResource ·</TxLine>
            <TxLine txId={last.pap.txId} block={last.pap.blockNumber}>PAP:BindResource (adm-001) ·</TxLine>
          </div>
        )}
      </Panel>
      <Panel title="Resultados registrados" icon={<ShieldCheck size={16} />}>
        <ErrorLine text={results.error} />
        {!results.data?.length && <div className="text-sm text-ink-faint">Nenhum resultado.</div>}
        <div className="overflow-x-auto">
          <table className="w-full min-w-[680px] text-left text-[12.5px]">
            <thead className="text-ink-faint"><tr><th className="py-1.5">DiagnosticReport</th><th>Exame</th><th>Rótulo</th><th>Emitido</th><th>Hash no PIP</th><th /></tr></thead>
            <tbody>
              {(results.data ?? []).map(item => (
                <tr key={item.id} className="border-t border-line">
                  <td className="py-2 font-mono">{item.id}</td>
                  <td>{item.exam}</td>
                  <td>{item.securityLabel.join(", ")}</td>
                  <td>{formatDate(item.issued)}</td>
                  <td className="font-mono">{item.onChain ? shortHash(item.onChain.reportHash) : "não registrado"}</td>
                  <td className="text-right">
                    {checks[item.id] ? (
                      <span className={checks[item.id].match ? "text-status-green" : "font-bold text-status-red"}>
                        {checks[item.id].match ? "hash confere" : "hash NÃO confere"}
                      </span>
                    ) : item.onChain && <button className={secondary} disabled={action.busy} onClick={() => verify(item.id)}>Verificar hash</button>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}
