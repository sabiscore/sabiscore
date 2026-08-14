#!/usr/bin/env node
import { access, readFile } from "node:fs/promises";
import { randomUUID } from "node:crypto";
import Ajv2020 from "ajv/dist/2020.js";
import { defaultLeagues, manifestDir, processedDir, rawDir } from "./config.mjs";
import { sourceRegistry, validateSourceRegistry } from "./registry.mjs";
import { PublicHttpClient } from "./http.mjs";
import { FootballDataAdapter } from "./adapters/football-data.mjs";
import {
  ensureStorage,
  probeImmutableStorage,
  readFixture,
  writeManifest,
} from "./storage.mjs";

const command = process.argv[2] ?? "validate";

function summarizeResults(results) {
  const rawFiles = [];
  const processedFiles = [];
  const payloadHashes = {};
  let recordCount = 0;
  const errors = [];

  for (const result of results) {
    if (result.artifacts?.raw) rawFiles.push(result.artifacts.raw);
    if (result.artifacts?.fixtures) processedFiles.push(result.artifacts.fixtures);
    if (result.artifacts?.team_form) processedFiles.push(result.artifacts.team_form);
    Object.assign(payloadHashes, result.payload_hashes ?? {});
    recordCount += Number(result.fixtures ?? result.rows ?? 0);
    if (result.skipped) errors.push({ league: result.league, reason: result.reason });
  }

  return { rawFiles, processedFiles, payloadHashes, recordCount, errors };
}

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
    try {
      results.push(await adapter.scrapeLeague({
        league, leagueCode, seasonCode, fixtureText, runId, acquiredAt
      }));
    } catch (error) {
      results.push({
        source_id: source.id,
        league,
        season_code: seasonCode,
        skipped: true,
        validation_status: "FAILED",
        reason: error instanceof Error && error.message.startsWith("schema_drift_")
          ? error.message
          : "acquisition_failed",
        failure: {
          type: error instanceof Error ? error.name : "Error",
          retryable: false,
        },
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
  const payload = {
    ok: true,
    zero_paid_api: true,
    dynamic_scrapers_enabled: process.env.ENABLE_DYNAMIC_SCRAPERS === "true",
    user_agent_rotation: false,
    storage: { rawDir, processedDir, manifestDir },
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
  const result = await probeImmutableStorage();
  console.log(JSON.stringify(result, null, 2));
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
