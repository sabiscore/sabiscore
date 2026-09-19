import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import {
  StakingOverrideBadge,
  StakingOverrideNotice,
} from "@/components/staking-override-notice";
import type { StakingAuthorization } from "@/lib/api";

const OVERRIDE: StakingAuthorization = {
  permitted: true,
  basis: "OPERATOR_OVERRIDE",
  certification_state: "OPERATOR_OVERRIDE_UNCERTIFIED",
  is_override: true,
  authorizing_identity: "ops@example.com",
  rationale: "Limited beta; accepting market-baseline failure.",
  authorized_at: "2026-09-19T00:00:00Z",
  acknowledged_failures: ["market_baseline", "error_association"],
};

const CERTIFIED: StakingAuthorization = {
  permitted: true,
  basis: "CERTIFIED",
  certification_state: "CERTIFIED",
  is_override: false,
  authorizing_identity: null,
  rationale: null,
  authorized_at: null,
  acknowledged_failures: [],
};

describe("staking override disclosure", () => {
  it("discloses the override next to the stake", () => {
    render(<StakingOverrideBadge auth={OVERRIDE} />);
    expect(screen.getByText(/operator override/i)).toBeInTheDocument();
  });

  it("names the overridden gates and the authorising identity", () => {
    render(<StakingOverrideNotice auth={OVERRIDE} />);
    expect(screen.getByText(/market_baseline/)).toBeInTheDocument();
    expect(screen.getByText(/error_association/)).toBeInTheDocument();
    expect(screen.getByText(/ops@example\.com/)).toBeInTheDocument();
    // The substance, not just the label: a reader must be told these are not
    // validated recommendations.
    expect(screen.getByText(/did not pass its certification gates/i)).toBeInTheDocument();
  });

  it("renders nothing for a genuinely certified generation", () => {
    const { container } = render(<StakingOverrideNotice auth={CERTIFIED} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when the field is absent, so it is safe to mount unconditionally", () => {
    const { container } = render(<StakingOverrideNotice auth={null} />);
    expect(container).toBeEmptyDOMElement();
    const undef = render(<StakingOverrideBadge auth={undefined} />);
    expect(undef.container).toBeEmptyDOMElement();
  });
});
