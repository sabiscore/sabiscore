import test from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  canonicalFixtureId,
  canonicalFixtureKey,
  canonicalTeamKey,
  isCorruptOrMojibake,
  normalizeFootballDataRows,
  parseCsv,
} from "../src/parsers.mjs";
import { calculateBackoffMs, PublicHttpClient } from "../src/http.mjs";
import { getDlqMetrics, writeDlqRecord } from "../src/storage.mjs";
import { dlqDir } from "../src/config.mjs";

test("canonical business identity uses competition, season, and participants (not kickoff timestamps)", () => {
  const original = {
    competition: "EPL",
    season: "2425",
    homeTeam: "Arsenal FC",
    awayTeam: "Chelsea",
  };

  const originalKey = canonicalFixtureKey(original);
  const originalId = canonicalFixtureId(original);

  assert.equal(originalKey, "EPL:2425:arsenal fc:vs:chelsea");
  assert.ok(originalId.startsWith("cfx-"));

  // Same participants and season with different casing or diacritics produce identical canonical identity
  const normalizedMatch = {
    competition: "epl",
    season: "2425",
    homeTeam: "ARSENAL fc",
    awayTeam: "  chelsea  ",
  };
  assert.equal(canonicalFixtureKey(normalizedMatch), originalKey);
  assert.equal(canonicalFixtureId(normalizedMatch), originalId);

  // Different competition, season, or teams produce different canonical IDs
  const diffSeason = { ...original, season: "2526" };
  assert.notEqual(canonicalFixtureId(diffSeason), originalId);

  const diffHome = { ...original, homeTeam: "Liverpool" };
  assert.notEqual(canonicalFixtureId(diffHome), originalId);

  const diffComp = { ...original, competition: "CHAMPIONSHIP" };
  assert.notEqual(canonicalFixtureId(diffComp), originalId);
});

test("idempotency is proven: match rescheduling preserves canonical business identity and source_native_id", () => {
  // Scenario: Match originally scheduled for 16/08/2024 at 15:00
  const initialCsv = [
    "Date,HomeTeam,AwayTeam,FTHG,FTAG",
    "16/08/2024,Arsenal,Wolves,2,0",
  ].join("\n");

  // Scenario: Same match rescheduled to 22/08/2024 at 20:00
  const rescheduledCsv = [
    "Date,HomeTeam,AwayTeam,FTHG,FTAG,Time",
    "22/08/2024,Arsenal,Wolves,2,0,20:00",
  ].join("\n");

  const [initialFixture] = normalizeFootballDataRows(parseCsv(initialCsv), "EPL", { season: "2425" });
  const [rescheduledFixture] = normalizeFootballDataRows(parseCsv(rescheduledCsv), "EPL", { season: "2425" });

  // Timestamps differ
  assert.notEqual(initialFixture.match_date, rescheduledFixture.match_date);
  assert.notEqual(initialFixture.match_time, rescheduledFixture.match_time);

  // Canonical business identity and source_native_id are strictly identical
  assert.equal(initialFixture.source_native_id, rescheduledFixture.source_native_id);
  assert.equal(initialFixture.canonical_fixture_id, rescheduledFixture.canonical_fixture_id);
  assert.equal(initialFixture.canonical_fixture_key, rescheduledFixture.canonical_fixture_key);
  assert.equal(initialFixture.canonical_fixture_key, "EPL:2425:arsenal:vs:wolves");
});

test("poison data fails closed: corrupt or mojibake entity names are rejected", () => {
  assert.equal(isCorruptOrMojibake("Arsenal"), false);
  assert.equal(isCorruptOrMojibake("Atlético Madrid"), false);
  assert.equal(isCorruptOrMojibake("Bayern München"), false);

  // Corrupt/mojibake indicators
  assert.equal(isCorruptOrMojibake(""), true);
  assert.equal(isCorruptOrMojibake("   "), true);
  assert.equal(isCorruptOrMojibake(null), true);
  assert.equal(isCorruptOrMojibake("Atl\uFFFDtico"), true); // Unicode replacement char
  assert.equal(isCorruptOrMojibake("Bad\x00Team"), true); // Control char
  assert.equal(isCorruptOrMojibake("AtlÃ©tico"), true); // Double-encoded UTF-8 mojibake

  const poisonCsv = [
    "Date,HomeTeam,AwayTeam,FTHG,FTAG",
    "16/08/2024,Atl\uFFFDtico,Real Madrid,1,1",
  ].join("\n");

  assert.throws(
    () => normalizeFootballDataRows(parseCsv(poisonCsv), "LA_LIGA"),
    /poison_payload_corrupt_entity:home_team=/,
  );
});

