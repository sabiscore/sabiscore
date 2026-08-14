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
