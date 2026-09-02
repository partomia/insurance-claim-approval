/** Format amounts in Indian Rupees (₹) for motor insurance UI. */
export function formatINR(
  value: number | null | undefined,
  options?: { maximumFractionDigits?: number },
): string {
  if (value == null || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: options?.maximumFractionDigits ?? 0,
  }).format(value);
}

/** Compact axis labels for charts (e.g. ₹12k, ₹4.5L). */
export function formatINRCompact(value: number): string {
  const abs = Math.abs(value);
  const sign = value < 0 ? "-" : "";
  if (abs >= 100_000) {
    const lakhs = abs / 100_000;
    const text = lakhs >= 10 ? lakhs.toFixed(0) : lakhs.toFixed(1).replace(/\.0$/, "");
    return `${sign}₹${text}L`;
  }
  if (abs >= 1_000) {
    return `${sign}₹${Math.round(abs / 1_000)}k`;
  }
  return formatINR(value);
}
