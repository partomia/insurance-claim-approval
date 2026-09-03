import { useEffect, useState } from "react";

function readVar(name: string, fallback: string): string {
  if (typeof document === "undefined") return fallback;
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

export interface ChartColors {
  primary: string;
  secondary: string;
  muted: string;
  border: string;
  foreground: string;
  green: string;
  amber: string;
  red: string;
  blue: string;
  chart1: string;
  chart2: string;
  chart3: string;
  /** True when the app is in dark mode (`.dark` on <html>). */
  isDark: boolean;
  /** Themed Recharts tooltip background — light surface in light mode, dark in dark. */
  tooltipBg: string;
  /** Themed Recharts tooltip text color. */
  tooltipText: string;
}

function isDarkMode(): boolean {
  if (typeof document === "undefined") return false;
  return document.documentElement.classList.contains("dark");
}

export function getChartColors(): ChartColors {
  const dark = isDarkMode();
  return {
    primary: readVar("--primary", "#F96702"),
    secondary: readVar("--secondary", "#201A5C"),
    muted: readVar("--muted-foreground", "#6b7280"),
    border: readVar("--border", "#e5e7eb"),
    foreground: readVar("--foreground", "#111827"),
    green: "#22c55e",
    amber: "#f59e0b",
    red: "#ef4444",
    blue: "#3b82f6",
    chart1: readVar("--chart-1", "#F96702"),
    chart2: readVar("--chart-2", "#201A5C"),
    chart3: readVar("--chart-3", "#3b82f6"),
    isDark: dark,
    tooltipBg: dark ? "#1f2937" : "#ffffff",
    tooltipText: dark ? "#f9fafb" : "#111827",
  };
}

export function useChartColors(): ChartColors {
  const [colors, setColors] = useState<ChartColors>(getChartColors);

  useEffect(() => {
    const update = () => setColors(getChartColors());
    update();

    const observer = new MutationObserver(update);
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["class"],
    });
    return () => observer.disconnect();
  }, []);

  return colors;
}

export function scoreColor(
  value: number,
  type: "confidence" | "fraud" | "evidence",
  colors: ChartColors
): string {
  const pct = value * 100;
  if (type === "fraud") {
    if (pct >= 75) return colors.red;
    if (pct >= 40) return colors.amber;
    return colors.green;
  }
  if (type === "confidence" || type === "evidence") {
    if (pct >= 70) return colors.green;
    if (pct >= 40) return colors.amber;
    return colors.red;
  }
  return colors.blue;
}

export const THRESHOLDS = {
  confidenceReview: 0.6,
  fraudEscalation: 0.4,
  evidenceStrong: 0.7,
} as const;

export function comparisonText(
  value: number,
  type: "confidence" | "fraud" | "evidence"
): string {
  const pct = Math.round(value * 100);
  if (type === "confidence") {
    return pct >= THRESHOLDS.confidenceReview * 100
      ? `${pct}% — above 60% review threshold`
      : `${pct}% — below 60% review threshold`;
  }
  if (type === "fraud") {
    return pct >= THRESHOLDS.fraudEscalation * 100
      ? `${pct}% — above 40% escalation threshold`
      : `${pct}% — below 40% escalation threshold`;
  }
  return pct >= THRESHOLDS.evidenceStrong * 100
    ? `${pct}% — strong documentation`
    : `${pct}% — limited documentation`;
}

/** Shorter labels for compact radial gauge layout */
export function gaugeComparisonText(
  value: number,
  type: "confidence" | "fraud" | "evidence"
): string {
  const pct = Math.round(value * 100);
  if (type === "confidence") {
    return pct >= THRESHOLDS.confidenceReview * 100
      ? "Above 60% review threshold"
      : "Below 60% review threshold";
  }
  if (type === "fraud") {
    return pct >= THRESHOLDS.fraudEscalation * 100
      ? "Above 40% escalation threshold"
      : "Below 40% escalation threshold";
  }
  return pct >= THRESHOLDS.evidenceStrong * 100
    ? "Strong documentation"
    : "Limited documentation";
}
