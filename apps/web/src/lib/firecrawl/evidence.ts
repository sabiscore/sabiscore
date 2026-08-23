import { readFileSync } from 'node:fs';
import path from 'node:path';

import { z } from 'zod';

const firecrawlEvidenceItemSchema =
  z.object({
    url: z.string().url(),

    title:
      z.string().optional(),

    description:
      z.string().optional(),

    language:
      z.string().optional(),

    statusCode:
      z
        .number()
        .int()
        .optional(),

    verifiedAt:
      z.string().datetime(),

    contentSha256:
      z
        .string()
        .regex(
          /^[a-f0-9]{64}$/,
        ),

    excerpt:
      z.string(),
  });

const firecrawlEvidenceBundleSchema =
  z.object({
    schemaVersion:
      z.literal(1),

    generatedAt:
      z
        .string()
        .datetime()
        .nullable(),

    sources:
      z.array(
        firecrawlEvidenceItemSchema,
      ),
  });

export type FirecrawlEvidenceItem =
  z.infer<
    typeof firecrawlEvidenceItemSchema
  >;

export type FirecrawlEvidenceBundle =
  z.infer<
    typeof firecrawlEvidenceBundleSchema
  >;

const EMPTY_BUNDLE: FirecrawlEvidenceBundle = {
  schemaVersion: 1,
  generatedAt: null,
  sources: [],
};

// Written by scripts/firecrawl-refresh.ts to the repo root, not inside
// apps/web -- it's cross-package generated data, not application source, so
// it's read at runtime rather than statically imported through the `@/*`
// alias (which only resolves within apps/web/src).
const EVIDENCE_PATH = path.resolve(
  process.cwd(),
  '../../data/generated/firecrawl-evidence.json',
);

/**
 * Reads the Firecrawl portfolio-evidence artifact.
 *
 * ponytail: fails toward silence (empty bundle), matching this repo's
 * established convention for optional/generated data (e.g. the offseason
 * notice fallback) -- a missing file (refresh never run), unreadable file,
 * or a malformed/stale schema must never crash the caller.
 *
 * `evidencePath` defaults to the real artifact location; overridable so
 * tests exercise this against a real temp file instead of mocking `fs`
 * (Node's built-in ESM exports are non-configurable, so `vi.spyOn`/`vi.mock`
 * on `node:fs` doesn't reliably intercept calls under this repo's jsdom test
 * environment).
 */
export function getFirecrawlEvidence(
  evidencePath: string = EVIDENCE_PATH,
): FirecrawlEvidenceBundle {
  let raw: unknown;
  try {
    raw = JSON.parse(readFileSync(evidencePath, 'utf8'));
  } catch {
    return EMPTY_BUNDLE;
  }

  const parsed = firecrawlEvidenceBundleSchema.safeParse(raw);
  return parsed.success ? parsed.data : EMPTY_BUNDLE;
}
