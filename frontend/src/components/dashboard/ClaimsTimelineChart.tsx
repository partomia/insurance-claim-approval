import { BarChart, Bar, XAxis, YAxis, ResponsiveContainer, Tooltip, CartesianGrid } from "recharts";
import { useChartColors } from "@/lib/chartTheme";

interface MonthSlice {
  month: string;
  count: number;
}

export function ClaimsTimelineChart({ data }: { data: MonthSlice[] }) {
  const colors = useChartColors();

  return (
    <ResponsiveContainer width="100%" height={220}>
      <BarChart data={data} margin={{ left: 0, right: 8, top: 8, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke={colors.border} vertical={false} />
        <XAxis
          dataKey="month"
          tick={{ fill: colors.muted, fontSize: 10 }}
          axisLine={{ stroke: colors.border }}
        />
        <YAxis
          allowDecimals={false}
          tick={{ fill: colors.muted, fontSize: 10 }}
          axisLine={{ stroke: colors.border }}
        />
        <Tooltip
          formatter={(value) => [`${value ?? 0} motor claims`, "Submitted"]}
          contentStyle={{
            background: colors.tooltipBg,
              color: colors.tooltipText,
            border: `1px solid ${colors.border}`,
            borderRadius: 8,
            fontSize: 12,
          }}
        />
        <Bar dataKey="count" fill={colors.primary} radius={[4, 4, 0, 0]} barSize={28} />
      </BarChart>
    </ResponsiveContainer>
  );
}
