import { isIP } from 'node:net';

import { Firecrawl } from 'firecrawl';
import { z } from 'zod';

const DEFAULT_TIMEOUT_MS = 20_000;
const DEFAULT_MAX_AGE_MS = 6 * 60 * 60 * 1000;

const MAX_TIMEOUT_MS = 60_000;
const MAX_SEARCH_RESULTS = 10;
const MAX_SEARCH_QUERY_LENGTH = 500;

const firecrawlEnvSchema = z.object({
  FIRECRAWL_API_KEY: z.string().trim().min(1),
  FIRECRAWL_API_URL: z.string().trim().url().optional(),
});

const firecrawlMetadataSchema = z
  .object({
    sourceURL: z.string().optional(),
    url: z.string().optional(),
    title: z.string().optional(),
    description: z.string().optional(),
    language: z.string().optional(),
    statusCode: z.number().int().optional(),
    scrapeId: z.string().optional(),
  })
  .passthrough();

const firecrawlDocumentSchema = z
  .object({
    markdown: z.string().optional(),
    html: z.string().optional(),
    links: z.array(z.string()).optional(),
    metadata: firecrawlMetadataSchema.optional(),
  })
  .passthrough();

const firecrawlSearchSchema = z
  .object({
    web: z.array(z.unknown()).optional(),
  })
  .passthrough();

const privateIpv4Ranges = [
  /^10\./,
  /^127\./,
  /^169\.254\./,
  /^192\.168\./,
  /^172\.(1[6-9]|2\d|3[01])\./,
];

export type FirecrawlFailureCode =
  | 'configuration'
  | 'invalid-input'
  | 'upstream'
  | 'invalid-response';

export class FirecrawlIntegrationError extends Error {
  readonly code: FirecrawlFailureCode;

  constructor(code: FirecrawlFailureCode, message: string) {
    super(message);

    this.name = 'FirecrawlIntegrationError';
    this.code = code;
  }
}

export interface ScrapePageOptions {
  onlyMainContent?: boolean;
  maxAgeMs?: number;
  timeoutMs?: number;
}

export interface SearchWebOptions {
  limit?: number;
  timeoutMs?: number;
}

export interface ScrapedPage {
  url: string;
  title?: string;
  description?: string;
  language?: string;
  statusCode?: number;
  scrapeId?: string;
  markdown: string;
}

export interface WebSearchHit {
  url: string;
  title?: string;
  description?: string;
  markdown?: string;
}

type FirecrawlClientPort = Pick<Firecrawl, 'scrape' | 'search'>;

function clampInteger(
  value: number | undefined,
  fallback: number,
  minimum: number,
  maximum: number,
): number {
  if (value === undefined || !Number.isFinite(value)) {
    return fallback;
  }

  return Math.min(
    maximum,
    Math.max(minimum, Math.trunc(value)),
  );
}

function isPrivateHostname(hostname: string): boolean {
  const normalized = hostname
    .toLowerCase()
    .replace(/^\[|\]$/g, '');

  if (
    normalized === 'localhost' ||
    normalized === '::1' ||
    normalized.endsWith('.localhost') ||
    normalized.endsWith('.local')
  ) {
    return true;
  }

  const ipVersion = isIP(normalized);

  if (ipVersion === 4) {
    return privateIpv4Ranges.some((pattern) =>
      pattern.test(normalized),
    );
  }

  if (ipVersion === 6) {
    return (
      normalized.startsWith('fc') ||
      normalized.startsWith('fd') ||
      normalized.startsWith('fe8') ||
      normalized.startsWith('fe9') ||
      normalized.startsWith('fea') ||
      normalized.startsWith('feb')
    );
  }

  return false;
}

/**
 * Normalizes and validates a URL before handing it to Firecrawl.
 *
 * This integration intentionally accepts public HTTPS pages only.
 * That prevents accidental localhost/private-network scraping if these
 * helpers are later exposed through an API route or automation.
 */
export function normalizeFirecrawlUrl(
  input: string,
): string {
  let url: URL;

  try {
    url = new URL(input.trim());
  } catch {
    throw new FirecrawlIntegrationError(
      'invalid-input',
      'Firecrawl URL must be a valid absolute URL.',
    );
  }

  if (url.protocol !== 'https:') {
    throw new FirecrawlIntegrationError(
      'invalid-input',
      'Firecrawl sources must use HTTPS.',
    );
  }

  if (url.username || url.password) {
    throw new FirecrawlIntegrationError(
      'invalid-input',
      'Firecrawl source URLs must not contain embedded credentials.',
    );
  }

  if (isPrivateHostname(url.hostname)) {
    throw new FirecrawlIntegrationError(
      'invalid-input',
      'Local and private-network Firecrawl targets are not allowed.',
    );
  }

  // Fragments are client-side and irrelevant to extraction identity.
  url.hash = '';

  return url.toString();
}

function createFirecrawlClient(): Firecrawl {
  const parsed = firecrawlEnvSchema.safeParse({
    FIRECRAWL_API_KEY:
      process.env.FIRECRAWL_API_KEY,

    FIRECRAWL_API_URL:
      process.env.FIRECRAWL_API_URL || undefined,
  });

  if (!parsed.success) {
    throw new FirecrawlIntegrationError(
      'configuration',
      'FIRECRAWL_API_KEY is not configured correctly.',
    );
  }

  return new Firecrawl({
    apiKey: parsed.data.FIRECRAWL_API_KEY,

    ...(parsed.data.FIRECRAWL_API_URL
      ? {
          apiUrl:
            parsed.data.FIRECRAWL_API_URL,
        }
      : {}),
  });
}

