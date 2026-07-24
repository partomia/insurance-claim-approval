import { BarChart, Bar, XAxis, YAxis, ResponsiveContainer, Tooltip, Cell } from "recharts";
import { useChartColors, scoreColor, comparisonText } from "@/lib/chartTheme";

interface Gauges {
  confidence: number;
  fraud: number;
  evidence: number;
}

type ScoreRow = {
  name: string;
  value: number;
  type: "confidence" | "fraud" | "evidence";
};

function ScoreTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: Array<{ payload?: ScoreRow }>;
  label?: string;
}) {
  if (!active || !payload?.length) return null;

  const payloadRow = payload[0]?.payload as ScoreRow | undefined;
  const labelRow = payload.find(
    (entry: { payload?: ScoreRow }) => (entry.payload as ScoreRow | undefined)?.name === label
  )?.payload as ScoreRow | undefined;
  const row = labelRow ?? payloadRow;
  if (!row) return null;

  return (
    <div className="rounded-lg border bg-card px-3 py-2 text-xs shadow-md">
      <p className="font-medium text-foreground">
        {row.name}: {row.value}%
      </p>
      <p className="mt-0.5 text-muted-foreground">{comparisonText(row.value / 100, row.type)}</p>
    </div>
  );
}

export function ScoreComparisonBarChart({ gauges }: { gauges: Gauges }) {
  const colors = useChartColors();

  const data: ScoreRow[] = [
    { name: "Confidence", value: Math.round((gauges.confidence || 0) * 100), type: "confidence" },
    { name: "Fraud Risk", value: Math.round((gauges.fraud || 0) * 100), type: "fraud" },
    { name: "Evidence", value: Math.round((gauges.evidence || 0) * 100), type: "evidence" },
  ];

  return (
    <ResponsiveContainer width="100%" height={140}>
      <BarChart data={data} layout="vertical" margin={{ left: 4, right: 16, top: 4, bottom: 4 }}>
        <XAxis type="number" domain={[0, 100]} tick={{ fill: colors.muted, fontSize: 10 }} unit="%" />
        <YAxis
          type="category"
          dataKey="name"
          width={72}
          tick={{ fill: colors.foreground, fontSize: 11 }}
        />
        <Tooltip content={<ScoreTooltip />} cursor={{ fill: "transparent" }} shared={false} />
        <Bar dataKey="value" radius={[0, 4, 4, 0]} barSize={16}>
          {data.map((entry) => (
            <Cell
              key={entry.name}
              fill={scoreColor(entry.value / 100, entry.type, colors)}
            />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
