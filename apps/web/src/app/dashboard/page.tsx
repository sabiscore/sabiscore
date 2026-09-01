"use client";

import React, { useState } from "react";
import Link from "next/link";
import {
  Bookmark,
  Heart,
  Sliders,
  User,
  ArrowRight,
  Trash2,
  ExternalLink,
  Check,
} from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import { AuthModal } from "@/components/AuthModal";
import { cn } from "@/lib/utils";

const TIMEZONE_OPTIONS = [
  { value: "Africa/Lagos", label: "Africa/Lagos (WAT, UTC+1)" },
  { value: "Africa/Johannesburg", label: "Africa/Johannesburg (SAST, UTC+2)" },
  { value: "Africa/Nairobi", label: "Africa/Nairobi (EAT, UTC+3)" },
  { value: "Europe/London", label: "Europe/London (GMT/BST)" },
  { value: "Europe/Paris", label: "Europe/Paris (CET, UTC+1)" },
  { value: "America/New_York", label: "America/New_York (EST/EDT)" },
  { value: "UTC", label: "UTC" },
];

const LEAGUE_OPTIONS = [
  { value: "EPL", label: "Premier League (EPL)" },
  { value: "LA_LIGA", label: "La Liga" },
  { value: "SERIE_A", label: "Serie A" },
  { value: "BUNDESLIGA", label: "Bundesliga" },
  { value: "LIGUE_1", label: "Ligue 1" },
  { value: "EREDIVISIE", label: "Eredivisie" },
  { value: "UCL", label: "Champions League (UCL)" },
];

