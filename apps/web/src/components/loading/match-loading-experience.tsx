"use client";

import { useEffect, useState, useMemo, useCallback, useRef } from "react";
import {
  motion,
  AnimatePresence,
  PanInfo,
  useMotionValue,
  useTransform,
  useReducedMotion,
} from "framer-motion";
import { Skeleton } from "@/components/ui/skeleton";
import { getTeamData, LEAGUE_CONFIG, resolveTeamName } from "@/components/team-display";
import { CountryFlag, TeamLogo } from "@/components/ui/cached-logo";
import { resolveTeamLogo } from "@/lib/assets/logo-resolver";
import { cn } from "@/lib/utils";
import { LOADING_FACTS, FUN_FACTS } from "@/components/loading/loading-facts";
import {
  hashMatchup,
  loadStoredPoll,
  loadSwipeChoices,
  persistPoll,
  persistSwipeChoice,
  INTERSTITIAL_SWIPE_QUESTIONS,
} from "@/lib/interstitial-storage";
import {
  Target,
  ChevronLeft,
  ChevronRight,
  Sparkles,
  Check,
} from "lucide-react";

interface MatchLoadingExperienceProps {
  homeTeam: string;
  awayTeam: string;
  league: string;
  matchupId?: string;
}

const SWIPE_QUESTIONS = INTERSTITIAL_SWIPE_QUESTIONS;

const FLAG_SIZE_HEADER = 16;
const FLAG_SIZE_COMPACT = 14;
const FLAG_SIZE_TINY = 12;
const FLAG_CLASS_HEADER = "rounded-sm h-4 w-4 flex-shrink-0";
const FLAG_CLASS_COMPACT = "rounded-sm h-3.5 w-3.5 flex-shrink-0";
const FLAG_CLASS_TINY = "rounded-sm h-3 w-3 flex-shrink-0";

// ============================================================================
// SUB-COMPONENTS
// ============================================================================

/**
 * Particle burst effect for milestone celebrations
 */
function ParticleBurst({ trigger }: { trigger: number }) {
  const [particles, setParticles] = useState<Array<{ id: number; x: number; y: number; color: string }>>([]);

  useEffect(() => {
    if (trigger === 0) return;
    
    const newParticles = Array.from({ length: 12 }, (_, i) => ({
      id: Date.now() + i,
      x: (Math.random() - 0.5) * 200,
      y: (Math.random() - 0.5) * 200,
      color: ["#818cf8", "#a78bfa", "#34d399", "#fbbf24"][Math.floor(Math.random() * 4)],
    }));
    setParticles(newParticles);

    const timer = setTimeout(() => setParticles([]), 1000);
    return () => clearTimeout(timer);
  }, [trigger]);

  return (
    <div className="pointer-events-none absolute inset-0 flex items-center justify-center overflow-hidden">
      {particles.map((p) => (
        <motion.div
          key={p.id}
          initial={{ x: 0, y: 0, scale: 1, opacity: 1 }}
          animate={{ x: p.x, y: p.y, scale: 0, opacity: 0 }}
          transition={{ duration: 0.8, ease: "easeOut" }}
          className="absolute h-2 w-2 rounded-full"
          style={{ backgroundColor: p.color }}
        />
      ))}
    </div>
  );
}

/**
 * Team evidence card — shown while real form/standings evidence loads.
 *
 * Zero-fabrication contract: this card must never display invented form,
 * goals, or table position. It renders labeled skeleton placeholders that
 * the real prediction screen replaces with backend-verified evidence.
 */
