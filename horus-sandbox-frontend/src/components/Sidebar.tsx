import { NavLink } from "react-router-dom";
import {
  LayoutGrid,
  PlusCircle,
  ListChecks,
  ShieldCheck,
  Link2,
  CircuitBoard,
  Database,
  Lock,
  FileText,
  Settings as SettingsIcon,
} from "lucide-react";

const navItems = [
  { to: "/", label: "Dashboard", icon: LayoutGrid },
  { to: "/new-job", label: "New job", icon: PlusCircle },
  { to: "/training", label: "Federated training", icon: CircuitBoard },
  { to: "/jobs", label: "My jobs", icon: ListChecks },
  { to: "/authorizations", label: "Authorizations", icon: ShieldCheck },
  { to: "/ledger", label: "Ledger (events)", icon: Link2 },
  { to: "/models", label: "Models", icon: CircuitBoard },
  { to: "/data", label: "Data & datasets", icon: Database },
  { to: "/security", label: "Security", icon: Lock },
  { to: "/reports", label: "Reports", icon: FileText },
  { to: "/settings", label: "Settings", icon: SettingsIcon },
];

export default function Sidebar() {
  return (
    <aside className="flex flex-col bg-gradient-to-b from-navy-950 via-navy-900 to-navy-800 px-3.5 pb-4 pt-5 text-[#e9e9f5] md:sticky md:top-0 md:h-screen">
      <div className="mb-4 flex items-center gap-2.5 border-b border-white/10 px-2 pb-5">
        <div className="flex h-9 w-9 flex-none items-center justify-center rounded-[10px] bg-[radial-gradient(circle_at_30%_25%,#f1dcae,#d7a544_55%,#a9772a_100%)]">
          <ShieldCheck size={19} className="text-navy-950" strokeWidth={2.4} />
        </div>
        <div>
          <div className="font-serif text-[19px] font-semibold leading-tight text-[#f5efe0]">
            Horus
          </div>
          <div className="text-[10.5px] text-[#9b9bc0]">
            Secure Research. Trusted AI.
          </div>
        </div>
      </div>

      <nav className="grid grid-cols-2 gap-0.5 md:flex md:flex-1 md:flex-col">
        {navItems.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            end={to === "/"}
            className={({ isActive }) =>
              [
                "flex items-center gap-2.5 rounded-[9px] px-3 py-2 text-[13.5px] font-medium transition-colors",
                isActive
                  ? "bg-gold/[0.14] text-[#f3e3bd]"
                  : "text-[#b7b7d4] hover:bg-white/5 hover:text-[#f1f1fa]",
              ].join(" ")
            }
          >
            <Icon size={17} strokeWidth={1.8} />
            {label}
          </NavLink>
        ))}
      </nav>

      <div className="mt-2.5 flex items-center gap-2 border-t border-white/10 pt-3.5 text-xs text-[#8f8fb3]">
        <span className="h-[7px] w-[7px] rounded-full bg-status-green shadow-[0_0_0_3px_rgba(31,157,111,0.25)]" />
        Sandbox online — v1.0.0
      </div>
    </aside>
  );
}
