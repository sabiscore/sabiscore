import { readFileSync } from "node:fs";

const registryUrl = new URL("./source-registry.json", import.meta.url);
export const sourceRegistry = JSON.parse(readFileSync(registryUrl, "utf8"));

const canonicalCompetitionKeys = [
  "EPL",
  "LA_LIGA",
  "SERIE_A",
  "BUNDESLIGA",
  "LIGUE_1",
  "EREDIVISIE",
  "UCL",
];

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
  const competitionKeys = Object.keys(registry.competitions ?? {});
  if (competitionKeys.length !== 7) {
    errors.push("exactly seven canonical competitions are required");
  }
  const sortedActual = [...competitionKeys].sort();
  const sortedExpected = [...canonicalCompetitionKeys].sort();
  if (JSON.stringify(sortedActual) !== JSON.stringify(sortedExpected)) {
    errors.push(
      `competitions must match canonical set: ${sortedExpected.join(", ")}`,
    );
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
