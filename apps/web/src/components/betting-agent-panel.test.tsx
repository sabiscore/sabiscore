import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { BettingAgentPanel } from "./betting-agent-panel";
import type { RLRecommendation } from "@/lib/api";

describe("BettingAgentPanel betting safety & default-deny posture (P9)", () => {
  const activeRec: RLRecommendation = {
    stake_fraction: 0.035,
    abstain: false,
    reason: "Positive edge with verified multi-factor support.",
    reward_components: {
      R_pnl: 0.12,
      R_ic: 0.08,
      R_cal: 0.05,
      R_risk: 0.04,
      R_abs: 0.01,
    },
  };

  const abstainRec: RLRecommendation = {
    stake_fraction: 0,
    abstain: true,
    reason: "Risk controls enforce abstention due to insufficient confidence.",
    reward_components: {},
  };

  it("suppresses staking controls by default (default-deny research mode)", () => {
    const { container } = render(<BettingAgentPanel recommendation={activeRec} />);

    // Zero input fields for wagering or entering stakes
    expect(container.querySelectorAll("input")).toHaveLength(0);
    expect(container.querySelectorAll("textarea")).toHaveLength(0);

    // Zero execution or placement buttons
    expect(screen.queryByRole("button", { name: /execute bet/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /place bet/i })).not.toBeInTheDocument();

    // Fallback messaging
    expect(screen.getByText("⚠ Staking Disabled")).toBeInTheDocument();
    expect(screen.getAllByText("Disabled").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/staking disabled in research mode/i)).toBeInTheDocument();

    // Reward decomposition is suppressed when staking is disabled
    expect(screen.queryByText(/Reward Components/i)).not.toBeInTheDocument();
  });

  it("suppresses staking controls when stakePermitted is explicitly false", () => {
    const { container } = render(
      <BettingAgentPanel recommendation={activeRec} stakePermitted={false} researchMode={false} />,
    );

    expect(container.querySelectorAll("input")).toHaveLength(0);
    expect(screen.queryByRole("button", { name: /execute bet/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /place bet/i })).not.toBeInTheDocument();
    expect(screen.getByText("⚠ Staking Disabled")).toBeInTheDocument();
    expect(screen.getAllByText("Disabled").length).toBeGreaterThanOrEqual(1);
  });

  it("enforces research mode override even if stakePermitted is passed as true", () => {
    const { container } = render(
      <BettingAgentPanel recommendation={activeRec} stakePermitted={true} researchMode={true} />,
    );

    expect(container.querySelectorAll("input")).toHaveLength(0);
    expect(screen.queryByRole("button", { name: /execute bet/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /place bet/i })).not.toBeInTheDocument();
    expect(screen.getByText("⚠ Staking Disabled")).toBeInTheDocument();
    expect(screen.getAllByText("Disabled").length).toBeGreaterThanOrEqual(1);
  });

  it("falls back to 'No Bet' and 'Abstain' messaging on abstention", () => {
    const { container } = render(<BettingAgentPanel recommendation={abstainRec} />);

    expect(container.querySelectorAll("input")).toHaveLength(0);
    expect(screen.queryByRole("button", { name: /execute bet/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /place bet/i })).not.toBeInTheDocument();

    expect(screen.getByText("⚠ Abstain")).toBeInTheDocument();
    expect(screen.getByText("No Bet")).toBeInTheDocument();
    expect(screen.getByText(/no bet recommended/i)).toBeInTheDocument();
  });

  it("renders empty DOM when recommendation is null or undefined", () => {
    const { container } = render(<BettingAgentPanel recommendation={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("never provides execution buttons even in authorized display mode", () => {
    const { container } = render(
      <BettingAgentPanel
        recommendation={activeRec}
        stakePermitted={true}
        researchMode={false}
      />,
    );

    // Advisory analytical display: active stake metrics are visible
    expect(screen.getByText("✓ Active Stake")).toBeInTheDocument();
    expect(screen.getAllByText("3.50%").length).toBeGreaterThanOrEqual(1);

    // But strictly NO automated execution buttons or wager input controls exist
    expect(container.querySelectorAll("input")).toHaveLength(0);
    expect(screen.queryByRole("button", { name: /execute bet/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /place bet/i })).not.toBeInTheDocument();
  });
});
