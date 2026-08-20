/**
 * Public readiness proxy. Runtime performance is sourced only from settled
 * backend predictions; absent evidence is Pending/null rather than a benchmark.
 */

import { NextResponse } from "next/server";
import {
  backendHealthIssues,
  isHealthyBackendStatus,
  mergeProviderEvidence,
  type ProviderHealthRow,
} from "@/lib/health-status";
import { RPS_PROMOTION_GATE } from "@/lib/model-gates";
import { isHtmlBody } from "@/lib/proxy-utils";

export const runtime = "edge";
export const dynamic = "force-dynamic";

const BACKEND_URL = process.env.SABISCORE_BACKEND_URL;
const READINESS_TIMEOUT_MS = 15_000;
const ANCILLARY_TIMEOUT_MS = 5_000;

type PerformanceSummary = {
  status?: string;
  total_settled?: number;
  accuracy_overall?: number | null;
  rps_overall?: number | null;
  generated_at?: string;
};

function backendFetch(path: string, timeoutMs: number) {
  return fetch(`${BACKEND_URL}${path}`, {
    signal: AbortSignal.timeout(timeoutMs),
    headers: { Accept: "application/json" },
    cache: "no-store" as const,
  });
}

export async function GET() {
  let backendStatus = "unavailable";
  let backendChecks: Record<string, unknown> = {};
  let backendCapability: Record<string, unknown> | null = null;
  let backendSha: string | null = null;
  let providers: ProviderHealthRow[] = [];
  let performance: PerformanceSummary = { status: "METRICS_UNAVAILABLE" };

  if (BACKEND_URL) {
    const [readinessResult, providerRegistryResult, providerEvidenceResult, performanceResult] =
      await Promise.allSettled([
        backendFetch("/health/ready", READINESS_TIMEOUT_MS),
        backendFetch("/api/v1/providers/health", ANCILLARY_TIMEOUT_MS),
        backendFetch("/api/v1/providers/evidence", ANCILLARY_TIMEOUT_MS),
        backendFetch("/api/v1/model-performance/summary", ANCILLARY_TIMEOUT_MS),
      ]);

    // Readiness is authoritative for backend process/data readiness. Provider or
    // performance endpoint failure must never erase a valid readiness response.
    if (readinessResult.status === "fulfilled") {
      const readinessRes = readinessResult.value;
      const readinessBody = await readinessRes.text().catch(() => "");
      if (!isHtmlBody(readinessBody)) {
        try {
          const data = JSON.parse(readinessBody) as Record<string, unknown>;
          backendStatus = (data.status as string) ?? (readinessRes.ok ? "unknown" : "degraded");
          backendChecks = (data.checks as Record<string, unknown>) ?? {};
          backendCapability = (
            (data.capabilities as Record<string, unknown> | undefined) ??
            (data.capability as Record<string, unknown> | undefined)
          ) ?? null;
          backendSha = typeof data.release_sha === "string" ? data.release_sha : null;
        } catch {
          backendStatus = "unavailable";
        }
      }
    }

    let providerRegistry: ProviderHealthRow[] = [];
    if (providerRegistryResult.status === "fulfilled" && providerRegistryResult.value.ok) {
      try {
        const providerData = (await providerRegistryResult.value.json()) as { providers?: unknown };
        providerRegistry = Array.isArray(providerData.providers)
          ? providerData.providers.filter(
              (row): row is ProviderHealthRow =>
                typeof row === "object" && row !== null && !Array.isArray(row),
            )
          : [];
      } catch {
        providerRegistry = [];
      }
    }

    let providerEvidence: unknown = null;
    if (providerEvidenceResult.status === "fulfilled" && providerEvidenceResult.value.ok) {
      try {
        const evidenceData = (await providerEvidenceResult.value.json()) as { providers?: unknown };
        providerEvidence = evidenceData.providers ?? null;
      } catch {
        providerEvidence = null;
      }
    }
    providers = mergeProviderEvidence(providerRegistry, providerEvidence);

    if (performanceResult.status === "fulfilled") {
      const performanceBody = await performanceResult.value.text().catch(() => "");
      if (!isHtmlBody(performanceBody)) {
        try {
          performance = JSON.parse(performanceBody) as PerformanceSummary;
        } catch {
          performance = { status: "METRICS_UNAVAILABLE" };
        }
      }
    }
  }

  const isHealthy = isHealthyBackendStatus(backendStatus);
  const hasSufficientData = performance.status === "OK" &&
    typeof performance.total_settled === "number" && performance.total_settled > 0;
  const accuracy = hasSufficientData && typeof performance.accuracy_overall === "number"
    ? performance.accuracy_overall
    : null;
  const rps = hasSufficientData && typeof performance.rps_overall === "number"
    ? performance.rps_overall
    : null;
  const predictionCount = hasSufficientData ? performance.total_settled ?? 0 : 0;
  const modelCheck = backendChecks.models as Record<string, unknown> | undefined;

  return NextResponse.json(
    {
      status: isHealthy ? "healthy" : "degraded",
      backendStatus,
      backendChecks,
      backendCapability,
      backendSha,
      providers,
      accuracy,
      brierScore: null,
      rps,
      rpsGate: RPS_PROMOTION_GATE,
      avgEdgePct: null,
      predictionCount,
      performanceStatus: hasSufficientData ? "MEASURED" : "PENDING",
      metrics: {
        accuracy,
        brierScore: null,
        rps,
        rpsGate: RPS_PROMOTION_GATE,
        avgEdgePct: null,
        predictionCount,
        status: hasSufficientData ? "MEASURED" : "PENDING",
      },
      issues: backendHealthIssues(backendStatus),
      hasSufficientData,
      lastUpdate: performance.generated_at ?? new Date().toISOString(),
      timestamp: new Date().toISOString(),
      modelVersion: modelCheck?.model_version ?? null,
      sha: process.env.VERCEL_GIT_COMMIT_SHA?.slice(0, 7) ?? "local",
      vercelSha: process.env.VERCEL_GIT_COMMIT_SHA ?? null,
    },
    {
      status: 200,
      headers: { "Cache-Control": "no-store" },
    },
  );
}
