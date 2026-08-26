import { describe, expect, it } from "vitest";
import { evidenceStateFor } from "@/lib/evidence-state";

describe("evidence state mapping (Mandate 2 R3 / APEX §15.2)", () => {
  it("maps every live backend token from fixtures.py's _build_evidence()", () => {
    expect(evidenceStateFor("VERIFIED")).toEqual({ label: "Verified", tone: "positive" });
    expect(evidenceStateFor("MODEL_READY")).toEqual({ label: "Verified", tone: "positive" });
    expect(evidenceStateFor("STALE")).toEqual({ label: "Stale", tone: "warning" });
    expect(evidenceStateFor("CONFLICTING")).toEqual({ label: "Limited evidence", tone: "warning" });
    expect(evidenceStateFor("DATA_GAP")).toEqual({ label: "Data unavailable", tone: "neutral" });
    expect(evidenceStateFor("DATA_UNAVAILABLE")).toEqual({ label: "Provider unavailable", tone: "neutral" });
    expect(evidenceStateFor("MODEL_UNAVAILABLE")).toEqual({ label: "Model unavailable", tone: "neutral" });
    expect(evidenceStateFor("RESEARCH_ONLY")).toEqual({ label: "Research mode", tone: "info" });
  });

  it("is case-insensitive, matching how the backend always emits upper-case tokens", () => {
    expect(evidenceStateFor("verified")).toEqual({ label: "Verified", tone: "positive" });
  });

  it("never echoes an unrecognised token — fails closed", () => {
    for (const value of ["SCHEMA_INVALID", "", null, undefined, 42]) {
      expect(evidenceStateFor(value)).toEqual({ label: "Status unavailable", tone: "neutral" });
    }
  });

  it("never renders a raw DATA_UNAVAILABLE/PROVIDER token as the generic danger tone", () => {
    // Mandate 2 R3: no generic red error state for a distinct evidence state.
    expect(evidenceStateFor("DATA_UNAVAILABLE").tone).not.toBe("danger");
  });
});
