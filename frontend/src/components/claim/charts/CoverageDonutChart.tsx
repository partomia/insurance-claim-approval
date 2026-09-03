import { PieChart, Pie, Cell, ResponsiveContainer, Legend, Tooltip } from "recharts";
import { useChartColors } from "@/lib/chartTheme";
import { formatINR } from "@/lib/currency";

interface Utilization {
  claim_amount: number;
  limit: number;
  pct: number;
}

export function CoverageDonutChart({ util }: { util: Utilization }) {
  const colors = useChartColors();
  const used = util.claim_amount || 0;
  const limit = util.limit || 1;
  const remaining = Math.max(limit - used, 0);

  const data = [
    { name: "Claimed", value: used },
    { name: "Remaining", value: remaining },
  ];

  return (
    <div>
      <ResponsiveContainer width="100%" height={180}>
        <PieChart>
          <Pie
            data={data}
            cx="50%"
            cy="50%"
            innerRadius={50}
            outerRadius={70}
            paddingAngle={2}
            dataKey="value"
          >
            <Cell fill={colors.primary} />
            <Cell fill={colors.border} />
          </Pie>
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
            verticalAlign="bottom"
            height={36}
            formatter={(value) => (
              <span style={{ color: colors.muted, fontSize: 11 }}>{value}</span>
            )}
          />
        </PieChart>
      </ResponsiveContainer>
      <p className="text-xs text-center text-muted-foreground -mt-2">
        {formatINR(used)} used / {formatINR(remaining)} remaining of {formatINR(limit)}
      </p>
    </div>
  );
}