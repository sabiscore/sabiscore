import { describe, expect, it } from "vitest";
import { summarizeAnalysis } from "./prediction-truth";
import { analysisFixture } from "./prediction-truth.fixture";

describe("summarizeAnalysis truth states", () => {
  it("certified model without verified market edge => No Verified Edge, staking withheld", () => {
    const result = summarizeAnalysis(analysisFixture());
    expect(result.status).toBe("OK");
    if (result.status !== "OK") return;
    expect(result.summary.truth_state).toBe("NO_VERIFIED_EDGE");
    expect(result.summary.market.health).toBe("UNAVAILABLE");
    expect(result.summary.suggested_stake_pct).toBeNull();
    expect(result.summary.probabilities).toEqual({ home: 0.52, draw: 0.26, away: 0.22 });
  });

  it("uncertified model => Research Mode", () => {
    const result = summarizeAnalysis(
      analysisFixture(
        { prediction_source: "UNCERTIFIED_MODEL" },
        { certification_state: "UNVERIFIED" },
      ),
    );
    expect(result.status === "OK" && result.summary.truth_state).toBe("RESEARCH_MODE");
  });

  it("unavailable prediction => WITHHELD with no probabilities", () => {
    const result = summarizeAnalysis(
      analysisFixture(
        {
          prediction_status: "UNAVAILABLE",
          prediction_source: "NONE",
          probabilities_available: false,
          top_outcome_probability: 0,
        },
        {
          probabilities_available: false,
          home_win_prob: 0,
          draw_prob: 0,
          away_win_prob: 0,
          top_outcome_probability: 0,
          confidence: 0,
        },
      ),
    );
    expect(result.status).toBe("WITHHELD");
    expect(result).not.toHaveProperty("summary");
    expect(result.truth_state).toBe("WITHHELD");
  });

  it("reduced-evidence baseline is not presented as a forecast", () => {
    const result = summarizeAnalysis(
      analysisFixture(
        {
          prediction_status: "REDUCED_EVIDENCE_BASELINE",
          prediction_source: "DIAGNOSTIC_BASELINE",
          is_reduced_evidence_baseline: true,
          probabilities_available: false,
        },
        {
          probabilities_available: false,
        },
      ),
    );
    expect(result.status).toBe("WITHHELD");
    expect(result.truth_state).toBe("INSUFFICIENT_VERIFIED_DATA");
  });
});