function TeamEvidenceCard({
  teamName,
  align,
  teamData,
}: {
  teamName: string;
  align: "left" | "right";
  teamData: ReturnType<typeof getTeamData>;
}) {
  const flagCode = teamData.countryCode;

  return (
    <motion.div
      initial={{ opacity: 0, x: align === "left" ? -20 : 20 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ delay: 0.3 }}
      className={cn(
        "flex-1 rounded-lg border border-slate-700/50 bg-slate-800/30 p-3",
        align === "right" && "text-right"
      )}
    >
      <div className={cn("mb-2 flex items-center gap-2", align === "right" && "flex-row-reverse")}>
        {flagCode ? (
          <CountryFlag countryCode={flagCode} size={FLAG_SIZE_COMPACT} className={FLAG_CLASS_COMPACT} />
        ) : (
          <span className="text-lg">{teamData.flag}</span>
        )}
        <span className="text-xs font-medium text-slate-400 truncate">{teamName}</span>
      </div>

      <div className="space-y-1.5" aria-hidden="true">
        <div className={cn("flex items-center gap-2", align === "right" && "flex-row-reverse")}>
          <span className="text-[10px] text-slate-500">Form:</span>
          <div className={cn("flex gap-1", align === "right" && "flex-row-reverse")}>
            {[0, 1, 2, 3, 4].map((i) => (
              <Skeleton key={i} className="h-5 w-5 rounded-full bg-slate-700/50" />
            ))}
          </div>
        </div>

        <div className={cn("flex gap-3", align === "right" && "justify-end")}>
          <Skeleton className="h-4 w-12 rounded bg-slate-700/40" />
          <Skeleton className="h-4 w-12 rounded bg-slate-700/40" />
        </div>

        <Skeleton className={cn("h-3 w-20 rounded bg-slate-700/30", align === "right" && "ml-auto")} />
      </div>

      <p className="mt-2 text-[10px] text-slate-500">Syncing form &amp; standings…</p>
    </motion.div>
  );
}

/**
 * Progressive confidence meter with milestones
 */
function ProgressiveConfidenceMeter({ 
  progress, 
  onMilestone 
}: { 
  progress: number;
  onMilestone?: (milestone: number) => void;
}) {
  const milestonesRef = useRef(new Set<number>());

  useEffect(() => {
    MILESTONES.forEach((m) => {
      if (progress >= m && !milestonesRef.current.has(m)) {
        milestonesRef.current.add(m);
        onMilestone?.(m);
      }
    });
  }, [progress, onMilestone]);

  const reduceMotion = useReducedMotion();

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between text-xs">
        <span className="text-slate-400">AI Analysis Progress</span>
        <span className="font-medium text-indigo-400">{Math.round(progress)}%</span>
      </div>
      <div
        className="relative h-3 overflow-hidden rounded-full bg-slate-800"
        role="progressbar"
        aria-label="AI analysis progress"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(progress)}
      >
        <motion.div
          className="h-full bg-gradient-to-r from-indigo-500 via-purple-500 to-indigo-500 bg-[length:200%_100%]"
          initial={{ width: 0 }}
          animate={
            reduceMotion
              ? { width: `${progress}%` }
              : { width: `${progress}%`, backgroundPosition: ["0% 0%", "100% 0%"] }
          }
          transition={{
            width: { duration: 0.5, ease: "easeOut" },
            backgroundPosition: { duration: 2, repeat: Infinity, ease: "linear" }
          }}
        />
        {/* Milestone markers */}
        {MILESTONES.map((m, i) => (
          <div
            key={m}
            className={cn(
              "absolute top-0 h-full w-0.5 transition-colors duration-300",
              progress >= m ? "bg-white/50" : "bg-slate-600/30",
              i === 0 && "left-[25%]",
              i === 1 && "left-[50%]",
              i === 2 && "left-[75%]",
              i === 3 && "right-0"
            )}
          />
        ))}
      </div>
      {/* Milestone labels */}
      <div className="flex justify-between text-[10px] text-slate-500">
        <span>Collect</span>
        <span>Calibrate</span>
        <span>Compare</span>
        <span>Ready</span>
      </div>
    </div>
  );
}

/**
 * Quick prediction poll (who will win).
 *
 * Records the user's own pick only — it must never display fabricated
 * community vote percentages (zero-fabrication contract).
 */
