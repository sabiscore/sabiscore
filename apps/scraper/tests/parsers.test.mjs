import test from "node:test";
import assert from "node:assert/strict";
import { buildTeamForm, normalizeFootballDataRows, parseCsv } from "../src/parsers.mjs";
import { parseRobotsAllow } from "../src/safety.mjs";
import * as safety from "../src/safety.mjs";
import { writeManifest } from "../src/storage.mjs";
import { sourceAllowlist } from "../src/config.mjs";
import { PublicHttpClient } from "../src/http.mjs";

test("parses football-data CSV and normalizes fixtures", () => {
  const csv = [
    "Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR,B365H,B365D,B365A",
    "16/08/2024,Man United,Fulham,1,0,H,1.65,4.20,5.50",
    "17/08/2024,Arsenal,Wolves,2,0,H,1.30,5.80,10.00"
  ].join("\n");

  const rows = parseCsv(csv);
  const fixtures = normalizeFootballDataRows(rows, "EPL");
  assert.equal(fixtures.length, 2);
  assert.equal(fixtures[0].home_team, "Man United");
  assert.equal(fixtures[0].market.bookmaker, "bet365");
  assert.equal(fixtures[0].market.raw_odds.home, 1.65);
  assert.ok(Math.abs(Object.values(fixtures[0].market.devigged_probabilities).reduce((a, b) => a + b, 0) - 1) < 1e-9);
});

test("builds rolling team form from normalized fixtures", () => {
  const fixtures = [
    { match_date: "2024-08-16", home_team: "A", away_team: "B", home_goals: 2, away_goals: 1 },
    { match_date: "2024-08-23", home_team: "C", away_team: "A", home_goals: 1, away_goals: 1 }
  ];
  const form = buildTeamForm(fixtures);
  const teamA = form.find((entry) => entry.team === "A");
  assert.equal(teamA.matches_sampled, 2);
  assert.equal(teamA.ppg, 2);
  assert.deepEqual([teamA.wins, teamA.draws, teamA.losses], [1, 1, 0]);
});

test("robots parser honors longest allow/disallow rule", () => {
  const robots = [
    "User-agent: *",
    "Disallow: /private",
    "Allow: /private/public"
  ].join("\n");
  assert.equal(parseRobotsAllow(robots, "/private/report"), false);
  assert.equal(parseRobotsAllow(robots, "/private/public/table"), true);
});

test("scraper does not expose user-agent rotation", () => {
  assert.equal("rotateUserAgent" in safety, false);
});

test("manifest writer creates immutable manifest files", async () => {
  const first = await writeManifest({ source_id: "test-source", command: "test", status: "SUCCESS" });
  const second = await writeManifest({ source_id: "test-source", command: "test", status: "SUCCESS" });
  assert.match(first, /data[\\/]+manifests[\\/]+node-scraper/);
  assert.match(second, /data[\\/]+manifests[\\/]+node-scraper/);
  assert.notEqual(first, second);
  assert.equal(first.endsWith(".manifest.json"), true);
});

test("source registry exposes policy controls", () => {
  assert.equal(sourceAllowlist.footballData.allowedDomains.includes("www.football-data.co.uk"), true);
  assert.equal(sourceAllowlist.footballData.concurrency, 1);
  assert.equal(sourceAllowlist.footballData.robotsPolicy, "enforce");
  assert.equal(Boolean(sourceAllowlist.footballData.killSwitchEnv), true);
});

test("never combines a partial bookmaker book with another bookmaker", () => {
  const csv = [
    "Date,HomeTeam,AwayTeam,FTHG,FTAG,B365H,B365D,B365A,PSH,PSD,PSA",
    "16/08/2024,A,B,1,0,2.00,,4.00,,3.50,4.20"
  ].join("\n");

  const [fixture] = normalizeFootballDataRows(parseCsv(csv), "EPL");

  assert.equal(fixture.market, null);
  assert.deepEqual(fixture.data_gaps, ["coherent_1x2_market_unavailable"]);
});

test("source registry covers exactly seven competitions", async () => {
  const { sourceRegistry } = await import("../src/registry.mjs");
  assert.deepEqual(Object.keys(sourceRegistry.competitions).sort(), [
    "BUNDESLIGA", "CHAMPIONSHIP", "EPL", "EREDIVISIE", "LA_LIGA", "LIGUE_1", "SERIE_A"
  ]);
});

test("Crawlee client enforces robots and disables blocked-response evasion", async () => {
  let observed;
  const client = new PublicHttpClient({
    crawlerFactory(options) {
      observed = options;
      return {
        async run() {
          await options.requestHandler({ body: Buffer.from("a,b\n1,2\n") });
        }
      };
    }
  });

  const body = await client.getText("https://www.football-data.co.uk/mmz4281/2526/E0.csv");

  assert.equal(body.includes("1,2"), true);
  assert.equal(observed.respectRobotsTxtFile, true);
  assert.equal(observed.retryOnBlocked, false);
  assert.equal(observed.useSessionPool, false);
  assert.equal(observed.maxConcurrency, 1);
  assert.equal(observed.maxRequestsPerCrawl, 1);
  assert.equal(typeof observed.errorHandler, "function");
});

test("fails closed when the provider schema drifts", () => {
  const csv = ["Date,HomeTeam,AwayTeam", "16/08/2024,A,B"].join("\n");
  assert.throws(
    () => normalizeFootballDataRows(parseCsv(csv), "EPL"),
    /schema_drift_missing_columns/,
  );
});
