#!/usr/bin/env node
import { access, readFile } from "node:fs/promises";
import { randomUUID } from "node:crypto";
import Ajv2020 from "ajv/dist/2020.js";
import { defaultLeagues, dlqDir, manifestDir, processedDir, rawDir } from "./config.mjs";
import { sourceRegistry, validateSourceRegistry } from "./registry.mjs";
import { PublicHttpClient } from "./http.mjs";
import { FootballDataAdapter } from "./adapters/football-data.mjs";
import {
  ensureStorage,
  getDlqMetrics,
  probeImmutableStorage,
  readFixture,
  storageFailureReport,
  summarizeResults,
  writeDlqRecord,
  writeManifest,
} from "./storage.mjs";

const command = process.argv[2] ?? "validate";

async function scrape({ adapterKind = "fixtures" } = {}) {
  await ensureStorage();
  const runId = randomUUID();
  const acquiredAt = new Date().toISOString();
  const source = sourceRegistry.sources.footballData;
  const client = new PublicHttpClient({
    minDelayMs: Number(process.env.SABISCORE_SCRAPER_DELAY_MS ?? source.sameDomainDelaySeconds * 1000),
    retries: source.maxRetries,
    maxRequestsPerMinute: source.maxRequestsPerMinute,
    timeoutMs: source.timeoutMs,
    respectRobots: true,
  });
  const adapter = new FootballDataAdapter(client);
  const seasonCode = process.env.SABISCORE_SEASON_CODE ?? "2425";
  const fixturePath = process.env.SABISCORE_SCRAPER_FIXTURE;
  const fixtureText = fixturePath ? await readFixture(fixturePath) : null;

  const selected = (process.env.SABISCORE_LEAGUES ?? Object.keys(defaultLeagues).join(","))
    .split(",")
    .map((league) => league.trim())
    .filter(Boolean);

  const results = [];
  for (const league of selected) {
    const leagueCode = defaultLeagues[league];
    if (!leagueCode) {
      results.push({ league, skipped: true, reason: "unsupported_league" });
      continue;
    }
    if (adapterKind !== "fixtures") {
      results.push({ league, skipped: true, reason: `${adapterKind}_adapter_disabled`, zero_paid_api: true });
      continue;
    }
    const firstAttemptAt = new Date().toISOString();
    try {
      results.push(await adapter.scrapeLeague({
        league, leagueCode, seasonCode, fixtureText, runId, acquiredAt
      }));
    } catch (error) {
      const lastAttemptAt = new Date().toISOString();
      const attemptCount = Number(error?.attempts ?? 1);
      const failureReason = error instanceof Error ? error.message : String(error);

      let dlqResult = null;
      try {
        dlqResult = await writeDlqRecord({
          originalQueue: `scraper:${source.id}:${league}`,
          failureReason,
          attemptCount,
          firstAttemptAt,
          lastAttemptAt,
          originalPayload: error?.rawPayload ?? fixtureText ?? null,
          reference: error?.rawArtifact?.uri ?? error?.rawArtifact?.file ?? null,
          sourceId: source.id,
          league,
          season: seasonCode,
          runId,
          errorDetails: error instanceof Error ? error.stack : String(error),
        });
      } catch (dlqError) {
        console.warn(JSON.stringify({ event: "dlq_route_failed", error: dlqError?.message }));
      }

      results.push({
        source_id: source.id,
        league,
        season_code: seasonCode,
        skipped: true,
        validation_status: "FAILED",
        reason: error instanceof Error && (error.message.startsWith("schema_drift_") || error.message.startsWith("poison_payload_"))
          ? error.message
          : "acquisition_failed",
        failure: {
          type: error instanceof Error ? error.name : "Error",
          retryable: false,
          // P10 DLQ enrichment: attempt_count comes from http.mjs's
          // failedRequestHandler when the failure was an HTTP crawl (absent —
          // defaults to 1 — for a non-HTTP failure, e.g. a parser/schema error).
          attempt_count: attemptCount,
          first_attempt_at: firstAttemptAt,
          last_attempt_at: lastAttemptAt,
        },
        ...(dlqResult ? { dlq: dlqResult.file, dlq_uri: dlqResult.uri } : {}),
      });
    }
  }

  const summary = summarizeResults(results);
  const manifestFile = await writeManifest({
    source_id: "football-data-csv",
    run_id: runId,
    adapter_version: source.parserVersion,
    schema_version: source.schemaVersion,
    registry_version: sourceRegistry.registryVersion,
    started_at: acquiredAt,
    status: summary.errors.length ? "PARTIAL" : "SUCCESS",
    command,
    sources: results,
    output_dir: processedDir,
    raw_files: summary.rawFiles,
    processed_files: summary.processedFiles,
    payload_hashes: summary.payloadHashes,
    record_count: summary.recordCount,
    errors: summary.errors,
    resource: summary.resource,
    attribution: "football-data.co.uk",
    licence: {
      source_policy: "public CSV; operator must review current terms before live use"
    },
    source_policy: adapter.source
  });
  console.log(JSON.stringify({ ok: true, manifest: manifestFile, results }, null, 2));
}

