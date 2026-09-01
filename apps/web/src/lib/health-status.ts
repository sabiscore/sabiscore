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
  // Emitted by /health/ready itself: readiness is side-effect free and does not
  // run the prediction pipeline, so it reports that rather than a fixture claim.
  | "not_probed_by_readiness"
  | "skipped_not_ready"
  | "failed"
  | "unknown";

export interface ProviderHealthRow extends Record<string, unknown> {
  provider?: unknown;
  display_name?: unknown;
  configured?: unknown;
  enabled?: unknown;
  status?: unknown;
  state?: unknown;
  evidence_status?: unknown;
  registry_status?: unknown;
}

export interface BackendHealthPayload {
  backendStatus?: unknown;
  timestamp?: unknown;
  backendChecks?: Record<string, BackendReadinessCheck | unknown>;
  backendCapability?: { status?: unknown; message?: unknown };
  providers?: ProviderHealthRow[];
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
  "not_probed_by_readiness",
  "skipped_not_ready",
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

const LIVE_PROVIDER_STATUSES = new Set(["LIVE_VERIFIED", "VERIFIED"]);
const DEGRADED_PROVIDER_STATUSES = new Set([
  "DEGRADED",
  "INVALID",
  "UNAVAILABLE",
  "CIRCUIT_OPEN",
  "RATE_LIMITED",
  "SCHEMA_INVALID",
  "CONFLICTING",
  "STALE",
]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function providerId(row: ProviderHealthRow): string | null {
  return typeof row.provider === "string" && row.provider.trim()
    ? row.provider.trim()
    : null;
}

/**
 * The one place that decides which field carries a provider's operational state.
 *
 * `state` wins over `status` because `mergeProviderEvidence` layers a live
 * evidence reading on top of the registry row. Exported so `ProviderMeter` reads
 * the same field this module does — it used to read `row.status` directly and
 * rendered the raw enum with a "?" whenever evidence had supplied `state`.
 */
export function providerOperationalStatus(provider: ProviderHealthRow): string {
  const raw = provider.state ?? provider.status;
  return String(raw ?? "UNKNOWN").toUpperCase();
}

export function normalizeProviderEvidence(raw: unknown): ProviderHealthRow[] {
  if (Array.isArray(raw)) {
    return raw
      .filter(isRecord)
      .map((row) => ({ ...row }));
  }
  if (!isRecord(raw)) return [];

  return Object.entries(raw).flatMap(([provider, value]) => {
    if (!isRecord(value)) return [];
    const explicitProvider =
      typeof value.provider === "string" && value.provider.trim()
        ? value.provider.trim()
        : provider;
    return [{ ...value, provider: explicitProvider }];
  });
}

export function mergeProviderEvidence(
  registry: ProviderHealthRow[],
  rawEvidence: unknown,
): ProviderHealthRow[] {
  const evidence = normalizeProviderEvidence(rawEvidence);
  const evidenceByProvider = new Map<string, ProviderHealthRow>();
  for (const row of evidence) {
    const id = providerId(row);
    if (id) evidenceByProvider.set(id, row);
  }

  const registryIds = new Set<string>();
  const merged = registry.map((row) => {
    const id = providerId(row);
    if (id) registryIds.add(id);
    const observed = id ? evidenceByProvider.get(id) : undefined;
    const operationalState = observed?.state ?? "UNKNOWN";
    return {
      ...row,
      ...(observed ?? {}),
      registry_status: row.status ?? null,
      evidence_status: observed?.status ?? null,
      status: operationalState,
      state: operationalState,
    } satisfies ProviderHealthRow;
  });

  for (const row of evidence) {
    const id = providerId(row);
    if (!id || registryIds.has(id)) continue;
    const operationalState = row.state ?? "UNKNOWN";
    merged.push({
      ...row,
      configured: false,
      enabled: false,
      registry_status: null,
      evidence_status: row.status ?? null,
      status: operationalState,
      state: operationalState,
    });
  }

  return merged;
}

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
  // `providers` crosses a fetch/JSON boundary (see fetchPlatformHealth's unchecked
  // `as Promise<BackendHealthPayload>` cast) — an unexpected shape here must not
  // crash the root layout that renders this on every page. Fail closed to "no
  // data" rather than throwing on `.filter()`.
  if (!Array.isArray(providers)) {
    return { total: 0, configured: 0, enabled: 0, live: 0, degraded: 0, label: "Unavailable" };
  }
  const configured = providers.filter((provider) => provider.configured === true).length;
  const enabled = providers.filter((provider) => provider.enabled === true).length;
  const live = providers.filter((provider) =>
    provider.enabled === true && LIVE_PROVIDER_STATUSES.has(providerOperationalStatus(provider))
  ).length;
  const degraded = providers.filter((provider) =>
    provider.enabled === true && DEGRADED_PROVIDER_STATUSES.has(providerOperationalStatus(provider))
  ).length;
  const label =
    configured > 0 && enabled === configured && live === enabled && degraded === 0
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
