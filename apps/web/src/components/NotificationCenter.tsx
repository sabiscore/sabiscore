"use client";

import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Bell, Check, CheckCheck } from "lucide-react";
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { cn } from "@/lib/utils";

interface InAppNotification {
  id: string;
  title: string;
  message: string;
  category?: string;
  match_id?: string;
  read: boolean;
  read_at?: string;
  created_at: string;
}

interface NotificationListResponse {
  items: InAppNotification[];
  unread_count: number;
  total: number;
}

export function NotificationCenter() {
  const queryClient = useQueryClient();
  const [isOpen, setIsOpen] = useState(false);

  const { data, isLoading } = useQuery<NotificationListResponse>({
    queryKey: ["in-app-notifications"],
    queryFn: async () => {
      const res = await fetch("/api/notifications/in-app", { cache: "no-store" });
      if (!res.ok) {
        return { items: [], unread_count: 0, total: 0 };
      }
      return res.json();
    },
    refetchInterval: 30_000,
  });

  const notifications = data?.items || [];
  const unreadCount = data?.unread_count || 0;

  const markReadMutation = useMutation({
    mutationFn: async (id: string) => {
      await fetch(`/api/notifications/in-app/${encodeURIComponent(id)}/read`, {
        method: "POST",
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["in-app-notifications"] });
    },
  });

  const markAllReadMutation = useMutation({
    mutationFn: async () => {
      await fetch("/api/notifications/in-app/read-all", {
        method: "POST",
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["in-app-notifications"] });
    },
  });

  return (
    <DropdownMenu.Root open={isOpen} onOpenChange={setIsOpen}>
      <DropdownMenu.Trigger asChild>
        <button
          type="button"
          className="relative flex h-8 w-8 items-center justify-center rounded-lg border border-white/10 bg-white/[0.04] text-slate-300 transition hover:bg-white/[0.08] hover:text-white focus:outline-none focus:ring-2 focus:ring-emerald-400"
          aria-label={`Notification center (${unreadCount} unread)`}
        >
          <Bell className="h-4 w-4" />
          {unreadCount > 0 && (
            <span className="absolute -right-1 -top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-emerald-500 px-1 text-[10px] font-bold text-slate-950 shadow-sm animate-pulse">
              {unreadCount > 9 ? "9+" : unreadCount}
            </span>
          )}
        </button>
      </DropdownMenu.Trigger>

      <DropdownMenu.Portal>
        <DropdownMenu.Content
          className="z-50 w-80 sm:w-96 rounded-2xl border border-white/10 bg-slate-900 p-0 shadow-2xl backdrop-blur-xl focus:outline-none overflow-hidden"
          sideOffset={8}
          align="end"
        >
          {/* Header */}
          <div className="flex items-center justify-between border-b border-white/10 bg-slate-950/60 px-4 py-3">
            <div className="flex items-center gap-2">
              <span className="flex h-6 w-6 items-center justify-center rounded-md bg-emerald-500/20 text-emerald-300">
                <Bell className="h-3.5 w-3.5" />
              </span>
              <span className="text-xs font-bold text-white tracking-wide uppercase">
                Intelligence Alerts
              </span>
            </div>

            {unreadCount > 0 && (
              <button
                type="button"
                onClick={() => markAllReadMutation.mutate()}
                disabled={markAllReadMutation.isPending}
                className="flex items-center gap-1 text-[11px] font-medium text-emerald-400 hover:text-emerald-300 transition focus:outline-none"
              >
                <CheckCheck className="h-3.5 w-3.5" />
                <span>Mark all read</span>
              </button>
            )}
          </div>

          {/* List */}
          <div className="max-h-80 overflow-y-auto divide-y divide-white/[0.06] p-1">
            {isLoading ? (
              <div className="p-6 text-center text-xs text-slate-400">Loading alerts...</div>
            ) : notifications.length === 0 ? (
              <div className="p-6 text-center text-xs text-slate-400">
                <p className="font-semibold text-slate-300">No active alerts</p>
                <p className="mt-1 text-[11px] text-slate-500">
                  Subscribe to kickoff reminders or probability swing alerts on any match page.
                </p>
              </div>
            ) : (
              notifications.map((notif) => (
                <div
                  key={notif.id}
                  className={cn(
                    "flex items-start justify-between gap-3 p-3 rounded-xl transition text-xs",
                    notif.read ? "opacity-75 hover:bg-white/[0.02]" : "bg-emerald-500/[0.05] hover:bg-emerald-500/[0.08]"
                  )}
                >
                  <div className="min-w-0 flex-1 space-y-1">
                    <div className="flex items-center gap-1.5">
                      {!notif.read && (
                        <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 shrink-0" />
                      )}
                      <p className="font-semibold text-white truncate">{notif.title}</p>
                    </div>
                    <p className="text-[11px] leading-relaxed text-slate-300">{notif.message}</p>
                    <p className="text-[10px] text-slate-500">
                      {new Date(notif.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                    </p>
                  </div>

                  {!notif.read && (
                    <button
                      type="button"
                      onClick={() => markReadMutation.mutate(notif.id)}
                      disabled={markReadMutation.isPending}
                      className="shrink-0 rounded-lg p-1.5 text-slate-400 hover:bg-white/10 hover:text-emerald-300 focus:outline-none"
                      aria-label="Mark notification as read"
                    >
                      <Check className="h-3.5 w-3.5" />
                    </button>
                  )}
                </div>
              ))
            )}
          </div>

          {/* Footer */}
          <div className="border-t border-white/10 bg-slate-950/60 px-4 py-2 text-center text-[10px] text-slate-400">
            Timezone-aware delivery configured to Africa/Lagos (WAT).
          </div>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}

export default NotificationCenter;
