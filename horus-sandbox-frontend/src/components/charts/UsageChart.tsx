import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import type { ResourceUsagePoint } from "@/types";

interface Props {
  data: ResourceUsagePoint[];
}

export default function UsageChart({ data }: Props) {
  return (
    <div className="h-[190px]">
      <div className="mb-1.5 flex gap-3.5 text-[11.5px] text-ink-muted">
        <Legend color="#6a5acd" label="CPU" />
        <Legend color="#d7a544" label="GPU" />
        <Legend color="#1f9d6f" label="Memory" />
      </div>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#eeedf5" vertical={false} />
          <XAxis dataKey="date" tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
          <YAxis
            domain={[0, 100]}
            tickFormatter={(v) => `${v}%`}
            tick={{ fontSize: 10 }}
            axisLine={false}
            tickLine={false}
          />
          <Tooltip />
          <Area type="monotone" dataKey="cpu" stroke="#6a5acd" fill="#6a5acd" fillOpacity={0.12} strokeWidth={2} />
          <Area type="monotone" dataKey="gpu" stroke="#d7a544" fill="#d7a544" fillOpacity={0.12} strokeWidth={2} />
          <Area
            type="monotone"
            dataKey="memory"
            stroke="#1f9d6f"
            fill="#1f9d6f"
            fillOpacity={0.12}
            strokeWidth={2}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

function Legend({ color, label }: { color: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <i className="inline-block h-2 w-2 rounded-full" style={{ background: color }} />
      {label}
    </span>
  );
}
