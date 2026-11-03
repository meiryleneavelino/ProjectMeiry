import { ShieldCheck } from "lucide-react";
import type { Authorization } from "@/types";
import Panel from "@/components/Panel";

interface Props {
  authorizations: Authorization[];
}

const stateStyle: Record<Authorization["state"], string> = {
  active: "bg-status-greenSoft text-status-green",
  expired: "bg-[#f1f0f5] text-ink-faint",
  revoked: "bg-status-redSoft text-status-red",
};

const stateLabel: Record<Authorization["state"], string> = {
  active: "Active",
  expired: "Expired",
  revoked: "Revoked",
};

export default function AuthorizationsPanel({ authorizations }: Props) {
  return (
    <Panel
      title="Active authorizations"
      icon={<ShieldCheck size={16} />}
      right={
        <a href="/authorizations" className="text-xs font-bold text-violet-deep">
          View all →
        </a>
      }
    >
      {authorizations.map((auth) => (
        <div key={auth.id} className="border-b border-line py-3 last:border-none">
          <div className="flex items-center justify-between">
            <span className="text-[12.5px] font-bold">{auth.id}</span>
            <span className={`rounded-full px-2 py-0.5 text-[10.5px] font-bold ${stateStyle[auth.state]}`}>
              {stateLabel[auth.state]}
            </span>
          </div>
          <div className="mt-1 text-[11.5px] text-ink-faint">
            {auth.purpose} · {auth.validFrom} – {auth.validUntil}
            <br />
            {auth.organization} · {auth.dataset}
          </div>
        </div>
      ))}
    </Panel>
  );
}
