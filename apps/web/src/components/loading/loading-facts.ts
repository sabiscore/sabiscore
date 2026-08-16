import {
  Trophy,
  TrendingUp,
  Users,
  Target,
  Zap,
  BarChart3,
  Star,
  Shield,
  Activity,
  Database,
  type LucideIcon,
} from "lucide-react";

export interface LoadingFact {
  icon: LucideIcon;
  text: string;
}

/**
 * Rotating status lines shown while an analysis loads.
 * First 5 mirror the 5-step pipeline visible on the homepage.
 * Remaining 4 are technical tips — no bookmaker brand claims.
 */
export const LOADING_FACTS: LoadingFact[] = [
  { icon: Database, text: "Collecting evidence from configured backend providers..." },
  { icon: Shield, text: "Reconciling fixture identity across providers..." },
  { icon: BarChart3, text: "Checking active model and calibration metadata..." },
  { icon: TrendingUp, text: "Checking coherent market evidence when available..." },
  { icon: Zap, text: "Applying evidence gates before any actionability decision..." },
  { icon: Trophy, text: "Checking historical matchup evidence when available..." },
  { icon: Target, text: "Checking expected-goals evidence when available..." },
  { icon: Users, text: "Checking squad-availability sources when available..." },
  { icon: Star, text: "Checking team-strength rating coverage..." },
  { icon: Activity, text: "Checking evidence freshness and calibration coverage..." },
];

/**
 * Neutral, educational facts shown during longer waits.
 * Analytical definitions only — no profit claims, no promotional
 * betting copy (CLAUDE.md prohibited-language rule).
 */
export const FUN_FACTS = [
  "The first ever international football match was played between Scotland and England in 1872.",
  "xG (Expected Goals) measures the quality of chances created, not just shots taken.",
  "The Kelly Criterion is a bankroll-proportional method for sizing stakes relative to estimated edge.",
  "PPDA (Passes Per Defensive Action) measures pressing intensity.",
  "Home advantage can influence match outcomes, but its size varies by competition and season.",
  "Weather is contextual evidence and should only influence a forecast when a verified source is available.",
  "xA (Expected Assists) measures the quality of key passes.",
  "Deep completions track passes into the penalty area.",
  "De-vigging removes the bookmaker margin to reveal fair market probabilities.",
  "Ranked Probability Score (RPS) rewards forecasts that are close in ordering, not just exactly right.",
];
