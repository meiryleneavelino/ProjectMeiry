import { PieChart, Pie, Cell, Legend, ResponsiveContainer, Tooltip } from "recharts";
import type { ModelUsageSlice } from "@/types";

interface Props {
  data: ModelUsageSlice[];
}

const COLORS = ["#6a5acd", "#d7a544", "#1f9d6f", "#3b6fd6", "#c9c9dc"];

export default function ModelDistributionChart({ data }: Props) {
  return (
    <div className="h-[190px]">
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie
            data={data}
            dataKey="value"
            nameKey="name"
            innerRadius="55%"
            outerRadius="80%"
            paddingAngle={2}
          >
            {data.map((_, i) => (
              <Cell key={i} fill={COLORS[i % COLORS.length]} stroke="#fff" strokeWidth={2} />
            ))}
          </Pie>
          <Tooltip />
          <Legend
            layout="vertical"
            align="right"
            verticalAlign="middle"
            iconType="circle"
            wrapperStyle={{ fontSize: 10.5 }}
          />
        </PieChart>
      </ResponsiveContainer>
    </div>
  );
}
