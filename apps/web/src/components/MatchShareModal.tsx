"use client";

import React, { useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { Share2, Copy, Check, X, Twitter, MessageCircle, Send } from "lucide-react";
import { analytics } from "@/lib/analytics";
import { VERDICT_TOKENS, type Verdict } from "@/lib/verdict-tokens";
import { certificationLabel } from "@/lib/model-identity";

interface MatchShareModalBaseProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  matchId: string;
  homeTeam: string;
  awayTeam: string;
  league: string;
}

interface FixtureShareProps extends MatchShareModalBaseProps {
  mode: "fixture";
}

interface AnalysisShareProps extends MatchShareModalBaseProps {
  mode: "analysis";
  probabilities: {
    home: number;
    draw: number;
    away: number;
  };
  verdict: Verdict;
  evidenceSummary: string;
  stakePermitted: boolean;
  certificationState: string | null;
}

export type MatchShareModalProps = FixtureShareProps | AnalysisShareProps;

function hasValidProbabilities(props: MatchShareModalProps): props is AnalysisShareProps {
  if (props.mode !== "analysis") return false;

  const values = Object.values(props.probabilities);
  const total = values.reduce((sum, value) => sum + value, 0);
  return values.every((value) => Number.isFinite(value) && value >= 0 && value <= 1)
    && Math.abs(total - 1) <= 0.01;
}