test("DLQ writer creates structured dead letter record with required metadata", async () => {
  const firstAttemptAt = new Date(Date.now() - 5000).toISOString();
  const lastAttemptAt = new Date().toISOString();
  const poisonPayload = "Date,HomeTeam,AwayTeam\n16/08/2024,Broken";

  const result = await writeDlqRecord({
    originalQueue: "scraper:football-data:EPL",
    failureReason: "schema_drift_missing_columns:FTHG|FTAG",
    attemptCount: 3,
    firstAttemptAt,
    lastAttemptAt,
    originalPayload: poisonPayload,
    reference: "data/raw/node-scraper/broken.csv",
    sourceId: "football-data-test",
    league: "EPL",
    season: "2425",
    runId: "test-run-dlq",
    errorDetails: "Error: missing columns at normalizeFootballDataRows",
  });

  try {
    assert.ok(result.file.endsWith(".dlq.json"));
    assert.equal(result.record.originalQueue, "scraper:football-data:EPL");
    assert.equal(result.record.failureReason, "schema_drift_missing_columns:FTHG|FTAG");
    assert.equal(result.record.attemptCount, 3);
    assert.equal(result.record.firstAttemptAt, firstAttemptAt);
    assert.equal(result.record.lastAttemptAt, lastAttemptAt);
    assert.equal(result.record.originalPayload, poisonPayload);
    assert.equal(result.record.reference, "data/raw/node-scraper/broken.csv");
    assert.equal(result.record.metadata.sourceId, "football-data-test");
    assert.equal(result.record.metadata.league, "EPL");
    assert.equal(result.record.metadata.season, "2425");
    assert.equal(result.record.metadata.runId, "test-run-dlq");
  } finally {
    await rm(result.file, { force: true });
  }
});

test("DLQ metrics accurately monitors DLQ depth and age", async () => {
  const tempDir = await mkdtemp(join(tmpdir(), "sabiscore-dlq-test-"));
  try {
    const emptyMetrics = await getDlqMetrics({ dir: tempDir });
    assert.equal(emptyMetrics.depth, 0);
    assert.equal(emptyMetrics.oldestEnqueuedAt, null);

    // Write a dummy record
    const { writeFile } = await import("node:fs/promises");
    await writeFile(join(tempDir, "item-1.dlq.json"), "{}", "utf8");
    await writeFile(join(tempDir, "item-2.dlq.json"), "{}", "utf8");

    const metrics = await getDlqMetrics({ dir: tempDir });
    assert.equal(metrics.depth, 2);
    assert.ok(metrics.oldestEnqueuedAt !== null);
    assert.ok(metrics.newestEnqueuedAt !== null);
  } finally {
    await rm(tempDir, { recursive: true, force: true });
  }
});

test("calculateBackoffMs provides capped exponential backoff with bounded additive jitter", () => {
  // Deterministic randomFn = 0 (minimum jitter)
  const minRandom = () => 0;
  assert.equal(calculateBackoffMs(0, { baseMs: 250, maxMs: 2000, maxJitterMs: 250, randomFn: minRandom }), 250);
  assert.equal(calculateBackoffMs(1, { baseMs: 250, maxMs: 2000, maxJitterMs: 250, randomFn: minRandom }), 500);
  assert.equal(calculateBackoffMs(2, { baseMs: 250, maxMs: 2000, maxJitterMs: 250, randomFn: minRandom }), 1000);
  assert.equal(calculateBackoffMs(3, { baseMs: 250, maxMs: 2000, maxJitterMs: 250, randomFn: minRandom }), 2000); // capped at 2000
  assert.equal(calculateBackoffMs(10, { baseMs: 250, maxMs: 2000, maxJitterMs: 250, randomFn: minRandom }), 2000); // capped

  // Deterministic randomFn = 1 (maximum jitter = 250ms)
  const maxRandom = () => 1;
  assert.equal(calculateBackoffMs(0, { baseMs: 250, maxMs: 2000, maxJitterMs: 250, randomFn: maxRandom }), 500); // 250 + 250
  assert.equal(calculateBackoffMs(1, { baseMs: 250, maxMs: 2000, maxJitterMs: 250, randomFn: maxRandom }), 750); // 500 + 250
  assert.equal(calculateBackoffMs(3, { baseMs: 250, maxMs: 2000, maxJitterMs: 250, randomFn: maxRandom }), 2250); // 2000 + 250
  assert.equal(calculateBackoffMs(10, { baseMs: 250, maxMs: 2000, maxJitterMs: 250, randomFn: maxRandom }), 2250); // 2000 + 250

  // Random output stays within [capped, capped + maxJitterMs]
  for (let i = 0; i < 50; i++) {
    const delay = calculateBackoffMs(1, { baseMs: 250, maxMs: 2000, maxJitterMs: 250 });
    assert.ok(delay >= 500 && delay <= 750, `Expected delay between 500 and 750, got ${delay}`);
  }
});

