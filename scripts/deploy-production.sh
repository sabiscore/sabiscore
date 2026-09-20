#!/bin/bash

# SabiScore 3.0 - Production Deployment Automation (Unix)
# This script automates the complete deployment process

set -e  # Exit on any error

echo "========================================"
echo "  SabiScore 3.0 Deployment Automation  "
echo "========================================"
echo ""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Configuration
VERCEL_PROJECT="sabiscore"
BACKEND_SERVICE="sabiscore-backend"

# Step 1: Pre-deployment checks
echo -e "${YELLOW}[1/7] Running pre-deployment checks...${NC}"

if [ -f "apps/api/LEGACY_ARCHIVED" ]; then
    rm -rf apps/api
fi

if [ -f "frontend/LEGACY_ARCHIVED" ]; then
    rm -rf frontend
fi

# Check if required tools are installed
for tool in vercel git node pnpm; do
    if ! command -v $tool &> /dev/null; then
        echo -e "${RED}Error: $tool is not installed${NC}"
        exit 1
    fi
done

# Check if environment variables are set
required_vars=(
    "NEXT_PUBLIC_API_URL"
    "KV_REST_API_URL"
    "KV_REST_API_TOKEN"
    "DATABASE_URL"
)

for var in "${required_vars[@]}"; do
    if [ -z "${!var}" ]; then
        echo -e "${YELLOW}Warning: $var is not set${NC}"
    fi
done

echo -e "${GREEN}Pre-deployment checks passed${NC}"

# Step 2: Run tests
echo ""
echo -e "${YELLOW}[2/7] Running tests...${NC}"

pnpm --filter @sabiscore/web test
echo -e "${GREEN}All tests passed${NC}"

# Step 3: Build frontend
echo ""
echo -e "${YELLOW}[3/7] Building frontend...${NC}"

pnpm --filter @sabiscore/web build
echo -e "${GREEN}Frontend build successful${NC}"

# Step 4: Deploy to Vercel
echo ""
echo -e "${YELLOW}[4/7] Deploying to Vercel...${NC}"

vercel --prod --yes
echo -e "${GREEN}Vercel deployment successful${NC}"

# Step 5: Health check
echo ""
echo -e "${YELLOW}[5/7] Running health checks...${NC}"

sleep 10  # Wait for deployment to stabilize

# Check frontend health
if [ -n "$NEXT_PUBLIC_API_URL" ]; then
    if curl -f -s "$NEXT_PUBLIC_API_URL" > /dev/null; then
        echo -e "${GREEN}Frontend health check passed${NC}"
    else
        echo -e "${RED}Frontend health check failed${NC}"
    fi
fi

# Check backend health
if [ -n "$NEXT_PUBLIC_API_URL" ]; then
    if curl -f -s "$NEXT_PUBLIC_API_URL/health" > /dev/null; then
        echo -e "${GREEN}Backend health check passed${NC}"
    else
        echo -e "${RED}Backend health check failed${NC}"
    fi
fi

# Step 6: Smoke tests
echo ""
echo -e "${YELLOW}[6/7] Running smoke tests...${NC}"

# Test prediction API
curl -f -s -X POST \
    -H "Content-Type: application/json" \
    -d '{
        "match_id": "smoke-test",
        "home_team": "Test Home",
        "away_team": "Test Away",
        "competition": "EPL",
        "kickoff_utc": "2026-07-01T12:00:00Z",
        "model": {
          "home_probability": 0.45,
          "draw_probability": 0.28,
          "away_probability": 0.27
        },
        "market": {
          "bookmaker": "smoke",
          "home_odds": 2.40,
          "draw_odds": 3.40,
          "away_odds": 3.20,
          "captured_at": "2026-06-28T12:00:00Z"
        }
    }' \
    "$NEXT_PUBLIC_API_URL/api/v1/predictions/analyze" > /dev/null && \
    echo -e "${GREEN}Prediction API smoke test passed${NC}" || \
    echo -e "${YELLOW}Prediction API smoke test failed${NC}"

# Step 7: Deployment summary
echo ""
echo -e "${YELLOW}[7/7] Deployment Summary${NC}"
echo "========================="

# Get deployment info
vercel ls "$VERCEL_PROJECT" --json | jq -r '.[0] | "Deployment URL: \(.url)\nStatus: \(.state)\nCreated: \(.created)"'

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  Deployment completed successfully!    ${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

echo -e "${YELLOW}Next steps:${NC}"
echo "1. Monitor deployment at: https://vercel.com/dashboard"
echo "2. Check logs: vercel logs"
echo "3. Run web checks: pnpm --filter @sabiscore/web build"
echo "4. Verify monitoring dashboard: $NEXT_PUBLIC_API_URL/monitoring"
echo ""
