#!/bin/sh
set -eu

if [ "${SCRAPER_PRODUCTION_ENABLED:-false}" != "true" ]; then
  printf '%s\n' '{"status":"SKIPPED","reason":"production_activation_disabled"}'
  exit 0
fi

if [ -z "${SABISCORE_ARTIFACT_BUCKET:-}" ]; then
  printf '%s\n' '{"status":"BLOCKED","reason":"missing_required_configuration","field":"SABISCORE_ARTIFACT_BUCKET"}'
  exit 78
fi
if [ -z "${DATABASE_URL:-}" ]; then
  printf '%s\n' '{"status":"BLOCKED","reason":"missing_required_configuration","field":"DATABASE_URL"}'
  exit 78
fi

# V22 section 1.2: cap the worker heap at 512 MB (scoped to this process). A
# run that needs more is misbehaving; fail rather than raise the cap. peakHeapUsed
# is recorded into the manifest's `resource` block (storage.mjs / cli.mjs).
NODE_OPTIONS="--max-old-space-size=512" node /app/apps/scraper/src/cli.mjs scrape
manifest="$(find /app/data/manifests/node-scraper -type f -name '*.manifest.json' -print | sort | tail -n 1)"
if [ -z "$manifest" ]; then
  printf '%s\n' '{"status":"FAIL","reason":"completed_manifest_missing"}'
  exit 1
fi

cd /app/backend
PYTHONPATH=. /opt/sabiscore-worker/bin/python -m src.cli ingest manifest "$manifest" \
  --data-root /app/data --commit
