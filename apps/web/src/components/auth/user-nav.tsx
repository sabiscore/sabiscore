"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  Code,
  LayoutDashboard,
  LogIn,
  LogOut,
  Sliders,
} from "lucide-react";
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { useAuth } from "@/lib/auth-context";
import { AuthModal } from "@/components/AuthModal";

const AUTH_ERROR_CODES = new Set([
  "google_cancelled",
  "google_not_configured",
  "oauth_state_invalid",
  "google_authorization_failed",
  "google_authentication_failed",
  "google_session_failed",
]);

export function UserNav() {
  const { user, isAuthenticated, logout } = useAuth();
  const [authModalOpen, setAuthModalOpen] = useState(false);
  const [authError, setAuthError] = useState<string | null>(null);

  useEffect(() => {
    if (typeof window === "undefined") return;

    const params = new URLSearchParams(window.location.search);
    const error = params.get("auth_error");
    if (!error || !AUTH_ERROR_CODES.has(error)) return;

    setAuthError(error);
    setAuthModalOpen(true);

    params.delete("auth_error");
    const query = params.toString();
    const cleanUrl = `${window.location.pathname}${query ? `?${query}` : ""}${window.location.hash}`;
    window.history.replaceState(window.history.state, "", cleanUrl);
  }, []);

  if (!isAuthenticated) {
    return (
      <>
        <button
          type="button"
          onClick={() => {
            setAuthError(null);
            setAuthModalOpen(true);
          }}
          className="flex min-h-8 items-center gap-1.5 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-1 text-xs font-semibold text-emerald-300 transition hover:bg-emerald-500/20 focus:outline-none focus:ring-2 focus:ring-emerald-400"
          aria-label="Sign in or register"
        >
          <LogIn className="h-3.5 w-3.5" aria-hidden="true" />
          <span>Sign In</span>
        </button>

        <AuthModal
          open={authModalOpen}
          onOpenChange={(open) => {
            setAuthModalOpen(open);
            if (!open) setAuthError(null);
          }}
          initialError={authError}
        />
      </>
    );
  }

  const displayName = user?.username || user?.full_name || user?.email.split("@")[0] || "Analyst";
  const initials = displayName.trim().slice(0, 1).toUpperCase();

  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button
          type="button"
          className="flex min-h-8 items-center gap-2 rounded-lg border border-white/10 bg-white/[0.04] px-2.5 py-1 text-xs font-semibold text-slate-200 transition hover:bg-white/[0.08] hover:text-white focus:outline-none focus:ring-2 focus:ring-emerald-400"
          aria-label="User profile and menu"
        >
          <span className="grid h-5 w-5 shrink-0 place-items-center overflow-hidden rounded-full bg-emerald-500/20 text-[10px] font-bold text-emerald-300">
            {user?.avatar_url ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={user.avatar_url} alt="" className="h-full w-full object-cover" />
            ) : (
              initials
            )}
          </span>
          <span className="max-w-[100px] truncate">{displayName}</span>
        </button>
      </DropdownMenu.Trigger>

      <DropdownMenu.Portal>
        <DropdownMenu.Content
          className="z-50 min-w-[210px] rounded-xl border border-white/10 bg-slate-900 p-1.5 text-xs shadow-2xl backdrop-blur-md focus:outline-none"
          sideOffset={6}
          align="end"
        >
          <div className="border-b border-white/10 px-2.5 py-2">
            <div className="flex items-center gap-2.5">
              <span className="grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full bg-emerald-500/20 text-xs font-bold text-emerald-300">
                {user?.avatar_url ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={user.avatar_url} alt="" className="h-full w-full object-cover" />
                ) : (
                  initials
                )}
              </span>
              <div className="min-w-0">
                <p className="truncate font-semibold text-white">{displayName}</p>
                <p className="truncate text-[10px] text-slate-400">{user?.email}</p>
              </div>
            </div>
          </div>

          <DropdownMenu.Item asChild>
            <Link
              href="/dashboard"
              className="flex cursor-pointer items-center gap-2 rounded-lg px-2.5 py-2 font-medium text-slate-300 hover:bg-white/10 hover:text-white focus:bg-white/10 focus:outline-none"
            >
              <LayoutDashboard className="h-3.5 w-3.5 text-emerald-400" aria-hidden="true" />
              <span>Dashboard</span>
            </Link>
          </DropdownMenu.Item>

          <DropdownMenu.Item asChild>
            <Link
              href="/developer"
              className="flex cursor-pointer items-center gap-2 rounded-lg px-2.5 py-2 font-medium text-slate-300 hover:bg-white/10 hover:text-white focus:bg-white/10 focus:outline-none"
            >
              <Code className="h-3.5 w-3.5 text-sky-400" aria-hidden="true" />
              <span>Developer API</span>
            </Link>
          </DropdownMenu.Item>

          <DropdownMenu.Item asChild>
            <Link
              href="/dashboard?tab=preferences"
              className="flex cursor-pointer items-center gap-2 rounded-lg px-2.5 py-2 font-medium text-slate-300 hover:bg-white/10 hover:text-white focus:bg-white/10 focus:outline-none"
            >
              <Sliders className="h-3.5 w-3.5 text-amber-400" aria-hidden="true" />
              <span>Preferences</span>
            </Link>
          </DropdownMenu.Item>

          <DropdownMenu.Separator className="my-1 h-px bg-white/10" />

          <DropdownMenu.Item
            onSelect={() => void logout()}
            className="flex cursor-pointer items-center gap-2 rounded-lg px-2.5 py-2 font-medium text-rose-300 hover:bg-rose-500/10 hover:text-rose-200 focus:bg-rose-500/10 focus:outline-none"
          >
            <LogOut className="h-3.5 w-3.5" aria-hidden="true" />
            <span>Log Out</span>
          </DropdownMenu.Item>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}

export default UserNav;