const POLL_CHOICE_CLASSES: Record<string, string> = {
  home: "border-indigo-500 bg-indigo-500/20 ring-2 ring-indigo-500/50",
  draw: "border-slate-500 bg-slate-500/20 ring-2 ring-slate-500/50",
  away: "border-emerald-500 bg-emerald-500/20 ring-2 ring-emerald-500/50",
};

function QuickPredictionPoll({
  homeTeam,
  awayTeam,
  matchupId,
  onVote,
}: {
  homeTeam: string;
  awayTeam: string;
  matchupId: string;
  onVote?: (choice: string) => void;
}) {
  const [voted, setVoted] = useState<string | null>(null);

  // Restore from localStorage
  useEffect(() => {
    const stored = loadStoredPoll(matchupId);
    if (stored) {
      setVoted(stored.choice);
    }
  }, [matchupId]);

  const handleVote = useCallback((choice: string) => {
    if (voted) return;

    setVoted(choice);
    persistPoll(matchupId, { choice, votes: {}, timestamp: Date.now() });
    onVote?.(choice);
  }, [voted, matchupId, onVote]);

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.5 }}
      className="rounded-xl border border-indigo-500/30 bg-gradient-to-br from-indigo-500/10 to-purple-500/10 p-4"
    >
      <div className="mb-3 flex items-center justify-center gap-2">
        <Target className="h-4 w-4 text-indigo-400" />
        <p className="text-sm font-medium text-slate-300">
          Your call — who wins this one?
        </p>
        {voted && (
          <span className="rounded-full bg-green-500/20 px-2 py-0.5 text-[10px] text-green-400">
            <Check className="mr-1 inline h-3 w-3" />
            Saved
          </span>
        )}
      </div>
      <div className="grid grid-cols-3 gap-2">
        {[
          { key: "home", label: homeTeam },
          { key: "draw", label: "Draw" },
          { key: "away", label: awayTeam },
        ].map(({ key, label }) => (
          <motion.button
            key={key}
            type="button"
            onClick={() => handleVote(key)}
            disabled={!!voted}
            whileHover={!voted ? { scale: 1.02 } : undefined}
            whileTap={!voted ? { scale: 0.98 } : undefined}
            aria-pressed={voted === key}
            className={cn(
              "relative overflow-hidden rounded-lg border p-3 text-center transition-all",
              voted === key
                ? POLL_CHOICE_CLASSES[key]
                : voted
                ? "border-slate-700 bg-slate-800/50 opacity-60"
                : "border-slate-700 bg-slate-800/50 hover:border-indigo-500/50 hover:bg-slate-800"
            )}
          >
            <span className="relative z-10 block text-xs font-medium text-slate-300 truncate">
              {label}
            </span>
            {voted === key && (
              <motion.span
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="relative z-10 mt-1 block text-xs font-bold text-green-400"
              >
                <Check className="inline h-3 w-3" /> Your pick
              </motion.span>
            )}
          </motion.button>
        ))}
      </div>
      <p className="mt-2 text-center text-[10px] text-slate-500">
        Compare your read against the model when the analysis lands.
      </p>
    </motion.div>
  );
}

/**
 * Swipe prediction card (Tinder-style)
 */
