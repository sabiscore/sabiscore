import { afterEach, describe, expect, it, vi } from "vitest";

import { GET } from "./route";

describe("semantic repair review proxy", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("forwards successful JSON without caching it", async () => {
    const payload = {
      generated_at: "2026-08-21T12:00:00+00:00",
      read_only: true,
      blocked: false,
      reason: null,
      manifest: {
        schema_version: 3,
        repair_manifest_sha256: "a".repeat(64),
        summary: {
          affected_matches: 518,
          repair_ready_matches: 518,
          repair_blocked_matches: 0,
          source_records_found: 518,
          source_records_missing: 0,
          source_evidence_hashed: 518,
          replay_required_matches: 518,
          proposed_team_creations: 1,
          proposed_team_creation_references: 266,
          blocker_counts: {},
          first_affected_match: "2019-08-10T00:00:00",
          last_affected_match: "2026-05-24T00:00:00",
          complete: true,
        },
      },
      replay_plan: {
        schema_version: 1,
        semantic_manifest_sha256: "a".repeat(64),
        elo_config: { k_base: 20, home_advantage: 100 },
        plan_sha256: "b".repeat(64),
        leagues: [
          {
            league: "EPL",
            boundary_utc: "2019-08-10T00:00:00",
            finished_matches: 2660,
            existing_snapshots_to_replace: 5320,
            expected_rebuilt_snapshots: 5320,
            match_sequence_sha256: "c".repeat(64),
          },
        ],
      },
      proposed_replacements: [],
      proposed_team_creations: [
        {
          team_id: "fdco-team-epl-west_ham",
          team_name: "West Ham",
          league_id: "EPL",
          participant_references: 266,
          source_fixture_ids: ["fdco-match"],
          source_evidence_sha256s: ["d".repeat(64)],
        },
      ],
      authorization: {
        review_ready: true,
        production_mutation_authorized: false,
        required: "explicit_class_c_authorization",
      },
    };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(payload), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const response = await GET();

    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toBe("no-store");
    await expect(response.json()).resolves.toEqual(payload);
    expect(fetchMock).toHaveBeenCalledOnce();
    expect(String(fetchMock.mock.calls[0]?.[0])).toContain(
      "/api/v1/release/semantic-repair-review",
    );
    expect(fetchMock.mock.calls[0]?.[1]).toMatchObject({ cache: "no-store" });
  });

  it("fails closed when the backend review violates the typed contract", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            generated_at: "2026-08-21T12:00:00+00:00",
            read_only: true,
            blocked: false,
            reason: null,
            manifest: { schema_version: 2 },
            replay_plan: null,
            proposed_replacements: [],
            proposed_team_creations: [],
            authorization: {
              review_ready: true,
              production_mutation_authorized: false,
            },
          }),
          { status: 200 },
        ),
      ),
    );

    const response = await GET();

    expect(response.status).toBe(502);
    expect(response.headers.get("cache-control")).toBe("no-store");
    await expect(response.json()).resolves.toEqual({
      status: "UNAVAILABLE",
      detail: "Backend returned an invalid semantic repair review",
    });
  });

  it("fails closed when the backend returns HTML", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response("<!doctype html><html>upstream error</html>", {
          status: 200,
        }),
      ),
    );

    const response = await GET();

    expect(response.status).toBe(502);
    expect(response.headers.get("cache-control")).toBe("no-store");
    await expect(response.json()).resolves.toEqual({
      status: "UNAVAILABLE",
      detail: "Backend returned an unexpected response (not JSON)",
    });
  });

  it("fails closed when the backend cannot be reached", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network")));

    const response = await GET();

    expect(response.status).toBe(503);
    await expect(response.json()).resolves.toEqual({
      status: "UNAVAILABLE",
      detail: "Backend service unavailable",
    });
  });
});
