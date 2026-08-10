/**
 * Public readiness proxy. Runtime performance is sourced only from settled
 * backend predictions; absent evidence is Pending/null rather than a benchmark.
 */

import { NextResponse } from "next/server";
import { backendHealthIssues, isHealthyBackendStatus } from "@/lib/health-status";
import { RPS_PROMOTION_GATE } from "@/lib/model-gates";
import { isHtmlBody } from "@/lib/proxy-utils";

export const runtime = "edge";
export const dynamic = "force-dynamic";

const BACKEND_URL = process.env.SABISCORE_BACKEND_URL;

type PerformanceSummary = {
  status?: string;
  total_settled?: number;
  accuracy_overall?: number | null;
  rps_overall?: number | null;
  generated_at?: string;
};

export async function GET() {
  let backendStatus = "unavailable";
  let backendChecks: Record<string, unknown> = {};
  let backendCapability: Record<string, unknown> | null = null;
  let backendSha: string | null = null;
  let providers: Array<Record<string, unknown>> = [];
  let performance: PerformanceSummary = { status: "METRICS_UNAVAILABLE" };

  if (BACKEND_URL) {
    try {
      const requestOptions = {
        signal: AbortSignal.timeout(5000),
        headers: { Accept: "application/json" },
        cache: "no-store" as const,
      };
      const [readinessRes, providersRes, performanceRes] = await Promise.all([
        fetch(`${BACKEND_URL}/health/ready`, requestOptions),
        fetch(`${BACKEND_URL}/api/v1/providers/health`, requestOptions),
        fetch(`${BACKEND_URL}/api/v1/model-performance/summary`, requestOptions),
      ]);

      const readinessBody = await readinessRes.text().catch(() => "");
      if (!isHtmlBody(readinessBody)) {
        try {
          const data = JSON.parse(readinessBody) as Record<string, unknown>;
          backendStatus = (data.status as string) ?? (readinessRes.ok ? "unknown" : "degraded");
          backendChecks = (data.checks as Record<string, unknown>) ?? {};
          backendCapability = (data.capability as Record<string, unknown>) ?? null;
          backendSha = typeof data.release_sha === "string" ? data.release_sha : null;
        } catch {
          backendStatus = "unavailable";
        }
      }

      if (providersRes.ok) {
        const providerData = (await providersRes.json()) as { providers?: unknown };
        providers = Array.isArray(providerData.providers)
          ? providerData.providers as Array<Record<string, unknown>>
          : [];
      }

      const performanceBody = await performanceRes.text().catch(() => "");
      if (!isHtmlBody(performanceBody)) {
        try {
          performance = JSON.parse(performanceBody) as PerformanceSummary;
        } catch {
          performance = { status: "METRICS_UNAVAILABLE" };
        }
      }
    } catch {
      backendStatus = "unavailable";
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
    },
    {
      status: 200,
      headers: { "Cache-Control": "no-store" },
    },
  );
}
