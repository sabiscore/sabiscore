import type { FullMatchAnalysisResponse } from "@/lib/full-analysis-contract";

export type Verdict = FullMatchAnalysisResponse["verdict"];

export interface VerdictTokens {
  label: string;
  color: string;
  bg: string;
  border: string;
  dot: string;
  tone: "positive" | "watch" | "neutral" | "partial" | "pass";
}

// Single source of truth for verdict badge colors. Previously duplicated
// independently across betting-intelligence-dashboard.tsx (raw hex in an
// inline <style> block), full-analysis-dashboard.tsx (this table's original
// home), and value-bet-scanner.tsx / phase8-analytics-panel.tsx's ad hoc
// "PARTIAL" chips — the same verdict label rendered in a different color
// depending on which component drew it (C8, confirmed 2026-08-14). Every
// verdict badge should import from here instead of defining its own mapping.
export const VERDICT_TOKENS: Record<Verdict, VerdictTokens> = {
  HIGH_CONVICTION: {
    label: "High Conviction",
    color: "text-[hsl(var(--conviction-high))]",
    bg: "bg-[hsl(var(--conviction-high)/0.10)]",
    border: "border-[hsl(var(--conviction-high)/0.30)]",
    dot: "bg-[hsl(var(--conviction-high))]",
    tone: "positive",
  },
  ACTIONABLE: {
    label: "Actionable",
    color: "text-[hsl(var(--conviction-actionable))]",
    bg: "bg-[hsl(var(--conviction-actionable)/0.10)]",
    border: "border-[hsl(var(--conviction-actionable)/0.30)]",
    dot: "bg-[hsl(var(--conviction-actionable))]",
    tone: "positive",
  },
  SPECULATIVE: {
    label: "Speculative",
    color: "text-[hsl(var(--conviction-speculative))]",
    bg: "bg-[hsl(var(--conviction-speculative)/0.10)]",
    border: "border-[hsl(var(--conviction-speculative)/0.30)]",
    dot: "bg-[hsl(var(--conviction-speculative))]",
    tone: "watch",
  },
  HOLD: {
    label: "Hold",
    color: "text-[hsl(var(--conviction-hold))]",
    bg: "bg-[hsl(var(--conviction-hold)/0.12)]",
    border: "border-[hsl(var(--conviction-hold)/0.35)]",
    dot: "bg-[hsl(var(--conviction-hold))]",
    tone: "neutral",
  },
  NO_BET: {
    label: "No Bet",
    color: "text-[hsl(var(--signal-danger))]",
    bg: "bg-[hsl(var(--signal-danger)/0.10)]",
    border: "border-[hsl(var(--signal-danger)/0.30)]",
    dot: "bg-[hsl(var(--signal-danger))]",
    tone: "pass",
  },
  PARTIAL: {
    label: "Partial Data",
    color: "text-[hsl(var(--conviction-partial))]",
    bg: "bg-[hsl(var(--conviction-partial)/0.10)]",
    border: "border-[hsl(var(--conviction-partial)/0.30)]",
    dot: "bg-[hsl(var(--conviction-partial))]",
    tone: "partial",
  },
};
