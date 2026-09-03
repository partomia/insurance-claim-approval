import { PieChart, Pie, Cell, ResponsiveContainer, Legend, Tooltip } from "recharts";
import { useChartColors } from "@/lib/chartTheme";

interface StatusSlice {
  status: string;
  label: string;
  count: number;
}

const STATUS_COLORS: Record<string, string> = {
  APPROVED: "#22c55e",
  REJECTED: "#ef4444",
  PENDING_REVIEW: "#f59e0b",
  PROCESSING: "#3b82f6",
  PENDING: "#f59e0b",
  DRAFT: "#94a3b8",
  HUMAN_REVIEW: "#a855f7",
  ESCALATE: "#f97316",
  REQUEST_MORE_INFO: "#06b6d4",
};

export function ClaimStatusDonutChart({
  data,
  onStatusClick,
}: {
  data: StatusSlice[];
  onStatusClick?: (status: string) => void;
}) {
  const colors = useChartColors();

  if (!data.length) {
    return <p className="text-sm text-muted-foreground py-8 text-center">No claims yet.</p>;
  }

  return (
    <ResponsiveContainer width="100%" height={220}>
      <PieChart>
        <Pie
          data={data}
          cx="50%"
          cy="50%"
          innerRadius={52}
          outerRadius={78}
          paddingAngle={2}
          dataKey="count"
          nameKey="label"
          onClick={(_, index) => {
            const slice = data[index];
            if (slice && onStatusClick) onStatusClick(slice.status);
          }}
          style={{ cursor: onStatusClick ? "pointer" : "default" }}
        >
          {data.map((entry) => (
            <Cell key={entry.status} fill={STATUS_COLORS[entry.status] || colors.chart3} />
          ))}
        </Pie>
        <Tooltip
          formatter={(value, _name, item) => [
            `${value ?? 0} motor claim${Number(value ?? 0) === 1 ? "" : "s"}`,
            (item?.payload as StatusSlice | undefined)?.label ?? "Status",
          ]}
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
          height={48}
          formatter={(value) => (
            <span style={{ color: colors.muted, fontSize: 11 }}>{value}</span>
          )}
        />
      </PieChart>
    </ResponsiveContainer>
  );
}
