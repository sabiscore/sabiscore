import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { UpcomingMatchesPanel } from "./upcoming-matches-panel";

const LEAGUES = [
  { id: "EPL", name: "Premier League", coverage: "FULL", low_evidence_allowed: false, caveat_text: null },
  { id: "LA_LIGA", name: "La Liga", coverage: "FULL", low_evidence_allowed: false, caveat_text: null },
  {
    id: "UCL",
    name: "UEFA Champions League",
    coverage: "SOFT",
    low_evidence_allowed: true,
    caveat_text: "Soft coverage — higher epistemic uncertainty",
  },
];

function fixtures(count: number) {
  return Array.from({ length: count }, (_, index) => ({
    match_id: `fixture-${index + 1}`,
    home_team: `Home ${index + 1}`,
    away_team: `Away ${index + 1}`,
    league: index % 2 === 0 ? "EPL" : "LA_LIGA",
    match_date: `2026-08-${String(15 + Math.floor(index / 8)).padStart(2, "0")}T15:00:00Z`,
    status: "scheduled",
    predictions: null,
    odds: null,
    value_bets: [],
    has_value: false,
    best_value_bet: null,
    data_quality: null,
    data_gaps: [],
    staleness_seconds: 0,
    source: "postgres",
  }));
}

function upcomingResponse(count: number) {
  return {
    upcoming_matches: fixtures(count),
    total: count,
    matches_with_value: 0,
    avg_edge_pct: 0,
    cache_hit: false,
    ttl_seconds: 300,
    source: "postgres",
    offseason: false,
    next_season_start: null,
    next_season_start_estimated: null,
    data_gap: false,
    unavailable_reasons: [],
    generated_at: "2026-08-14T00:00:00Z",
  };
}

function renderPanel(props: { league?: string } = {}) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return render(
    <QueryClientProvider client={client}>
      <UpcomingMatchesPanel {...props} />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  sessionStorage.clear();
});

describe("UpcomingMatchesPanel fixture reachability", () => {
  it("expands all 24 fixtures, collapses, and resets when the league changes", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string | URL | Request) => {
        const url = String(input);
        return new Response(
          JSON.stringify(url.startsWith("/api/leagues") ? LEAGUES : upcomingResponse(24)),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }),
    );

    renderPanel();

    await waitFor(() => expect(screen.getAllByRole("link")).toHaveLength(12));
    const expand = screen.getByRole("button", { name: "Show all 24" });
    expect(expand).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(expand);

    expect(screen.getAllByRole("link")).toHaveLength(24);
    expect(screen.getByText("Showing 24 of 24 fixtures")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Show first 12" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );

    fireEvent.click(screen.getByRole("button", { name: /^La Liga \(LA_LIGA\)$/ }));
    await waitFor(() => expect(screen.getAllByRole("link")).toHaveLength(12));
    expect(screen.getByRole("button", { name: "Show all 24" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
  });

  it("puts soft coverage in the UCL accessible name and shows a touch-visible legend", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string | URL | Request) => {
        const url = String(input);
        return new Response(
          JSON.stringify(url.startsWith("/api/leagues") ? LEAGUES : upcomingResponse(1)),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }),
    );

    renderPanel();

    expect(
      await screen.findByRole("button", {
        name: /UEFA Champions League \(UCL\).*Soft coverage.*higher epistemic uncertainty/i,
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Soft coverage — higher uncertainty while provider evidence is limited/i),
    ).toBeInTheDocument();
  });

  it("uses estimated-date wording for an empty UCL fixture response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(
          JSON.stringify({
            ...upcomingResponse(0),
            offseason: true,
            next_season_start: "2026-09-15",
            next_season_start_estimated: true,
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        )),
    );

    renderPanel({ league: "UCL" });

    expect(await screen.findByText("UEFA Champions League — Off Season")).toBeInTheDocument();
    expect(screen.getByText("UCL")).toBeInTheDocument();
    expect(screen.getByText(/Season currently expected around/i)).toBeInTheDocument();
    expect(screen.getByText(/Date not yet confirmed by the provider/i)).toBeInTheDocument();
  });
});

// ─── C9: per-league offseason detection ──────────────────────────────────────
// When a specific league chip is selected and the global offseason flag is
// false (other leagues are live), but the per-league /api/offseason query
// returns OFF_SEASON, the panel should render LeagueOffseasonNotice instead
// of the generic "No upcoming fixtures" message.
//
// Tests use a multi-route fetch mock that handles:
//   /api/leagues          → league list
//   /api/upcoming         → match response (0 fixtures, offseason: false)
//   /api/offseason/{id}   → per-league offseason response

