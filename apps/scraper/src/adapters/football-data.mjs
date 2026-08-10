import { sourceAllowlist } from "../config.mjs";
import { parseCsv, normalizeFootballDataRows, buildTeamForm } from "../parsers.mjs";
import { writeJson, writeRaw } from "../storage.mjs";

export class FootballDataAdapter {
  constructor(client) {
    this.client = client;
    this.source = sourceAllowlist.footballData;
  }

  _runtimeEnvironment() {
    return String(
      process.env.SABISCORE_ENV
      ?? process.env.APP_ENV
      ?? process.env.NODE_ENV
      ?? "development"
    ).toLowerCase();
  }

  _skipResult(league, seasonCode, reason) {
    return {
      source_id: this.source.id,
      league,
      season_code: seasonCode,
      rows: 0,
      fixtures: 0,
      skipped: true,
      reason,
    };
  }

  _enforceSourcePolicy(league, seasonCode) {
    const runtimeEnv = this._runtimeEnvironment();

    if (this.source.enabled !== true) {
      return this._skipResult(league, seasonCode, "source_disabled");
    }

    const supportedEnvironments = Array.isArray(this.source.supportedEnvironments)
      ? this.source.supportedEnvironments
      : [];
    if (
      supportedEnvironments.length > 0
      && !supportedEnvironments.map((env) => String(env).toLowerCase()).includes(runtimeEnv)
    ) {
      return this._skipResult(league, seasonCode, "source_environment_not_supported");
    }

    if (runtimeEnv === "production") {
      const activation = String(this.source.productionActivation ?? "").toLowerCase();
      if (activation !== "approved") {
        return this._skipResult(league, seasonCode, "source_production_activation_required");
      }

      const termsReviewStatus = String(this.source.termsReviewStatus ?? "").toLowerCase();
      if (!termsReviewStatus.startsWith("reviewed_")) {
        return this._skipResult(league, seasonCode, "source_terms_not_reviewed");
      }
    }

    return null;
  }

  buildUrl(seasonCode, leagueCode) {
    return `${this.source.baseUrl}/mmz4281/${seasonCode}/${leagueCode}.csv`;
  }

  async scrapeLeague({ league, leagueCode, seasonCode = "2425", fixtureText = null, runId, acquiredAt }) {
    const blockedByPolicy = this._enforceSourcePolicy(league, seasonCode);
    if (blockedByPolicy) {
      return blockedByPolicy;
    }

    if (process.env[this.source.killSwitchEnv] === "true") {
      return this._skipResult(league, seasonCode, "source_kill_switch_enabled");
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