function SwipePredictionCard({
  question,
  leftLabel,
  rightLabel,
  centerLabel,
  matchupId,
  questionId,
  onSwipe,
}: {
  question: string;
  leftLabel: string;
  rightLabel: string;
  centerLabel?: string;
  matchupId: string;
  questionId: string;
  onSwipe?: (direction: "left" | "right" | "center") => void;
}) {
  const [answered, setAnswered] = useState<"left" | "right" | "center" | null>(null);
  const x = useMotionValue(0);
  const rotate = useTransform(x, [-150, 0, 150], [-15, 0, 15]);
  const leftOpacity = useTransform(x, [-150, 0], [1, 0]);
  const rightOpacity = useTransform(x, [0, 150], [0, 1]);

  // Restore from localStorage
  useEffect(() => {
    const stored = loadSwipeChoices(matchupId);
    if (stored && stored[questionId]) {
      setAnswered(stored[questionId] as "left" | "right" | "center");
    }
  }, [matchupId, questionId]);

  const handleDragEnd = useCallback((_: never, info: PanInfo) => {
    if (answered) return;
    
    if (info.offset.x < -100) {
      setAnswered("left");
      persistSwipeChoice(matchupId, questionId, "left");
      onSwipe?.("left");
    } else if (info.offset.x > 100) {
      setAnswered("right");
      persistSwipeChoice(matchupId, questionId, "right");
      onSwipe?.("right");
    }
  }, [answered, matchupId, questionId, onSwipe]);

  const handleCenterTap = useCallback(() => {
    if (answered || !centerLabel) return;
    setAnswered("center");
    persistSwipeChoice(matchupId, questionId, "center");
    onSwipe?.("center");
  }, [answered, centerLabel, matchupId, questionId, onSwipe]);

  if (answered) {
    return (
      <motion.div
        initial={{ scale: 0.9, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        className="flex items-center justify-center rounded-xl border border-green-500/30 bg-green-500/10 p-4"
      >
        <Check className="mr-2 h-4 w-4 text-green-400" />
        <span className="text-sm text-green-400">
          {answered === "left" ? leftLabel : answered === "right" ? rightLabel : centerLabel}
        </span>
      </motion.div>
    );
  }

  return (
    <div className="relative">
      {/* Direction hints */}
      <motion.div 
        style={{ opacity: leftOpacity }}
        className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 rounded-full bg-red-500/20 px-3 py-1"
      >
        <span className="text-xs font-bold text-red-400">{leftLabel}</span>
      </motion.div>
      <motion.div 
        style={{ opacity: rightOpacity }}
        className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 rounded-full bg-green-500/20 px-3 py-1"
      >
        <span className="text-xs font-bold text-green-400">{rightLabel}</span>
      </motion.div>

      <motion.div
        drag="x"
        dragConstraints={{ left: 0, right: 0 }}
        dragElastic={0.5}
        onDragEnd={handleDragEnd}
        style={{ x, rotate }}
        whileDrag={{ cursor: "grabbing" }}
        className="cursor-grab rounded-xl border border-purple-500/30 bg-gradient-to-br from-purple-500/10 to-indigo-500/10 p-4"
      >
        <div className="text-center">
          <p className="mb-2 text-sm font-medium text-slate-300">{question}</p>
          <div className="flex items-center justify-center gap-4 text-xs text-slate-500">
            <span className="flex items-center gap-1">
              <ChevronLeft className="h-3 w-3" />
              Swipe {leftLabel}
            </span>
            {centerLabel && (
              <button
                type="button"
                onClick={handleCenterTap}
                className="rounded-full bg-slate-700/50 px-3 py-1 text-slate-400 transition-colors hover:bg-slate-700"
              >
                Tap: {centerLabel}
              </button>
            )}
            <span className="flex items-center gap-1">
              Swipe {rightLabel}
              <ChevronRight className="h-3 w-3" />
            </span>
          </div>
        </div>
      </motion.div>
    </div>
  );
}

/**
 * Rotating loading tips display
 */
function LoadingTips() {
  const [tipIndex, setTipIndex] = useState(0);

  useEffect(() => {
    const interval = setInterval(() => {
      setTipIndex((prev) => (prev + 1) % LOADING_FACTS.length);
    }, 2500);
    return () => clearInterval(interval);
  }, []);

  const CurrentIcon = LOADING_FACTS[tipIndex].icon;

  return (
    <div className="h-6 overflow-hidden">
      <AnimatePresence mode="wait">
        <motion.div
          key={tipIndex}
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -10 }}
          className="flex items-center justify-center gap-2 text-xs text-indigo-400/80"
        >
          <CurrentIcon className="h-3.5 w-3.5" />
          {LOADING_FACTS[tipIndex].text}
        </motion.div>
      </AnimatePresence>
    </div>
  );
}

