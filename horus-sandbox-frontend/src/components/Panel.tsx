import type { ReactNode } from "react";

interface PanelProps {
  title: string;
  icon?: ReactNode;
  right?: ReactNode;
  children: ReactNode;
  className?: string;
}

export default function Panel({ title, icon, right, children, className }: PanelProps) {
  return (
    <div className={`mb-4.5 rounded-card border border-line bg-white p-5 ${className ?? ""}`}>
      <div className="mb-3.5 flex items-center justify-between">
        <h3 className="m-0 flex items-center gap-2 text-[14.5px] font-bold text-violet-deep">
          {icon}
          <span className="text-ink">{title}</span>
        </h3>
        {right}
      </div>
      {children}
    </div>
  );
}
