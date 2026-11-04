import type { ReactNode } from "react";
import { Link2, FileText } from "lucide-react";
import Panel from "@/components/Panel";
import { formatDate, shortHash } from "@/data/fhir";
import type { TimelineEntry } from "@/types/fhir";

interface Props {
  entries: TimelineEntry[];
  title?: string;
  right?: ReactNode;
  actions?: (entry: TimelineEntry) => ReactNode;
}

const NAME_STYLE: Record<string, string> = {
  PolicyCreated: "text-gold", PolicyUpdated: "text-gold", ResourceBound: "text-gold",
  ConsentGranted: "text-status-blue", ConsentRevoked: "text-status-red", ResourceRegistered: "text-status-blue",
  AccessDecision: "text-violet-deep", AuditEvent: "text-ink",
};

function summary(entry: TimelineEntry) {
  const detail = entry.detail;
  switch (entry.name) {
    case "AccessDecision":
      return `${detail.requester} → ${detail.reportId}: ${detail.permitted === "true" ? "PERMITIR" : `NEGAR (${detail.reason})`}`;
    case "AuditEvent":
      return `${detail.what} · ${detail.decision} ${detail.reason === "PERMIT" ? "" : detail.reason} · bloco ${detail.fabricBlock}`;
    case "ConsentGranted":
      return `${detail.consentId}: ${detail.serviceRequestId} → ${detail.grantee} até ${formatDate(detail.validUntil)}`;
    case "ConsentRevoked":
      return `${detail.consentId} revogado`;
    case "ResourceRegistered":
      return `${detail.reportId} (${detail.serviceRequestId}, label ${detail.securityLabel}) hash ${shortHash(detail.reportHash)}`;
    case "ResourceBound":
      return `${detail.target} → ${detail.policyId}`;
    default:
      return `${detail.policyId ?? ""} v${detail.version ?? ""} hash ${shortHash(detail.policyHash)}`;
  }
}

// On-chain events (fhir-channel) and off-chain AuditEvents (FHIR) in one line.
export default function FhirTimeline({ entries, title = "Linha do tempo (on-chain e off-chain)", right, actions }: Props) {
  return (
    <Panel title={title} icon={<Link2 size={16} />} right={right}>
      {!entries.length && <div className="text-sm text-ink-faint">Nenhum evento ainda.</div>}
      <ol className="m-0 flex list-none flex-col p-0">
        {entries.map((entry, index) => (
          <li key={`${entry.txId}-${entry.id}-${index}`} className="flex flex-wrap items-start gap-x-3 gap-y-1 border-b border-line py-2.5 last:border-0">
            <span className={`mt-0.5 flex w-20 flex-none items-center gap-1 text-[10.5px] font-semibold uppercase ${entry.source === "on-chain" ? "text-violet-deep" : "text-ink-faint"}`}>
              {entry.source === "on-chain" ? <Link2 size={11} /> : <FileText size={11} />} {entry.source}
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-baseline gap-2">
                <span className={`text-[13px] font-bold ${NAME_STYLE[entry.name] ?? "text-ink"}`}>{entry.name}</span>
                <span className="text-[11px] text-ink-faint">{entry.component} · {entry.actor ?? "—"} · {formatDate(entry.timestamp)}</span>
              </div>
              <div className="text-[12.5px] text-ink-muted">{summary(entry)}</div>
              <div className="font-mono text-[10.5px] text-ink-faint">tx {shortHash(entry.txId, 20)}{entry.id ? ` · AuditEvent/${entry.id}` : ""}</div>
            </div>
            {actions && <div className="flex flex-none gap-1.5">{actions(entry)}</div>}
          </li>
        ))}
      </ol>
    </Panel>
  );
}
