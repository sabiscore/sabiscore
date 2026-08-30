import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { BackendHealthPayload } from "@/lib/health-status";
import { MobilePlatformSummary } from "./mobile-platform-summary";

const { fetchPlatformHealth, fetchModelStatus } = vi.hoisted(() => ({
  fetchPlatformHealth: vi.fn(),
  fetchModelStatus: vi.fn(),
}));

vi.mock("@/lib/health-status", async () => {
  const actual = await vi.importActual<typeof import("@/lib/health-status")>("@/lib/health-status");
  return { ...actual, fetchPlatformHealth };
});

vi.mock("@/lib/model-status", async () => {
  const actual = await vi.importActual<typeof import("@/lib/model-status")>("@/lib/model-status");
  return { ...actual, fetchModelStatus };
});

function renderSummary(payload: BackendHealthPayload) {
  fetchPlatformHealth.mockResolvedValueOnce(payload);
  fetchModelStatus.mockResolvedValueOnce({
    active_version: "v5_phase7",
    generation: "v5_phase7-20260808",
    certification_state: "UNVERIFIED",
    promotion_state: "ACTIVE_FAIL_CLOSED",
    manifest_valid: true,
  });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MobilePlatformSummary />
    </QueryClientProvider>,
  );
}

describe("MobilePlatformSummary", () => {
  it("shows authoritative model/certification metadata and keeps provider live validation separate", async () => {
    renderSummary({
      backendStatus: "ok",
      backendChecks: {
        database: { status: "ready" },
        migrations: { status: "ready" },
        cache: { status: "ready" },
        models: { status: "ready" },
      },
      providers: Array.from({ length: 5 }, (_, index) => ({
        configured: true,
        enabled: true,
        status: index === 0 ? "VERIFIED" : "CONFIGURED_UNVERIFIED",
      })),
    });

    // APEX §11 — product language on a consumer surface, including the
    // screen-reader label, which is consumer output too.
    expect(
      await screen.findByLabelText(
        "Model Generation 5; certification Research mode; providers 5 configured; live-validated 1",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("Generation 5")).toBeInTheDocument();
    expect(screen.getByText("Research mode")).toBeInTheDocument();
    expect(screen.getByText("5 cfg · 5 on")).toBeInTheDocument();
    expect(screen.queryByText("v5_phase7")).not.toBeInTheDocument();
    expect(screen.queryByText("UNVERIFIED")).not.toBeInTheDocument();
  });
});
