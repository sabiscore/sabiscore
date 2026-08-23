import 'server-only';

export {
  FirecrawlIntegrationError,
  normalizeFirecrawlUrl,
  scrapePage,
  searchWeb,
} from '@/lib/firecrawl/client';

export type {
  FirecrawlFailureCode,
  ScrapedPage,
  ScrapePageOptions,
  SearchWebOptions,
  WebSearchHit,
} from '@/lib/firecrawl/client';