test("PublicHttpClient retries transient errors with backoff and reports machine attempt count", async () => {
  const sleptDelays = [];
  let observedOptions;
  const client = new PublicHttpClient({
    retries: 2,
    crawlerFactory(options) {
      observedOptions = options;
      return {
        async run() {
          // Simulate two failures then exhaustion
          await options.errorHandler({ request: { retryCount: 0 } });
          await options.errorHandler({ request: { retryCount: 1 } });
          const terminalErr = new Error("Gateway Timeout (504)");
          terminalErr.name = "TimeoutError";
          await options.failedRequestHandler(
            { request: { url: "https://www.football-data.co.uk/mmz4281/2425/E0.csv", retryCount: 2 } },
            terminalErr,
          );
        },
      };
    },
    backoffOptions: { baseMs: 100, maxMs: 1000, maxJitterMs: 0 },
    async sleepFn(delayMs, retryCount) {
      sleptDelays.push({ delayMs, retryCount });
    },
  });

  await assert.rejects(
    client.getText("https://www.football-data.co.uk/mmz4281/2425/E0.csv"),
    (err) => {
      assert.equal(err.attempts, 3);
      assert.match(err.message, /crawl_failed/);
      assert.match(err.message, /attempts=3/);
      return true;
    },
  );

  assert.deepEqual(sleptDelays, [
    { delayMs: 100, retryCount: 0 },
    { delayMs: 200, retryCount: 1 },
  ]);
  assert.ok(observedOptions.additionalHttpErrorStatusCodes.includes(429));
  assert.ok(observedOptions.additionalHttpErrorStatusCodes.includes(504));
});

test("FootballDataAdapter attaches raw payload on failure enabling DLQ capture of poison data", async () => {
  const { FootballDataAdapter } = await import("../src/adapters/football-data.mjs");
  const adapter = new FootballDataAdapter({
    async getText() {
      return "Date,HomeTeam,AwayTeam\n16/08/2024,A,B"; // missing FTHG, FTAG -> schema drift
    },
  });

  const firstAttemptAt = new Date().toISOString();
  let caughtError = null;
  try {
    await adapter.scrapeLeague({
      league: "EPL",
      leagueCode: "E0",
      seasonCode: "2425",
      runId: "dlq-test-run",
      acquiredAt: firstAttemptAt,
    });
  } catch (error) {
    caughtError = error;
  }

  assert.ok(caughtError !== null);
  assert.match(caughtError.message, /schema_drift_missing_columns/);
  assert.equal(caughtError.rawPayload, "Date,HomeTeam,AwayTeam\n16/08/2024,A,B");
  assert.ok(caughtError.rawArtifact !== null);

  // Route caught poison data to DLQ
  const dlq = await writeDlqRecord({
    originalQueue: "scraper:footballData:EPL",
    failureReason: caughtError.message,
    attemptCount: 1,
    firstAttemptAt,
    lastAttemptAt: new Date().toISOString(),
    originalPayload: caughtError.rawPayload,
    reference: caughtError.rawArtifact.file,
    sourceId: "footballData",
    league: "EPL",
    season: "2425",
    runId: "dlq-test-run",
  });

  try {
    assert.equal(dlq.record.originalQueue, "scraper:footballData:EPL");
    assert.equal(dlq.record.failureReason, caughtError.message);
    assert.equal(dlq.record.originalPayload, "Date,HomeTeam,AwayTeam\n16/08/2024,A,B");
    assert.equal(dlq.record.reference, caughtError.rawArtifact.file);
  } finally {
    await rm(dlq.file, { force: true });
    await rm(caughtError.rawArtifact.file, { force: true });
  }
});
