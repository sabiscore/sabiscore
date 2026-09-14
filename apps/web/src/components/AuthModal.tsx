"use client";

import React, { useEffect, useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import {
  ArrowRight,
  Check,
  Eye,
  EyeOff,
  KeyRound,
  Loader2,
  Mail,
  ShieldCheck,
  User,
  X,
} from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import { cn } from "@/lib/utils";

interface AuthModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  defaultMode?: "login" | "register";
  initialError?: string | null;
}

function mapOAuthError(code: string | null | undefined): string | null {
  switch (code) {
    case "google_cancelled":
      return "Google sign-in was cancelled.";
    case "google_not_configured":
      return "Google sign-in is not configured for this deployment yet.";
    case "oauth_state_invalid":
      return "The authentication session expired or could not be verified. Please try again.";
    case "google_authorization_failed":
    case "google_authentication_failed":
    case "google_session_failed":
      return "Google sign-in could not be completed. Please try again.";
    default:
      return null;
  }
}

function GoogleMark() {
  return (
    <svg viewBox="0 0 24 24" className="h-4 w-4" aria-hidden="true">
      <path
        fill="#4285F4"
        d="M21.35 12.23c0-.79-.07-1.55-.22-2.27H12v4.3h5.24a4.48 4.48 0 0 1-1.95 2.94v2.45h3.16c1.85-1.7 2.9-4.2 2.9-7.42Z"
      />
      <path
        fill="#34A853"
        d="M12 21.7c2.65 0 4.87-.88 6.49-2.4l-3.16-2.45c-.88.59-2 .94-3.33.94-2.56 0-4.73-1.73-5.51-4.05H3.22v2.53A9.8 9.8 0 0 0 12 21.7Z"
      />
      <path
        fill="#FBBC05"
        d="M6.49 13.74a5.9 5.9 0 0 1 0-3.48V7.73H3.22a9.8 9.8 0 0 0 0 8.54l3.27-2.53Z"
      />
      <path
        fill="#EA4335"
        d="M12 6.2c1.45 0 2.75.5 3.77 1.48l2.83-2.83C16.86 3.24 14.64 2.3 12 2.3a9.8 9.8 0 0 0-8.78 5.43l3.27 2.53C7.27 7.93 9.44 6.2 12 6.2Z"
      />
    </svg>
  );
}

