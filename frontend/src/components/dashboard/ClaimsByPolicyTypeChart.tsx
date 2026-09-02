import { BarChart, Bar, XAxis, YAxis, ResponsiveContainer, Tooltip, CartesianGrid, Cell } from "recharts";
import { useChartColors } from "@/lib/chartTheme";
import { formatINR } from "@/lib/currency";

interface PolicyTypeSlice {
  policy_type: string;
  count: number;
  total_amount: number;
}

const TYPE_COLORS = ["#F96702", "#201A5C", "#3b82f6", "#22c55e", "#a855f7"];

export function ClaimsByPolicyTypeChart({ data }: { data: PolicyTypeSlice[] }) {
  const colors = useChartColors();

  if (!data.length) {
    return <p className="text-sm text-muted-foreground py-8 text-center">No submitted claims yet.</p>;
  }

  return (
    <ResponsiveContainer width="100%" height={220}>
      <BarChart data={data} layout="vertical" margin={{ left: 8, right: 16, top: 8, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke={colors.border} horizontal={false} />
        <XAxis type="number" allowDecimals={false} tick={{ fill: colors.muted, fontSize: 10 }} />
        <YAxis
          type="category"
          dataKey="policy_type"
          width={64}
          tick={{ fill: colors.foreground, fontSize: 11 }}
        />
        <Tooltip
          formatter={(value, _name, item) => {
            const row = item?.payload as PolicyTypeSlice | undefined;
            return [
              `${value ?? 0} motor claims · ${formatINR(row?.total_amount ?? 0)} total`,
              row?.policy_type ?? "Type",
            ];
          }}
          contentStyle={{
            background: colors.foreground === "#111827" ? "#fff" : "#1f2937",
            border: `1px solid ${colors.border}`,
            borderRadius: 8,
            fontSize: 12,
          }}
        />
        <Bar dataKey="count" radius={[0, 4, 4, 0]} barSize={18}>
          {data.map((entry, index) => (
            <Cell key={entry.policy_type} fill={TYPE_COLORS[index % TYPE_COLORS.length]} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}