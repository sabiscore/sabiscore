import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { BackendHealthPayload } from "@/lib/health-status";
import { MobilePlatformSummary } from "./mobile-platform-summary";

const { fetchPlatformHealth } = vi.hoisted(() => ({ fetchPlatformHealth: vi.fn() }));

vi.mock("@/lib/health-status", async () => {
  const actual = await vi.importActual<typeof import("@/lib/health-status")>("@/lib/health-status");
  return { ...actual, fetchPlatformHealth };
});

function renderSummary(payload: BackendHealthPayload) {
  fetchPlatformHealth.mockResolvedValueOnce(payload);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MobilePlatformSummary />
    </QueryClientProvider>,
  );
}

describe("MobilePlatformSummary", () => {
  it("keeps configured providers separate from live verification", async () => {
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

    expect(
      await screen.findByLabelText(
        "Core 4 of 4; providers 5 configured, 1 live-verified; models ready",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("5 cfg · 1 live")).toBeInTheDocument();
  });
});
