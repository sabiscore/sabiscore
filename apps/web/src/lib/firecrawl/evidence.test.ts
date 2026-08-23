import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';

import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { getFirecrawlEvidence } from './evidence';

let dir: string;

beforeEach(() => {
  dir = mkdtempSync(path.join(tmpdir(), 'firecrawl-evidence-'));
});

afterEach(() => {
  rmSync(dir, { recursive: true, force: true });
});

function writeEvidence(content: string): string {
  const file = path.join(dir, 'firecrawl-evidence.json');
  writeFileSync(file, content, 'utf8');
  return file;
}

describe('getFirecrawlEvidence', () => {
  it('returns the empty bundle when the artifact has never been generated', () => {
    const missing = path.join(dir, 'does-not-exist.json');

    expect(getFirecrawlEvidence(missing)).toEqual({
      schemaVersion: 1,
      generatedAt: null,
      sources: [],
    });
  });

  it('returns the empty bundle on malformed JSON rather than throwing', () => {
    const file = writeEvidence('{not valid json');

    expect(getFirecrawlEvidence(file)).toEqual({
      schemaVersion: 1,
      generatedAt: null,
      sources: [],
    });
  });

  it('returns the empty bundle when the parsed JSON fails schema validation', () => {
    const file = writeEvidence(JSON.stringify({ schemaVersion: 2 }));

    expect(getFirecrawlEvidence(file)).toEqual({
      schemaVersion: 1,
      generatedAt: null,
      sources: [],
    });
  });

  it('parses a real, valid evidence bundle', () => {
    const bundle = {
      schemaVersion: 1,
      generatedAt: '2026-08-22T10:00:00.000Z',
      sources: [
        {
          url: 'https://example.com/',
          title: 'Example',
          verifiedAt: '2026-08-22T10:00:00.000Z',
          contentSha256: 'a'.repeat(64),
          excerpt: 'Portfolio evidence.',
        },
      ],
    };
    const file = writeEvidence(JSON.stringify(bundle));

    expect(getFirecrawlEvidence(file)).toEqual(bundle);
  });
});
