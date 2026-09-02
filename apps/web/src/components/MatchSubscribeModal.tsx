"use client";

import React, { useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { Bell, Check, X, Clock, TrendingUp, Loader2, Mail, Smartphone } from "lucide-react";
import { analytics } from "@/lib/analytics";

type NotificationChannel = "IN_APP" | "EMAIL";

interface MatchSubscribeModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  matchId: string;
  homeTeam: string;
  awayTeam: string;
}

export function MatchSubscribeModal({
  open,
  onOpenChange,
  matchId,
  homeTeam,
  awayTeam,
}: MatchSubscribeModalProps) {
  const [reminderType, setReminderType] = useState<"KICKOFF_REMINDER" | "PROBABILITY_SWING">("KICKOFF_REMINDER");
  const [channel, setChannel] = useState<NotificationChannel>("IN_APP");
  const [emailDestination, setEmailDestination] = useState("");
  const [minutesBefore, setMinutesBefore] = useState<number>(15);
  const [deltaThreshold, setDeltaThreshold] = useState<number>(0.05);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [success, setSuccess] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSubmitting(true);

    try {
      const res = await fetch("/api/notifications/subscriptions/matches", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          match_id: matchId,
          subscription_type: reminderType,
          channel,
          destination: channel === "EMAIL" ? emailDestination : undefined,
          reminder_minutes_before: minutesBefore,
          threshold_pct: deltaThreshold,
        }),
      });

      if (res.ok) {
        setSuccess(true);
        analytics.track("notification_subscribed", {
          match_id: matchId,
          reminder_type: reminderType,
          channel,
        });
        setTimeout(() => {
          setSuccess(false);
          onOpenChange(false);
        }, 1500);
      }
    } catch {}
    setIsSubmitting(false);
  };

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-sm" />
        <Dialog.Content
          className="fixed left-[50%] top-[50%] z-50 w-full max-w-md translate-x-[-50%] translate-y-[-50%] rounded-2xl border border-white/10 bg-slate-900 p-6 shadow-2xl focus:outline-none"
          aria-describedby="match-subscribe-description"
        >
          <div className="flex items-center justify-between border-b border-white/10 pb-4">
            <div className="flex items-center gap-2">
              <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-500/20 text-emerald-300">
                <Bell className="h-4 w-4" />
              </span>
              <Dialog.Title className="text-lg font-bold text-white tracking-tight">
                Match Intelligence Alerts
              </Dialog.Title>
            </div>
            <Dialog.Close
              className="rounded-lg p-1.5 text-slate-400 hover:bg-white/10 hover:text-white focus:outline-none focus:ring-2 focus:ring-emerald-400"
              aria-label="Close subscription dialog"
            >
              <X className="h-4 w-4" />
            </Dialog.Close>
          </div>

          <p id="match-subscribe-description" className="mt-3 text-xs text-slate-400">
            Configure alerts for <strong className="text-white">{homeTeam} vs {awayTeam}</strong>.
          </p>

          {success ? (
            <div className="my-8 flex flex-col items-center justify-center gap-2 text-center">
              <span className="flex h-12 w-12 items-center justify-center rounded-full bg-emerald-500/20 text-emerald-400">
                <Check className="h-6 w-6" />
              </span>
              <p className="text-sm font-bold text-white">Alert Configured Successfully!</p>
              <p className="text-xs text-slate-400">
                {channel === "EMAIL"
                  ? "You will receive an in-app notification and an email before kickoff."
                  : "You will receive an in-app notification before kickoff."}
              </p>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="mt-4 space-y-4">
              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1.5">Delivery</label>
                <div className="grid grid-cols-2 gap-2">
                  <button
                    type="button"
                    onClick={() => setChannel("IN_APP")}
                    className={`flex items-center gap-2 rounded-xl border p-3 text-left transition ${
                      channel === "IN_APP"
                        ? "border-emerald-500/50 bg-emerald-500/10 text-white"
                        : "border-white/10 bg-slate-950 text-slate-400 hover:text-slate-200"
                    }`}
                  >
                    <Smartphone className="h-4 w-4 text-emerald-400 shrink-0" />
                    <p className="text-xs font-semibold">In-App</p>
                  </button>

                  <button
                    type="button"
                    onClick={() => setChannel("EMAIL")}
                    className={`flex items-center gap-2 rounded-xl border p-3 text-left transition ${
                      channel === "EMAIL"
                        ? "border-emerald-500/50 bg-emerald-500/10 text-white"
                        : "border-white/10 bg-slate-950 text-slate-400 hover:text-slate-200"
                    }`}
                  >
                    <Mail className="h-4 w-4 text-sky-400 shrink-0" />
                    <p className="text-xs font-semibold">Email</p>
                  </button>
                </div>
              </div>

              {channel === "EMAIL" && (
                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1" htmlFor="sub-email">
                    Email Address
                  </label>
                  <input
                    id="sub-email"
                    type="email"
                    required
                    value={emailDestination}
                    onChange={(e) => setEmailDestination(e.target.value)}
                    placeholder="you@example.com"
                    className="w-full rounded-xl border border-white/10 bg-slate-950 px-3 py-2 text-xs text-white placeholder:text-slate-500 focus:outline-none focus:ring-1 focus:ring-emerald-400"
                  />
                  <p className="mt-1 text-[10px] text-slate-500">
                    Email alerts are best-effort, sent alongside the in-app notification.
                  </p>
                </div>
              )}

              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1.5">Alert Type</label>
                <div className="grid grid-cols-2 gap-2">
                  <button
                    type="button"
                    onClick={() => setReminderType("KICKOFF_REMINDER")}
                    className={`flex items-center gap-2 rounded-xl border p-3 text-left transition ${
                      reminderType === "KICKOFF_REMINDER"
                        ? "border-emerald-500/50 bg-emerald-500/10 text-white"
                        : "border-white/10 bg-slate-950 text-slate-400 hover:text-slate-200"
                    }`}
                  >
                    <Clock className="h-4 w-4 text-emerald-400 shrink-0" />
                    <div>
                      <p className="text-xs font-semibold">Kickoff Alert</p>
                      <p className="text-[10px] text-slate-400">Pre-match reminder</p>
                    </div>
                  </button>

                  <button
                    type="button"
                    onClick={() => setReminderType("PROBABILITY_SWING")}
                    className={`flex items-center gap-2 rounded-xl border p-3 text-left transition ${
                      reminderType === "PROBABILITY_SWING"
                        ? "border-emerald-500/50 bg-emerald-500/10 text-white"
                        : "border-white/10 bg-slate-950 text-slate-400 hover:text-slate-200"
                    }`}
                  >
                    <TrendingUp className="h-4 w-4 text-sky-400 shrink-0" />
                    <div>
                      <p className="text-xs font-semibold">Odds / Model Swing</p>
                      <p className="text-[10px] text-slate-400">Probability shifts</p>
                    </div>
                  </button>
                </div>
              </div>

              {reminderType === "KICKOFF_REMINDER" ? (
                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1" htmlFor="sub-minutes">
                    Reminder Timing
                  </label>
                  <select
                    id="sub-minutes"
                    value={minutesBefore}
                    onChange={(e) => setMinutesBefore(Number(e.target.value))}
                    className="w-full rounded-xl border border-white/10 bg-slate-950 px-3 py-2 text-xs text-white focus:outline-none focus:ring-1 focus:ring-emerald-400"
                  >
                    <option value={15}>15 minutes before kickoff</option>
                    <option value={30}>30 minutes before kickoff</option>
                    <option value={60}>1 hour before kickoff</option>
                    <option value={120}>2 hours before kickoff</option>
                  </select>
                </div>
              ) : (
                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1" htmlFor="sub-delta">
                    Probability Delta Threshold
                  </label>
                  <select
                    id="sub-delta"
                    value={deltaThreshold}
                    onChange={(e) => setDeltaThreshold(Number(e.target.value))}
                    className="w-full rounded-xl border border-white/10 bg-slate-950 px-3 py-2 text-xs text-white focus:outline-none focus:ring-1 focus:ring-emerald-400"
                  >
                    <option value={0.03}>≥ 3% probability swing</option>
                    <option value={0.05}>≥ 5% probability swing</option>
                    <option value={0.08}>≥ 8% probability swing</option>
                    <option value={0.10}>≥ 10% probability swing</option>
                  </select>
                </div>
              )}

              <button
                type="submit"
                disabled={isSubmitting}
                className="mt-4 flex w-full items-center justify-center gap-2 rounded-xl bg-emerald-400 py-2.5 text-xs font-bold text-slate-950 transition hover:bg-emerald-300 focus:outline-none focus:ring-2 focus:ring-emerald-400 disabled:opacity-50"
              >
                {isSubmitting ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <span>{channel === "EMAIL" ? "Set Email Alert" : "Set In-App Alert"}</span>
                )}
              </button>
            </form>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

export default MatchSubscribeModal;
