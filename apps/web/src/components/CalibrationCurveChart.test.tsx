import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  CalibrationCurveChart,
  poolCurves,
  toPlotBins,
  type CalibrationBin,
} from "./CalibrationCurveChart";

// ─── Pure helpers ───────────────────────────────────────────────────────────
// Asserted directly against the data handed to the chart, not pixel output —
// recharts' <ResponsiveContainer> needs a real ResizeObserver-backed layout to
// render anything in jsdom, which this repo's test setup doesn't provide (see
// rolling-accuracy-chart.test.ts, which tests its own pure `withFoldLabels`
// the same way rather than rendering the chart).

describe("toPlotBins", () => {
  it("drops unfilled bins (count 0 / null values) instead of plotting a fabricated zero", () => {
    const bins: CalibrationBin[] = [
      { bin_index: 0, predicted_mean: 0.05, empirical_frequency: 0.1, count: 4 },
      { bin_index: 1, predicted_mean: null, empirical_frequency: null, count: 0 },
      { bin_index: 2, predicted_mean: 0.85, empirical_frequency: 0.9, count: 6 },
    ];

    expect(toPlotBins(bins)).toEqual([
      { x: 0.05, y: 0.1, count: 4 },
      { x: 0.85, y: 0.9, count: 6 },
    ]);
  });
});

describe("poolCurves", () => {
  it("produces a count-weighted pooled curve that differs from any single class", () => {
    const homeWin: CalibrationBin[] = [
      { bin_index: 0, predicted_mean: 0.1, empirical_frequency: 0.2, count: 10 },
      { bin_index: 1, predicted_mean: 0.5, empirical_frequency: 0.4, count: 20 },
    ];
    const draw: CalibrationBin[] = [
      { bin_index: 0, predicted_mean: 0.1, empirical_frequency: 0.6, count: 5 },
      { bin_index: 1, predicted_mean: null, empirical_frequency: null, count: 0 },
    ];
    const awayWin: CalibrationBin[] = [
      { bin_index: 0, predicted_mean: null, empirical_frequency: null, count: 0 },
      { bin_index: 1, predicted_mean: 0.5, empirical_frequency: 0.9, count: 10 },
    ];

    const pooled = poolCurves({ home_win: homeWin, draw, away_win: awayWin });
    const homeOnly = toPlotBins(homeWin);

    expect(pooled).toEqual([
      { x: 0.1, y: 0.333, count: 15 },
      { x: 0.5, y: 0.567, count: 30 },
    ]);
    // The "Overall Ensemble" tab used to silently alias to curves.home_win.
    // A real pooled figure must not match the single-class figure it was
    // fabricated from.
    expect(pooled).not.toEqual(homeOnly);
  });
});

// ─── Rendered component ─────────────────────────────────────────────────────

function renderWithClient() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return render(
    <QueryClientProvider client={client}>
      <CalibrationCurveChart />
    </QueryClientProvider>,
  );
}

function mockCalibration(body: unknown, status = 200) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: status >= 200 && status < 300,
      status,
      json: async () => body,
    }),
  );
}

describe("CalibrationCurveChart", () => {
  beforeEach(() => vi.restoreAllMocks());
  afterEach(() => vi.unstubAllGlobals());

  it("renders — for absent metrics, never the previous hardcoded fallback numbers", async () => {
    // No `ece`, `brier_decomposition`, or `curves` — the shape a fresh
    // deployment with no walk-forward history yet would actually return.
    mockCalibration({ sample_size: 12 });

    renderWithClient();

    await screen.findByText("Awaiting settled match prediction records.");

    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
    // The deleted hardcoded fallbacks, rendered as they used to be.
    expect(screen.queryByText("1.80%")).not.toBeInTheDocument();
    expect(screen.queryByText("0.178")).not.toBeInTheDocument();
    expect(screen.queryByText("0.0060")).not.toBeInTheDocument();
    expect(screen.queryByText("0.0780")).not.toBeInTheDocument();
    expect(screen.queryByText("0.2500")).not.toBeInTheDocument();
  });

  it("renders a floor message instead of the chart/tiles below the sample floor", async () => {
    mockCalibration({ meets_sample_floor: false, minimum_sample_size: 30, sample_size: 7 });

    renderWithClient();

    const notice = await screen.findByText(/not enough settled predictions yet/i);
    expect(notice).toBeInTheDocument();
    expect(
      screen.getByText(/calibration requires at least 30 settled predictions/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/currently 7/i)).toBeInTheDocument();

    expect(screen.queryByText("Multiclass ECE")).not.toBeInTheDocument();
    expect(screen.queryByText("Awaiting settled match prediction records.")).not.toBeInTheDocument();
  });

  it("uses aria-pressed outcome tabs (not the incomplete tablist pattern) and responds to clicks", async () => {
    mockCalibration({ sample_size: 5 });

    renderWithClient();
    await screen.findByText("Awaiting settled match prediction records.");

    expect(screen.getByRole("group", { name: /select outcome class/i })).toBeInTheDocument();

    const overallTab = screen.getByRole("button", { name: "Overall Ensemble" });
    const homeTab = screen.getByRole("button", { name: "Home Win" });
    expect(overallTab).toHaveAttribute("aria-pressed", "true");
    expect(homeTab).toHaveAttribute("aria-pressed", "false");

    fireEvent.click(homeTab);

    expect(homeTab).toHaveAttribute("aria-pressed", "true");
    expect(overallTab).toHaveAttribute("aria-pressed", "false");
  });
});
