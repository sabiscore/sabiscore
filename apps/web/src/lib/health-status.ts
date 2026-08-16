export const BACKEND_READINESS_CHECKS = [
  "database",
  "migrations",
  "cache",
  "models",
] as const;

const READY_STATUSES = new Set(["ok", "ready", "healthy"]);

export interface BackendReadinessCheck {
  status?: unknown;
}

export type CapabilityStatus =
  | "verified"
  | "unverified_no_fixtures"
  | "unverified_insufficient_evidence"
  | "failed"
  | "unknown";

export interface BackendHealthPayload {
  backendStatus?: unknown;
  timestamp?: unknown;
  backendChecks?: Record<string, BackendReadinessCheck | unknown>;
  backendCapability?: { status?: unknown; message?: unknown };
  providers?: Array<{
    provider?: unknown;
    display_name?: unknown;
    configured?: unknown;
    enabled?: unknown;
    status?: unknown;
  }>;
}

export const PLATFORM_HEALTH_QUERY_KEY = ["platform-health"] as const;

export async function fetchPlatformHealth(): Promise<BackendHealthPayload> {
  const response = await fetch("/api/health", { cache: "no-store" });
  if (!response.ok) return { backendStatus: "unavailable", providers: [] };
  return response.json() as Promise<BackendHealthPayload>;
}

export interface BackendReadinessStats {
  total: number;
  ready: number;
  unavailable: number;
  score: number;
  label: "Core ready" | "Core partial" | "Core unavailable";
  capability: CapabilityStatus;
  capabilityMessage?: string;
}

const CAPABILITY_STATUSES = new Set<CapabilityStatus>([
  "verified",
  "unverified_no_fixtures",
  "unverified_insufficient_evidence",
  "failed",
]);

export function normalizeCapabilityStatus(raw: unknown): CapabilityStatus {
  return typeof raw === "string" && CAPABILITY_STATUSES.has(raw as CapabilityStatus)
    ? (raw as CapabilityStatus)
    : "unknown";
}

export interface ProviderActivationStats {
  total: number;
  configured: number;
  enabled: number;
  live: number;
  degraded: number;
  label: "Ready" | "Partial" | "Unavailable";
}

const DEGRADED_PROVIDER_STATUSES = new Set([
  "INVALID",
  "UNAVAILABLE",
  "CIRCUIT_OPEN",
  "RATE_LIMITED",
  "SCHEMA_INVALID",
  "CONFLICTING",
]);

export function isHealthyBackendStatus(status: unknown): boolean {
  return typeof status === "string" && READY_STATUSES.has(status.toLowerCase());
}

export function backendHealthIssues(status: unknown): string[] {
  return isHealthyBackendStatus(status)
    ? []
    : [`Backend status: ${String(status)}`];
}

export function deriveBackendReadiness(
  payload: BackendHealthPayload,
): BackendReadinessStats {
  const checks = payload.backendChecks ?? {};
  const ready = BACKEND_READINESS_CHECKS.filter((name) => {
    const check = checks[name];
    if (!check || typeof check !== "object") return false;
    return isHealthyBackendStatus((check as BackendReadinessCheck).status);
  }).length;
  const total = BACKEND_READINESS_CHECKS.length;
  const score = ready / total;
  const backendHealthy = isHealthyBackendStatus(payload.backendStatus);
  const label =
    backendHealthy && ready === total
      ? "Core ready"
      : ready > 0
        ? "Core partial"
        : "Core unavailable";

  const capability = normalizeCapabilityStatus(payload.backendCapability?.status);
  const capabilityMessage =
    typeof payload.backendCapability?.message === "string"
      ? payload.backendCapability.message
      : undefined;

  return { total, ready, unavailable: total - ready, score, label, capability, capabilityMessage };
}

export function deriveProviderActivation(
  providers: NonNullable<BackendHealthPayload["providers"]>,
): ProviderActivationStats {
  const configured = providers.filter((provider) => provider.configured === true).length;
  const enabled = providers.filter((provider) => provider.enabled === true).length;
  const live = providers.filter((provider) =>
    provider.enabled === true && String(provider.status).toUpperCase() === "VERIFIED"
  ).length;
  const degraded = providers.filter((provider) =>
    provider.enabled === true && DEGRADED_PROVIDER_STATUSES.has(String(provider.status).toUpperCase())
  ).length;
  const label =
    configured > 0 && enabled === configured && degraded === 0
      ? "Ready"
      : enabled > 0
        ? "Partial"
        : "Unavailable";

  return { total: providers.length, configured, enabled, live, degraded, label };
}

export function derivePlatformHealth(payload: BackendHealthPayload) {
  const readiness = deriveBackendReadiness(payload);
  const providers = payload.providers ?? [];
  const providerActivation = deriveProviderActivation(providers);
  const models = payload.backendChecks?.models;
  const modelsReady = Boolean(
    models && typeof models === "object" &&
      isHealthyBackendStatus((models as BackendReadinessCheck).status)
  );
  return {
    readiness,
    providers,
    ...providerActivation,
    providerActivation,
    modelsReady,
  };
}

export function liveMetricLabel(
  hasSufficientData: boolean,
  formattedValue: string,
): string {
  return hasSufficientData ? formattedValue : "Pending";
}