export default function DashboardPage() {
  const {
    user,
    isAuthenticated,
    favorites,
    savedMatches,
    preferences,
    toggleFavorite,
    removeSavedMatch,
    updatePreferences,
  } = useAuth();

  const [activeTab, setActiveTab] = useState<"saved" | "favorites" | "preferences">("saved");
  const [authModalOpen, setAuthModalOpen] = useState(false);

  // Preference form state
  const [oddsFormat, setOddsFormat] = useState(preferences?.odds_format || "DECIMAL");
  const [timezone, setTimezone] = useState(preferences?.timezone || "Africa/Lagos");
  const [defaultLeague, setDefaultLeague] = useState(preferences?.default_league || "EPL");
  const [prefSaved, setPrefSaved] = useState(false);

  const handleSavePreferences = async (e: React.FormEvent) => {
    e.preventDefault();
    const success = await updatePreferences({
      odds_format: oddsFormat,
      timezone: timezone,
      default_league: defaultLeague,
    });
    if (success) {
      setPrefSaved(true);
      setTimeout(() => setPrefSaved(false), 2500);
    }
  };

  const displayName = user?.username || user?.full_name || user?.email.split("@")[0] || "Guest Analyst";

  return (
    <div className="mx-auto max-w-5xl space-y-6 pb-12">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-white/10 bg-slate-900/80 p-6 backdrop-blur shadow-xl">
        <div className="flex items-center gap-4">
          <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-emerald-500/20 text-emerald-300 font-bold text-lg">
            <User className="h-6 w-6" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-xl font-bold text-white tracking-tight sm:text-2xl">
                {displayName}&apos;s Workspace
              </h1>
              {isAuthenticated ? (
                <span className="rounded-md bg-emerald-500/20 px-2 py-0.5 text-[10px] font-bold text-emerald-300 border border-emerald-500/30">
                  VERIFIED ANALYST
                </span>
              ) : (
                <span className="rounded-md bg-amber-500/20 px-2 py-0.5 text-[10px] font-bold text-amber-300 border border-amber-500/30">
                  ANONYMOUS SESSION
                </span>
              )}
            </div>
            <p className="mt-1 text-xs text-slate-400">
              {isAuthenticated
                ? user?.email
                : "Personalization saved locally. Register to sync across all your devices."}
            </p>
          </div>
        </div>

        {!isAuthenticated && (
          <button
            type="button"
            onClick={() => setAuthModalOpen(true)}
            className="flex items-center gap-2 rounded-xl bg-emerald-400 px-4 py-2 text-xs font-bold text-slate-950 transition hover:bg-emerald-300 focus:outline-none focus:ring-2 focus:ring-emerald-400"
          >
            <span>Upgrade to Free Account</span>
            <ArrowRight className="h-3.5 w-3.5" />
          </button>
        )}
      </div>

      {/* Tabs */}
      <div className="flex border-b border-white/10" role="tablist" aria-label="Dashboard views">
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === "saved"}
          onClick={() => setActiveTab("saved")}
          className={cn(
            "flex items-center gap-2 border-b-2 px-4 py-3 text-xs font-semibold transition",
            activeTab === "saved"
              ? "border-emerald-400 text-emerald-400"
              : "border-transparent text-slate-400 hover:text-slate-200"
          )}
        >
          <Bookmark className="h-4 w-4" />
          <span>Saved Matches ({savedMatches.length})</span>
        </button>

        <button
          type="button"
          role="tab"
          aria-selected={activeTab === "favorites"}
          onClick={() => setActiveTab("favorites")}
          className={cn(
            "flex items-center gap-2 border-b-2 px-4 py-3 text-xs font-semibold transition",
            activeTab === "favorites"
              ? "border-emerald-400 text-emerald-400"
              : "border-transparent text-slate-400 hover:text-slate-200"
          )}
        >
          <Heart className="h-4 w-4" />
          <span>Favorites ({favorites.length})</span>
        </button>

        <button
          type="button"
          role="tab"
          aria-selected={activeTab === "preferences"}
          onClick={() => setActiveTab("preferences")}
          className={cn(
            "flex items-center gap-2 border-b-2 px-4 py-3 text-xs font-semibold transition",
            activeTab === "preferences"
              ? "border-emerald-400 text-emerald-400"
              : "border-transparent text-slate-400 hover:text-slate-200"
          )}
        >
          <Sliders className="h-4 w-4" />
          <span>Preferences & Timezone</span>
        </button>
      </div>

      {/* Tab 1: Saved Matches */}
      {activeTab === "saved" && (
        <div className="space-y-4">
          {savedMatches.length === 0 ? (
            <div className="rounded-2xl border border-white/10 bg-slate-900/40 p-12 text-center">
              <Bookmark className="mx-auto h-8 w-8 text-slate-500 mb-3" />
              <h2 className="text-base font-semibold text-white">No saved matches in your watchlist</h2>
              <p className="mt-1 text-xs text-slate-400 max-w-sm mx-auto">
                Track fixtures and monitor probability movements by clicking &quot;Save Match&quot; on any match intelligence page.
              </p>
              <Link
                href="/intelligence"
                className="mt-4 inline-flex items-center gap-2 rounded-xl bg-slate-800 px-4 py-2 text-xs font-semibold text-emerald-300 hover:bg-slate-700 transition"
              >
                <span>Browse Live Intelligence</span>
                <ArrowRight className="h-3.5 w-3.5" />
              </Link>
            </div>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2">
              {savedMatches.map((sm) => (
                <div
                  key={sm.id || sm.match_id}
                  className="flex flex-col justify-between rounded-xl border border-white/10 bg-slate-900/60 p-4 transition hover:border-white/20"
                >
                  <div>
                    <div className="flex items-center justify-between">
                      <span className="text-[11px] font-bold text-emerald-400 uppercase tracking-wider">
                        WATCHLIST FIXTURE
                      </span>
                      <button
                        type="button"
                        onClick={() => removeSavedMatch(sm.match_id || sm.id)}
                        className="rounded-lg p-1 text-slate-500 hover:bg-rose-500/10 hover:text-rose-400 focus:outline-none"
                        aria-label={`Remove ${sm.match_id} from saved matches`}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>

                    <h2 className="mt-2 text-sm font-bold text-white">{sm.match_id}</h2>
                    {sm.notes && (
                      <p className="mt-1.5 rounded-lg bg-white/[0.03] p-2 text-xs text-slate-300 border border-white/5">
                        &ldquo;{sm.notes}&rdquo;
                      </p>
                    )}
                  </div>

                  <div className="mt-4 flex items-center justify-between border-t border-white/10 pt-3">
                    <span className="text-[10px] text-slate-500">
                      Target: {sm.target_outcome || "Any"}
                    </span>
                    <Link
                      href={`/match/${encodeURIComponent(sm.match_id)}`}
                      className="flex items-center gap-1 text-xs font-semibold text-emerald-400 hover:text-emerald-300"
                    >
                      <span>Analyze</span>
                      <ExternalLink className="h-3 w-3" />
                    </Link>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Tab 2: Favorites */}
      {activeTab === "favorites" && (
        <div className="space-y-4">
          {favorites.length === 0 ? (
            <div className="rounded-2xl border border-white/10 bg-slate-900/40 p-12 text-center">
              <Heart className="mx-auto h-8 w-8 text-slate-500 mb-3" />
              <h2 className="text-base font-semibold text-white">No favorite teams or competitions yet</h2>
              <p className="mt-1 text-xs text-slate-400 max-w-sm mx-auto">
                Add teams to your favorites to get prioritized fixture alerts and dedicated analytical dashboards.
              </p>
            </div>
          ) : (
            <div className="grid gap-3 sm:grid-cols-3">
              {favorites.map((fav) => (
                <div
                  key={fav.id || fav.entity_id}
                  className="flex items-center justify-between rounded-xl border border-white/10 bg-slate-900/60 p-4 transition hover:border-white/20"
                >
                  <div>
                    <span className="text-[10px] font-bold text-emerald-400 uppercase">
                      {fav.entity_type || "TEAM"}
                    </span>
                    <h2 className="text-sm font-bold text-white capitalize">{fav.entity_id}</h2>
                  </div>

                  <div className="flex items-center gap-1">
                    <Link
                      href={fav.entity_type === "competition" ? `/intelligence?league=${fav.entity_id}` : `/team/${fav.entity_id}`}
                      className="rounded-lg p-1.5 text-slate-400 hover:bg-white/10 hover:text-white"
                      aria-label={`View ${fav.entity_id}`}
                    >
                      <ExternalLink className="h-3.5 w-3.5" />
                    </Link>
                    <button
                      type="button"
                      onClick={() => toggleFavorite(fav.entity_type, fav.entity_id)}
                      className="rounded-lg p-1.5 text-slate-500 hover:bg-rose-500/10 hover:text-rose-400"
                      aria-label={`Remove ${fav.entity_id} from favorites`}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Tab 3: Preferences */}
      {activeTab === "preferences" && (
        <form
          onSubmit={handleSavePreferences}
          className="rounded-2xl border border-white/10 bg-slate-900/60 p-6 space-y-5"
        >
          <div className="flex items-center justify-between border-b border-white/10 pb-3">
            <div>
              <h2 className="text-base font-bold text-white">Platform Settings & Display Preferences</h2>
              <p className="text-xs text-slate-400">Configure how odds, timezones, and leagues appear across all devices.</p>
            </div>
            {prefSaved && (
              <span className="flex items-center gap-1 text-xs font-semibold text-emerald-400 bg-emerald-500/10 px-2.5 py-1 rounded-lg border border-emerald-500/30">
                <Check className="h-3.5 w-3.5" />
                <span>Saved!</span>
              </span>
            )}
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label htmlFor="pref-odds-format" className="block text-xs font-semibold text-slate-300 mb-1">
                Odds Display Format
              </label>
              <select
                id="pref-odds-format"
                value={oddsFormat}
                onChange={(e) => setOddsFormat(e.target.value)}
                className="w-full rounded-xl border border-white/10 bg-slate-950 px-3 py-2 text-xs text-white focus:outline-none focus:ring-1 focus:ring-emerald-400"
              >
                <option value="DECIMAL">Decimal (e.g. 2.50)</option>
                <option value="FRACTIONAL">Fractional (e.g. 6/4)</option>
                <option value="AMERICAN">American (e.g. +150)</option>
              </select>
            </div>

            <div>
              <label htmlFor="pref-timezone" className="block text-xs font-semibold text-slate-300 mb-1">
                Timezone (Kickoff & Alert Scheduling)
              </label>
              <select
                id="pref-timezone"
                value={timezone}
                onChange={(e) => setTimezone(e.target.value)}
                className="w-full rounded-xl border border-white/10 bg-slate-950 px-3 py-2 text-xs text-white focus:outline-none focus:ring-1 focus:ring-emerald-400"
              >
                {TIMEZONE_OPTIONS.map((tz) => (
                  <option key={tz.value} value={tz.value}>
                    {tz.label}
                  </option>
                ))}
              </select>
            </div>

            <div className="sm:col-span-2">
              <label htmlFor="pref-default-league" className="block text-xs font-semibold text-slate-300 mb-1">
                Default Primary Competition
              </label>
              <select
                id="pref-default-league"
                value={defaultLeague}
                onChange={(e) => setDefaultLeague(e.target.value)}
                className="w-full rounded-xl border border-white/10 bg-slate-950 px-3 py-2 text-xs text-white focus:outline-none focus:ring-1 focus:ring-emerald-400"
              >
                {LEAGUE_OPTIONS.map((l) => (
                  <option key={l.value} value={l.value}>
                    {l.label}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="border-t border-white/10 pt-4 flex justify-end">
            <button
              type="submit"
              className="flex items-center gap-2 rounded-xl bg-emerald-400 px-5 py-2 text-xs font-bold text-slate-950 transition hover:bg-emerald-300 focus:outline-none focus:ring-2 focus:ring-emerald-400"
            >
              <span>Save Preferences</span>
            </button>
          </div>
        </form>
      )}

      <AuthModal open={authModalOpen} onOpenChange={setAuthModalOpen} />
    </div>
  );
}
