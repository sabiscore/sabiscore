import { createHash } from 'node:crypto';

import {
  mkdir,
  rename,
  writeFile,
} from 'node:fs/promises';

import path from 'node:path';

import dotenv from 'dotenv';

import {
  FirecrawlIntegrationError,
  normalizeFirecrawlUrl,
  scrapePage,
} from '../lib/firecrawl/client';

dotenv.config({
  path: '.env.local',
  quiet: true,
});

const MAX_SOURCES = 20;
const EXCERPT_LENGTH = 1_200;

const OUTPUT_PATH = path.resolve(
  process.cwd(),
  'data/generated/firecrawl-evidence.json',
);

interface EvidenceItem {
  url: string;

  title?: string;
  description?: string;
  language?: string;

  statusCode?: number;

  verifiedAt: string;

  contentSha256: string;

  excerpt: string;
}

interface EvidenceBundle {
  schemaVersion: 1;

  generatedAt: string;

  sources: EvidenceItem[];
}

function getConfiguredSources(): string[] {
  const rawSources =
    process.env.FIRECRAWL_SOURCE_URLS;

  if (!rawSources?.trim()) {
    throw new Error(
      'FIRECRAWL_SOURCE_URLS is empty. Add a comma-separated list of HTTPS URLs to .env.local.',
    );
  }

  const sources = Array.from(
    new Set(
      rawSources
        .split(',')
        .map((value) => value.trim())
        .filter(Boolean)
        .map(normalizeFirecrawlUrl),
    ),
  );

  if (sources.length === 0) {
    throw new Error(
      'No valid Firecrawl source URLs were configured.',
    );
  }

  if (sources.length > MAX_SOURCES) {
    throw new Error(
      `Refusing to refresh ${sources.length} sources; maximum is ${MAX_SOURCES}.`,
    );
  }

  return sources;
}

function createExcerpt(
  markdown: string,
): string {
  return markdown
    /*
     * Evidence cards do not need embedded code blocks.
     * Keep generated repository data compact.
     */
    .replace(/```[\s\S]*?```/g, ' ')

    .replace(
      /`([^`]+)`/g,
      '$1',
    )

    .replace(/\s+/g, ' ')

    .trim()

    .slice(
      0,
      EXCERPT_LENGTH,
    );
}

function sha256(
  value: string,
): string {
  return createHash('sha256')
    .update(value, 'utf8')
    .digest('hex');
}

async function buildEvidenceItem(
  url: string,
): Promise<EvidenceItem> {
  const page =
    await scrapePage(url, {
      onlyMainContent: true,

      maxAgeMs:
        6 * 60 * 60 * 1000,

      timeoutMs: 20_000,
    });

  return {
    url: page.url,

    ...(page.title
      ? {
          title: page.title,
        }
      : {}),

    ...(page.description
      ? {
          description:
            page.description,
        }
      : {}),

    ...(page.language
      ? {
          language:
            page.language,
        }
      : {}),

    ...(page.statusCode !== undefined
      ? {
          statusCode:
            page.statusCode,
        }
      : {}),

    verifiedAt:
      new Date().toISOString(),

    contentSha256:
      sha256(page.markdown),

    excerpt:
      createExcerpt(
        page.markdown,
      ),
  };
}

async function writeAtomically(
  bundle: EvidenceBundle,
): Promise<void> {
  const directory =
    path.dirname(OUTPUT_PATH);

  const temporaryPath =
    `${OUTPUT_PATH}.tmp`;

  await mkdir(directory, {
    recursive: true,
  });

  await writeFile(
    temporaryPath,

    `${JSON.stringify(
      bundle,
      null,
      2,
    )}\n`,

    'utf8',
  );

  /*
   * Readers see either the previous complete artifact or the new complete
   * artifact, never a half-written JSON document.
   */
  await rename(
    temporaryPath,
    OUTPUT_PATH,
  );
}

async function main(): Promise<void> {
  const dryRun =
    process.argv.includes(
      '--dry-run',
    );

  const sources =
    getConfiguredSources();

  console.info(
    `[firecrawl] refreshing ${sources.length} source(s)`,
  );

  const evidence:
    EvidenceItem[] = [];

  /*
   * Deliberately sequential.
   *
   * Portfolio evidence refreshes are low-volume and do not justify a
   * request burst against Firecrawl.
   */
  for (
    const [index, url]
    of sources.entries()
  ) {
    console.info(
      `[firecrawl] ${index + 1}/${sources.length} ${url}`,
    );

    evidence.push(
      await buildEvidenceItem(
        url,
      ),
    );
  }

  evidence.sort(
    (left, right) =>
      left.url.localeCompare(
        right.url,
      ),
  );

  const bundle:
    EvidenceBundle = {
      schemaVersion: 1,

      generatedAt:
        new Date().toISOString(),

      sources: evidence,
    };

  if (dryRun) {
    console.log(
      JSON.stringify(
        bundle,
        null,
        2,
      ),
    );

    return;
  }

  await writeAtomically(
    bundle,
  );

  console.info(
    `[firecrawl] wrote ${OUTPUT_PATH}`,
  );
}

main().catch(
  (error: unknown) => {
    if (
      error instanceof
      FirecrawlIntegrationError
    ) {
      console.error(
        `[firecrawl] ${error.code}: ${error.message}`,
      );
    } else if (
      error instanceof Error
    ) {
      console.error(
        `[firecrawl] ${error.message}`,
      );
    } else {
      console.error(
        '[firecrawl] refresh failed with an unknown error',
      );
    }

    process.exitCode = 1;
  },
);