/**
 * Fun fact card that rotates
 */
function FunFactCard() {
  const [factIndex, setFactIndex] = useState(() => Math.floor(Math.random() * FUN_FACTS.length));

  useEffect(() => {
    const interval = setInterval(() => {
      setFactIndex((prev) => (prev + 1) % FUN_FACTS.length);
    }, 6000);
    return () => clearInterval(interval);
  }, []);

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ delay: 0.7 }}
      className="rounded-lg border border-amber-500/20 bg-amber-500/5 p-3"
    >
      <div className="mb-1 flex items-center gap-1.5">
        <Sparkles className="h-3 w-3 text-amber-400" />
        <span className="text-[10px] font-medium uppercase tracking-wider text-amber-400/80">
          Did you know?
        </span>
      </div>
      <AnimatePresence mode="wait">
        <motion.p
          key={factIndex}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="text-xs leading-relaxed text-slate-400"
        >
          {FUN_FACTS[factIndex]}
        </motion.p>
      </AnimatePresence>
    </motion.div>
  );
}

// ============================================================================
// MAIN COMPONENT
// ============================================================================

const MILESTONES = [25, 50, 75, 90];

/**
 * MatchLoadingExperience V2
 * 
 * Enhanced loading interstitial with:
 * - Progressive confidence meter with milestone celebrations
 * - Quick prediction poll (persisted to localStorage)
 * - Swipe prediction cards (Tinder-style interactions)
 * - Team stats preview
 * - Rotating facts and tips
 * - Particle effects on milestones
 * 
 * Feature flagged under: PREDICTION_INTERSTITIAL_V2
 */
