"use client";

import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Key,
  Copy,
  Check,
  Plus,
  Trash2,
  Terminal,
  Zap,
  CheckCircle2,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { formatLagosTimestamp } from "@/lib/full-analysis-contract";

interface ApiKeyItem {
  id: string;
  name: string;
  key_prefix: string;
  tier: string;
  rate_limit_per_minute: number;
  daily_quota: number;
  is_active: boolean;
  created_at: string;
  last_used_at?: string | null;
}

interface DeveloperUsage {
  key_id?: string;
  tier: string;
  minute_limit?: number;
  minute_used?: number;
  daily_limit?: number;
  daily_used?: number;
  rate_limit_per_minute?: number;
  minute_requests_used?: number;
  minute_requests_remaining?: number;
  daily_quota?: number;
  daily_requests_used?: number;
  daily_requests_remaining?: number;
  reset_seconds?: number;
}

export default function DeveloperPage() {
  const queryClient = useQueryClient();
  const [newKeyName, setNewKeyName] = useState("");
  const [createdSecret, setCreatedSecret] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [selectedLanguage, setSelectedLanguage] = useState<"curl" | "javascript" | "python">("curl");

  // Fetch list of API keys
  const { data: keys = [], isLoading: keysLoading } = useQuery<ApiKeyItem[]>({
    queryKey: ["developer-keys"],
    queryFn: async () => {
      const res = await fetch("/api/developer/keys", { cache: "no-store" });
      if (!res.ok) {
        return [];
      }
      const data = await res.json();
      return Array.isArray(data) ? data : data.keys || [];
    },
  });

  // Fetch usage stats
  const { data: usage } = useQuery<DeveloperUsage>({
    queryKey: ["developer-usage"],
    queryFn: async () => {
      const res = await fetch("/api/developer/usage", { cache: "no-store" });
      if (!res.ok) {
        return {
          tier: "FREE",
          minute_limit: 10,
          minute_used: 0,
          daily_limit: 100,
          daily_used: 0,
        };
      }
      return res.json();
    },
  });

  // Create Key Mutation
  const createKeyMutation = useMutation({
    mutationFn: async (name: string) => {
      const res = await fetch("/api/developer/keys", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, tier: "FREE" }),
      });
      if (!res.ok) throw new Error("Failed to create key");
      return res.json();
    },
    onSuccess: (data) => {
      const keySecret = data.api_key || data.key;
      setCreatedSecret(keySecret);
      setNewKeyName("");
      queryClient.invalidateQueries({ queryKey: ["developer-keys"] });
    },
  });

  // Revoke Key Mutation
  const revokeKeyMutation = useMutation({
    mutationFn: async (keyId: string) => {
      const res = await fetch(`/api/developer/keys/${encodeURIComponent(keyId)}`, {
        method: "DELETE",
      });
      if (!res.ok) throw new Error("Failed to revoke key");
      return res.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["developer-keys"] });
    },
  });

  const handleCopySecret = async () => {
    if (!createdSecret) return;
    try {
      await navigator.clipboard.writeText(createdSecret);
      setCopied(true);
      setTimeout(() => setCopied(false), 2500);
    } catch {}
  };

  const minuteLimit = usage?.minute_limit ?? usage?.rate_limit_per_minute ?? 10;
  const minuteUsed = usage?.minute_used ?? usage?.minute_requests_used ?? 0;
  const dailyLimit = usage?.daily_limit ?? usage?.daily_quota ?? 100;
  const dailyUsed = usage?.daily_used ?? usage?.daily_requests_used ?? 0;

  const minutePct = Math.min(100, Math.round((minuteUsed / minuteLimit) * 100));
  const dailyPct = Math.min(100, Math.round((dailyUsed / dailyLimit) * 100));

  const codeSnippets = {
    curl: `curl -X GET "https://sabiscore.com/api/v1/predict/arsenal-vs-chelsea" \\
  -H "x-api-key: ${createdSecret || "sbk_live_YOUR_API_KEY"}" \\
  -H "Accept: application/json"`,
    javascript: `const response = await fetch("https://sabiscore.com/api/v1/predict/arsenal-vs-chelsea", {
  headers: {
    "x-api-key": "${createdSecret || "sbk_live_YOUR_API_KEY"}",
    "Accept": "application/json"
  }
});
const data = await response.json();
console.log("Model Verdict:", data.verdict);
console.log("Probabilities:", data.ensemble);`,
    python: `import httpx

headers = {
    "x-api-key": "${createdSecret || "sbk_live_YOUR_API_KEY"}",
    "Accept": "application/json"
}

with httpx.Client() as client:
    res = client.get("https://sabiscore.com/api/v1/predict/arsenal-vs-chelsea", headers=headers)
    prediction = res.json()
    print("Top Probability:", prediction["top_outcome_probability"])
    print("Verdict:", prediction["verdict"])`,
  };

  return (
    <div className="mx-auto max-w-5xl space-y-6 pb-12">
      {/* 100% Free Developer Banner */}
      <div className="rounded-2xl border border-emerald-500/30 bg-gradient-to-r from-emerald-950/60 via-slate-900/90 to-slate-900/90 p-6 shadow-xl backdrop-blur">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-emerald-500/20 text-emerald-300">
                <Zap className="h-4 w-4" />
              </span>
              <h1 className="text-xl font-extrabold text-white tracking-tight sm:text-2xl">
                SabiScore Developer Platform
              </h1>
            </div>
            <p className="text-xs text-slate-300 max-w-2xl leading-relaxed">
              Programmatic access to evidence-backed football probabilities, calibration statistics, and live match intelligence. <strong className="text-emerald-300 font-semibold">100% Free Developer Tier</strong> with zero credit card or billing required.
            </p>
          </div>

          <div className="flex items-center gap-2 rounded-xl bg-emerald-500/10 px-3.5 py-2 border border-emerald-500/30 text-emerald-300 text-xs font-bold tracking-wide uppercase">
            <CheckCircle2 className="h-4 w-4" />
            <span>Free Tier · 100 req/day</span>
          </div>
        </div>
      </div>

      {/* Usage Telemetry & Rate Limits */}
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="rounded-2xl border border-white/10 bg-slate-900/60 p-5 backdrop-blur">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold uppercase tracking-wider text-slate-400">
              Minute Rate Limit
            </span>
            <span className="text-xs font-bold text-emerald-400 tabular-nums">
              {minuteUsed} / {minuteLimit} req/min
            </span>
          </div>
          <div className="mt-3 h-2 w-full overflow-hidden rounded-full bg-slate-800">
            <div
              className={cn(
                "h-full transition-all duration-300",
                minutePct > 80 ? "bg-amber-400" : "bg-emerald-400"
              )}
              style={{ width: `${Math.max(5, minutePct)}%` }}
            />
          </div>
          <p className="mt-2 text-[10px] text-slate-500">Sliding 60-second window quota. Tier: FREE</p>
        </div>

        <div className="rounded-2xl border border-white/10 bg-slate-900/60 p-5 backdrop-blur">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold uppercase tracking-wider text-slate-400">
              Daily Request Quota
            </span>
            <span className="text-xs font-bold text-sky-400 tabular-nums">
              {dailyUsed} / {dailyLimit} req/day
            </span>
          </div>
          <div className="mt-3 h-2 w-full overflow-hidden rounded-full bg-slate-800">
            <div
              className={cn(
                "h-full transition-all duration-300",
                dailyPct > 80 ? "bg-amber-400" : "bg-sky-400"
              )}
              style={{ width: `${Math.max(5, dailyPct)}%` }}
            />
          </div>
          <p className="mt-2 text-[10px] text-slate-500">Resets daily at 00:00 UTC. Tier: FREE</p>
        </div>
      </div>

      {/* Secret Shown Once Alert */}
      {createdSecret && (
        <div className="rounded-2xl border border-emerald-500/40 bg-emerald-950/40 p-5 shadow-2xl animate-in fade-in slide-in-from-top-2">
          <div className="flex items-start justify-between gap-3">
            <div className="space-y-1">
              <div className="flex items-center gap-2">
                <CheckCircle2 className="h-5 w-5 text-emerald-400" />
                <h3 className="text-sm font-bold text-white">API Key Created Successfully</h3>
              </div>
              <p className="text-xs text-slate-300">
                Copy your key now. For your security, <strong className="text-emerald-300">it will never be displayed again</strong>.
              </p>
            </div>
            <button
              type="button"
              onClick={() => setCreatedSecret(null)}
              className="text-xs font-semibold text-slate-400 hover:text-white"
            >
              Dismiss
            </button>
          </div>

          <div className="mt-3 flex items-center gap-2 rounded-xl border border-emerald-500/30 bg-slate-950 p-2.5">
            <code className="flex-1 font-mono text-xs font-bold text-emerald-300 break-all select-all">
              {createdSecret}
            </code>
            <button
              type="button"
              onClick={handleCopySecret}
              className="flex items-center gap-1.5 rounded-lg bg-emerald-400 px-3 py-1.5 text-xs font-bold text-slate-950 hover:bg-emerald-300 transition shrink-0"
            >
              {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
              <span>{copied ? "Copied" : "Copy Key"}</span>
            </button>
          </div>
        </div>
      )}

      {/* API Key Management */}
      <div className="rounded-2xl border border-white/10 bg-slate-900/60 p-6 space-y-5">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/10 pb-4">
          <div>
            <h2 className="text-base font-bold text-white">Active API Keys</h2>
            <p className="text-xs text-slate-400">Manage credentials for your applications and scripts.</p>
          </div>

          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (newKeyName.trim()) {
                createKeyMutation.mutate(newKeyName.trim());
              }
            }}
            className="flex items-center gap-2"
          >
            <input
              type="text"
              placeholder="e.g. Ingestion Script"
              value={newKeyName}
              onChange={(e) => setNewKeyName(e.target.value)}
              className="rounded-xl border border-white/10 bg-slate-950 px-3 py-1.5 text-xs text-white placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-emerald-400"
            />
            <button
              type="submit"
              disabled={createKeyMutation.isPending || !newKeyName.trim()}
              className="flex items-center gap-1.5 rounded-xl bg-emerald-400 px-3 py-1.5 text-xs font-bold text-slate-950 hover:bg-emerald-300 transition disabled:opacity-50"
            >
              <Plus className="h-3.5 w-3.5" />
              <span>Create Key</span>
            </button>
          </form>
        </div>

        {keysLoading ? (
          <div className="py-8 text-center text-xs text-slate-400">Loading API keys...</div>
        ) : keys.length === 0 ? (
          <div className="py-8 text-center text-xs text-slate-400">
            <Key className="mx-auto h-7 w-7 text-slate-600 mb-2" />
            <p className="font-semibold text-slate-300">No active developer API keys</p>
            <p className="mt-1 text-[11px] text-slate-500">Create an API key above to start querying the API.</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-white/10 text-slate-400">
                  <th className="pb-2 font-semibold">Key Name</th>
                  <th className="pb-2 font-semibold">Prefix</th>
                  <th className="pb-2 font-semibold">Tier</th>
                  <th className="pb-2 font-semibold">Created</th>
                  <th className="pb-2 font-semibold text-right">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/[0.06]">
                {keys.map((k) => (
                  <tr key={k.id} className="hover:bg-white/[0.02]">
                    <td className="py-3 font-semibold text-white">{k.name}</td>
                    <td className="py-3 font-mono text-emerald-400">{k.key_prefix}...</td>
                    <td className="py-3">
                      <span className="rounded bg-emerald-500/10 px-2 py-0.5 font-bold text-emerald-300 border border-emerald-500/20 text-[10px]">
                        {k.tier || "FREE"}
                      </span>
                    </td>
                    <td className="py-3 text-slate-400">
                      {formatLagosTimestamp(k.created_at)} WAT
                    </td>
                    <td className="py-3 text-right">
                      <button
                        type="button"
                        onClick={() => revokeKeyMutation.mutate(k.id)}
                        disabled={revokeKeyMutation.isPending}
                        className="rounded-lg p-1.5 text-slate-400 hover:bg-rose-500/10 hover:text-rose-400 transition"
                        aria-label={`Revoke API key ${k.name}`}
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Code Examples & Quickstart */}
      <div className="rounded-2xl border border-white/10 bg-slate-900/60 p-6 space-y-4">
        <div className="flex items-center justify-between border-b border-white/10 pb-3">
          <div className="flex items-center gap-2">
            <Terminal className="h-4 w-4 text-emerald-400" />
            <h2 className="text-base font-bold text-white">Quickstart & Code Examples</h2>
          </div>

          <div className="flex rounded-lg border border-white/10 bg-slate-950 p-0.5 text-xs">
            {(["curl", "javascript", "python"] as const).map((lang) => (
              <button
                key={lang}
                type="button"
                onClick={() => setSelectedLanguage(lang)}
                className={cn(
                  "rounded-md px-2.5 py-1 font-semibold uppercase transition text-[10px]",
                  selectedLanguage === lang
                    ? "bg-slate-800 text-white"
                    : "text-slate-400 hover:text-slate-200"
                )}
              >
                {lang}
              </button>
            ))}
          </div>
        </div>

        <div className="relative rounded-xl border border-white/10 bg-slate-950 p-4 font-mono text-xs text-emerald-300 overflow-x-auto">
          <pre>{codeSnippets[selectedLanguage]}</pre>
        </div>
      </div>
    </div>
  );
}
