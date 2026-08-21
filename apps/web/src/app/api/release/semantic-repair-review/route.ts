import { NextResponse } from "next/server";
import { z } from "zod";
import {
  ERROR_CACHE_HEADERS,
  isHtmlBody,
  proxyHeaders,
  resolveBackendBaseUrl,
  sanitizeBackendError,
} from "@/lib/proxy-utils";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const sha256Schema = z.string().regex(/^[0-9a-f]{64}$/);
const nonNegativeInteger = z.number().int().nonnegative();

const proposedTeamCreationSchema = z
  .object({
    team_id: z.string().min(1),
    team_name: z.string().min(1),
    league_id: z.string().min(1),
    participant_references: z.number().int().positive(),
    source_fixture_ids: z.array(z.string().min(1)).min(1),
    source_evidence_sha256s: z.array(sha256Schema).min(1),
  })
  .passthrough();

const semanticRepairReviewSchema = z
  .object({
    generated_at: z.string().min(1),
    read_only: z.literal(true),
    blocked: z.boolean(),
    reason: z.string().nullable(),
    manifest: z
      .object({
        schema_version: z.number().int().min(3),
        repair_manifest_sha256: sha256Schema,
        summary: z
          .object({
            affected_matches: nonNegativeInteger,
            repair_ready_matches: nonNegativeInteger,
            repair_blocked_matches: nonNegativeInteger,
            source_records_found: nonNegativeInteger,
            source_records_missing: nonNegativeInteger,
            source_evidence_hashed: nonNegativeInteger,
            replay_required_matches: nonNegativeInteger,
            proposed_team_creations: nonNegativeInteger,
            proposed_team_creation_references: nonNegativeInteger,
            blocker_counts: z.record(nonNegativeInteger),
            first_affected_match: z.string().nullable(),
            last_affected_match: z.string().nullable(),
            complete: z.boolean(),
          })
          .passthrough(),
      })
      .passthrough()
      .nullable(),
    replay_plan: z
      .object({
        schema_version: z.number().int().positive(),
        semantic_manifest_sha256: sha256Schema,
        elo_config: z
          .object({
            k_base: z.number(),
            home_advantage: z.number(),
          })
          .passthrough(),
        plan_sha256: sha256Schema,
        leagues: z.array(
          z
            .object({
              league: z.string().min(1),
              boundary_utc: z.string().min(1),
              finished_matches: nonNegativeInteger,
              existing_snapshots_to_replace: nonNegativeInteger,
              expected_rebuilt_snapshots: nonNegativeInteger,
              match_sequence_sha256: sha256Schema,
            })
            .passthrough(),
        ),
      })
      .passthrough()
      .nullable(),
    proposed_replacements: z.array(
      z
        .object({
          stored_team_id: z.string().min(1),
          stored_team_name: z.string().nullable(),
          target_team_id: z.string().min(1),
          source_team_name: z.string().nullable(),
          participant_references: z.number().int().positive(),
        })
        .passthrough(),
    ),
    proposed_team_creations: z.array(proposedTeamCreationSchema),
    authorization: z
      .object({
        review_ready: z.boolean(),
        production_mutation_authorized: z.literal(false),
        required: z.string().min(1).optional(),
      })
      .passthrough(),
  })
  .passthrough();

export async function GET() {
  try {
    const response = await fetch(
      `${resolveBackendBaseUrl()}/api/v1/release/semantic-repair-review`,
      {
        headers: proxyHeaders(),
        cache: "no-store",
      },
    );
    const body = await response.text().catch(() => "");

    if (!response.ok || isHtmlBody(body)) {
      return NextResponse.json(
        {
          status: "UNAVAILABLE",
          detail: sanitizeBackendError(body, response.status),
        },
        {
          status: response.ok ? 502 : response.status,
          headers: ERROR_CACHE_HEADERS,
        },
      );
    }

    try {
      const parsed = semanticRepairReviewSchema.safeParse(JSON.parse(body));
      if (!parsed.success) {
        return NextResponse.json(
          {
            status: "UNAVAILABLE",
            detail: "Backend returned an invalid semantic repair review",
          },
          { status: 502, headers: ERROR_CACHE_HEADERS },
        );
      }
      return NextResponse.json(parsed.data, {
        status: response.status,
        headers: ERROR_CACHE_HEADERS,
      });
    } catch {
      return NextResponse.json(
        {
          status: "UNAVAILABLE",
          detail: "Backend returned invalid JSON",
        },
        { status: 502, headers: ERROR_CACHE_HEADERS },
      );
    }
  } catch {
    return NextResponse.json(
      {
        status: "UNAVAILABLE",
        detail: "Backend service unavailable",
      },
      { status: 503, headers: ERROR_CACHE_HEADERS },
    );
  }
}
