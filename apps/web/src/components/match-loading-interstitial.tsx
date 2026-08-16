"use client";

import { useState, useEffect, useMemo, useId, useRef } from "react";
import { motion, AnimatePresence, useReducedMotion } from "framer-motion";
import { cn } from "@/lib/utils";
import {
  getTeamData,
  LEAGUE_CONFIG,
  resolveTeamName,
} from "@/components/team-display";
import { CountryFlag, TeamLogo } from "@/components/ui/cached-logo";
import { resolveTeamLogo } from "@/lib/assets/logo-resolver";
import { LOADING_FACTS } from "@/components/loading/loading-facts";

const FLAG_SIZE_HEADER = 16;
const FLAG_SIZE_TEAM = 14;
const FLAG_CLASS_HEADER = "rounded-sm h-4 w-4 flex-shrink-0";
const FLAG_CLASS_TEAM = "rounded-sm h-3.5 w-3.5 flex-shrink-0";

/**
 * Neutral analysis-focus copy. These lines describe what the evidence gate may
 * inspect; they never claim a historical fact or source is actually available.
 */
function analysisFocus(homeTeam: string, awayTeam: string): string {
  const focuses = [
    `Checking verified form evidence for ${homeTeam} and ${awayTeam}`,
    "Comparing team-strength signals only where source coverage is available",
    "Checking whether a coherent 1X2 market is available for comparison",
    "Reviewing evidence freshness before any actionability decision",
  ];
  const hash = (homeTeam + awayTeam).split("").reduce((sum, char) => sum + char.charCodeAt(0), 0);
  return focuses[hash % focuses.length];
}

interface MatchLoadingInterstitialProps {
  homeTeam: string;
  awayTeam: string;
  league?: string;
  isLoading?: boolean;
  onLoadComplete?: () => void;
  className?: string;
}

/**
 * MatchLoadingInterstitial Component
 * 
 * A rich, engaging loading experience that:
 * - Shows animated team crests/colors
 * - Displays rotating evidence-safe status lines
 * - Provides a loading-progress indicator (never model confidence)
 * - Creates smooth transitions to prediction screen
 * 
 * Design goals:
 * - Make 3-8 second waits feel shorter and valuable
 * - 60fps animations for native feel
 * - Graceful fallbacks if data fails
 * - Zero layout shifts when content loads
 */
