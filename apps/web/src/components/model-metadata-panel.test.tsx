import { describe, expect, it, vi, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ModelMetadataPanel } from "./model-metadata-panel";

/** The exact provenance shape `backend/models/active_generation.json` serves. */
function governanceResponse() {
  return {
    ok: true,
    json: async () => ({
      active_version: "v5_phase7",
      generation: "v5_phase7-20260808",
      generation_hash: "abc123def456ghi789",
      certification_state: "UNVERIFIED",
      promotion_state: "ACTIVE_FAIL_CLOSED",
      models: {
        EPL: { feature_schema_version: "phase7_68", served_head: "SoftmaxMetaModel", loaded: true },
        UCL: { feature_schema_version: "phase7_68", served_head: "SoftmaxMetaModel", loaded: false },
      },
    }),
  } as unknown as Response;
}

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

  it("renders governance state as product language, never raw provenance", async () => {
    vi.spyOn(global, "fetch").mockResolvedValue(governanceResponse());

    renderPanel();

    // APEX §11 — the consumer surface carries meaning, not internal identifiers.
    expect(await screen.findByText("Generation 5")).toBeInTheDocument();
    expect(screen.getByText("Research mode")).toBeInTheDocument();
    expect(screen.getByText("Serving forecasts · staking blocked")).toBeInTheDocument();
    expect(screen.getByText("1 of 2")).toBeInTheDocument();
    expect(screen.queryByText("Loading…")).not.toBeInTheDocument();

    for (const identifier of [
      "v5_phase7",
      "v5_phase7-20260808",
      "abc123def456ghi789",
      "phase7_68",
      "SoftmaxMetaModel",
      "UNVERIFIED",
      "ACTIVE_FAIL_CLOSED",
    ]) {
      expect(screen.queryByText(identifier)).not.toBeInTheDocument();
    }
  });

  it("shows Unavailable, not Unknown, when the request fails", async () => {
    vi.spyOn(global, "fetch").mockResolvedValue({ ok: false } as Response);

    renderPanel();

    await waitFor(() => expect(screen.getAllByText("Unavailable").length).toBeGreaterThan(0));
    expect(screen.queryByText("Unknown")).not.toBeInTheDocument();
  });

  it("keeps the plain-language validation explanation visible", async () => {
    vi.spyOn(global, "fetch").mockResolvedValue(governanceResponse());

    renderPanel();
    await screen.findByText("Research mode");

    expect(screen.getByText(/analytical output only/i)).toBeVisible();
    expect(screen.getByText(/no stake is recommended until validation passes/i)).toBeVisible();
  });
});
