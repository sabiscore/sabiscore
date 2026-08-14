import { describe, expect, it, vi, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ModelMetadataPanel } from "./model-metadata-panel";

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ModelMetadataPanel />
    </QueryClientProvider>,
  );
}

describe("ModelMetadataPanel", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows a loading skeleton instead of rendering Unknown before data arrives", () => {
    vi.spyOn(global, "fetch").mockReturnValue(new Promise(() => {}));
    renderPanel();

    expect(screen.queryByText("Unknown")).not.toBeInTheDocument();
    expect(screen.getAllByLabelText(/Loading…/).length).toBeGreaterThan(0);
  });

  it("renders real governance metadata once the backend responds", async () => {
    vi.spyOn(global, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({
        active_version: "v5_phase7-20260808",
        generation: "v5_phase7",
        generation_hash: "abc123def456ghi789",
        certification_state: "UNVERIFIED",
        promotion_state: "ACTIVE_FAIL_CLOSED",
        models: {
          EPL: { feature_schema_version: "phase7_68", served_head: "SoftmaxMetaModel" },
        },
      }),
    } as unknown as Response);

    renderPanel();

    expect(await screen.findByText("v5_phase7-20260808")).toBeInTheDocument();
    expect(screen.getByText("UNVERIFIED")).toBeInTheDocument();
    expect(screen.getByText("SoftmaxMetaModel")).toBeInTheDocument();
    expect(screen.queryByText("Loading…")).not.toBeInTheDocument();
  });

  it("shows Unavailable, not Unknown, when the request fails", async () => {
    vi.spyOn(global, "fetch").mockResolvedValue({ ok: false } as Response);

    renderPanel();

    await waitFor(() => expect(screen.getAllByText("Unavailable").length).toBeGreaterThan(0));
    expect(screen.queryByText("Unknown")).not.toBeInTheDocument();
  });

  it("keeps plain-language Certification and Promotion explanations visible", async () => {
    vi.spyOn(global, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({
        active_version: "v5_phase7-20260808",
        generation: "v5_phase7",
        generation_hash: "abc123def456ghi789",
        certification_state: "UNVERIFIED",
        promotion_state: "ACTIVE_FAIL_CLOSED",
        models: {
          EPL: { feature_schema_version: "phase7_68", served_head: "SoftmaxMetaModel" },
        },
      }),
    } as unknown as Response);

    renderPanel();
    await screen.findByText("UNVERIFIED");

    expect(screen.getByText(/research output only/i)).toBeVisible();
    expect(screen.getByText(/blocks staking until it is certified/i)).toBeVisible();
  });
});