export function MatchLoadingInterstitial({
  homeTeam,
  awayTeam,
  league = "EPL",
  isLoading = true,
  onLoadComplete,
  className,
}: MatchLoadingInterstitialProps) {
  const [currentFactIndex, setCurrentFactIndex] = useState(0);
  const [progressValue, setProgressValue] = useState(0);
  const [showAnalysisFocus, setShowAnalysisFocus] = useState(false);
  const titleId = useId();
  const descriptionId = useId();
  const containerRef = useRef<HTMLDivElement>(null);
  const reduceMotion = useReducedMotion();

  const homeTeamData = useMemo(() => getTeamData(homeTeam), [homeTeam]);
  const awayTeamData = useMemo(() => getTeamData(awayTeam), [awayTeam]);
  const homeCanonical = useMemo(() => resolveTeamName(homeTeam), [homeTeam]);
  const awayCanonical = useMemo(() => resolveTeamName(awayTeam), [awayTeam]);
  const homeLogoMeta = useMemo(() => resolveTeamLogo(homeCanonical), [homeCanonical]);
  const awayLogoMeta = useMemo(() => resolveTeamLogo(awayCanonical), [awayCanonical]);
  const leagueConfig = useMemo(() => LEAGUE_CONFIG[league], [league]);
  const focusText = useMemo(() => analysisFocus(homeTeam, awayTeam), [homeTeam, awayTeam]);
  const homeCountryCode = homeTeamData.countryCode || leagueConfig?.countryCode;
  const awayCountryCode = awayTeamData.countryCode || leagueConfig?.countryCode;

  // Rotate through loading facts
  useEffect(() => {
    if (!isLoading) return;
    
    const interval = setInterval(() => {
      setCurrentFactIndex((prev) => (prev + 1) % LOADING_FACTS.length);
    }, 2000);

    return () => clearInterval(interval);
  }, [isLoading]);

  // Animate progress bar
  useEffect(() => {
    if (!isLoading) {
      setProgressValue(100);
      return;
    }

    const interval = setInterval(() => {
      setProgressValue((prev) => {
        // Slow down as we approach 90% to simulate real loading
        if (prev >= 90) return prev + 0.5;
        if (prev >= 70) return prev + 1;
        if (prev >= 50) return prev + 2;
        return prev + 3;
      });
    }, 100);

    return () => clearInterval(interval);
  }, [isLoading]);

  // Show a neutral analysis-focus line after the initial animation
  useEffect(() => {
    const timer = setTimeout(() => setShowAnalysisFocus(true), 1500);
    return () => clearTimeout(timer);
  }, []);

  // Notify when loading completes
  useEffect(() => {
    if (progressValue >= 100 && !isLoading && onLoadComplete) {
      const timer = setTimeout(onLoadComplete, 300);
      return () => clearTimeout(timer);
    }
  }, [progressValue, isLoading, onLoadComplete]);

  useEffect(() => {
    if (isLoading) {
      containerRef.current?.focus();
    }
  }, [isLoading]);

  const CurrentIcon = LOADING_FACTS[currentFactIndex].icon;

  return (
    <motion.div
      ref={containerRef}
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className={cn(
        "relative overflow-hidden rounded-2xl border border-slate-700/50",
        "bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900",
        "p-6 md:p-8",
        "min-h-[400px] md:min-h-[450px]", // Fixed min-height to prevent CLS
        className
      )}
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      aria-describedby={descriptionId}
      aria-busy={isLoading}
      tabIndex={-1}
    >
      {/* Hidden title and description for ARIA */}
      <h2 id={titleId} className="sr-only">
        Loading prediction for {homeTeam} vs {awayTeam}
      </h2>
      <p id={descriptionId} className="sr-only">
        Analyzing match data and generating AI prediction. Please wait.
      </p>
      
      {/* Background gradient animation */}
      <div className="absolute inset-0 bg-gradient-to-r from-purple-500/5 via-blue-500/5 to-green-500/5 animate-pulse" />
      
      {/* League badge */}
      {leagueConfig && (
        <motion.div
          initial={{ y: -20, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          transition={{ delay: 0.1 }}
          className="absolute top-4 left-1/2 -translate-x-1/2 flex items-center gap-2"
        >
          {leagueConfig.countryCode ? (
                <CountryFlag countryCode={leagueConfig.countryCode} size={FLAG_SIZE_HEADER} className={FLAG_CLASS_HEADER} />
          ) : (
            <span className="text-2xl">{leagueConfig.flag}</span>
          )}
          <span className="text-sm font-medium text-slate-400">
            {leagueConfig.fullName}
          </span>
        </motion.div>
      )}

      {/* Team matchup display */}
      <div className="relative z-10 mt-8 mb-6">
        <div className="flex items-center justify-center gap-4 md:gap-8">
          {/* Home Team */}
          <motion.div
            initial={{ x: -50, opacity: 0 }}
            animate={{ x: 0, opacity: 1 }}
            transition={{ type: "spring", stiffness: 100, delay: 0.2 }}
            className="flex flex-col items-center text-center"
          >
            <motion.div
              animate={reduceMotion ? undefined : {
                scale: [1, 1.05, 1],
                rotate: [0, 2, -2, 0]
              }}
              transition={{
                duration: 2,
                repeat: Infinity,
                ease: "easeInOut"
              }}
              className={cn(
                "w-16 h-16 md:w-20 md:h-20 rounded-full flex items-center justify-center",
                "bg-slate-800/60 ring-1 ring-white/10 shadow-lg shadow-slate-900/50 overflow-hidden"
              )}
            >
              <TeamLogo
                teamName={homeCanonical}
                logoUrl={homeLogoMeta.url}
                fallbackUrls={homeLogoMeta.fallbackUrls}
                placeholder={homeLogoMeta.placeholder}
                colors={homeLogoMeta.colors || homeTeamData.colors}
                size={80}
                className="h-full w-full"
                priority
              />
            </motion.div>
            <motion.span
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: 0.4 }}
              className="mt-3 font-bold text-white text-sm md:text-base max-w-24 md:max-w-32 truncate"
            >
              {homeTeam}
            </motion.span>
            <span className="text-xs text-slate-500 flex items-center gap-1">
              {homeCountryCode ? (
                <CountryFlag countryCode={homeCountryCode} size={FLAG_SIZE_TEAM} className={FLAG_CLASS_TEAM} />
              ) : (
                <span>{homeTeamData.flag}</span>
              )}
              <span>HOME</span>
            </span>
          </motion.div>

          {/* VS Badge */}
          <motion.div
            initial={{ scale: 0 }}
            animate={{ scale: 1 }}
            transition={{ type: "spring", stiffness: 200, delay: 0.3 }}
            className="relative"
          >
            <div className="w-12 h-12 md:w-14 md:h-14 rounded-full bg-gradient-to-br from-purple-600 to-blue-600 flex items-center justify-center shadow-lg">
              <span className="text-white font-bold text-sm md:text-base">VS</span>
            </div>
            {/* Pulsing ring */}
            <motion.div
              animate={reduceMotion ? undefined : { scale: [1, 1.3, 1], opacity: [0.5, 0, 0.5] }}
              transition={{ duration: 2, repeat: Infinity }}
              className="absolute inset-0 rounded-full border-2 border-purple-500"
            />
          </motion.div>

          {/* Away Team */}
          <motion.div
            initial={{ x: 50, opacity: 0 }}
            animate={{ x: 0, opacity: 1 }}
            transition={{ type: "spring", stiffness: 100, delay: 0.2 }}
            className="flex flex-col items-center text-center"
          >
            <motion.div
              animate={reduceMotion ? undefined : {
                scale: [1, 1.05, 1],
                rotate: [0, -2, 2, 0]
              }}
              transition={{
                duration: 2,
                repeat: Infinity,
                ease: "easeInOut",
                delay: 0.5
              }}
              className={cn(
                "w-16 h-16 md:w-20 md:h-20 rounded-full flex items-center justify-center",
                "bg-slate-800/60 ring-1 ring-white/10 shadow-lg shadow-slate-900/50 overflow-hidden"
              )}
            >
              <TeamLogo
                teamName={awayCanonical}
                logoUrl={awayLogoMeta.url}
                fallbackUrls={awayLogoMeta.fallbackUrls}
                placeholder={awayLogoMeta.placeholder}
                colors={awayLogoMeta.colors || awayTeamData.colors}
                size={80}
                className="h-full w-full"
                priority
              />
            </motion.div>
            <motion.span
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: 0.4 }}
              className="mt-3 font-bold text-white text-sm md:text-base max-w-24 md:max-w-32 truncate"
            >
              {awayTeam}
            </motion.span>
            <span className="text-xs text-slate-500 flex items-center gap-1">
              {awayCountryCode ? (
                <CountryFlag countryCode={awayCountryCode} size={FLAG_SIZE_TEAM} className={FLAG_CLASS_TEAM} />
              ) : (
                <span>{awayTeamData.flag}</span>
              )}
              <span>AWAY</span>
            </span>
          </motion.div>
        </div>
      </div>

      {/* Evidence-safe analysis focus — never a synthetic H2H/stat claim. */}
      <AnimatePresence mode="wait">
        {showAnalysisFocus && (
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
            className="text-center mb-6"
          >
            <p className="text-sm text-slate-400 italic px-4">
              {focusText}
            </p>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Loading status with rotating facts */}
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 0.5 }}
        className="space-y-4"
        aria-live="polite"
        aria-atomic="true"
      >
        {/* Progress bar */}
        <div
          className="relative h-2 bg-slate-700/50 rounded-full overflow-hidden"
          role="progressbar"
          aria-label="Analysis loading progress"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.min(Math.round(progressValue), 100)}
        >
          <motion.div
            className="absolute inset-y-0 left-0 bg-gradient-to-r from-purple-500 via-blue-500 to-green-500 rounded-full"
            initial={{ width: "0%" }}
            animate={{ width: `${Math.min(progressValue, 100)}%` }}
            transition={{ duration: 0.3, ease: "easeOut" }}
          />
          {/* Shimmer effect */}
          {!reduceMotion && (
            <motion.div
              animate={{ x: ["-100%", "200%"] }}
              transition={{ duration: 1.5, repeat: Infinity, ease: "linear" }}
              className="absolute inset-y-0 w-1/3 bg-gradient-to-r from-transparent via-white/20 to-transparent"
            />
          )}
        </div>

        {/* Rotating fact */}
        <AnimatePresence mode="wait">
          <motion.div
            key={currentFactIndex}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
            transition={{ duration: 0.3 }}
            className="flex items-center justify-center gap-2 text-slate-400"
            role="status"
            aria-live="polite"
            aria-atomic="true"
          >
            <CurrentIcon className="w-4 h-4 text-purple-400" />
            <span className="text-sm">{LOADING_FACTS[currentFactIndex].text}</span>
          </motion.div>
        </AnimatePresence>

        {/* Finalizing status — never shows a fabricated confidence figure;
            real confidence comes from the backend with the prediction */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: progressValue > 50 ? 1 : 0 }}
          className="flex items-center justify-center gap-2 pt-2"
        >
          <div className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
          <span className="text-xs text-slate-500">Finalizing analysis…</span>
        </motion.div>
      </motion.div>

      {/* Skeleton preview of prediction layout */}
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: progressValue > 70 ? 0.5 : 0 }}
        transition={{ duration: 0.5 }}
        className="mt-6 grid grid-cols-3 gap-4"
      >
        {["Home Win", "Draw", "Away Win"].map((label) => (
          <div key={label} className="text-center space-y-2">
            <div className="h-3 bg-slate-700/50 rounded animate-pulse" />
            <div className="h-8 bg-slate-700/30 rounded animate-pulse" />
            <span className="text-xs text-slate-600">{label}</span>
          </div>
        ))}
      </motion.div>
    </motion.div>
  );
}