function offseasonStatusResponse(
  league: string,
  seasonStatus: "OFF_SEASON" | "IN_SEASON" | "UNKNOWN",
  nextSeasonStart: string | null = "2026-08-28",
) {
  return {
    league,
    league_slug: league.toLowerCase(),
    season_status: seasonStatus,
    current_season_label: null,
    current_season_end: null,
    next_season_start: nextSeasonStart,
    next_season_start_estimated: false,
    days_until_next_season: 13,
    data_availability: {
      historical_data: true,
      live_odds: false,
      live_standings: false,
      live_form: false,
      pi_ratings: false,
      berrar_ratings: false,
      market_drift: false,
      match_context: false,
    },
    prediction_advisory: "Season not started.",
    queried_at: new Date().toISOString(),
  };
}

function makeMultiRouteFetch(seasonStatus: "OFF_SEASON" | "IN_SEASON" | "UNKNOWN") {
  return vi.fn(async (input: string | URL | Request) => {
    const url = String(input);
    if (url.startsWith("/api/leagues")) {
      return new Response(JSON.stringify(LEAGUES), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }
    if (url.startsWith("/api/offseason/")) {
      const league = decodeURIComponent(url.split("/api/offseason/")[1]);
      return new Response(JSON.stringify(offseasonStatusResponse(league, seasonStatus)), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }
    // All other routes → 0 fixtures, global offseason: false
    return new Response(JSON.stringify(upcomingResponse(0)), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  });
}

describe("C9 — per-league offseason detection in UpcomingMatchesPanel", () => {
  it("shows LeagueOffseasonNotice when league chip selected + 0 fixtures + per-league OFF_SEASON", async () => {
    vi.stubGlobal("fetch", makeMultiRouteFetch("OFF_SEASON"));

    renderPanel();

    // Click the Bundesliga chip (a league that hasn't started yet)
    const chip = await screen.findByRole("button", { name: /Bundesliga/i });
    fireEvent.click(chip);

    expect(await screen.findByText("Bundesliga — Off Season")).toBeInTheDocument();
    expect(screen.queryByText(/No upcoming fixtures in the next/i)).not.toBeInTheDocument();
  });

  it("shows generic message when league chip selected + 0 fixtures + per-league IN_SEASON", async () => {
    vi.stubGlobal("fetch", makeMultiRouteFetch("IN_SEASON"));

    renderPanel();

    const chip = await screen.findByRole("button", { name: /Bundesliga/i });
    fireEvent.click(chip);

    expect(await screen.findByText(/No upcoming fixtures in the next 14 days/i)).toBeInTheDocument();
    expect(screen.queryByText("Bundesliga — Off Season")).not.toBeInTheDocument();
  });

  it("does not crash while per-league offseason query is loading", async () => {
    // Mock returns the leagues list immediately but offseason endpoint hangs.
    // The panel must render without errors while awaiting the offseason response.
    let resolveOffseason!: (v: Response) => void;
    const offseasonPending = new Promise<Response>((r) => { resolveOffseason = r; });

    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string | URL | Request) => {
        const url = String(input);
        if (url.startsWith("/api/leagues")) {
          return new Response(JSON.stringify(LEAGUES), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }
        if (url.startsWith("/api/offseason/")) return offseasonPending;
        return new Response(JSON.stringify(upcomingResponse(0)), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }),
    );

    renderPanel();

    const chip = await screen.findByRole("button", { name: /Bundesliga/i });
    fireEvent.click(chip);

    // Should render the generic message (offseason query not yet resolved)
    await waitFor(() =>
      expect(screen.getByText(/No upcoming fixtures in the next 14 days/i)).toBeInTheDocument()
    );

    // Resolve to avoid act() warnings
    resolveOffseason(
      new Response(
        JSON.stringify(offseasonStatusResponse("BUNDESLIGA", "OFF_SEASON")),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
  });

  it("does NOT call the offseason endpoint when ALL leagues are shown (no chip selected)", async () => {
    const fetchMock = makeMultiRouteFetch("OFF_SEASON");
    vi.stubGlobal("fetch", fetchMock);

    renderPanel();

    // Wait for fixture list to load (no chip selected)
    await waitFor(() => {
      expect(screen.getByText(/No upcoming fixtures in the next 14 days/i)).toBeInTheDocument();
    });

    const offseasonCalls = (fetchMock.mock.calls as [string | URL | Request][])
      .map(([url]) => String(url))
      .filter((url) => url.startsWith("/api/offseason/"));

    expect(offseasonCalls).toHaveLength(0);
  });
});
