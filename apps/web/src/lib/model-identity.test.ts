import { describe, expect, it } from "vitest";
import {
  certificationIsCertified,
  certificationLabel,
  generationLabel,
  isOperatorOverride,
  promotionLabel,
} from "@/lib/model-identity";

describe("model identity mapping (APEX §11 product language)", () => {
  it("maps the live manifest's active_version to a generation label", () => {
    expect(generationLabel("v5_phase7")).toBe("Generation 5");
    expect(generationLabel("v6_phase8")).toBe("Generation 6");
  });

  it("never echoes an unrecognised version string", () => {
    for (const value of ["phase7_68", "SoftmaxMetaModel", "", null, undefined, 42]) {
      expect(generationLabel(value)).toBe("Current generation");
    }
  });

  it("maps both real certification states to product language", () => {
    expect(certificationLabel("CERTIFIED")).toBe("Production-validated");
    expect(certificationLabel("UNVERIFIED")).toBe("Research mode");
  });

  it("fails closed on an unknown certification state", () => {
    // A state added backend-side must not leak, and must not read as certified.
    expect(certificationLabel("SHADOW_PENDING")).toBe("Pending validation");
    expect(certificationLabel(null)).toBe("Pending validation");
    expect(certificationIsCertified("SHADOW_PENDING")).toBe(false);
    expect(certificationIsCertified("CERTIFIED")).toBe(true);
  });

  it("describes the live promotion state without echoing the enum", () => {
    expect(promotionLabel("ACTIVE_FAIL_CLOSED")).toBe("Serving forecasts · staking blocked");
    expect(promotionLabel("ACTIVE_FAIL_CLOSED")).not.toContain("ACTIVE_FAIL_CLOSED");
    expect(promotionLabel("UNKNOWN")).toBe("Status unavailable");
  });

  it("labels an operator override as staking, never as validation", () => {
    // ADR-0011. The override permits staking without conferring certification,
    // so the label must say so on both counts: it must not borrow certified
    // language, and it must not read as inert while stakes are being published.
    const label = certificationLabel("OPERATOR_OVERRIDE_UNCERTIFIED");
    expect(label).toBe("Unvalidated · staking under operator override");
    expect(label).not.toContain("Production-validated");
    expect(label).not.toContain("OPERATOR_OVERRIDE_UNCERTIFIED");
    expect(certificationIsCertified("OPERATOR_OVERRIDE_UNCERTIFIED")).toBe(false);
    expect(isOperatorOverride("OPERATOR_OVERRIDE_UNCERTIFIED")).toBe(true);
    expect(isOperatorOverride("UNVERIFIED")).toBe(false);
  });

  it("never claims staking is blocked while an override has it enabled", () => {
    // ⚠️ The regression this pins: `promotion_state` stays ACTIVE_FAIL_CLOSED
    // under an override, so the old one-argument copy would have told a reader
    // "staking blocked" on a system that is actively staking.
    const overridden = promotionLabel(
      "ACTIVE_FAIL_CLOSED",
      "OPERATOR_OVERRIDE_UNCERTIFIED",
    );
    expect(overridden).toBe("Serving forecasts · staking enabled by operator override");
    expect(overridden).not.toContain("blocked");

    expect(promotionLabel("ACTIVE_FAIL_CLOSED", "UNVERIFIED")).toBe(
      "Serving forecasts · staking blocked",
    );
    expect(promotionLabel("ACTIVE_FAIL_CLOSED", "CERTIFIED")).toBe(
      "Serving forecasts · staking permitted",
    );
    // An unknown certification state must fall back to the safe sentence.
    expect(promotionLabel("ACTIVE_FAIL_CLOSED", "SHADOW_PENDING")).toBe(
      "Serving forecasts · staking blocked",
    );
  });
});
