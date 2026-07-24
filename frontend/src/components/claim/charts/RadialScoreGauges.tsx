import { RadialBarChart, RadialBar, ResponsiveContainer, PolarAngleAxis } from "recharts";
import { useChartColors, scoreColor, gaugeComparisonText } from "@/lib/chartTheme";

interface Gauges {
  confidence: number;
  fraud: number;
  evidence: number;
}

const GAUGE_CONFIG = [
  { key: "confidence" as const, label: "Confidence" },
  { key: "fraud" as const, label: "Fraud Risk" },
  { key: "evidence" as const, label: "Evidence" },
];

function SingleGauge({
  label,
  value,
  type,
}: {
  label: string;
  value: number;
  type: "confidence" | "fraud" | "evidence";
}) {
  const colors = useChartColors();
  const pct = Math.round(value * 100);
  const fill = scoreColor(value, type, colors);
  const data = [{ name: label, value: pct, fill }];

  return (
    <div className="flex min-w-0 flex-col items-center">
      <div className="relative h-[92px] w-full max-w-[120px]">
        <ResponsiveContainer width="100%" height="100%">
          <RadialBarChart
            cx="50%"
            cy="50%"
            innerRadius="62%"
            outerRadius="88%"
            barSize={7}
            data={data}
            startAngle={90}
            endAngle={-270}
          >
            <PolarAngleAxis type="number" domain={[0, 100]} tick={false} />
            <RadialBar background={{ fill: colors.border }} dataKey="value" cornerRadius={4} />
          </RadialBarChart>
        </ResponsiveContainer>
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
          <span className="text-base font-bold leading-none" style={{ color: fill }}>
            {pct}%
          </span>
        </div>
      </div>
      <p className="mt-1 w-full text-center text-xs font-medium text-foreground">{label}</p>
      <p className="mt-0.5 w-full px-0.5 text-center text-[10px] leading-snug text-muted-foreground">
        {gaugeComparisonText(value, type)}
      </p>
    </div>
  );
}

export function RadialScoreGauges({ gauges }: { gauges: Gauges }) {
  return (
    <div className="grid grid-cols-3 gap-x-2 gap-y-1">
      {GAUGE_CONFIG.map(({ key, label }) => (
        <SingleGauge key={key} label={label} value={gauges[key] || 0} type={key} />
      ))}
    </div>
  );
}
