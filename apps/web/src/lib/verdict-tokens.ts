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
    color: "text-conviction-high",
    bg: "bg-conviction-high/10",
    border: "border-conviction-high/30",
    dot: "bg-conviction-high",
    tone: "positive",
  },
  ACTIONABLE: {
    label: "Actionable",
    color: "text-conviction-actionable",
    bg: "bg-conviction-actionable/10",
    border: "border-conviction-actionable/30",
    dot: "bg-conviction-actionable",
    tone: "positive",
  },
  SPECULATIVE: {
    label: "Speculative",
    color: "text-conviction-speculative",
    bg: "bg-conviction-speculative/10",
    border: "border-conviction-speculative/30",
    dot: "bg-conviction-speculative",
    tone: "watch",
  },
  HOLD: {
    label: "Hold",
    color: "text-conviction-hold",
    bg: "bg-conviction-hold/12",
    border: "border-conviction-hold/35",
    dot: "bg-conviction-hold",
    tone: "neutral",
  },
  NO_BET: {
    label: "No Bet",
    color: "text-signal-danger",
    bg: "bg-signal-danger/10",
    border: "border-signal-danger/30",
    dot: "bg-signal-danger",
    tone: "pass",
  },
  PARTIAL: {
    label: "Partial Data",
    color: "text-conviction-partial",
    bg: "bg-conviction-partial/10",
    border: "border-conviction-partial/30",
    dot: "bg-conviction-partial",
    tone: "partial",
  },
};
