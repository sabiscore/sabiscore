import { isValidElement, type ReactElement, type ReactNode } from "react";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MatchAnalysisContent } from "./PredictionSection";
import { FullAnalysisDashboard } from "@/components/full-analysis-dashboard";
import { analysisFixture } from "@/lib/prediction-truth.fixture";

afterEach(() => {
  vi.unstubAllGlobals();
});

function childElements(node: ReactNode): ReactElement[] {
  if (!isValidElement(node)) return [];
  const props = node.props as { children?: ReactNode };
  return ([] as ReactNode[]).concat(props.children).filter(isValidElement) as ReactElement[];
}

describe("one full-analysis request per match page", () => {
  it("fetches once and hands the same payload to the card and the dashboard", async () => {
    const fetchSpy = vi.fn(async () => new Response(JSON.stringify(analysisFixture()), { status: 200 }));
    vi.stubGlobal("fetch", fetchSpy);

    const tree = await MatchAnalysisContent({ matchId: "fd-1", league: "EPL" });

    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const [cardSection, dashboard] = childElements(tree);
    const card = childElements(cardSection)[0];
    const cardResult = (card.props as { result: { status: string } }).result;
    const seeded = (dashboard.props as { initialData?: { match_id: string } }).initialData;
    expect(cardResult.status).toBe("OK");
    expect(seeded?.match_id).toBe(analysisFixture().match_id);
  });

  it("gives the dashboard no seed when the server fetch failed, so it can fetch and retry itself", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("down", { status: 503 })));

    const tree = await MatchAnalysisContent({ matchId: "fd-1", league: "EPL" });

    const [, dashboard] = childElements(tree);
    expect((dashboard.props as { initialData?: unknown }).initialData).toBeUndefined();
  });

  it("a seeded dashboard renders without a client request", async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    render(
      <QueryClientProvider client={client}>
        <FullAnalysisDashboard matchId="fd-1" league="EPL" initialData={analysisFixture()} />
      </QueryClientProvider>,
    );

    expect((await screen.findAllByText(/Home Win/i)).length).toBeGreaterThan(0);
    const analysisCalls = fetchSpy.mock.calls.filter(([url]) => String(url).includes("full-analysis"));
    expect(analysisCalls).toHaveLength(0);
  });

  it("never shows the raw generation id on the rendered dashboard (APEX section 11)", async () => {
    vi.stubGlobal("fetch", vi.fn());
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const fixture = analysisFixture();

    const { container } = render(
      <QueryClientProvider client={client}>
        <FullAnalysisDashboard matchId="fd-1" league="EPL" initialData={fixture} />
      </QueryClientProvider>,
    );

    await screen.findAllByText(/Home Win/i);
    expect(fixture.ensemble.model_version).toBe("v5_phase7");
    expect(container.textContent ?? "").not.toContain("v5_phase7");
  });
});
