import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MatchShareModal } from "./MatchShareModal";

vi.mock("@/lib/analytics", () => ({
  analytics: { track: vi.fn() },
}));

const clipboardWrite = vi.fn<(...args: [string]) => Promise<void>>();

beforeEach(() => {
  clipboardWrite.mockReset();
  clipboardWrite.mockResolvedValue();
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText: clipboardWrite },
  });
});

describe("MatchShareModal", () => {
  it("shares only fixture identity when no analysis result owns the action", async () => {
    render(
      <MatchShareModal
        open
        onOpenChange={() => {}}
        mode="fixture"
        matchId="fd-123"
        homeTeam="Arsenal"
        awayTeam="Chelsea"
        league="EPL"
      />
    );

    expect(screen.getByRole("dialog", { name: "Share Match" })).toBeInTheDocument();
    expect(screen.getByText("Fixture link")).toBeInTheDocument();
    expect(screen.queryByText(/Actionable/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/50%|28%|22%/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Copy Match Link" }));

    await waitFor(() => expect(clipboardWrite).toHaveBeenCalledTimes(1));
    const sharedText = clipboardWrite.mock.calls[0]?.[0] ?? "";
    expect(sharedText).toContain("SabiScore match intelligence: Arsenal vs Chelsea");
    expect(sharedText).toContain("/match/fd-123?league=EPL");
    expect(sharedText).not.toMatch(/Forecast:|Verdict:|Verified quantitative evidence/);
  });

  it("renders analytical fields only when they are supplied explicitly", () => {
    render(
      <MatchShareModal
        open
        onOpenChange={() => {}}
        mode="analysis"
        matchId="fd-456"
        homeTeam="Liverpool"
        awayTeam="Everton"
        league="EPL"
        probabilities={{ home: 0.45, draw: 0.3, away: 0.25 }}
        verdict="NO_BET"
        evidenceSummary="Two critical evidence gaps remain unresolved."
        stakePermitted={false}
        certificationState="UNVERIFIED"
      />
    );

    expect(screen.getByRole("dialog", { name: "Share Match Analysis" })).toBeInTheDocument();
    expect(screen.getByText("45%")).toBeInTheDocument();
    expect(screen.getByText("30%")).toBeInTheDocument();
    expect(screen.getByText("25%")).toBeInTheDocument();
    expect(screen.getByText("No Bet")).toHaveClass("text-signal-danger");
    expect(screen.getByText(/Research mode · Informational only/i)).toBeInTheDocument();
  });
});