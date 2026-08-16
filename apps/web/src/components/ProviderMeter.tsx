"use client";

/**
 * ProviderMeter — shows real-time health of the five configured evidence providers.
 *
 * Displays only the canonical SabiScore provider registry:
 *   Football-Data.org | API-Football | Sportmonks | The Odds API | ESPN
 *
 * Status semantics keep configuration separate from explicit live validation:
 *   ✓ Live-validated — VERIFIED
 *   ◌ Not validated  — CONFIGURED_UNVERIFIED (neutral, not an outage)
 *   ⚠ Partial        — PARTIAL
 *   ✗ Unavailable    — UNAVAILABLE / CIRCUIT_OPEN / INVALID / SCHEMA_INVALID
 *   ○ Not configured — UNCONFIGURED
 *   ⏸ Quota          — RATE_LIMITED
 *
 * Data comes from /api/providers/health (proxied to backend); never from
 * provider hosts directly.
 */

import { useQuery } from "@tanstack/react-query";
import {
  fetchPlatformHealth,
  PLATFORM_HEALTH_QUERY_KEY,
  type BackendHealthPayload,
} from "@/lib/health-status";

type ProviderStatus =
  | "VERIFIED"
  | "CONFIGURED_UNVERIFIED"
  | "UNCONFIGURED"
  | "PARTIAL"
  | "UNAVAILABLE"
  | "CIRCUIT_OPEN"
  | "RATE_LIMITED"
  | "INVALID"
  | "SCHEMA_INVALID"
  | "CONFLICTING";

interface ProviderRow {
  provider: string;
  display_name: string;
  enabled: boolean;
  configured: boolean;
  status: ProviderStatus;
  trust_tier: string;
  requires_key: boolean;
}

// Canonical display order matching directive registry
const CANONICAL_ORDER = [
  "football_data_org",
  "api_football",
  "sportmonks",
  "the_odds_api",
  "espn",
];

const DISPLAY_NAMES: Record<string, string> = {
  football_data_org: "Football-Data.org",
  api_football: "API-Football",
  sportmonks: "Sportmonks",
  the_odds_api: "The Odds API",
  espn: "ESPN",
};

function statusBadge(row: ProviderRow): { icon: string; label: string; className: string } {
  if (!row.enabled) return { icon: "○", label: "Not configured", className: "pm-off" };
  switch (row.status) {
    case "VERIFIED":
      return { icon: "✓", label: "Live-validated", className: "pm-live" };
    case "RATE_LIMITED":
      return { icon: "⏸", label: "Quota exhausted", className: "pm-quota" };
    case "CIRCUIT_OPEN":
    case "UNAVAILABLE":
    case "INVALID":
    case "SCHEMA_INVALID":
      return { icon: "✗", label: "Unavailable", className: "pm-down" };
    case "UNCONFIGURED":
      return { icon: "○", label: "Not configured", className: "pm-off" };
    case "CONFLICTING":
      return { icon: "⚡", label: "Conflict", className: "pm-conflict" };
    case "PARTIAL":
      return { icon: "⚠", label: "Partial evidence", className: "pm-stale" };
    case "CONFIGURED_UNVERIFIED":
      return { icon: "◌", label: "Not live-validated", className: "pm-unverified" };
    default:
      return { icon: "?", label: row.status, className: "pm-off" };
  }
}

export function ProviderMeter() {
  const { data, isLoading } = useQuery<BackendHealthPayload>({
    queryKey: PLATFORM_HEALTH_QUERY_KEY,
    queryFn: fetchPlatformHealth,
    staleTime: 30_000,
    refetchInterval: 60_000,
  });
  const rows = data?.providers as ProviderRow[] | undefined;
  const error = data && data.backendStatus === "unavailable"
    ? "Provider status unavailable — backend unreachable"
    : null;
  const lastChecked = typeof data?.timestamp === "string" ? data.timestamp : null;

  // Sort by canonical order; append unknown providers at end
  const sorted = rows
    ? [
        ...CANONICAL_ORDER.map((id) => rows.find((r) => r.provider === id)).filter(Boolean),
        ...rows.filter((r) => !CANONICAL_ORDER.includes(r.provider)),
      ].filter(Boolean) as ProviderRow[]
    : null;

  return (
    <section
      className="pm-root"
      aria-label="Evidence provider status meter"
      role="status"
    >
      <div className="pm-header">
        <span className="pm-title">Evidence Sources</span>
        {lastChecked && (
          <time className="pm-ts" dateTime={lastChecked} title={`Last checked ${lastChecked}`}>
            {new Date(lastChecked).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
          </time>
        )}
      </div>

      {error ? (
        <p className="pm-error">{error}</p>
      ) : isLoading || sorted === null ? (
        <div className="pm-loading" aria-busy="true">Checking providers…</div>
      ) : (
        <ul className="pm-list" role="list">
          {sorted.map((row) => {
            const badge = statusBadge(row);
            return (
              <li key={row.provider} className={`pm-row ${badge.className}`}>
                <span className="pm-icon" aria-hidden="true">{badge.icon}</span>
                <span className="pm-name">
                  {DISPLAY_NAMES[row.provider] ?? row.display_name}
                </span>
                <span className="pm-label">{badge.label}</span>
              </li>
            );
          })}
        </ul>
      )}

      <p className="pm-disclaimer">
        Configuration and live validation are separate. Routine health checks do not
        spend provider quota; live validation appears only after an explicit operator probe.
      </p>

      <style>{`
        .pm-root {
          background: #0d1c18;
          border: 1px solid #1f3529;
          border-radius: 8px;
          padding: 12px 14px;
          font-size: 12px;
          color: #9fb3aa;
        }
        .pm-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 8px;
        }
        .pm-title {
          font-size: 11px;
          font-weight: 700;
          text-transform: uppercase;
          letter-spacing: 0.06em;
          color: #6b8c7a;
        }
        .pm-ts { color: inherit; font-size: 10px; }
        .pm-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 5px; }
        .pm-row {
          display: flex;
          align-items: center;
          gap: 7px;
          padding: 4px 6px;
          border-radius: 4px;
          background: #111e1a;
        }
        .pm-icon { font-size: 13px; width: 16px; text-align: center; flex-shrink: 0; }
        .pm-name { flex: 1; color: #c8dbd2; font-weight: 500; }
        .pm-label { font-size: 10px; color: #6b8c7a; flex-shrink: 0; }
        /* Status colour tokens */
        .pm-live .pm-icon { color: #4ade80; }
        .pm-live .pm-label { color: #4ade80; }
        .pm-stale .pm-icon { color: #facc15; }
        .pm-stale .pm-label { color: #facc15; }
        .pm-unverified .pm-icon { color: #94a3b8; }
        .pm-unverified .pm-label { color: #94a3b8; }
        .pm-down .pm-icon { color: #f87171; }
        .pm-down .pm-label { color: #f87171; }
        .pm-quota .pm-icon { color: #c084fc; }
        .pm-quota .pm-label { color: #c084fc; }
        .pm-off .pm-icon { color: inherit; }
        .pm-off .pm-label { color: inherit; }
        .pm-loading { color: inherit; padding: 6px 0; }
        .pm-error { color: #f87171; margin: 4px 0 6px; }
        .pm-disclaimer {
          margin-top: 8px;
          font-size: 10px;
          line-height: 1.4;
          color: inherit;
        }
      `}</style>
    </section>
  );
}