export function MatchShareModal(props: MatchShareModalProps) {
  const { open, onOpenChange, matchId, homeTeam, awayTeam, league } = props;
  const [copied, setCopied] = useState(false);

  const siteUrl = typeof window !== "undefined" ? window.location.origin : "https://sabiscore.com";
  const matchUrl = `${siteUrl}/match/${encodeURIComponent(matchId)}?league=${encodeURIComponent(league)}`;
  const analysis = hasValidProbabilities(props) ? props : null;
  const verdictTokens = analysis ? VERDICT_TOKENS[analysis.verdict] : null;
  const maturityLabel = analysis ? certificationLabel(analysis.certificationState) : null;
  const fixtureText = `SabiScore match intelligence: ${homeTeam} vs ${awayTeam}\nLeague: ${league}\nReview current evidence availability and analysis at: ${matchUrl}`;
  const exportText = analysis
    ? `SabiScore match intelligence: ${homeTeam} vs ${awayTeam}\nLeague: ${league}\nForecast: Home Win ${(analysis.probabilities.home * 100).toFixed(1)}% | Draw ${(analysis.probabilities.draw * 100).toFixed(1)}% | Away Win ${(analysis.probabilities.away * 100).toFixed(1)}%\nVerdict: ${verdictTokens?.label}\nModel maturity: ${maturityLabel}\nStatus: ${analysis.stakePermitted ? "Stake permitted by backend policy" : "Informational only; no stake permitted"}\nEvidence: ${analysis.evidenceSummary}\nExplore full match intelligence at: ${matchUrl}`
    : fixtureText;

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
  const telegramUrl = `https://t.me/share/url?url=${encodeURIComponent(matchUrl)}&text=${encodeURIComponent(exportText)}`;

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
                {analysis ? "Share Match Analysis" : "Share Match"}
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
            {analysis
              ? "Share the available forecast, backend verdict, and evidence summary."
              : "Share this fixture link. No forecast or verdict is added without analysis data."}
          </p>

          {/* Social Share Card Preview */}
          <div className="mt-4 overflow-hidden rounded-xl border border-white/10 bg-slate-950 p-3 shadow-inner">
            <div className="mb-2 flex items-center justify-between text-[11px] font-semibold text-slate-400">
              <span>Share preview</span>
              <span className="text-emerald-400 font-bold">{league}</span>
            </div>
            <div className="rounded-lg border border-white/[0.06] bg-slate-900/90 p-3">
              <p className="text-sm font-extrabold text-white">{homeTeam} vs {awayTeam}</p>
              {analysis ? (
                <div className="mt-2 grid grid-cols-3 gap-2 text-center text-xs">
                  <div className="rounded-lg border border-emerald-500/20 bg-emerald-500/10 p-1.5">
                    <p className="text-[10px] uppercase text-slate-400">Home</p>
                    <p className="text-sm font-bold text-emerald-400">{(analysis.probabilities.home * 100).toFixed(0)}%</p>
                  </div>
                  <div className="rounded-lg border border-white/10 bg-white/[0.03] p-1.5">
                    <p className="text-[10px] uppercase text-slate-400">Draw</p>
                    <p className="text-sm font-bold text-slate-300">{(analysis.probabilities.draw * 100).toFixed(0)}%</p>
                  </div>
                  <div className="rounded-lg border border-sky-500/20 bg-sky-500/10 p-1.5">
                    <p className="text-[10px] uppercase text-slate-400">Away</p>
                    <p className="text-sm font-bold text-sky-400">{(analysis.probabilities.away * 100).toFixed(0)}%</p>
                  </div>
                </div>
              ) : (
                <p className="mt-2 text-xs leading-relaxed text-slate-400">
                  Open the match page to review current evidence availability and analysis.
                </p>
              )}
              <div className="mt-2 flex items-center justify-between border-t border-white/10 pt-2 text-[10px] text-slate-400">
                {analysis && verdictTokens ? (
                  <span>
                    Verdict: <strong className={verdictTokens.color}>{verdictTokens.label}</strong>
                  </span>
                ) : (
                  <span>Fixture link</span>
                )}
                <span>sabiscore.com</span>
              </div>
              {analysis && (
                <p className="mt-2 text-[10px] text-slate-400">
                  {maturityLabel} · {analysis.stakePermitted ? "Stake permitted" : "Informational only"}
                </p>
              )}
            </div>
          </div>

          {/* Share Action Buttons */}
          <div className="mt-5 grid grid-cols-3 gap-2">
            <a
              href={twitterUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="flex min-h-11 items-center justify-center gap-1.5 rounded-xl border border-white/10 bg-slate-950 py-2.5 text-xs font-semibold text-slate-200 transition hover:bg-white/10 hover:text-white focus:outline-none focus:ring-2 focus:ring-sky-400"
            >
              <Twitter className="h-3.5 w-3.5 text-sky-400" />
              <span>Twitter / X</span>
            </a>
            <a
              href={whatsappUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="flex min-h-11 items-center justify-center gap-1.5 rounded-xl border border-white/10 bg-slate-950 py-2.5 text-xs font-semibold text-slate-200 transition hover:bg-white/10 hover:text-white focus:outline-none focus:ring-2 focus:ring-emerald-400"
            >
              <MessageCircle className="h-3.5 w-3.5 text-emerald-400" />
              <span>WhatsApp</span>
            </a>
            <a
              href={telegramUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="flex min-h-11 items-center justify-center gap-1.5 rounded-xl border border-white/10 bg-slate-950 py-2.5 text-xs font-semibold text-slate-200 transition hover:bg-white/10 hover:text-white focus:outline-none focus:ring-2 focus:ring-blue-400"
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
              className="flex min-h-11 flex-1 items-center justify-center gap-2 rounded-xl bg-emerald-400 py-2.5 text-xs font-bold text-slate-950 transition hover:bg-emerald-300 focus:outline-none focus:ring-2 focus:ring-emerald-400"
            >
              {copied ? (
                <>
                  <Check className="h-4 w-4" />
                  <span>{analysis ? "Copied Analysis" : "Copied Match Link"}</span>
                </>
              ) : (
                <>
                  <Copy className="h-4 w-4" />
                  <span>{analysis ? "Copy Analysis" : "Copy Match Link"}</span>
                </>
              )}
            </button>

            {typeof navigator !== "undefined" && typeof navigator.share === "function" && (
              <button
                type="button"
                onClick={handleWebShare}
                className="flex min-h-11 min-w-11 items-center justify-center rounded-xl border border-white/10 bg-slate-950 px-3 text-slate-300 hover:bg-white/10 hover:text-white focus:outline-none focus:ring-2 focus:ring-emerald-400"
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
