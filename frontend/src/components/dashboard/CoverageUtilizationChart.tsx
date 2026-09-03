import { BarChart, Bar, XAxis, YAxis, ResponsiveContainer, Tooltip, CartesianGrid, Legend } from "recharts";
import { useChartColors } from "@/lib/chartTheme";
import { formatINR, formatINRCompact } from "@/lib/currency";

interface CoverageSlice {
  policy_number: string;
  policy_type: string;
  coverage_limit: number;
  claimed_amount: number;
}

export function CoverageUtilizationChart({ data }: { data: CoverageSlice[] }) {
  const colors = useChartColors();

  if (!data.length) {
    return <p className="text-sm text-muted-foreground py-8 text-center">No policies on file.</p>;
  }

  const chartData = data.map((row) => ({
    name: row.policy_type,
    limit: row.coverage_limit,
    claimed: row.claimed_amount,
    remaining: Math.max(row.coverage_limit - row.claimed_amount, 0),
  }));

  return (
    <ResponsiveContainer width="100%" height={240}>
      <BarChart data={chartData} margin={{ left: 0, right: 8, top: 8, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke={colors.border} vertical={false} />
        <XAxis dataKey="name" tick={{ fill: colors.muted, fontSize: 10 }} />
        <YAxis
          tick={{ fill: colors.muted, fontSize: 10 }}
          tickFormatter={(v) => formatINRCompact(Number(v))}
        />
        <Tooltip
          formatter={(value) => formatINR(Number(value ?? 0))}
          contentStyle={{
            background: colors.tooltipBg,
              color: colors.tooltipText,
            border: `1px solid ${colors.border}`,
            borderRadius: 8,
            fontSize: 12,
          }}
        />
        <Legend
          formatter={(value) => (
            <span style={{ color: colors.muted, fontSize: 11 }}>{value}</span>
          )}
        />
        <Bar dataKey="claimed" stackId="coverage" fill={colors.primary} name="Claimed" radius={[0, 0, 0, 0]} />
        <Bar dataKey="remaining" stackId="coverage" fill={colors.border} name="Remaining" radius={[4, 4, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}