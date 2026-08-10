import { Configuration, HttpCrawler } from "crawlee";
import { scraperUserAgent } from "./config.mjs";

export class PublicHttpClient {
  constructor({
    minDelayMs = 3000,
    retries = 2,
    respectRobots = true,
    maxRequestsPerMinute = 6,
    timeoutMs = 20_000,
    crawlerFactory = null,
  } = {}) {
    this.minDelayMs = minDelayMs;
    this.retries = retries;
    this.respectRobots = respectRobots;
    this.maxRequestsPerMinute = maxRequestsPerMinute;
    this.timeoutMs = timeoutMs;
    this.crawlerFactory = crawlerFactory;
  }

  async getText(url) {
    let bodyText = null;
    let terminalError = null;
    const options = {
      minConcurrency: 1,
      maxConcurrency: 1,
      maxRequestsPerCrawl: 1,
      maxRequestsPerMinute: this.maxRequestsPerMinute,
      maxRequestRetries: this.retries,
      requestHandlerTimeoutSecs: Math.ceil(this.timeoutMs / 1000),
      navigationTimeoutSecs: Math.ceil(this.timeoutMs / 1000),
      sameDomainDelaySecs: Math.max(1, Math.ceil(this.minDelayMs / 1000)),
      respectRobotsTxtFile: this.respectRobots,
      retryOnBlocked: false,
      useSessionPool: false,
      additionalMimeTypes: ["text/csv", "text/plain", "application/octet-stream"],
      additionalHttpErrorStatusCodes: [408, 425, 429],
      async errorHandler({ request }) {
        const delayMs = Math.min(2_000, 250 * (2 ** Number(request.retryCount ?? 0)))
          + Math.floor(Math.random() * 250);
        await new Promise((resolve) => setTimeout(resolve, delayMs));
      },
      preNavigationHooks: [
        async (_context, requestOptions) => {
          requestOptions.headers = {
            ...requestOptions.headers,
            "user-agent": scraperUserAgent,
            accept: "text/csv,text/plain;q=0.9,*/*;q=0.5",
          };
        },
      ],
      async requestHandler({ body }) {
        bodyText = Buffer.isBuffer(body) ? body.toString("utf8") : String(body);
        if (!bodyText.trim()) throw new Error("empty_response_body");
      },
      async failedRequestHandler({ request }, error) {
        terminalError = new Error(
          `crawl_failed url=${new URL(request.url).origin} attempts=${request.retryCount + 1} reason=${error?.name ?? "Error"}`
        );
      },
    };
    const configuration = new Configuration({ persistStorage: false });
    const crawler = this.crawlerFactory
      ? this.crawlerFactory(options, configuration)
      : new HttpCrawler(options, configuration);
    await crawler.run([{ url, uniqueKey: url }]);
    if (terminalError) throw terminalError;
    if (bodyText === null) throw new Error("crawl_skipped_or_empty");
    return bodyText;
  }
}