export function MatchLoadingExperience({
  homeTeam,
  awayTeam,
  league,
  matchupId,
}: MatchLoadingExperienceProps) {
  const [progress, setProgress] = useState(0);
  const [particleTrigger, setParticleTrigger] = useState(0);
  const [swipeIndex, setSwipeIndex] = useState(0);
  const [showColdHint, setShowColdHint] = useState(false);
  const reduceMotion = useReducedMotion();

  const matchupKey = useMemo(() => matchupId ?? hashMatchup(homeTeam, awayTeam), [homeTeam, awayTeam, matchupId]);

  const homeTeamData = useMemo(() => getTeamData(homeTeam), [homeTeam]);
  const awayTeamData = useMemo(() => getTeamData(awayTeam), [awayTeam]);
  const homeCanonical = useMemo(() => resolveTeamName(homeTeam), [homeTeam]);
  const awayCanonical = useMemo(() => resolveTeamName(awayTeam), [awayTeam]);
  const homeLogoMeta = useMemo(() => resolveTeamLogo(homeCanonical), [homeCanonical]);
  const awayLogoMeta = useMemo(() => resolveTeamLogo(awayCanonical), [awayCanonical]);
  const leagueConfig = useMemo(() => LEAGUE_CONFIG[league], [league]);
  const homeCountryCode = homeTeamData.countryCode || leagueConfig?.countryCode;
  const awayCountryCode = awayTeamData.countryCode || leagueConfig?.countryCode;

  // ponytail: cubic ease-out asymptotes at 90% over the 28s client budget.
  // Stops itself at saturation — it previously kept firing every 300ms
  // indefinitely, worst on the slow cold-start path this screen exists for.
  useEffect(() => {
    const start = Date.now();
    const interval = setInterval(() => {
      const t = Math.min((Date.now() - start) / 28_000, 1);
      setProgress(Math.floor(90 * (1 - Math.pow(1 - t, 3))));
      if (t >= 1) clearInterval(interval);
    }, 300);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    const t = setTimeout(() => setShowColdHint(true), 15_000);
    return () => clearTimeout(t);
  }, []);

  const handleMilestone = useCallback((milestone: number) => {
    setParticleTrigger((p) => p + 1);
    
    // Show next swipe question at certain milestones
    if (milestone === 50 || milestone === 75) {
      setSwipeIndex((i) => Math.min(i + 1, SWIPE_QUESTIONS.length - 1));
    }
  }, []);

  return (
    // Container matches the results page (max-w-6xl) so loading→results does not
    // snap ~480px wider on desktop. The 3/2 grid keeps card widths readable at
    // that size instead of stretching one column across the full width.
    // No padding of its own: the root <main> already applies px-4 py-5 sm:px-6
    // lg:px-8, and app/match/[id]/page.tsx adds none — a p-4 here inset the
    // loading content 16px per side and snapped it wider once results landed.
    <div className="mx-auto w-full max-w-6xl">
      <div className="grid gap-4 lg:grid-cols-5 lg:items-start">
      <div className="space-y-4 lg:col-span-3">
      {/* Main card with team matchup */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="relative overflow-hidden rounded-2xl border border-slate-700/50 bg-gradient-to-br from-slate-800/80 to-slate-900/80 backdrop-blur-sm"
      >
        {!reduceMotion && <ParticleBurst trigger={particleTrigger} />}

        {/* Header with league */}
        <div className="border-b border-slate-700/50 bg-slate-800/50 px-4 py-2">
          <div className="flex items-center justify-between">
            {leagueConfig ? (
              <span className="flex items-center gap-1.5 text-sm font-medium text-slate-400">
                {leagueConfig.countryCode ? (
                  <CountryFlag countryCode={leagueConfig.countryCode} size={FLAG_SIZE_HEADER} className={FLAG_CLASS_HEADER} />
                ) : (
                  <span>{leagueConfig.flag}</span>
                )}
                {leagueConfig.fullName}
              </span>
            ) : (
              <span className="text-sm font-medium text-slate-400">{league}</span>
            )}
            <span className="flex items-center gap-1.5 text-xs text-indigo-400">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-indigo-400" />
              Generating AI Insights
            </span>
          </div>
        </div>

        <div className="space-y-4 p-4">
          {/* Team matchup with entrance animation */}
          <div className="flex items-center justify-center gap-3">
            <motion.div
              initial={{ opacity: 0, x: -30, scale: 0.8 }}
              animate={{ opacity: 1, x: 0, scale: 1 }}
              transition={{ type: "spring", stiffness: 200, damping: 20 }}
              className="flex flex-col items-center text-center"
            >
              <motion.div
                animate={reduceMotion ? undefined : { scale: [1, 1.05, 1] }}
                transition={{ duration: 2, repeat: Infinity }}
                className={cn(
                  "flex h-14 w-14 items-center justify-center rounded-full shadow-lg ring-1 ring-white/10 bg-slate-800/60 overflow-hidden",
                  homeTeamData.bgColor
                )}
              >
                <TeamLogo
                  teamName={homeCanonical}
                  logoUrl={homeLogoMeta.url}
                  fallbackUrls={homeLogoMeta.fallbackUrls}
                  placeholder={homeLogoMeta.placeholder}
                  colors={homeLogoMeta.colors || homeTeamData.colors}
                  size={72}
                  className="h-full w-full"
                  priority
                />
              </motion.div>
              <span className="mt-2 max-w-20 truncate text-sm font-bold text-white">{homeTeam}</span>
              <span className="flex items-center gap-1 text-[10px] text-slate-500">
                {homeCountryCode ? (
                  <CountryFlag countryCode={homeCountryCode} size={FLAG_SIZE_TINY} className={FLAG_CLASS_TINY} />
                ) : (
                  <span>{homeTeamData.flag}</span>
                )}
                HOME
              </span>
            </motion.div>

            <motion.div
              initial={{ scale: 0 }}
              animate={{ scale: 1 }}
              transition={{ type: "spring", delay: 0.2 }}
              className="relative"
            >
              <div className="flex h-10 w-10 items-center justify-center rounded-full bg-gradient-to-br from-purple-600 to-blue-600 shadow-lg">
                <span className="text-xs font-bold text-white">VS</span>
              </div>
              <motion.div
                animate={reduceMotion ? undefined : { scale: [1, 1.3, 1], opacity: [0.5, 0, 0.5] }}
                transition={{ duration: 2, repeat: Infinity }}
                className="absolute inset-0 rounded-full border-2 border-purple-500"
              />
            </motion.div>

            <motion.div
              initial={{ opacity: 0, x: 30, scale: 0.8 }}
              animate={{ opacity: 1, x: 0, scale: 1 }}
              transition={{ type: "spring", stiffness: 200, damping: 20 }}
              className="flex flex-col items-center text-center"
            >
              <motion.div
                animate={reduceMotion ? undefined : { scale: [1, 1.05, 1] }}
                transition={{ duration: 2, repeat: Infinity, delay: 0.5 }}
                className={cn(
                  "flex h-14 w-14 items-center justify-center rounded-full shadow-lg ring-1 ring-white/10 bg-slate-800/60 overflow-hidden",
                  awayTeamData.bgColor
                )}
              >
                <TeamLogo
                  teamName={awayCanonical}
                  logoUrl={awayLogoMeta.url}
                  fallbackUrls={awayLogoMeta.fallbackUrls}
                  placeholder={awayLogoMeta.placeholder}
                  colors={awayLogoMeta.colors || awayTeamData.colors}
                  size={72}
                  className="h-full w-full"
                  priority
                />
              </motion.div>
              <span className="mt-2 max-w-20 truncate text-sm font-bold text-white">{awayTeam}</span>
              <span className="flex items-center gap-1 text-[10px] text-slate-500">
                {awayCountryCode ? (
                  <CountryFlag countryCode={awayCountryCode} size={FLAG_SIZE_TINY} className={FLAG_CLASS_TINY} />
                ) : (
                  <span>{awayTeamData.flag}</span>
                )}
                AWAY
              </span>
            </motion.div>
          </div>

          {/* Progressive confidence meter */}
          <ProgressiveConfidenceMeter progress={progress} onMilestone={handleMilestone} />

          {/* Cold-start hint — appears after 15s if still loading */}
          <AnimatePresence>
            {showColdHint && (
              <motion.p
                initial={reduceMotion ? {} : { opacity: 0 }}
                animate={{ opacity: 1 }}
                className="text-center text-xs text-slate-500"
              >
                Taking longer than usual? The backend may be warming up from idle — analysis continues automatically.
              </motion.p>
            )}
          </AnimatePresence>

          {/* Loading tips ticker */}
          <LoadingTips />

          {/* Team evidence cards — real data replaces these on the prediction screen */}
          <div className="flex gap-3">
            <TeamEvidenceCard teamName={homeTeam} align="left" teamData={homeTeamData} />
            <TeamEvidenceCard teamName={awayTeam} align="right" teamData={awayTeamData} />
          </div>

          {/* Skeleton preview of prediction layout */}
          <motion.div 
            initial={{ opacity: 0 }}
            animate={{ opacity: progress > 70 ? 0.5 : 0 }}
            className="space-y-2 rounded-xl border border-slate-700/30 bg-slate-900/50 p-3"
          >
            <div className="flex items-center justify-between">
              <Skeleton className="h-3 w-28 bg-slate-700/50" />
              <Skeleton className="h-3 w-16 rounded-full bg-slate-700/50" />
            </div>
            <div className="grid grid-cols-3 gap-2">
              {[1, 2, 3].map((i) => (
                <div key={i} className="space-y-1">
                  <Skeleton className="h-6 w-full bg-slate-700/40" />
                  <Skeleton className="h-2 w-full bg-slate-700/30" />
                </div>
              ))}
            </div>
          </motion.div>
        </div>
      </motion.div>
      </div>

      {/* Engagement column — sits beside the main card on large screens */}
      <div className="space-y-4 lg:col-span-2">
      {/* Quick prediction poll */}
      <QuickPredictionPoll
        homeTeam={homeTeam}
        awayTeam={awayTeam}
        matchupId={matchupKey}
      />

      {/* Swipe prediction cards */}
      <AnimatePresence mode="wait">
        {swipeIndex < SWIPE_QUESTIONS.length && (
          <motion.div
            key={SWIPE_QUESTIONS[swipeIndex].id}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -20 }}
          >
            <SwipePredictionCard
              question={SWIPE_QUESTIONS[swipeIndex].question}
              leftLabel={SWIPE_QUESTIONS[swipeIndex].left}
              rightLabel={SWIPE_QUESTIONS[swipeIndex].right}
              centerLabel={"center" in SWIPE_QUESTIONS[swipeIndex] ? SWIPE_QUESTIONS[swipeIndex].center : undefined}
              matchupId={matchupKey}
              questionId={SWIPE_QUESTIONS[swipeIndex].id}
              onSwipe={() => setSwipeIndex((i) => i + 1)}
            />
          </motion.div>
        )}
      </AnimatePresence>

      {/* Fun fact card */}
      <FunFactCard />
      </div>
      </div>

      {/* Footer disclaimer */}
      <motion.p
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 0.8 }}
        className="mt-4 text-center text-[10px] text-slate-600"
      >
        Ensemble ML models · calibrated per league · verified evidence only
      </motion.p>
    </div>
  );
}

