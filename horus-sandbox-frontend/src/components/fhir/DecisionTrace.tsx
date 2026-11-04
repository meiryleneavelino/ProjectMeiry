import { CheckCircle2, XCircle } from "lucide-react";
import { shortHash } from "@/data/fhir";
import type { AccessOutcome, TraceStep } from "@/types/fhir";

const COMPONENT_STYLE: Record<string, string> = {
  PEP: "bg-navy-800 text-white",
  PDP: "bg-violet-deep text-white",
  PAP: "bg-gold text-navy-950",
  PIP: "bg-status-blue text-white",
};

function Badge({ name }: { name: string }) {
  return <span className={`inline-flex w-11 flex-none justify-center rounded-md py-0.5 text-[11px] font-bold ${COMPONENT_STYLE[name] ?? "bg-line text-ink"}`}>{name}</span>;
}

function attributes(step: TraceStep) {
  const entries = Object.entries(step.attributes ?? {});
  if (!entries.length) return null;
  return (
    <div className="mt-1 flex flex-wrap gap-1">
      {entries.map(([key, value]) => (
        <span key={key} className="rounded bg-paper px-1.5 py-0.5 font-mono text-[10.5px] text-ink-muted">
          {key}={value.length > 24 ? shortHash(value, 16) : value}
        </span>
      ))}
    </div>
  );
}

// The decision trail, in order: PEP -> PDP -> PAP (policy) -> PIP (attributes) -> decision.
export default function DecisionTrace({ outcome, reportId, persona }: { outcome: AccessOutcome; reportId: string; persona: string }) {
  const steps: { component: string; title: string; step?: TraceStep }[] = [
    { component: "PEP", title: `GET /reports/${reportId}?as=${persona} → submit PDP:RequestAccess` },
    ...outcome.decisionTrace.map(step => ({ component: step.component, title: `${step.action}: ${step.result}`, step })),
  ];
  return (
    <ol className="m-0 flex list-none flex-col gap-2 p-0">
      {steps.map((item, index) => (
        <li key={index} className="flex gap-3">
          <Badge name={item.component} />
          <div className="min-w-0 text-[13px] text-ink">
            {item.title}
            {item.step && attributes(item.step)}
          </div>
        </li>
      ))}
      <li className="flex gap-3">
        <Badge name="PDP" />
        <div className={`flex items-center gap-1.5 text-[13px] font-bold ${outcome.reason === "PERMIT" ? "text-status-green" : "text-status-red"}`}>
          {outcome.reason === "PERMIT" ? <CheckCircle2 size={15} /> : <XCircle size={15} />}
          decisão: {outcome.reason === "PERMIT" ? "PERMITIR" : `NEGAR (${outcome.reason})`}
          <span className="font-normal text-ink-faint">· gravada no bloco {outcome.blockNumber ?? "—"}</span>
        </div>
      </li>
      {outcome.hashCheck && (
        <li className="flex gap-3">
          <Badge name="PEP" />
          <div className={`text-[13px] ${outcome.hashCheck.match ? "text-ink" : "font-bold text-status-red"}`}>
            hash do recurso no FHIR {outcome.hashCheck.match ? "==" : "≠"} hash no PIP ({shortHash(outcome.hashCheck.computed, 16)})
            {!outcome.hashCheck.match && " → conteúdo NÃO entregue"}
          </div>
        </li>
      )}
      <li className="flex gap-3">
        <Badge name="PEP" />
        <div className="text-[13px] text-ink">
          {outcome.httpStatus === 200 ? "entrega o recurso (200)" : `responde ${outcome.httpStatus} só com o motivo`} · AuditEvent {outcome.auditEventId ?? "—"} com a tx {shortHash(outcome.txId)}
        </div>
      </li>
    </ol>
  );
}
