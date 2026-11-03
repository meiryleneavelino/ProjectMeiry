import { Link2 } from "lucide-react";
import type { LedgerEvent } from "@/types";
import Panel from "@/components/Panel";

interface Props {
  events: LedgerEvent[];
}

export default function LedgerTimeline({ events }: Props) {
  return (
    <Panel
      title="Ledger events (latest)"
      icon={<Link2 size={16} />}
      right={
        <a href="/ledger" className="text-xs font-bold text-violet-deep">
          View all →
        </a>
      }
    >
      <div className="relative pl-5 before:absolute before:bottom-1 before:left-[5px] before:top-1 before:w-px before:bg-line">
        {events.map((ev) => (
          <div key={ev.id} className="relative pb-4 last:pb-0">
            <span className="absolute -left-5 top-0.5 h-[11px] w-[11px] rounded-full border-2 border-violet bg-white" />
            <div className="text-[10.5px] text-ink-faint">
              {new Date(ev.timestamp).toLocaleString("en-US")}
            </div>
            <div className="text-[12.5px] font-bold">{ev.type}</div>
            <div className="text-[11px] text-ink-faint">{ev.subject}</div>
          </div>
        ))}
      </div>
    </Panel>
  );
}