/**
 * Skeleton version for SSR
 */
export function MatchLoadingExperienceSkeleton() {
  return (
    // Mirrors the live layout exactly — a different container here would shift
    // the whole screen the moment the client component hydrates.
    <div className="mx-auto grid w-full max-w-6xl gap-4 lg:grid-cols-5 lg:items-start">
      <div className="rounded-2xl border border-slate-700/50 bg-slate-900/50 p-4 lg:col-span-3">
        {/* Header skeleton */}
        <div className="mb-4 flex justify-between">
          <Skeleton className="h-5 w-32 bg-slate-700/50" />
          <Skeleton className="h-5 w-24 bg-slate-700/50" />
        </div>

        {/* Team matchup skeleton */}
        <div className="mb-4 flex items-center justify-center gap-4">
          <div className="flex flex-col items-center gap-2">
            <Skeleton className="h-14 w-14 rounded-full bg-slate-700/50" />
            <Skeleton className="h-4 w-16 bg-slate-700/50" />
          </div>
          <Skeleton className="h-10 w-10 rounded-full bg-slate-700/50" />
          <div className="flex flex-col items-center gap-2">
            <Skeleton className="h-14 w-14 rounded-full bg-slate-700/50" />
            <Skeleton className="h-4 w-16 bg-slate-700/50" />
          </div>
        </div>

        {/* Progress bar skeleton */}
        <Skeleton className="mb-4 h-3 w-full rounded-full bg-slate-700/50" />

        {/* Stats cards skeleton */}
        <div className="flex gap-3">
          <Skeleton className="h-24 flex-1 rounded-lg bg-slate-700/30" />
          <Skeleton className="h-24 flex-1 rounded-lg bg-slate-700/30" />
        </div>
      </div>

      {/* Engagement column skeleton */}
      <div className="space-y-4 lg:col-span-2">
        <Skeleton className="h-28 w-full rounded-xl bg-slate-700/30" />
        <Skeleton className="h-20 w-full rounded-xl bg-slate-700/20" />
      </div>

      {/* Footer placeholder — the live component renders a disclaimer line here;
          without it the whole card shifted up ~24px the moment it hydrated. */}
      <div className="lg:col-span-5">
        <Skeleton className="mx-auto h-3 w-72 max-w-full bg-slate-700/20" />
      </div>
    </div>
  );
}

export default MatchLoadingExperience;