function upstreamError(
  operation: 'scrape' | 'search',
): FirecrawlIntegrationError {
  /*
   * Do not propagate raw provider exceptions here.
   *
   * They can contain request/transport information that should not become
   * part of public application error messages or persistent logs.
   */
  return new FirecrawlIntegrationError(
    'upstream',
    `Firecrawl ${operation} request failed.`,
  );
}

function optionalTrimmedString(
  value: unknown,
): string | undefined {
  if (typeof value !== 'string') {
    return undefined;
  }

  const trimmed = value.trim();

  return trimmed.length > 0
    ? trimmed
    : undefined;
}

function normalizeSearchHit(
  value: unknown,
): WebSearchHit | null {
  if (!value || typeof value !== 'object') {
    return null;
  }

  const record =
    value as Record<string, unknown>;

  const metadata =
    record.metadata &&
    typeof record.metadata === 'object'
      ? (record.metadata as Record<
          string,
          unknown
        >)
      : undefined;

  const rawUrl =
    optionalTrimmedString(record.url) ??
    optionalTrimmedString(
      metadata?.sourceURL,
    ) ??
    optionalTrimmedString(metadata?.url);

  if (!rawUrl) {
    return null;
  }

  let url: string;

  try {
    url = normalizeFirecrawlUrl(rawUrl);
  } catch {
    // Invalid search hits are discarded rather than poisoning the
    // entire result set.
    return null;
  }

  return {
    url,

    title:
      optionalTrimmedString(record.title) ??
      optionalTrimmedString(
        metadata?.title,
      ),

    description:
      optionalTrimmedString(
        record.description,
      ) ??
      optionalTrimmedString(
        metadata?.description,
      ),

    markdown:
      optionalTrimmedString(
        record.markdown,
      ),
  };
}

/**
 * Scrape one known page.
 *
 * Firecrawl's current SDK returns a Document directly from scrape().
 */
export async function scrapePage(
  inputUrl: string,
  options: ScrapePageOptions = {},
  client: FirecrawlClientPort =
    createFirecrawlClient(),
): Promise<ScrapedPage> {
  const url =
    normalizeFirecrawlUrl(inputUrl);

  const timeout = clampInteger(
    options.timeoutMs,
    DEFAULT_TIMEOUT_MS,
    1_000,
    MAX_TIMEOUT_MS,
  );

  const maxAge = clampInteger(
    options.maxAgeMs,
    DEFAULT_MAX_AGE_MS,
    0,
    7 * 24 * 60 * 60 * 1000,
  );

  let rawDocument: unknown;

  try {
    rawDocument = await client.scrape(
      url,
      {
        formats: ['markdown'],

        onlyMainContent:
          options.onlyMainContent ?? true,

        removeBase64Images: true,

        blockAds: true,

        timeout,

        /*
         * Reuse Firecrawl cache for portfolio evidence.
         * There is no reason to re-scrape the same source for every
         * development refresh.
         */
        maxAge,
        storeInCache: true,
      },
    );
  } catch {
    throw upstreamError('scrape');
  }

  const parsed =
    firecrawlDocumentSchema.safeParse(
      rawDocument,
    );

  if (!parsed.success) {
    throw new FirecrawlIntegrationError(
      'invalid-response',
      'Firecrawl returned an unexpected scrape response.',
    );
  }

  const metadata =
    parsed.data.metadata;

  const responseUrl =
    optionalTrimmedString(
      metadata?.sourceURL,
    ) ??
    optionalTrimmedString(
      metadata?.url,
    ) ??
    url;

  return {
    url: normalizeFirecrawlUrl(
      responseUrl,
    ),

    title:
      optionalTrimmedString(
        metadata?.title,
      ),

    description:
      optionalTrimmedString(
        metadata?.description,
      ),

    language:
      optionalTrimmedString(
        metadata?.language,
      ),

    statusCode:
      metadata?.statusCode,

    scrapeId:
      optionalTrimmedString(
        metadata?.scrapeId,
      ),

    markdown:
      parsed.data.markdown ?? '',
  };
}

/**
 * Discovery-only web search.
 *
 * We intentionally do not hydrate every result with scrapeOptions here.
 * Discovery and extraction remain separate, reducing latency and API cost.
 */
export async function searchWeb(
  inputQuery: string,
  options: SearchWebOptions = {},
  client: FirecrawlClientPort =
    createFirecrawlClient(),
): Promise<WebSearchHit[]> {
  const query = inputQuery.trim();

  if (
    query.length < 2 ||
    query.length >
      MAX_SEARCH_QUERY_LENGTH
  ) {
    throw new FirecrawlIntegrationError(
      'invalid-input',
      `Firecrawl search query must contain between 2 and ${MAX_SEARCH_QUERY_LENGTH} characters.`,
    );
  }

  const limit = clampInteger(
    options.limit,
    5,
    1,
    MAX_SEARCH_RESULTS,
  );

  const timeout = clampInteger(
    options.timeoutMs,
    DEFAULT_TIMEOUT_MS,
    1_000,
    MAX_TIMEOUT_MS,
  );

  let rawSearch: unknown;

  try {
    rawSearch = await client.search(
      query,
      {
        sources: ['web'],
        limit,
        timeout,
        ignoreInvalidURLs: true,
      },
    );
  } catch {
    throw upstreamError('search');
  }

  const parsed =
    firecrawlSearchSchema.safeParse(
      rawSearch,
    );

  if (!parsed.success) {
    throw new FirecrawlIntegrationError(
      'invalid-response',
      'Firecrawl returned an unexpected search response.',
    );
  }

  return (parsed.data.web ?? [])
    .map(normalizeSearchHit)
    .filter(
      (
        hit,
      ): hit is WebSearchHit =>
        hit !== null,
    )
    .slice(0, limit);
}