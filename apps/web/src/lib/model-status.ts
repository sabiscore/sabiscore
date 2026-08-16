export const MODEL_STATUS_QUERY_KEY = ["model-status"] as const;

export type ModelRecord = {
  feature_schema_version?: unknown;
  feature_count?: unknown;
  served_head?: unknown;
  artifact?: unknown;
  artifact_sha256?: unknown;
  required?: unknown;
  loaded?: unknown;
};

export type ModelStatus = {
  active_version?: unknown;
  generation?: unknown;
  generation_hash?: unknown;
  certification_state?: unknown;
  promotion_state?: unknown;
  validation_status?: unknown;
  manifest_valid?: unknown;
  models_loaded?: unknown;
  stake_permitted?: unknown;
  models?: Record<string, ModelRecord>;
};

export async function fetchModelStatus(): Promise<ModelStatus> {
  const response = await fetch("/api/models/status", { cache: "no-store" });
  if (!response.ok) throw new Error("Model status unavailable");
  return response.json() as Promise<ModelStatus>;
}

export function displayModelVersion(status: ModelStatus | null | undefined): string {
  if (!status?.active_version) return "Unavailable";
  return String(status.active_version);
}

export function displayCertification(status: ModelStatus | null | undefined): string {
  if (!status?.certification_state) return "Unavailable";
  return String(status.certification_state);
}
