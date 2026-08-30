import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { PerformancePageClient } from "./performance-page-client";

// recharts measures its container and the scanner fetches on its own; neither is
// under test here. The summary panel is.
vi.mock("@/components/rolling-accuracy-chart", () => ({
  RollingAccuracyChart: () => <div data-testid="chart-stub" />,
}));
vi.mock("@/components/value-bet-scanner", () => ({
  ValueBetScanner: () => <div data-testid="scanner-stub" />,
}));

function renderWithClient() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return render(
    <QueryClientProvider client={client}>
      <PerformancePageClient />
    </QueryClientProvider>,
  );
}

function mockSummary(body: unknown, status = 200) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: status >= 200 && status < 300,
      status,
      json: async () => body,
    }),
  );
}

describe("PerformancePageClient summary", () => {
  beforeEach(() => vi.restoreAllMocks());
  afterEach(() => vi.unstubAllGlobals());

  it("renders measured accuracy and RPS when a walk-forward run produced them", async () => {
    mockSummary({
      status: "OK",
      total_settled: 42,
      accuracy_overall: 0.4762,
      rps_overall: 0.198,
      n_splits: 5,
      validated_at: "2026-08-05T09:00:00Z",
    });

    renderWithClient();

    expect(await screen.findByText("47.6%")).toBeInTheDocument();
    expect(screen.getByText("0.198")).toBeInTheDocument();
    expect(screen.getByText("42")).toBeInTheDocument();
    expect(screen.getByText("5")).toBeInTheDocument();
    expect(screen.queryByTestId("performance-summary-notice")).not.toBeInTheDocument();
  });

  it("explains WHY the panel is empty instead of showing zeros", async () => {
    // The backend answers this 503 correctly during the off-season. The old proxy
    // replaced it with literal zeros, which rendered as "0.0% accuracy" — a
    // measurement the system had not made.
    mockSummary(
      {
        status: "METRICS_UNAVAILABLE",
        reason: "insufficient_settled_predictions",
        settled_predictions: 0,
      },
      503,
    );

    renderWithClient();

    const notice = await screen.findByTestId("performance-summary-notice");
    expect(notice).toHaveTextContent(/awaiting settled predictions/i);
    expect(notice).toHaveTextContent(/none have settled yet/i);
    expect(screen.queryByText("0.0%")).not.toBeInTheDocument();
    expect(screen.queryByText("0.000")).not.toBeInTheDocument();
  });

  it("distinguishes a real outage from having no settled data", async () => {
    mockSummary(
      { status: "METRICS_UNAVAILABLE", reason: "backend_unreachable", error: "fetch failed" },
      503,
    );

    renderWithClient();

    const notice = await screen.findByTestId("performance-summary-notice");
    expect(notice).toHaveTextContent(/unreachable/i);
    expect(notice).toHaveAttribute("role", "alert");
  });

  it("never offers ROI, which this pipeline cannot compute", async () => {
    mockSummary({
      status: "OK",
      total_settled: 42,
      accuracy_overall: 0.48,
      rps_overall: 0.2,
      n_splits: 5,
    });

    renderWithClient();
    await screen.findByText("48.0%");

    // No stake is ever placed (NO_BET / shadow only), so ROI has no referent at
    // all — unlike CLV below, which is a real capability still filling up.
    await waitFor(() => {
      expect(screen.queryByText(/ROI/i)).not.toBeInTheDocument();
    });
  });

  // This case previously asserted CLV was never shown, on the rationale that
  // "MatchPredictionLog stores no odds so CLV has nothing to join". That stopped
  // being true when clv_service + get_clv_records shipped: production reports
  // real joined pairs under the service's own floor. Below the floor the tile
  // must report progress, never a mean computed from too few pairs.
  it("shows CLV progress toward its floor instead of a premature mean", async () => {
    mockSummary({
      status: "OK",
      total_settled: 21,
      accuracy_overall: 0.4,
      rps_overall: 0.2436,
      n_splits: 5,
      clv: { skipped: true, n: 6, reason: "need >= 10 joined predictions, got 6" },
    });

    renderWithClient();

    expect(await screen.findByText(/closing line value/i)).toBeInTheDocument();
    expect(screen.getByText(/6 of 10 joined predictions/i)).toBeInTheDocument();
    expect(screen.queryByText(/pp$/)).not.toBeInTheDocument();
  });

  it("reports a measured CLV mean once the floor is cleared", async () => {
    mockSummary({
      status: "OK",
      total_settled: 40,
      accuracy_overall: 0.45,
      rps_overall: 0.21,
      n_splits: 5,
      clv: { skipped: false, n: 12, mean_clv: 0.0231, positive_rate: 0.58 },
    });

    renderWithClient();

    expect(await screen.findByText("+2.3pp")).toBeInTheDocument();
    expect(
      screen.getByText(/mean vs\. market close across 12 joined predictions/i),
    ).toBeInTheDocument();
  });
});
