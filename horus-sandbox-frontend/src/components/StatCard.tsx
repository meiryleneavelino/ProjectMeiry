import type { ReactNode } from "react";

interface StatCardProps {
  title: string;
  value: number;
  footnote: string;
  icon: ReactNode;
  iconBg: string;
  selected?: boolean;
  onClick?: () => void;
}

export default function StatCard({
  title,
  value,
  footnote,
  icon,
  iconBg,
  selected,
  onClick,
}: StatCardProps) {
  return (
    <button
      onClick={onClick}
      className={[
        "flex w-full flex-col gap-2.5 rounded-card border border-line bg-white p-4 text-left transition-shadow",
        selected ? "shadow-[inset_0_0_0_2px_theme(colors.violet.DEFAULT)]" : "",
      ].join(" ")}
    >
      <div className="flex items-center gap-2.5">
        <div
          className="flex h-[30px] w-[30px] flex-none items-center justify-center rounded-[9px]"
          style={{ background: iconBg }}
        >
          {icon}
        </div>
        <div className="text-[12.5px] font-semibold text-ink-muted">{title}</div>
      </div>
      <div className="font-serif text-[25px] font-extrabold">{value}</div>
      <div className="text-[11.5px] text-ink-faint">{footnote}</div>
    </button>
  );
}
