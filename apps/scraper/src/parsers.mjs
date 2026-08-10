export function parseCsv(text) {
  const rows = [];
  const lines = text.trim().split(/\r?\n/);
  if (lines.length === 0) return rows;
  const headers = splitCsvLine(lines[0]);
  for (const line of lines.slice(1)) {
    if (!line.trim()) continue;
    const cells = splitCsvLine(line);
    const row = {};
    headers.forEach((header, index) => {
      row[header] = cells[index] ?? "";
    });
    rows.push(row);
  }
  return rows;
}

function splitCsvLine(line) {
  const values = [];
  let current = "";
  let quoted = false;
  for (let index = 0; index < line.length; index += 1) {
    const char = line[index];
    if (char === '"' && line[index + 1] === '"') {
      current += '"';
      index += 1;
    } else if (char === '"') {
      quoted = !quoted;
    } else if (char === "," && !quoted) {
      values.push(current);
      current = "";
    } else {
      current += char;
    }
  }
  values.push(current);
  return values;
}

export function normalizeFootballDataRows(rows, league) {
  if (rows.length > 0) {
    const required = ["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG"];
    const missing = required.filter((field) => !(field in rows[0]));
    if (missing.length > 0) {
      throw new Error(`schema_drift_missing_columns:${missing.join("|")}`);
    }
  }
  const sourceTimezones = {
    EPL: "Europe/London",
    CHAMPIONSHIP: "Europe/London",
    LA_LIGA: "Europe/Madrid",
    SERIE_A: "Europe/Rome",
    BUNDESLIGA: "Europe/Berlin",
    LIGUE_1: "Europe/Paris",
    EREDIVISIE: "Europe/Amsterdam",
  };
  return rows
    .filter((row) => row.Date && row.HomeTeam && row.AwayTeam)
    .map((row, sourceRowIndex) => {
      const market = coherentBook(row);
      return {
        source: "football-data-csv",
        source_native_id: null,
        source_row_index: sourceRowIndex + 2,
        league,
        match_date: row.Date,
        match_time: row.Time || null,
        source_timezone: sourceTimezones[league] ?? null,
        home_team: row.HomeTeam,
        away_team: row.AwayTeam,
        home_goals: numberOrNull(row.FTHG),
        away_goals: numberOrNull(row.FTAG),
        full_time_result: row.FTR || null,
        market,
        data_gaps: market ? [] : ["coherent_1x2_market_unavailable"],
      };
    });
}

function coherentBook(row) {
  const candidates = [
    ["bet365", "B365H", "B365D", "B365A"],
    ["pinnacle", "PSH", "PSD", "PSA"],
  ];
  for (const [bookmaker, homeKey, drawKey, awayKey] of candidates) {
    const rawOdds = {
      home: numberOrNull(row[homeKey]),
      draw: numberOrNull(row[drawKey]),
      away: numberOrNull(row[awayKey]),
    };
    if (Object.values(rawOdds).every((value) => value !== null && value > 1)) {
      const inverse = Object.fromEntries(
        Object.entries(rawOdds).map(([outcome, odds]) => [outcome, 1 / odds])
      );
      const overround = inverse.home + inverse.draw + inverse.away;
      return {
        bookmaker,
        market_type: "1X2",
        coherent: true,
        raw_odds: rawOdds,
        overround,
        devigged_probabilities: {
          home: inverse.home / overround,
          draw: inverse.draw / overround,
          away: inverse.away / overround,
        },
      };
    }
  }
  return null;
}

export function buildTeamForm(fixtures, windowSize = 10) {
  const teams = new Map();
  for (const match of fixtures) {
    addTeamMatch(teams, match.home_team, {
      date: match.match_date,
      opponent: match.away_team,
      home_or_away: "home",
      goals_for: match.home_goals,
      goals_against: match.away_goals,
      result: resultFor(match.home_goals, match.away_goals)
    });
    addTeamMatch(teams, match.away_team, {
      date: match.match_date,
      opponent: match.home_team,
      home_or_away: "away",
      goals_for: match.away_goals,
      goals_against: match.home_goals,
      result: resultFor(match.away_goals, match.home_goals)
    });
  }

  return [...teams.entries()].map(([team, matches]) => {
    const recent = matches.slice(-windowSize);
    const points = recent.reduce((sum, match) => sum + pointsFor(match.result), 0);
    const goalsFor = recent.reduce((sum, match) => sum + (match.goals_for ?? 0), 0);
    const goalsAgainst = recent.reduce((sum, match) => sum + (match.goals_against ?? 0), 0);
    const wins = recent.filter((match) => match.result === "W").length;
    const draws = recent.filter((match) => match.result === "D").length;
    const losses = recent.filter((match) => match.result === "L").length;
    return {
      team,
      matches_sampled: recent.length,
      ppg: recent.length ? points / recent.length : null,
      wins,
      draws,
      losses,
      goals_for_avg: recent.length ? goalsFor / recent.length : null,
      goals_against_avg: recent.length ? goalsAgainst / recent.length : null,
      goal_difference_avg: recent.length ? (goalsFor - goalsAgainst) / recent.length : null,
      latest_match_date: recent.at(-1)?.date ?? null,
      recent
    };
  });
}

function addTeamMatch(teams, team, match) {
  if (!teams.has(team)) teams.set(team, []);
  teams.get(team).push(match);
}

function resultFor(goalsFor, goalsAgainst) {
  if (goalsFor === null || goalsAgainst === null) return null;
  if (goalsFor > goalsAgainst) return "W";
  if (goalsFor < goalsAgainst) return "L";
  return "D";
}

function pointsFor(result) {
  if (result === "W") return 3;
  if (result === "D") return 1;
  return 0;
}

function numberOrNull(value) {
  if (value === null || value === undefined || String(value).trim() === "") return null;
  const num = Number(value);
  return Number.isFinite(num) ? num : null;
}
