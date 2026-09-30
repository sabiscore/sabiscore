# SabiScore — Live Production Verification Report

**Date of Verification**: 2026-09-30  
**Target Environments**:
- **Backend API**: Render Free Tier Linux Container (`https://sabiscore-api-bav1.onrender.com`)
- **Frontend UI**: Vercel Serverless Edge/Node Runtime (`https://web-32ahwz29p-oversabis-projects.vercel.app`)

---

## 1. Live Infrastructure & Health Telemetry

Live probing was performed against the authoritative production endpoints without mocking:

### Endpoint: `GET https://sabiscore-api-bav1.onrender.com/health`
- **HTTP Status**: `200 OK`
- **Reported Git SHA**: `a004dd98906d786eee3360086d6ce15347782999`
- **Uptime**: >8,100 seconds (stable single worker)
- **Container Memory Telemetry (cgroup v2)**:
  - `cgroup_limit_mb`: `512 MB`
  - `cgroup_working_set_mb`: `334 MB`
  - `process_rss_mb`: `329 MB`
  - `headroom_mb`: `177 MB` (healthy buffer well above minimum 50 MB safety margin)
- **Database Status**: PostgreSQL 16 `Connected`
- **Cache Status**: External Redis `Connected`, Tier-1 available, circuits closed
- **Staking Governance State**:
  - `permitted`: `false`
  - `basis`: `"NONE"`
  - `certification_state`: `"UNVERIFIED"`
  - `is_override`: `false`
- **Background Async Lifespan Jobs**:
  - `fixture_sync`: Status `informational`, outcome `ok`, 50 candidates received
  - `settlement`: Status `informational`, outcome `ok`, model `v5_phase7`
  - `clv_capture`: Status `informational`, outcome `ok`
  - `prediction_capture`: Status `informational`, outcome `ok`
  - `notification_dispatch`: Status `informational`, outcome `ok`

### Endpoint: `GET https://sabiscore-api-bav1.onrender.com/health/ready`
- **HTTP Status**: `200 OK`
- **Database**: `Ready`
- **Alembic Migration State**: `0014_social_auth_identities` (Applied head matches migration file head)
- **Models Loaded**: `6 of 6` domestic leagues loaded (`bundesliga`, `epl`, `eredivisie`, `la_liga`, `ligue_1`, `serie_a`) across 12 artifacts
- **Elo Authority**: PostgreSQL containing 26,192 match records across 222 unique teams

---

## 2. Live Data Acquisition & Fixture Integrity

Probing `GET https://sabiscore-api-bav1.onrender.com/api/v1/upcoming/matches?days_ahead=30&limit=10`:
- **HTTP Status**: `200 OK`
- **Verified Scheduled Fixtures Retrieved**: 10 genuine domestic league fixtures scheduled for October 9–10, 2026.
- **Sample Verified Fixture Records**:
  1. `fd-558881`: PSV vs. SC Heerenveen (`EREDIVISIE`, 2026-10-09 18:00 UTC / 19:00 WAT)
  2. `fd-565820`: Dortmund vs. Werder Bremen (`BUNDESLIGA`, 2026-10-09 18:30 UTC / 19:30 WAT)
  3. `fd-559669`: Racing Club de Lens vs. Olympique Lyonnais (`LIGUE_1`, 2026-10-09 18:45 UTC / 19:45 WAT)
  4. `fd-564706`: Málaga CF vs. RCD Espanyol de Barcelona (`LA_LIGA`, 2026-10-09 19:00 UTC / 20:00 WAT)
  5. `fd-560593`: Arsenal FC vs. Leeds United FC (`EPL`, 2026-10-10 11:30 UTC / 12:30 WAT)

Zero synthetic fixtures were produced. Statuses strictly distinguish `scheduled` from `finished` or `timed`.

---

## 3. End-to-End Live Prediction & Decision Serving

Probing `GET https://sabiscore-api-bav1.onrender.com/api/v1/matches/upcoming/fd-558881/full-analysis`:
- **HTTP Status**: `200 OK`
- **Model Output**:
  - `prediction_status`: `"AVAILABLE"`
  - `prediction_source`: `"UNCERTIFIED_MODEL"`
  - `probabilities_available`: `true`
  - `top_outcome_probability`: `0.646` (Home Win: 64.6%, Draw: 21.1%, Away Win: 14.3%)
- **Market Comparison**:
  - Market: Draw
  - Decimal Odds: `7.38` (Pinnacle quote)
  - Model Probability: `0.2112`
  - Calculated Edge: `+0.0830` (+8.30 percentage points)
  - Staking Fraction: `0.0%` (Withheld)
- **Fail-Closed Risk & Staking Controls**:
  - `verdict`: `"PARTIAL"`
  - `stake_permitted`: `false`
  - `critical_gaps`: `["MODEL_GENERATION_UNCERTIFIED", "MODEL_UNCERTAINTY_UNAVAILABLE"]`
  - `advisory_gaps`: 9 non-blocking items
  - `rl_recommendation.abstain`: `true` ("Abstained: insufficient verified evidence")

---

## 4. Frontend Projection & UI Verification Audit

Visual verification was conducted using user-provided production screenshots from Vercel (`web-32ahwz29p-oversabis-projects.vercel.app`):

| UI Component / Surface | Live Observation | Verification Outcome |
| :--- | :--- | :---: |
| **Workspace Header** | "Core ready 100% · 4 of 4 core checks", Postgres Ready, Providers 5 configured · 1 live-validated, Models Ready. | **CONFIRMED** |
| **Notice Banner** | `RESEARCH FORECAST — STAKING DISABLED`: Prominently warns that the model generation has not been certified against the market baseline. | **CONFIRMED** |
| **Tri-State Verdict** | Rendered as `Withheld` badge (`CircleDashed` icon) with headline *"This model hasn't passed certification yet."* | **CONFIRMED** |
| **Probability Triple** | PSV vs. Heerenveen correctly renders Home Win 65%, Draw 21%, Away Win 14%. | **CONFIRMED** |
| **Hypothetical Match** | Arsenal vs. Bournemouth renders clean `—` probabilities without fake data. | **CONFIRMED** |
| **Counter-Case Panel** | Unconditionally renders "Why this might fail", explicitly stating loss probability (35.4%), uncertified edge (8.3pp), 200-sample milestone threshold, and 9 advisory gaps. | **CONFIRMED** |
| **Evidence Passport** | Explicit status badges: Fixture Identity (Resolved), Model Prediction (Resolved), Market Price (Resolved), Model Uncertainty (Gapped), Team Strength (Resolved). | **CONFIRMED** |
| **Timezone Display** | Explicitly labeled as West Africa Time (`WAT`), eliminating client browser timezone confusion. | **CONFIRMED** |
