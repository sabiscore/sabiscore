#!/usr/bin/env bash
set -euo pipefail

# Download models and processed data from external storage.
# Production builds should set MODEL_BASE_URL to a secure HTTPS URL.
# Optionally set MODEL_FETCH_TOKEN to a bearer token used to access private storage.

MODEL_BASE_URL="${MODEL_BASE_URL:-""}"
MODEL_FETCH_TOKEN="${MODEL_FETCH_TOKEN:-""}"
DEST_DIR="${1:-backend}"

if [ -z "$MODEL_BASE_URL" ]; then
  echo "ERROR: MODEL_BASE_URL not set. In production this must be configured as a secret."
  echo "Set MODEL_BASE_URL to the base URL where models are hosted, e.g. https://storage.example.com/sabiscore"
  exit 1
fi

if [[ "$MODEL_BASE_URL" != https://* ]]; then
  echo "ERROR: MODEL_BASE_URL must use https:// for production safety."
  exit 1
fi

mkdir -p "$DEST_DIR/models"
mkdir -p "$DEST_DIR/data/processed"

# List of artifacts to fetch. Keep this in sync with backend expectations.
ARTIFACTS=(
  "models/epl_ensemble.pkl"
  "models/serie_a_ensemble.pkl"
  "models/ligue_1_ensemble.pkl"
  "models/la_liga_ensemble.pkl"
  "models/bundesliga_ensemble.pkl"
  "data/processed/epl_training.csv"
  "data/processed/serie_a_training.csv"
  "data/processed/ligue_1_training.csv"
  "data/processed/la_liga_training.csv"
  "data/processed/bundesliga_training.csv"
)

# If a fetch token is provided, use it as a Bearer token header.
AUTH_HEADER=()
if [ -n "$MODEL_FETCH_TOKEN" ]; then
  AUTH_HEADER=( -H "Authorization: Bearer $MODEL_FETCH_TOKEN" )
fi

for a in "${ARTIFACTS[@]}"; do
  dest="$DEST_DIR/${a}"
  dir=$(dirname "$dest")
  mkdir -p "$dir"
  url="$MODEL_BASE_URL/$a"
  echo "Fetching artifact $a"
  # Retry a few times for transient network errors
  if ! curl -fsSL --retry 3 "${AUTH_HEADER[@]}" "$url" -o "$dest"; then
    echo "ERROR: failed to fetch artifact $a" >&2
    exit 2
  fi
done

echo "Fetch complete. Files placed under $DEST_DIR/models and $DEST_DIR/data/processed"
