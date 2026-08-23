import {
  describe,
  expect,
  it,
  vi,
} from 'vitest';

import {
  FirecrawlIntegrationError,
  normalizeFirecrawlUrl,
  scrapePage,
  searchWeb,
} from '@/lib/firecrawl/client';

describe(
  'normalizeFirecrawlUrl',
  () => {
    it(
      'normalizes public HTTPS URLs and strips fragments',
      () => {
        expect(
          normalizeFirecrawlUrl(
            'https://example.com/path?q=1#section',
          ),
        ).toBe(
          'https://example.com/path?q=1',
        );
      },
    );

    it.each([
      'http://example.com',

      'https://localhost:3000',

      'https://127.0.0.1',

      'https://10.0.0.4',

      'https://192.168.1.2',

      'https://172.16.0.1',

      'https://user:pass@example.com',
    ])(
      'rejects unsafe target %s',
      (url) => {
        expect(() =>
          normalizeFirecrawlUrl(
            url,
          ),
        ).toThrow(
          FirecrawlIntegrationError,
        );
      },
    );
  },
);

describe(
  'scrapePage',
  () => {
    it(
      'normalizes a Firecrawl document into the portfolio contract',
      async () => {
        const client = {
          scrape:
            vi
              .fn()
              .mockResolvedValue({
                markdown:
                  '# Example\n\nPortfolio evidence.',

                metadata: {
                  sourceURL:
                    'https://example.com/',

                  title:
                    'Example',

                  description:
                    'A description',

                  language:
                    'en',

                  statusCode:
                    200,

                  scrapeId:
                    'scrape-123',
                },
              }),

          search:
            vi.fn(),
        };

        const result =
          await scrapePage(
            'https://example.com',

            {},

            client as never,
          );

        expect(
          result,
        ).toEqual({
          url:
            'https://example.com/',

          title:
            'Example',

          description:
            'A description',

          language:
            'en',

          statusCode:
            200,

          scrapeId:
            'scrape-123',

          markdown:
            '# Example\n\nPortfolio evidence.',
        });

        expect(
          client.scrape,
        ).toHaveBeenCalledWith(
          'https://example.com/',

          expect.objectContaining({
            formats: [
              'markdown',
            ],

            onlyMainContent:
              true,

            removeBase64Images:
              true,

            blockAds:
              true,

            storeInCache:
              true,
          }),
        );
      },
    );

    it(
      'does not leak upstream error details',
      async () => {
        const client = {
          scrape:
            vi
              .fn()
              .mockRejectedValue(
                new Error(
                  'Authorization: Bearer secret-value',
                ),
              ),

          search:
            vi.fn(),
        };

        await expect(
          scrapePage(
            'https://example.com',

            {},

            client as never,
          ),
        ).rejects.toMatchObject({
          code:
            'upstream',

          message:
            'Firecrawl scrape request failed.',
        });
      },
    );
  },
);

describe(
  'searchWeb',
  () => {
    it(
      'reads web results from SearchData.web',
      async () => {
        const client = {
          scrape:
            vi.fn(),

          search:
            vi
              .fn()
              .mockResolvedValue({
                web: [
                  {
                    url:
                      'https://example.com/one',

                    title:
                      'One',

                    description:
                      'First result',
                  },

                  {
                    markdown:
                      'Hydrated result',

                    metadata: {
                      sourceURL:
                        'https://example.com/two',

                      title:
                        'Two',
                    },
                  },
                ],
              }),
        };

        const results =
          await searchWeb(
            'portfolio engineering',

            {
              limit: 2,
            },

            client as never,
          );

        expect(
          results,
        ).toEqual([
          {
            url:
              'https://example.com/one',

            title:
              'One',

            description:
              'First result',

            markdown:
              undefined,
          },

          {
            url:
              'https://example.com/two',

            title:
              'Two',

            description:
              undefined,

            markdown:
              'Hydrated result',
          },
        ]);

        expect(
          client.search,
        ).toHaveBeenCalledWith(
          'portfolio engineering',

          expect.objectContaining({
            sources: [
              'web',
            ],

            limit: 2,

            ignoreInvalidURLs:
              true,
          }),
        );
      },
    );

    it(
      'rejects empty search queries before calling Firecrawl',
      async () => {
        const client = {
          scrape:
            vi.fn(),

          search:
            vi.fn(),
        };

        await expect(
          searchWeb(
            ' ',

            {},

            client as never,
          ),
        ).rejects.toMatchObject({
          code:
            'invalid-input',
        });

        expect(
          client.search,
        ).not.toHaveBeenCalled();
      },
    );
  },
);