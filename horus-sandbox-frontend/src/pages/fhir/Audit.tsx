import { useState } from "react";
import { CheckCircle2, FileText, Link2, XCircle } from "lucide-react";
import StatCard from "@/components/StatCard";
import FhirTimeline from "@/components/fhir/FhirTimeline";
import FhirUnavailable from "@/components/fhir/FhirUnavailable";
import { useFhir } from "@/components/fhir/FhirLayout";
import { ErrorLine, PageTitle, secondary, useAction, useFhirData } from "@/components/fhir/common";
import { fhirApi } from "@/data/fhir";
import type { TimelineEntry, TransactionCheck, Verification } from "@/types/fhir";

type Check = { text: string; ok: boolean };

function hashTarget(entry: TimelineEntry): [string, string] | null {
  if (entry.name === "ConsentGranted" || entry.name === "ConsentRevoked") return ["consent", entry.detail.consentId];
  if (entry.name === "ResourceRegistered") return ["report", entry.detail.reportId];
  if (entry.name === "AuditEvent" && entry.detail.what?.startsWith("DiagnosticReport/")) return ["report", entry.detail.what.split("/")[1]];
  return null;
}

export default function FhirAudit() {
  const { unavailable } = useFhir();
  const timeline = useFhirData<TimelineEntry[]>("/audit");
  const [checks, setChecks] = useState<Record<string, Check>>({});
  const action = useAction();
  if (unavailable) return <FhirUnavailable />;

  const entries = [...(timeline.data ?? [])].reverse();
  const decisions = entries.filter(item => item.name === "AccessDecision");
  const key = (entry: TimelineEntry, kind: string) => `${kind}:${entry.txId}:${entry.id ?? ""}`;

  const verifyHash = async (entry: TimelineEntry) => {
    const target = hashTarget(entry);
    if (!target) return;
    const result = await action.run(() => fhirApi<Verification>(`/verify/${target[0]}/${target[1]}`));
    if (result) setChecks(current => ({ ...current, [key(entry, "hash")]: {
      ok: result.match,
      text: result.match
        ? `hash confere${result.matchesVersion ? ` (versão ${result.matchesVersion} do FHIR; atual v${result.currentVersion}, ${result.fhirStatus})` : ""}`
        : "hash NÃO confere com o FHIR",
    } }));
  };
  const verifyTx = async (entry: TimelineEntry) => {
    const result = await action.run(() => fhirApi<TransactionCheck>(`/transactions/${entry.txId}`));
    if (result) setChecks(current => ({ ...current, [key(entry, "tx")]: { ok: result.valid, text: `${result.validationCode} · bloco ${result.blockNumber}` } }));
  };

  return (
    <div>
      <PageTitle title="Auditoria" subtitle="Eventos gravados no fhir-channel (PAP, PIP, PDP) e AuditEvents criados pelo PEP no FHIR, cada um apontando para a sua transação." />
      <div className="mb-4.5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard title="Eventos on-chain" value={entries.filter(item => item.source === "on-chain").length} footnote="fhir-channel" icon={<Link2 size={16} className="text-white" />} iconBg="#4b3f9e" />
        <StatCard title="AuditEvents (FHIR)" value={entries.filter(item => item.source === "off-chain").length} footnote="off-chain, com a tx" icon={<FileText size={16} className="text-navy-950" />} iconBg="#f1dcae" />
        <StatCard title="Permitidos" value={decisions.filter(item => item.detail.permitted === "true").length} footnote="AccessDecision" icon={<CheckCircle2 size={16} className="text-white" />} iconBg="#1f9d6f" />
        <StatCard title="Negados" value={decisions.filter(item => item.detail.permitted !== "true").length} footnote="AccessDecision" icon={<XCircle size={16} className="text-white" />} iconBg="#d5504a" />
      </div>
      <ErrorLine text={timeline.error || action.error} />
      <FhirTimeline entries={entries}
        right={<button className={secondary} onClick={timeline.reload}>Atualizar</button>}
        actions={entry => (
          <div className="flex flex-col items-end gap-1">
            <div className="flex gap-1.5">
              {hashTarget(entry) && <button className={secondary} disabled={action.busy} onClick={() => verifyHash(entry)}>Verificar hash</button>}
              {entry.txId && entry.txId !== "none" && <button className={secondary} disabled={action.busy} onClick={() => verifyTx(entry)}>Verificar tx</button>}
            </div>
            {["hash", "tx"].map(kind => checks[key(entry, kind)] && (
              <span key={kind} className={`text-[11.5px] ${checks[key(entry, kind)].ok ? "text-status-green" : "font-bold text-status-red"}`}>
                {kind}: {checks[key(entry, kind)].text}
              </span>
            ))}
          </div>
        )} />
    </div>
  );
}