/**
 * Skeleton version for server-side rendering
 */
export function MatchLoadingInterstitialSkeleton() {
  return (
    <div className="rounded-2xl border border-slate-700/50 bg-slate-900/50 p-6 md:p-8 min-h-[400px]">
      {/* League badge skeleton */}
      <div className="flex justify-center mb-8">
        <div className="h-6 w-32 bg-slate-700/50 rounded animate-pulse" />
      </div>

      {/* Team matchup skeleton */}
      <div className="flex items-center justify-center gap-8 mb-8">
        <div className="flex flex-col items-center gap-2">
          <div className="w-16 h-16 md:w-20 md:h-20 rounded-full bg-slate-700/50 animate-pulse" />
          <div className="h-4 w-20 bg-slate-700/50 rounded animate-pulse" />
        </div>
        <div className="w-12 h-12 rounded-full bg-slate-700/50 animate-pulse" />
        <div className="flex flex-col items-center gap-2">
          <div className="w-16 h-16 md:w-20 md:h-20 rounded-full bg-slate-700/50 animate-pulse" />
          <div className="h-4 w-20 bg-slate-700/50 rounded animate-pulse" />
        </div>
      </div>

      {/* Progress bar skeleton */}
      <div className="h-2 bg-slate-700/50 rounded-full overflow-hidden mb-4">
        <div className="h-full w-1/3 bg-slate-600/50 animate-pulse" />
      </div>

      {/* Fact skeleton */}
      <div className="flex items-center justify-center gap-2">
        <div className="w-4 h-4 bg-slate-700/50 rounded animate-pulse" />
        <div className="h-4 w-48 bg-slate-700/50 rounded animate-pulse" />
      </div>
    </div>
  );
}

export default MatchLoadingInterstitial;
