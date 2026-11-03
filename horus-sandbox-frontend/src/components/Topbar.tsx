import { Bell } from "lucide-react";

interface TopbarProps {
  title: string;
  subtitle: string;
  userName?: string;
  userRole?: string;
}

export default function Topbar({
  title,
  subtitle,
  userName = "Meirylene Avelino",
  userRole = "Researcher",
}: TopbarProps) {
  const initials = userName
    .split(" ")
    .map((n) => n[0])
    .slice(0, 2)
    .join("");

  return (
    <div className="sticky top-0 z-10 flex items-center justify-between border-b border-line bg-white px-7 py-4">
      <div>
        <h1 className="m-0 text-[16px] font-bold">{title}</h1>
        <div className="mt-0.5 text-xs text-ink-faint">{subtitle}</div>
      </div>
      <div className="flex items-center gap-4.5">
        <button
          aria-label="Notifications"
          className="relative flex h-9 w-9 items-center justify-center rounded-[10px] border border-line bg-white"
        >
          <Bell size={16} className="text-ink-muted" />
          <span className="absolute -right-1 -top-1 flex h-4 w-4 items-center justify-center rounded-full bg-status-red text-[10px] font-bold text-white">
            1
          </span>
        </button>
        <div className="flex items-center gap-2.5">
          <div className="flex h-[34px] w-[34px] items-center justify-center rounded-full bg-gradient-to-br from-violet to-[#9c8cf0] text-[13px] font-bold text-white">
            {initials}
          </div>
          <div>
            <div className="text-[13px] font-bold leading-tight">{userName}</div>
            <div className="text-[11px] text-ink-faint">{userRole}</div>
          </div>
        </div>
      </div>
    </div>
  );
}