export function AuthModal({
  open,
  onOpenChange,
  defaultMode = "login",
  initialError = null,
}: AuthModalProps) {
  const [mode, setMode] = useState<"login" | "register">(defaultMode);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [username, setUsername] = useState("");
  const [fullName, setFullName] = useState("");
  const [rememberMe, setRememberMe] = useState(true);
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(mapOAuthError(initialError) ?? initialError);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isGoogleLoading, setIsGoogleLoading] = useState(false);

  const { login, register, startGoogleSignIn } = useAuth();
  const googleEnabled = process.env.NEXT_PUBLIC_GOOGLE_AUTH_ENABLED !== "false";

  useEffect(() => {
    if (!open) return;
    setMode(defaultMode);
    setError(mapOAuthError(initialError) ?? initialError);
  }, [open, defaultMode, initialError]);

  useEffect(() => {
    if (!open) {
      setIsSubmitting(false);
      setIsGoogleLoading(false);
      return;
    }

    const authError = new URLSearchParams(window.location.search).get("auth_error");
    const mapped = mapOAuthError(authError);
    if (mapped) setError(mapped);
  }, [open]);

  const resetAndClose = () => {
    setEmail("");
    setPassword("");
    setConfirmPassword("");
    setUsername("");
    setFullName("");
    setError(null);
    setIsSubmitting(false);
    setIsGoogleLoading(false);
    onOpenChange(false);
  };

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (isSubmitting || isGoogleLoading) return;

    setError(null);

    const normalizedEmail = email.trim().toLowerCase();
    const normalizedUsername = username.trim().toLowerCase();

    if (!normalizedEmail || !password) {
      setError("Enter your email address and password.");
      return;
    }

    if (password.length < 8) {
      setError("Your password must contain at least 8 characters.");
      return;
    }

    if (mode === "register") {
      if (!/^[a-z0-9][a-z0-9._-]{2,31}$/.test(normalizedUsername)) {
        setError("Username must be 3–32 characters and use letters, numbers, dots, underscores, or hyphens.");
        return;
      }

      if (password !== confirmPassword) {
        setError("Passwords do not match.");
        return;
      }
    }

    setIsSubmitting(true);

    const result = mode === "login"
      ? await login(normalizedEmail, password, rememberMe)
      : await register(normalizedUsername, normalizedEmail, password, fullName);

    setIsSubmitting(false);

    if (result.success) {
      resetAndClose();
    } else {
      setError(result.error || "Authentication failed. Please try again.");
    }
  };

  const handleGoogleSignIn = () => {
    if (isSubmitting || isGoogleLoading) return;
    setError(null);
    setIsGoogleLoading(true);
    startGoogleSignIn();
  };

  return (
    <Dialog.Root open={open} onOpenChange={(nextOpen) => (nextOpen ? onOpenChange(true) : resetAndClose())}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-sm" />

        <Dialog.Content
          className="fixed left-1/2 top-1/2 z-50 max-h-[calc(100dvh-1.5rem)] w-[calc(100%-1rem)] max-w-md -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-2xl border border-white/10 bg-[var(--brand-elevated)] p-5 shadow-2xl shadow-black/50 focus:outline-none sm:p-6"
          aria-describedby="auth-modal-description"
        >
          <div className="flex items-start justify-between gap-4 border-b border-white/10 pb-4">
            <div className="flex min-w-0 items-center gap-2.5">
              <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl border border-emerald-400/20 bg-emerald-400/10 text-emerald-300">
                <ShieldCheck className="h-4 w-4" aria-hidden="true" />
              </span>
              <div className="min-w-0">
                <Dialog.Title className="text-lg font-bold tracking-tight text-white">
                  {mode === "login" ? "Welcome back" : "Create your SabiScore account"}
                </Dialog.Title>
                <p className="mt-0.5 text-[11px] font-medium uppercase tracking-[0.14em] text-slate-500">
                  Evidence-first football intelligence
                </p>
              </div>
            </div>

            <Dialog.Close
              className="grid h-8 w-8 shrink-0 place-items-center rounded-lg text-slate-400 transition hover:bg-white/10 hover:text-white focus:outline-none focus:ring-2 focus:ring-emerald-400"
              aria-label="Close authentication dialog"
            >
              <X className="h-4 w-4" aria-hidden="true" />
            </Dialog.Close>
          </div>

          <p id="auth-modal-description" className="mt-3 text-xs leading-5 text-slate-400">
            {mode === "login"
              ? "Sign in to sync your watchlist, preferences, alerts, and analyst workspace across devices."
              : "Create a free account to sync your workspace and saved football research across devices."}
          </p>

          <div className="mt-4 flex rounded-xl border border-white/10 bg-slate-950/70 p-1" role="tablist" aria-label="Authentication mode">
            {(["login", "register"] as const).map((tab) => (
              <button
                key={tab}
                type="button"
                role="tab"
                aria-selected={mode === tab}
                onClick={() => {
                  setMode(tab);
                  setError(null);
                }}
                className={cn(
                  "flex-1 rounded-lg py-2 text-xs font-semibold transition",
                  mode === tab
                    ? "bg-slate-800 text-white shadow-sm"
                    : "text-slate-400 hover:text-slate-200",
                )}
              >
                {tab === "login" ? "Sign In" : "Register"}
              </button>
            ))}
          </div>

          {googleEnabled && (
            <>
              <button
                type="button"
                onClick={handleGoogleSignIn}
                disabled={isSubmitting || isGoogleLoading}
                className="mt-4 flex min-h-11 w-full items-center justify-center gap-2.5 rounded-xl border border-white/15 bg-white text-sm font-semibold text-slate-900 transition hover:bg-slate-100 focus:outline-none focus:ring-2 focus:ring-emerald-400 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {isGoogleLoading ? (
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                ) : (
                  <GoogleMark />
                )}
                <span>{mode === "login" ? "Continue with Google" : "Sign up with Google"}</span>
              </button>

              <div className="my-4 flex items-center gap-3" aria-hidden="true">
                <div className="h-px flex-1 bg-white/10" />
                <span className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-600">or email</span>
                <div className="h-px flex-1 bg-white/10" />
              </div>
            </>
          )}

          {error && (
            <div
              role="alert"
              className="mb-3 rounded-xl border border-rose-500/30 bg-rose-500/10 px-3 py-2.5 text-xs leading-5 text-rose-300"
            >
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-3.5" noValidate>
            {mode === "register" && (
              <>
                <div>
                  <label className="block text-xs font-semibold text-slate-300" htmlFor="auth-username">
                    Analyst username
                  </label>
                  <div className="relative mt-1.5">
                    <User className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" aria-hidden="true" />
                    <input
                      id="auth-username"
                      name="username"
                      type="text"
                      required
                      minLength={3}
                      maxLength={32}
                      autoComplete="username"
                      value={username}
                      onChange={(event) => setUsername(event.target.value)}
                      placeholder="analyst_2026"
                      className="w-full rounded-xl border border-white/10 bg-slate-950 py-2.5 pl-9 pr-3 text-sm text-white placeholder-slate-600 outline-none transition focus:border-emerald-400/60 focus:ring-1 focus:ring-emerald-400/40"
                    />
                  </div>
                </div>

                <div>
                  <label className="block text-xs font-semibold text-slate-300" htmlFor="auth-full-name">
                    Display name <span className="font-normal text-slate-600">(optional)</span>
                  </label>
                  <input
                    id="auth-full-name"
                    name="name"
                    type="text"
                    maxLength={200}
                    autoComplete="name"
                    value={fullName}
                    onChange={(event) => setFullName(event.target.value)}
                    placeholder="Your name"
                    className="mt-1.5 w-full rounded-xl border border-white/10 bg-slate-950 px-3 py-2.5 text-sm text-white placeholder-slate-600 outline-none transition focus:border-emerald-400/60 focus:ring-1 focus:ring-emerald-400/40"
                  />
                </div>
              </>
            )}

            <div>
              <label className="block text-xs font-semibold text-slate-300" htmlFor="auth-email">
                Email address
              </label>
              <div className="relative mt-1.5">
                <Mail className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" aria-hidden="true" />
                <input
                  id="auth-email"
                  name="email"
                  type="email"
                  required
                  autoComplete="email"
                  inputMode="email"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  placeholder="analyst@example.com"
                  className="w-full rounded-xl border border-white/10 bg-slate-950 py-2.5 pl-9 pr-3 text-sm text-white placeholder-slate-600 outline-none transition focus:border-emerald-400/60 focus:ring-1 focus:ring-emerald-400/40"
                />
              </div>
            </div>

            <div>
              <div className="flex items-center justify-between gap-3">
                <label className="block text-xs font-semibold text-slate-300" htmlFor="auth-password">
                  Password
                </label>
                {mode === "login" && (
                  <span className="text-[10px] text-slate-600">8+ characters</span>
                )}
              </div>
              <div className="relative mt-1.5">
                <KeyRound className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" aria-hidden="true" />
                <input
                  id="auth-password"
                  name="password"
                  type={showPassword ? "text" : "password"}
                  required
                  minLength={8}
                  maxLength={128}
                  autoComplete={mode === "login" ? "current-password" : "new-password"}
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  placeholder="••••••••"
                  className="w-full rounded-xl border border-white/10 bg-slate-950 py-2.5 pl-9 pr-10 text-sm text-white placeholder-slate-600 outline-none transition focus:border-emerald-400/60 focus:ring-1 focus:ring-emerald-400/40"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((visible) => !visible)}
                  className="absolute right-2 top-1/2 grid h-7 w-7 -translate-y-1/2 place-items-center rounded-md text-slate-500 hover:text-slate-200 focus:outline-none focus:ring-2 focus:ring-emerald-400"
                  aria-label={showPassword ? "Hide password" : "Show password"}
                >
                  {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
            </div>

            {mode === "register" && (
              <div>
                <label className="block text-xs font-semibold text-slate-300" htmlFor="auth-confirm-password">
                  Confirm password
                </label>
                <div className="relative mt-1.5">
                  <Check className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" aria-hidden="true" />
                  <input
                    id="auth-confirm-password"
                    name="confirm-password"
                    type={showPassword ? "text" : "password"}
                    required
                    minLength={8}
                    maxLength={128}
                    autoComplete="new-password"
                    value={confirmPassword}
                    onChange={(event) => setConfirmPassword(event.target.value)}
                    placeholder="Repeat your password"
                    className="w-full rounded-xl border border-white/10 bg-slate-950 py-2.5 pl-9 pr-3 text-sm text-white placeholder-slate-600 outline-none transition focus:border-emerald-400/60 focus:ring-1 focus:ring-emerald-400/40"
                  />
                </div>
              </div>
            )}

            {mode === "login" && (
              <label className="flex cursor-pointer items-center gap-2 text-xs text-slate-400">
                <input
                  type="checkbox"
                  checked={rememberMe}
                  onChange={(event) => setRememberMe(event.target.checked)}
                  className="h-3.5 w-3.5 rounded border-white/20 bg-slate-950 accent-emerald-400"
                />
                Keep me signed in on this device
              </label>
            )}

            <button
              type="submit"
              disabled={isSubmitting || isGoogleLoading}
              className="flex min-h-11 w-full items-center justify-center gap-2 rounded-xl bg-emerald-400 px-4 py-2.5 text-sm font-bold text-slate-950 transition hover:bg-emerald-300 focus:outline-none focus:ring-2 focus:ring-emerald-300 focus:ring-offset-2 focus:ring-offset-[var(--brand-elevated)] disabled:cursor-not-allowed disabled:opacity-50"
              aria-busy={isSubmitting}
            >
              {isSubmitting ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              ) : (
                <>
                  <span>{mode === "login" ? "Sign In" : "Create Free Account"}</span>
                  <ArrowRight className="h-4 w-4" aria-hidden="true" />
                </>
              )}
            </button>
          </form>

          <p className="mt-4 text-center text-[10px] leading-4 text-slate-600">
            Your authentication session is stored in an HttpOnly cookie. Passwords and OAuth tokens are never stored in localStorage.
          </p>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

export default AuthModal;
