import { describe, expect, it } from "vitest";
import {
  certificationIsCertified,
  certificationLabel,
  generationLabel,
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
});
