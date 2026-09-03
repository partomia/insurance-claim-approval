import { BarChart, Bar, XAxis, YAxis, ResponsiveContainer, Tooltip, Cell, ReferenceLine } from "recharts";
import { useChartColors } from "@/lib/chartTheme";
import { formatINR, formatINRCompact } from "@/lib/currency";

interface PayoutStep {
  name: string;
  value: number;
}

interface PayoutBreakdown {
  gross?: number;
  deductible?: number;
  payable?: number;
  co_pay_pct?: number;
  co_pay_amount?: number;
  depreciation_amount?: number;
  steps?: PayoutStep[];
}

export function PayoutWaterfallChart({ payout }: { payout: PayoutBreakdown }) {
  const colors = useChartColors();

  const steps: PayoutStep[] =
    payout.steps && payout.steps.length > 0
      ? payout.steps
      : (() => {
          const gross = payout.gross || 0;
          const deductible = payout.deductible || 0;
          const coPay = payout.co_pay_amount ?? 0;
          const depreciation = payout.depreciation_amount ?? 0;
          const payable = payout.payable || 0;
          return [
            { name: "Claimed", value: gross },
            { name: "Compulsory excess", value: -deductible },
            ...(coPay > 0 ? [{ name: "Co-pay", value: -coPay }] : []),
            ...(depreciation > 0 ? [{ name: "Depreciation", value: -depreciation }] : []),
            { name: "Payable", value: payable },
          ];
        })();

  const gross = payout.gross || 0;
  const payable = payout.payable || steps[steps.length - 1]?.value || 0;

  const stepColors: Record<string, string> = {
    Claimed: colors.primary,
    Deductible: colors.red,
    "Compulsory excess": colors.red,
    "Co-pay": colors.amber,
    Depreciation: colors.amber,
    Payable: colors.green,
  };

  return (
    <div>
      <ResponsiveContainer width="100%" height={160}>
        <BarChart data={steps} margin={{ left: 0, right: 8, top: 8, bottom: 0 }}>
          <XAxis
            dataKey="name"
            tick={{ fill: colors.muted, fontSize: 10 }}
            axisLine={{ stroke: colors.border }}
          />
          <YAxis
            tick={{ fill: colors.muted, fontSize: 10 }}
            axisLine={{ stroke: colors.border }}
            tickFormatter={(v) => formatINRCompact(Number(v))}
          />
          <ReferenceLine y={0} stroke={colors.border} />
          <Tooltip
            formatter={(value) => formatINR(Math.abs(Number(value ?? 0)))}
            contentStyle={{
              background: colors.foreground === "#111827" ? "#fff" : "#1f2937",
              border: `1px solid ${colors.border}`,
              borderRadius: 8,
              fontSize: 12,
            }}
          />
          <Bar dataKey="value" radius={[4, 4, 0, 0]}>
            {steps.map((entry) => (
              <Cell key={entry.name} fill={stepColors[entry.name] || colors.primary} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      <div className="flex justify-between text-xs text-muted-foreground mt-1 px-1">
        <span>Gross {formatINR(gross)}</span>
        <span className="font-semibold text-green-600">Payable {formatINR(Math.abs(Number(payable)))}</span>
      </div>
    </div>
  );
}