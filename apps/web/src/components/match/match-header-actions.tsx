"use client";

import React, { useState } from "react";
import { Bookmark, Share2, Bell, Check } from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import { MatchShareModal } from "@/components/MatchShareModal";
import { MatchSubscribeModal } from "@/components/MatchSubscribeModal";
import { cn } from "@/lib/utils";

interface MatchHeaderActionsProps {
  matchId: string;
  homeTeam: string;
  awayTeam: string;
  league: string;
}

export function MatchHeaderActions({
  matchId,
  homeTeam,
  awayTeam,
  league,
}: MatchHeaderActionsProps) {
  const { isMatchSaved, saveMatch, removeSavedMatch } = useAuth();
  const [shareModalOpen, setShareModalOpen] = useState(false);
  const [subscribeModalOpen, setSubscribeModalOpen] = useState(false);

  const saved = isMatchSaved(matchId);

  const handleToggleSave = async () => {
    if (saved) {
      await removeSavedMatch(matchId);
    } else {
      await saveMatch(matchId);
    }
  };

  return (
    <>
      <div className="flex flex-wrap items-center gap-2">
        {/* Save Match Button */}
        <button
          type="button"
          onClick={handleToggleSave}
          className={cn(
            "flex min-h-9 items-center gap-1.5 rounded-xl border px-3 py-1.5 text-xs font-semibold transition focus:outline-none focus:ring-2 focus:ring-emerald-400",
            saved
              ? "border-emerald-500/40 bg-emerald-500/20 text-emerald-300"
              : "border-white/10 bg-white/[0.04] text-slate-300 hover:bg-white/[0.08] hover:text-white"
          )}
          aria-label={saved ? `Saved ${homeTeam} vs ${awayTeam}` : `Save ${homeTeam} vs ${awayTeam}`}
        >
          {saved ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Bookmark className="h-3.5 w-3.5" />}
          <span>{saved ? "Saved" : "Save Match"}</span>
        </button>

        {/* Subscribe Alert Button */}
        <button
          type="button"
          onClick={() => setSubscribeModalOpen(true)}
          className="flex min-h-9 items-center gap-1.5 rounded-xl border border-white/10 bg-white/[0.04] px-3 py-1.5 text-xs font-semibold text-slate-300 transition hover:bg-white/[0.08] hover:text-white focus:outline-none focus:ring-2 focus:ring-emerald-400"
          aria-label="Set match alert"
        >
          <Bell className="h-3.5 w-3.5 text-amber-400" />
          <span>Set Alert</span>
        </button>

        {/* Share Button */}
        <button
          type="button"
          onClick={() => setShareModalOpen(true)}
          className="flex min-h-9 items-center gap-1.5 rounded-xl border border-white/10 bg-white/[0.04] px-3 py-1.5 text-xs font-semibold text-slate-300 transition hover:bg-white/[0.08] hover:text-white focus:outline-none focus:ring-2 focus:ring-emerald-400"
          aria-label="Share match analysis"
        >
          <Share2 className="h-3.5 w-3.5 text-sky-400" />
          <span>Share</span>
        </button>
      </div>

      <MatchShareModal
        open={shareModalOpen}
        onOpenChange={setShareModalOpen}
        mode="fixture"
        matchId={matchId}
        homeTeam={homeTeam}
        awayTeam={awayTeam}
        league={league}
      />

      <MatchSubscribeModal
        open={subscribeModalOpen}
        onOpenChange={setSubscribeModalOpen}
        matchId={matchId}
        homeTeam={homeTeam}
        awayTeam={awayTeam}
      />
    </>
  );
}

export default MatchHeaderActions;
