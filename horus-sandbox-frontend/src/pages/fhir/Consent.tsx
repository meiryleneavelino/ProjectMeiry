import { useState } from "react";
import { HeartHandshake, ListChecks } from "lucide-react";
import Panel from "@/components/Panel";
import FhirUnavailable from "@/components/fhir/FhirUnavailable";
import { useFhir } from "@/components/fhir/FhirLayout";
import { ErrorLine, PageTitle, RoleHint, TxLine, input, primary, secondary, useAction, useFhirData } from "@/components/fhir/common";
import { formatDate, postFhir, shortHash } from "@/data/fhir";
import type { ConsentItem, Receipt, ServiceRequestItem } from "@/types/fhir";

interface GrantResult extends Receipt { fhir: { id: string }; consentHash: string }

export default function FhirConsent() {
  const { persona, personas, unavailable } = useFhir();
  const consents = useFhirData<ConsentItem[]>("/consents");
  const orders = useFhirData<ServiceRequestItem[]>("/service-requests");
  const physicians = personas.filter(item => item.role === "physician");
  const [request, setRequest] = useState("sr-001");
  const [grantee, setGrantee] = useState("phy-001");
  const [days, setDays] = useState(30);
  const [last, setLast] = useState<GrantResult | null>(null);
  const action = useAction();
  if (unavailable) return <FhirUnavailable />;

  const grant = async () => {
    const result = await action.run(() => postFhir<GrantResult>(`/consents?as=${persona?.id}`, { serviceRequestId: request, grantee, days }));
    if (result) { setLast(result); consents.reload(); }
  };
  const revoke = async (id: string) => {
    if (await action.run(() => postFhir(`/consents/${id}/revoke?as=${persona?.id}`))) consents.reload();
  };

  return (
    <div>
      <PageTitle title="Consentimento" subtitle="O paciente decide quem vê qual exame e até quando. O Consent fica no FHIR; na ledger ficam só o hash e os atributos (PIP)." />
      <Panel title="Dar consentimento" icon={<HeartHandshake size={16} />}>
        <RoleHint persona={persona} expected="patient" who="João (paciente)" />
        {!orders.data?.length && <div className="mb-3 text-[12.5px] text-ink-muted">Ainda não há pedidos de exame. A Dra. Ana os cria na tela Acesso (passo 1).</div>}
        <div className="grid gap-3 md:grid-cols-[1fr_1fr_120px_auto] md:items-end">
          <label className="text-[12.5px] text-ink-muted">Exame
            <select className={input} value={request} onChange={event => setRequest(event.target.value)}>
              {(orders.data ?? []).map(item => <option key={item.id} value={item.id}>{item.exam} · {item.id}</option>)}
            </select>
          </label>
          <label className="text-[12.5px] text-ink-muted">Quem pode ver
            <select className={input} value={grantee} onChange={event => setGrantee(event.target.value)}>
              {physicians.map(item => <option key={item.id} value={item.id}>{item.label} · {item.id}</option>)}
            </select>
          </label>
          <label className="text-[12.5px] text-ink-muted">Dias
            <input className={input} type="number" min={1} max={365} value={days} onChange={event => setDays(Number(event.target.value))} />
          </label>
          <button className={primary} disabled={action.busy || !orders.data?.length} onClick={grant}>
            {action.busy ? "Gravando…" : "Consentir"}
          </button>
        </div>
        <ErrorLine text={action.error} />
        {last && (
          <div className="mt-3 rounded-lg bg-status-greenSoft px-3 py-2 text-[12.5px] text-status-green">
            Consent {last.fhir.id} criado no FHIR · hash {shortHash(last.consentHash, 16)} gravado no PIP
            <TxLine txId={last.txId} block={last.blockNumber}>PIP:PutConsent ·</TxLine>
          </div>
        )}
      </Panel>
      <Panel title="Consentimentos" icon={<ListChecks size={16} />}>
        <ErrorLine text={consents.error} />
        {!consents.data?.length && <div className="text-sm text-ink-faint">Nenhum consentimento.</div>}
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-left text-[12.5px]">
            <thead className="text-ink-faint"><tr><th className="py-1.5">Consent</th><th>Exame</th><th>Beneficiário</th><th>Válido até</th><th>FHIR</th><th>Ledger (PIP)</th><th /></tr></thead>
            <tbody>
              {(consents.data ?? []).map(item => (
                <tr key={item.id} className="border-t border-line">
                  <td className="py-2 font-mono">{item.id}</td>
                  <td>{item.serviceRequestId}</td>
                  <td>{item.onChain?.grantee ?? item.grantee}</td>
                  <td>{formatDate(item.validUntil)}</td>
                  <td>{item.fhirStatus}</td>
                  <td className={item.onChain?.status === "active" ? "text-status-green" : "text-status-red"}>
                    {item.onChain ? `${item.onChain.status} · ${shortHash(item.onChain.consentHash, 8)}` : "não registrado"}
                  </td>
                  <td className="text-right">
                    {item.onChain?.status === "active" && (
                      <button className={secondary} disabled={action.busy} onClick={() => revoke(item.id)}>Revogar</button>
                    )}
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
