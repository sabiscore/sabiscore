"use client";

import React, { useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { X, KeyRound, Mail, User, ShieldCheck, ArrowRight, Loader2 } from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import { cn } from "@/lib/utils";

interface AuthModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  defaultMode?: "login" | "register";
}

export function AuthModal({ open, onOpenChange, defaultMode = "login" }: AuthModalProps) {
  const [mode, setMode] = useState<"login" | "register">(defaultMode);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [username, setUsername] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const { login, register } = useAuth();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setIsSubmitting(true);

    if (!email || !password) {
      setError("Please fill in all required fields.");
      setIsSubmitting(false);
      return;
    }

    if (mode === "register" && !username) {
      setError("Please provide an analyst username.");
      setIsSubmitting(false);
      return;
    }

    let result;
    if (mode === "login") {
      result = await login(email, password);
    } else {
      result = await register(username, email, password);
    }

    setIsSubmitting(false);

    if (result.success) {
      onOpenChange(false);
      setEmail("");
      setPassword("");
      setUsername("");
    } else {
      setError(result.error || "Authentication failed. Please check your credentials.");
    }
  };

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-sm transition-opacity" />
        <Dialog.Content
          className="fixed left-[50%] top-[50%] z-50 w-full max-w-md translate-x-[-50%] translate-y-[-50%] rounded-2xl border border-white/10 bg-slate-900 p-6 shadow-2xl focus:outline-none"
          aria-describedby="auth-modal-description"
        >
          <div className="flex items-center justify-between border-b border-white/10 pb-4">
            <div className="flex items-center gap-2">
              <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-500/20 text-emerald-300">
                <ShieldCheck className="h-4 w-4" />
              </span>
              <Dialog.Title className="text-lg font-bold text-white tracking-tight">
                {mode === "login" ? "Sign In to SabiScore" : "Create Free Analyst Account"}
              </Dialog.Title>
            </div>
            <Dialog.Close
              className="rounded-lg p-1.5 text-slate-400 hover:bg-white/10 hover:text-white focus:outline-none focus:ring-2 focus:ring-emerald-400"
              aria-label="Close authentication modal"
            >
              <X className="h-4 w-4" />
            </Dialog.Close>
          </div>

          <p id="auth-modal-description" className="mt-3 text-xs text-slate-400">
            {mode === "login"
              ? "Access your saved match watchlist, customized leagues, and developer API keys."
              : "100% Free forever. Save matches, configure alerts, and sync across devices without telemetry tracking."}
          </p>

          {/* Mode Switcher Tabs */}
          <div className="mt-4 flex rounded-xl border border-white/10 bg-slate-950 p-1">
            <button
              type="button"
              onClick={() => {
                setMode("login");
                setError(null);
              }}
              className={cn(
                "flex-1 rounded-lg py-1.5 text-xs font-semibold transition",
                mode === "login"
                  ? "bg-slate-800 text-white shadow"
                  : "text-slate-400 hover:text-slate-200"
              )}
            >
              Sign In
            </button>
            <button
              type="button"
              onClick={() => {
                setMode("register");
                setError(null);
              }}
              className={cn(
                "flex-1 rounded-lg py-1.5 text-xs font-semibold transition",
                mode === "register"
                  ? "bg-slate-800 text-white shadow"
                  : "text-slate-400 hover:text-slate-200"
              )}
            >
              Register
            </button>
          </div>

          {error && (
            <div
              role="alert"
              className="mt-3 rounded-lg border border-rose-500/30 bg-rose-500/10 p-2.5 text-xs text-rose-300"
            >
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} className="mt-4 space-y-3">
            {mode === "register" && (
              <div>
                <label className="block text-xs font-semibold text-slate-300" htmlFor="auth-username">
                  Username
                </label>
                <div className="relative mt-1">
                  <span className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-slate-500">
                    <User className="h-4 w-4" />
                  </span>
                  <input
                    id="auth-username"
                    type="text"
                    required
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    placeholder="analyst_2026"
                    className="w-full rounded-xl border border-white/10 bg-slate-950 py-2 pl-9 pr-3 text-sm text-white placeholder-slate-500 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
                  />
                </div>
              </div>
            )}

            <div>
              <label className="block text-xs font-semibold text-slate-300" htmlFor="auth-email">
                Email Address
              </label>
              <div className="relative mt-1">
                <span className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-slate-500">
                  <Mail className="h-4 w-4" />
                </span>
                <input
                  id="auth-email"
                  type="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="analyst@example.com"
                  className="w-full rounded-xl border border-white/10 bg-slate-950 py-2 pl-9 pr-3 text-sm text-white placeholder-slate-500 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
                />
              </div>
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-300" htmlFor="auth-password">
                Password
              </label>
              <div className="relative mt-1">
                <span className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-slate-500">
                  <KeyRound className="h-4 w-4" />
                </span>
                <input
                  id="auth-password"
                  type="password"
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                  className="w-full rounded-xl border border-white/10 bg-slate-950 py-2 pl-9 pr-3 text-sm text-white placeholder-slate-500 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
                />
              </div>
            </div>

            <button
              type="submit"
              disabled={isSubmitting}
              className="mt-4 flex w-full items-center justify-center gap-2 rounded-xl bg-emerald-400 py-2.5 text-sm font-bold text-slate-950 transition hover:bg-emerald-300 focus:outline-none focus:ring-2 focus:ring-emerald-400 disabled:opacity-50"
            >
              {isSubmitting ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <>
                  <span>{mode === "login" ? "Sign In" : "Create Free Account"}</span>
                  <ArrowRight className="h-4 w-4" />
                </>
              )}
            </button>
          </form>

          <div className="mt-4 border-t border-white/10 pt-3 text-center text-[11px] text-slate-400">
            <span>Anonymous device state merges automatically upon signing in. Zero telemetry tokens stored in localStorage.</span>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

export default AuthModal;
