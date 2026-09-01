"use client";

import React, { useState } from "react";
import Link from "next/link";
import { User, LogIn, LogOut, LayoutDashboard, Code, Sliders } from "lucide-react";
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { useAuth } from "@/lib/auth-context";
import { AuthModal } from "@/components/AuthModal";

export function UserNav() {
  const { user, isAuthenticated, logout } = useAuth();
  const [authModalOpen, setAuthModalOpen] = useState(false);

  if (!isAuthenticated) {
    return (
      <>
        <button
          type="button"
          onClick={() => setAuthModalOpen(true)}
          className="flex min-h-8 items-center gap-1.5 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-1 text-xs font-semibold text-emerald-300 transition hover:bg-emerald-500/20 focus:outline-none focus:ring-2 focus:ring-emerald-400"
          aria-label="Sign in or register"
        >
          <LogIn className="h-3.5 w-3.5" />
          <span>Sign In</span>
        </button>
        <AuthModal open={authModalOpen} onOpenChange={setAuthModalOpen} />
      </>
    );
  }

  const displayName = user?.username || user?.full_name || user?.email.split("@")[0] || "Analyst";

  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button
          type="button"
          className="flex min-h-8 items-center gap-2 rounded-lg border border-white/10 bg-white/[0.04] px-2.5 py-1 text-xs font-semibold text-slate-200 transition hover:bg-white/[0.08] hover:text-white focus:outline-none focus:ring-2 focus:ring-emerald-400"
          aria-label="User profile and menu"
        >
          <div className="flex h-5 w-5 items-center justify-center rounded-full bg-emerald-500/20 text-emerald-300">
            <User className="h-3 w-3" />
          </div>
          <span className="max-w-[100px] truncate">{displayName}</span>
        </button>
      </DropdownMenu.Trigger>

      <DropdownMenu.Portal>
        <DropdownMenu.Content
          className="z-50 min-w-[180px] rounded-xl border border-white/10 bg-slate-900 p-1.5 shadow-2xl text-xs backdrop-blur-md focus:outline-none"
          sideOffset={6}
          align="end"
        >
          <div className="px-2.5 py-1.5 border-b border-white/10">
            <p className="font-semibold text-white truncate">{displayName}</p>
            <p className="text-[10px] text-slate-400 truncate">{user?.email}</p>
          </div>

          <DropdownMenu.Item asChild>
            <Link
              href="/dashboard"
              className="flex items-center gap-2 rounded-lg px-2.5 py-1.5 font-medium text-slate-300 hover:bg-white/10 hover:text-white cursor-pointer focus:bg-white/10 focus:outline-none"
            >
              <LayoutDashboard className="h-3.5 w-3.5 text-emerald-400" />
              <span>Dashboard</span>
            </Link>
          </DropdownMenu.Item>

          <DropdownMenu.Item asChild>
            <Link
              href="/developer"
              className="flex items-center gap-2 rounded-lg px-2.5 py-1.5 font-medium text-slate-300 hover:bg-white/10 hover:text-white cursor-pointer focus:bg-white/10 focus:outline-none"
            >
              <Code className="h-3.5 w-3.5 text-sky-400" />
              <span>Developer API</span>
            </Link>
          </DropdownMenu.Item>

          <DropdownMenu.Item asChild>
            <Link
              href="/dashboard?tab=preferences"
              className="flex items-center gap-2 rounded-lg px-2.5 py-1.5 font-medium text-slate-300 hover:bg-white/10 hover:text-white cursor-pointer focus:bg-white/10 focus:outline-none"
            >
              <Sliders className="h-3.5 w-3.5 text-amber-400" />
              <span>Preferences</span>
            </Link>
          </DropdownMenu.Item>

          <DropdownMenu.Separator className="my-1 h-px bg-white/10" />

          <DropdownMenu.Item
            onClick={() => logout()}
            className="flex items-center gap-2 rounded-lg px-2.5 py-1.5 font-medium text-rose-300 hover:bg-rose-500/10 hover:text-rose-200 cursor-pointer focus:bg-rose-500/10 focus:outline-none"
          >
            <LogOut className="h-3.5 w-3.5" />
            <span>Log Out</span>
          </DropdownMenu.Item>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}

export default UserNav;
