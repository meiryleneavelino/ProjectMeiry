import { CheckCircle2 } from "lucide-react";
import type { SandboxComponentStatus } from "@/types";
import Panel from "@/components/Panel";

interface Props {
  items: SandboxComponentStatus[];
}

export default function SandboxStatusPanel({ items }: Props) {
  const allHealthy = items.every((i) => i.healthy);

  return (
    <Panel
      title="Sandbox status"
      icon={<CheckCircle2 size={16} />}
      right={
        <span className="rounded-full bg-status-greenSoft px-2.5 py-0.5 text-[11px] font-bold text-status-green">
          {allHealthy ? "Operational" : "Attention"}
        </span>
      }
    >
      <ul className="flex flex-col">
        {items.map((item) => (
          <li
            key={item.label}
            className="flex items-center gap-2.5 border-b border-line py-2.5 last:border-none"
          >
            <div className="flex h-[30px] w-[30px] flex-none items-center justify-center rounded-[9px] bg-violet-soft">
              <span className="h-2 w-2 rounded-full bg-violet-deep" />
            </div>
            <div>
              <div className="text-[12.5px] font-bold">{item.label}</div>
              <div className={`text-[11.5px] font-semibold ${item.healthy ? "text-status-green" : "text-ink-muted"}`}>{item.value}</div>
            </div>
          </li>
        ))}
      </ul>
    </Panel>
  );
}
