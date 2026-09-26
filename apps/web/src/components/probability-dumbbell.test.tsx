import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { FullMatchMarket } from "@/lib/full-analysis-contract";
import { ProbabilityDumbbell } from "./probability-dumbbell";

// Live PSV v Heerenveen block: a withheld fixture with a positive gap on two outcomes.
const market: FullMatchMarket = {
  devig_method: "proportional",
  overround: 1.058,
  evaluable: false,
  outcomes: [
    { outcome: "home_win", odds: 1.24, implied: 0.8065, fair: 0.762, model_prob: 0.646, edge: -0.116, expected_value: null },
    { outcome: "draw", odds: 7.36, implied: 0.1359, fair: 0.128, model_prob: 0.211, edge: 0.083, expected_value: null },
    { outcome: "away_win", odds: 8.65, implied: 0.1156, fair: 0.109, model_prob: 0.143, edge: 0.034, expected_value: null },
  ],
};

const rows = (container: HTMLElement) => Array.from(container.querySelectorAll("g[data-outcome]"));
const marks = (container: HTMLElement, name: string, attr: string) =>
  Array.from(container.querySelectorAll(`[data-mark="${name}"]`)).map((el) => Number(el.getAttribute(attr)));

describe("ProbabilityDumbbell (directive v10 U5)", () => {
  it("renders one row per outcome in the backend's order, labelled like the table", () => {
    const { container } = render(<ProbabilityDumbbell market={market} />);
    expect(rows(container).map((row) => row.getAttribute("data-outcome"))).toEqual(["home_win", "draw", "away_win"]);
    expect(rows(container).map((row) => row.textContent)).toEqual(["Home Win", "Draw", "Away Win"]);
  });

  it("places the fair and model dots at the backend probabilities on a 0-100 track", () => {
    const { container } = render(<ProbabilityDumbbell market={market} />);
    expect(marks(container, "fair", "cx")).toEqual([76.2, 12.8, 10.9]);
    expect(marks(container, "model", "cx")).toEqual([64.6, 21.1, 14.3]);
  });

  it("puts the break-even tick at the implied probability, not at the fair one", () => {
    const { container } = render(<ProbabilityDumbbell market={market} />);
    expect(marks(container, "implied", "x1")).toEqual([80.65, 13.59, 11.56]);
    expect(marks(container, "implied", "x2")).toEqual([80.65, 13.59, 11.56]);
  });

  it("stays neutral while the backend withholds a stake, whatever the gap's sign", () => {
    const { container } = render(<ProbabilityDumbbell market={market} />);
    expect(container.innerHTML).not.toMatch(/--state-play/);
    const dots = Array.from(container.querySelectorAll("circle"));
    expect(dots).toHaveLength(6);
    for (const dot of dots) expect(dot.getAttribute("class")).toMatch(/--state-withheld/);
  });

  it("colours only the positive-gap rows when the backend permits a stake", () => {
    const { container } = render(<ProbabilityDumbbell market={market} stakePermitted />);
    const [home, draw, away] = rows(container);
    expect(home.innerHTML).not.toMatch(/--state-play/);
    for (const row of [draw, away]) {
      expect(row.querySelector('[data-mark="model"]')?.getAttribute("class")).toMatch(/--state-play/);
      expect(row.querySelector('[data-mark="gap"]')?.getAttribute("class")).toMatch(/--state-play/);
    }
  });

  it("draws the fair dot and tick but no model dot or segment without a measured forecast", () => {
    const marketOnly: FullMatchMarket = {
      ...market,
      outcomes: market.outcomes.map((row, i) => (i === 0 ? { ...row, model_prob: null, edge: null } : row)),
    };
    const [home] = rows(render(<ProbabilityDumbbell market={marketOnly} />).container);
    expect(home.querySelector('[data-mark="fair"]')).not.toBeNull();
    expect(home.querySelector('[data-mark="implied"]')).not.toBeNull();
    expect(home.querySelector('[data-mark="model"]')).toBeNull();
    expect(home.querySelector('[data-mark="gap"]')).toBeNull();
  });

  it("hides the svg from assistive tech and keeps the legend as visible text", () => {
    const { container } = render(<ProbabilityDumbbell market={market} />);
    const svg = container.querySelector("svg");
    expect(svg).toHaveAttribute("aria-hidden", "true");
    expect(svg).toHaveAttribute("focusable", "false");
    expect(screen.getByText(/break-even/).closest('[aria-hidden="true"]')).toBeNull();
  });
});
