import { sourceAllowlist } from "../config.mjs";
import { parseCsv, normalizeFootballDataRows, buildTeamForm } from "../parsers.mjs";
import { writeJson, writeRaw } from "../storage.mjs";

export class FootballDataAdapter {
  constructor(client) {
    this.client = client;
    this.source = sourceAllowlist.footballData;
  }

  buildUrl(seasonCode, leagueCode) {
    return `${this.source.baseUrl}/mmz4281/${seasonCode}/${leagueCode}.csv`;
  }

  async scrapeLeague({ league, leagueCode, seasonCode = "2425", fixtureText = null, runId, acquiredAt }) {
    if (process.env[this.source.killSwitchEnv] === "true") {
      return {
        source_id: this.source.id,
        league,
        season_code: seasonCode,
        rows: 0,
        fixtures: 0,
        skipped: true,
        reason: "source_kill_switch_enabled",
      };
    }
    const url = this.buildUrl(seasonCode, leagueCode);
    const raw = fixtureText ?? await this.client.getText(url);
    const artifactContext = {
      sourceId: this.source.id,
      league,
      season: seasonCode,
      runId,
      acquiredAt,
    };
    const rawArtifact = await writeRaw(
      `football-data-${league}-${seasonCode}.csv`, raw, artifactContext
    );

    const rows = parseCsv(raw);
    const fixtures = normalizeFootballDataRows(rows, league);
    const teamForm = buildTeamForm(fixtures);

    const fixturesArtifact = await writeJson(
      "fixtures", `${league}-${seasonCode}`, fixtures, artifactContext
    );
    const formArtifact = await writeJson(
      "team-form", `${league}-${seasonCode}`, teamForm, artifactContext
    );
    return {
      source_id: this.source.id,
      url,
      league,
      season_code: seasonCode,
      rows: rows.length,
      fixtures: fixtures.length,
      artifacts: {
        raw: rawArtifact,
        fixtures: fixturesArtifact,
        team_form: formArtifact,
      },
      payload_hashes: {
        [rawArtifact.uri]: rawArtifact.hash,
        [fixturesArtifact.uri]: fixturesArtifact.hash,
        [formArtifact.uri]: formArtifact.hash,
      },
      acquired_at: acquiredAt,
      parser_version: this.source.parserVersion,
      schema_version: this.source.schemaVersion,
    };
  }
}
