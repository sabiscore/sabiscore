"use client";

import React, { useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { Share2, Copy, Check, X, Twitter, MessageCircle, Send } from "lucide-react";
import { analytics } from "@/lib/analytics";

export interface MatchShareModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  matchId: string;
  homeTeam: string;
  awayTeam: string;
  league: string;
  homeWinProb?: number;
  drawProb?: number;
  awayWinProb?: number;
  verdict?: string;
  narrative?: string;
}

export function MatchShareModal({
  open,
  onOpenChange,
  matchId,
  homeTeam,
  awayTeam,
  league,
  homeWinProb = 0.5,
  drawProb = 0.28,
  awayWinProb = 0.22,
  verdict = "ACTIONABLE",
  narrative = "Verified quantitative evidence supports model positioning.",
}: MatchShareModalProps) {
  const [copied, setCopied] = useState(false);

  const siteUrl = typeof window !== "undefined" ? window.location.origin : "https://sabiscore.com";
  const matchUrl = `${siteUrl}/match/${encodeURIComponent(matchId)}?league=${encodeURIComponent(league)}`;

  const exportText = `SabiScore Analytical Forecast: ${homeTeam} vs ${awayTeam}\nLeague: ${league}\nForecast: Home Win ${(homeWinProb * 100).toFixed(1)}% | Draw ${(drawProb * 100).toFixed(1)}% | Away Win ${(awayWinProb * 100).toFixed(1)}%\nVerdict: ${verdict}\nEvidence: ${narrative}\nExplore full match intelligence at: ${matchUrl}`;

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(exportText);
      setCopied(true);
      analytics.track("share_card_generated", { match_id: matchId, share_type: "clipboard" });
      setTimeout(() => setCopied(false), 2500);
    } catch {}
  };

  const handleWebShare = async () => {
    if (typeof navigator !== "undefined" && navigator.share) {
      try {
        await navigator.share({
          title: `${homeTeam} vs ${awayTeam} Analysis | SabiScore`,
          text: exportText,
          url: matchUrl,
        });
        analytics.track("share_card_generated", { match_id: matchId, share_type: "web_share" });
        onOpenChange(false);
      } catch {
        // User cancelled or share failed
      }
    }
  };

  const twitterUrl = `https://twitter.com/intent/tweet?text=${encodeURIComponent(exportText)}`;
  const whatsappUrl = `https://api.whatsapp.com/send?text=${encodeURIComponent(exportText)}`;
  const telegramUrl = `https://t.me/share/url?url=${encodeURIComponent(matchUrl)}&text=${encodeURIComponent(`${homeTeam} vs ${awayTeam} Forecast: Home ${(homeWinProb * 100).toFixed(0)}% | Draw ${(drawProb * 100).toFixed(0)}% | Away ${(awayWinProb * 100).toFixed(0)}% [${verdict}]`)}`;

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-sm" />
        <Dialog.Content
          className="fixed left-[50%] top-[50%] z-50 w-full max-w-lg translate-x-[-50%] translate-y-[-50%] rounded-2xl border border-white/10 bg-slate-900 p-6 shadow-2xl focus:outline-none"
          aria-describedby="match-share-description"
        >
          <div className="flex items-center justify-between border-b border-white/10 pb-4">
            <div className="flex items-center gap-2">
              <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-500/20 text-emerald-300">
                <Share2 className="h-4 w-4" />
              </span>
              <Dialog.Title className="text-lg font-bold text-white tracking-tight">
                Share Match Forecast
              </Dialog.Title>
            </div>
            <Dialog.Close
              className="rounded-lg p-1.5 text-slate-400 hover:bg-white/10 hover:text-white focus:outline-none focus:ring-2 focus:ring-emerald-400"
              aria-label="Close share dialog"
            >
              <X className="h-4 w-4" />
            </Dialog.Close>
          </div>

          <p id="match-share-description" className="mt-2 text-xs text-slate-400">
            Export evidence-backed probability models and analysis with zero promotional or gambling jargon.
          </p>

          {/* Social Share Card Preview */}
          <div className="mt-4 overflow-hidden rounded-xl border border-white/10 bg-slate-950 p-3 shadow-inner">
            <div className="flex items-center justify-between text-[11px] font-semibold text-slate-400 mb-2">
              <span>Card Preview (1200x630)</span>
              <span className="text-emerald-400 font-bold">{league}</span>
            </div>
            <div className="rounded-lg border border-white/[0.06] bg-slate-900/90 p-3">
              <p className="text-sm font-extrabold text-white">{homeTeam} vs {awayTeam}</p>
              <div className="mt-2 grid grid-cols-3 gap-2 text-center text-xs">
                <div className="rounded-lg bg-emerald-500/10 p-1.5 border border-emerald-500/20">
                  <p className="text-[10px] text-slate-400 uppercase">Home</p>
                  <p className="text-sm font-bold text-emerald-400">{(homeWinProb * 100).toFixed(0)}%</p>
                </div>
                <div className="rounded-lg bg-white/[0.03] p-1.5 border border-white/10">
                  <p className="text-[10px] text-slate-400 uppercase">Draw</p>
                  <p className="text-sm font-bold text-slate-300">{(drawProb * 100).toFixed(0)}%</p>
                </div>
                <div className="rounded-lg bg-sky-500/10 p-1.5 border border-sky-500/20">
                  <p className="text-[10px] text-slate-400 uppercase">Away</p>
                  <p className="text-sm font-bold text-sky-400">{(awayWinProb * 100).toFixed(0)}%</p>
                </div>
              </div>
              <div className="mt-2 flex items-center justify-between text-[10px] text-slate-400 border-t border-white/10 pt-2">
                <span>Verdict: <strong className="text-emerald-300">{verdict}</strong></span>
                <span>sabiscore.com</span>
              </div>
            </div>
          </div>

          {/* Share Action Buttons */}
          <div className="mt-5 grid grid-cols-3 gap-2">
            <a
              href={twitterUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center justify-center gap-1.5 rounded-xl border border-white/10 bg-slate-950 py-2.5 text-xs font-semibold text-slate-200 transition hover:bg-white/10 hover:text-white focus:outline-none focus:ring-2 focus:ring-sky-400"
            >
              <Twitter className="h-3.5 w-3.5 text-sky-400" />
              <span>Twitter / X</span>
            </a>
            <a
              href={whatsappUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center justify-center gap-1.5 rounded-xl border border-white/10 bg-slate-950 py-2.5 text-xs font-semibold text-slate-200 transition hover:bg-white/10 hover:text-white focus:outline-none focus:ring-2 focus:ring-emerald-400"
            >
              <MessageCircle className="h-3.5 w-3.5 text-emerald-400" />
              <span>WhatsApp</span>
            </a>
            <a
              href={telegramUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center justify-center gap-1.5 rounded-xl border border-white/10 bg-slate-950 py-2.5 text-xs font-semibold text-slate-200 transition hover:bg-white/10 hover:text-white focus:outline-none focus:ring-2 focus:ring-blue-400"
            >
              <Send className="h-3.5 w-3.5 text-blue-400" />
              <span>Telegram</span>
            </a>
          </div>

          {/* Copy to Clipboard */}
          <div className="mt-3 flex gap-2">
            <button
              type="button"
              onClick={handleCopy}
              className="flex flex-1 items-center justify-center gap-2 rounded-xl bg-emerald-400 py-2.5 text-xs font-bold text-slate-950 transition hover:bg-emerald-300 focus:outline-none focus:ring-2 focus:ring-emerald-400"
            >
              {copied ? (
                <>
                  <Check className="h-4 w-4" />
                  <span>Copied Forecast to Clipboard</span>
                </>
              ) : (
                <>
                  <Copy className="h-4 w-4" />
                  <span>Copy Forecast to Clipboard</span>
                </>
              )}
            </button>

            {typeof navigator !== "undefined" && typeof navigator.share === "function" && (
              <button
                type="button"
                onClick={handleWebShare}
                className="flex items-center justify-center rounded-xl border border-white/10 bg-slate-950 px-3 text-slate-300 hover:text-white hover:bg-white/10 focus:outline-none focus:ring-2 focus:ring-emerald-400"
                aria-label="Native Web Share"
              >
                <Share2 className="h-4 w-4" />
              </button>
            )}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

export default MatchShareModal;
