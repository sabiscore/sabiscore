import { readFileSync } from "node:fs";

const registryUrl = new URL("./source-registry.json", import.meta.url);
export const sourceRegistry = JSON.parse(readFileSync(registryUrl, "utf8"));

const requiredFields = [
  "id", "baseUrl", "type", "enabled", "transport", "purpose",
  "allowedDomains", "allowedUrlPatterns", "collectedFields", "termsReviewStatus",
  "robotsPolicy", "attribution", "cadence", "freshnessExpectationSeconds",
  "concurrency", "maxRequestsPerMinute", "sameDomainDelaySeconds", "timeoutMs",
  "maxRetries", "parserVersion", "schemaVersion", "supportedEnvironments",
  "productionActivation", "owner", "killSwitchEnv"
];

export function validateSourceRegistry(registry = sourceRegistry) {
  const errors = [];
  if (!String(registry.registryVersion ?? "").startsWith("2.")) {
    errors.push("registryVersion must be 2.x");
  }
  if (Object.keys(registry.competitions ?? {}).length !== 7) {
    errors.push("exactly seven canonical competitions are required");
  }
  for (const [name, source] of Object.entries(registry.sources ?? {})) {
    for (const field of requiredFields) {
      if (!(field in source)) errors.push(`${name}.${field} is required`);
    }
    if (!String(source.baseUrl ?? "").startsWith("https://")) {
      errors.push(`${name}.baseUrl must use HTTPS`);
    }
    if (Number(source.concurrency) < 1 || Number(source.concurrency) > 2) {
      errors.push(`${name}.concurrency must be between 1 and 2`);
    }
  }
  return { valid: errors.length === 0, errors };
}