async function validate() {
  await ensureStorage();
  await access(processedDir);
  const schema = JSON.parse(
    await readFile(new URL("./source-registry.schema.json", import.meta.url), "utf8")
  );
  const ajv = new Ajv2020({ allErrors: true, strict: false });
  const schemaValid = ajv.validate(schema, sourceRegistry);
  const semantic = validateSourceRegistry(sourceRegistry);
  if (!schemaValid || !semantic.valid) {
    const errors = [
      ...(ajv.errors ?? []).map((error) => `${error.instancePath} ${error.message}`),
      ...semantic.errors,
    ];
    throw new Error(`source_registry_invalid: ${errors.join("; ")}`);
  }
  const manifestFile = await writeManifest({
    source_id: "node-scraper",
    status: "SUCCESS",
    command: "validate",
    sources: [],
    output_dir: processedDir,
    validation: {
      storage_ready: true,
      paid_api_dependencies: false,
      public_source_allowlist: true,
      source_registry_valid: true,
      source_registry_version: sourceRegistry.registryVersion,
      raw_dir: rawDir,
      processed_dir: processedDir,
      manifest_dir: manifestDir
    }
  });
  console.log(JSON.stringify({ ok: true, manifest: manifestFile }, null, 2));
}

async function doctor() {
  await ensureStorage();
  const dlqMetrics = await getDlqMetrics();
  const payload = {
    ok: true,
    zero_paid_api: true,
    dynamic_scrapers_enabled: process.env.ENABLE_DYNAMIC_SCRAPERS === "true",
    user_agent_rotation: false,
    storage: { rawDir, processedDir, manifestDir, dlqDir },
    dlq: dlqMetrics,
    source_registry: {
      version: sourceRegistry.registryVersion,
      valid: validateSourceRegistry(sourceRegistry).valid,
      competitions: Object.keys(sourceRegistry.competitions),
    },
  };
  const manifestFile = await writeManifest({
    source_id: "node-scraper",
    status: "SUCCESS",
    command: "doctor",
    record_count: 0,
    validation: payload,
  });
  console.log(JSON.stringify({ ...payload, manifest: manifestFile }, null, 2));
}

async function storageProbe() {
  try {
    const result = await probeImmutableStorage();
    console.log(JSON.stringify(result, null, 2));
  } catch (error) {
    console.error(JSON.stringify(storageFailureReport(error), null, 2));
    process.exitCode = 1;
  }
}

if (command === "storage:probe") {
  await storageProbe();
} else if (command === "scrape" || command === "scrape:fixtures") {
  await scrape({ adapterKind: "fixtures" });
} else if (command === "scrape:metrics") {
  await scrape({ adapterKind: "metrics" });
} else if (command === "scrape:results") {
  await scrape({ adapterKind: "results" });
} else if (command === "scrape:availability") {
  await scrape({ adapterKind: "availability" });
} else if (command === "scrape:markets") {
  await scrape({ adapterKind: "markets" });
} else if (command === "validate") {
  await validate();
} else if (command === "doctor") {
  await doctor();
} else {
  console.error(`Unknown command: ${command}`);
  process.exitCode = 1;
}
