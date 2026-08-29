import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ReadinessRing } from "./readiness-ring";
import type { BackendHealthPayload } from "@/lib/health-status";

const { fetchPlatformHealth } = vi.hoisted(() => ({ fetchPlatformHealth: vi.fn() }));

vi.mock("@/lib/health-status", async () => {
  const actual = await vi.importActual<typeof import("@/lib/health-status")>("@/lib/health-status");
  return { ...actual, fetchPlatformHealth };
});

function renderRing(payload: BackendHealthPayload) {
  fetchPlatformHealth.mockResolvedValueOnce(payload);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ReadinessRing />
    </QueryClientProvider>,
  );
}

const READY_CHECKS = {
  database: { status: "ready" },
  migrations: { status: "ready" },
  cache: { status: "ready" },
  models: { status: "ready" },
};

describe("ReadinessRing capability line (D6)", () => {
  it("shows verified predictions distinctly from infra readiness", async () => {
    renderRing({
      backendStatus: "ok",
      backendChecks: READY_CHECKS,
      backendCapability: { status: "verified", message: "ok" },
    });
    expect(await screen.findByText("Runtime capability check passed")).toBeInTheDocument();
    expect(screen.getByText("Core ready")).toBeInTheDocument();
  });

  it("never claims broken when there's simply nothing to test yet", async () => {
    renderRing({
      backendStatus: "ok",
      backendChecks: READY_CHECKS,
      backendCapability: { status: "unverified_no_fixtures", message: "no fixtures" },
    });
    expect(await screen.findByText("No fixtures to verify yet")).toBeInTheDocument();
  });

  it("surfaces a failed capability even while infra reports Core ready", async () => {
    renderRing({
      backendStatus: "ok",
      backendChecks: READY_CHECKS,
      backendCapability: { status: "failed", message: "prediction_status=UNAVAILABLE" },
    });
    await waitFor(() => expect(screen.getByText("Core ready")).toBeInTheDocument());
    expect(screen.getByText("Prediction pipeline not verified")).toBeInTheDocument();
  });

  it("falls back to the neutral copy for a backend response with no capability field yet", async () => {
    renderRing({ backendStatus: "ok", backendChecks: READY_CHECKS });
    expect(await screen.findByText("Capability not reported")).toBeInTheDocument();
  });

  // Regression: /health/ready is side-effect free and reports this state on every
  // healthy call. It was absent from the whitelist, so it degraded to "unknown"
  // and rendered "No fixtures to verify yet" while 60 fixtures were live.
  it("never claims there are no fixtures when readiness simply did not probe", async () => {
    renderRing({
      backendStatus: "ok",
      backendChecks: READY_CHECKS,
      backendCapability: {
        status: "not_probed_by_readiness",
        message: "Readiness verifies infrastructure and loaded-model state only",
      },
    });
    expect(await screen.findByText("Capability checked separately")).toBeInTheDocument();
    expect(screen.queryByText("No fixtures to verify yet")).not.toBeInTheDocument();
  });
});
