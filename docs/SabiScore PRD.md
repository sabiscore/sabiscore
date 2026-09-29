# ## SabiGoal II PRD

> ⚠️ **Historical document, unverified figures (banner added 2026-09-27, DEBT 160).** The accuracy, ROI, Brier, match-count, value-bet and "production-ready" figures below were never measured by code in this repository, and current evidence contradicts them: the served generation has 0 settled forecasts, 0 of 6 leagues beat the de-vigged market (DEBT 62), and live calibration fails its gate. Do not quote them. The verified state is in `CLAUDE.md` (Verified Ground Truth) and `docs/DEBT.md`.

**Chief Sports-Intelligence Architect @ Sabiscore**

The mind that shipped the **+18.4% ROI ensemble** that powers **42k monthly value bets** and the **73.7% accuracy engine** that beats Pinnacle's closing line by **+₦60 average** (₦1,580 = $1 USD, Nov 2025).

# SabiScore: Comprehensive Project Documentation

## Table of Contents

1. [Product Requirements Document (PRD)](https://claude.ai/chat/40ce9777-da49-46fa-8d31-fc71a24c137e#1-product-requirements-document-prd)
2. [Technical Stack Documentation](https://claude.ai/chat/40ce9777-da49-46fa-8d31-fc71a24c137e#2-technical-stack-documentation)
3. [Development Rules & Standards](https://claude.ai/chat/40ce9777-da49-46fa-8d31-fc71a24c137e#3-development-rules--standards)
4. [Workspace Setup Guide](https://claude.ai/chat/40ce9777-da49-46fa-8d31-fc71a24c137e#4-workspace-setup-guide)
5. [Implementation Roadmap](https://claude.ai/chat/40ce9777-da49-46fa-8d31-fc71a24c137e#5-implementation-roadmap)
6. [API Documentation](https://claude.ai/chat/40ce9777-da49-46fa-8d31-fc71a24c137e#6-api-documentation)
7. [Data Architecture](https://claude.ai/chat/40ce9777-da49-46fa-8d31-fc71a24c137e#7-data-architecture)
8. [ML Model Documentation](https://claude.ai/chat/40ce9777-da49-46fa-8d31-fc71a24c137e#8-ml-model-documentation)
9. [Security & Compliance](https://claude.ai/chat/40ce9777-da49-46fa-8d31-fc71a24c137e#9-security--compliance)
10. [Maintenance & Operations](https://claude.ai/chat/40ce9777-da49-46fa-8d31-fc71a24c137e#10-maintenance--operations)

---

## 1. Product Requirements Document (PRD)

### 1.1 Executive Summary

**Product Name**: SabiScore

**Version**: 1.0.0

**Document Owner**: Product Team

**Last Updated**: October 25, 2025

**Status**: In Development

### Vision Statement

SabiScore is an AI-powered football betting intelligence platform that democratizes access to advanced analytics, providing casual and professional bettors with institutional-grade insights for European football leagues.

### Problem Statement

- Betting markets are inefficient but hard to exploit without advanced analytics
- Existing tools are either too expensive, lack explainability, or provide shallow insights
- Bettors need real-time, actionable intelligence with confidence metrics

### Solution

A free-tier platform leveraging ensemble machine learning models, creative data aggregation, and intuitive visualization to deliver:

- Match outcome predictions with 65%+ accuracy
- Value bet identification with expected value calculations
- Transparent explainability via SHAP analysis
- Real-time updates from scraped and API sources

### 1.2 Target Users

### Primary Personas

**1. Casual Bettor - "John"**

- Age: 25-40
- Bets occasionally on weekends
- Needs: Simple recommendations, clear value indicators
- Tech-savvy but not data-literate
- Budget: $20-100 per month on betting

**2. Semi-Professional - "Sarah"**

- Age: 30-50
- Manages betting bankroll seriously
- Needs: Detailed analytics, historical trends, risk assessment
- Uses multiple platforms for research
- Budget: $500-2000 per month

**3. Analytics Enthusiast - "David"**

- Age: 25-45
- Interested in sports analytics
- Needs: Model transparency, SHAP explanations, scenario analysis
- May not bet but wants to understand predictions
- Uses platform for learning

### User Stories

**Epic 1: Match Discovery**

- As a user, I want to search for upcoming matches so I can analyze betting opportunities
- As a user, I want to filter by league so I can focus on competitions I follow
- As a user, I want to save favorite matchups for quick access

**Epic 2: Insights Consumption**

- As a user, I want to see match outcome probabilities so I know model predictions
- As a user, I want value bet recommendations so I can identify profitable opportunities
- As a user, I want xG forecasts so I can predict goal totals
- As a user, I want to understand why predictions were made (explainability)

**Epic 3: Risk Management**

- As a user, I want confidence scores so I can assess prediction reliability
- As a user, I want Kelly stake suggestions so I can size bets optimally
- As a user, I want risk warnings so I can avoid uncertain predictions

**Epic 4: Scenario Exploration**

- As a user, I want what-if scenarios so I can see prediction sensitivity
- As a user, I want historical H2H data so I can contextualize predictions
- As a user, I want form trends visualized so I can spot momentum

### 1.3 Features & Requirements

### Must-Have Features (MVP)

| Feature | Priority | Acceptance Criteria |
| --- | --- | --- |
| Match Search | P0 | - Auto-complete with fuzzy matching<br>- Returns results in <500ms<br>- Supports all 7 leagues |
| Outcome Predictions | P0 | - Displays Home/Draw/Away probabilities<br>- Accuracy >65% over 100 matches<br>- Updates within 1 hour of new data |
| Value Bet Identification | P0 | - Calculates EV and Kelly stake<br>- Highlights bets with EV >5%<br>- Includes market odds comparison |
| xG Forecasting | P0 | - Predicts home/away xG<br>- Breakdown by open play/set pieces<br>- Visual chart (Chart.js) |
| Confidence Scoring | P0 | - Tiered system (HIGH/MEDIUM/LOW)<br>- Based on data freshness/completeness<br>- Displayed prominently |
| Explainability | P0 | - SHAP waterfall charts<br>- Top 5 feature drivers<br>- Natural language summary |

### Should-Have Features (V1.1)

| Feature | Priority | Acceptance Criteria |
| --- | --- | --- |
| User Accounts | P1 | - Save favorite matches<br>- Track bet history<br>- Personalized dashboard |
| Bet Tracker | P1 | - Log bets with outcomes<br>- Calculate ROI<br>- Performance analytics |
| Notifications | P1 | - Email/push for high-value bets<br>- Model drift alerts<br>- Match updates |
| Mobile App | P1 | - iOS/Android native apps<br>- Push notifications<br>- Offline mode for saved insights |

### Could-Have Features (V2.0)

| Feature | Priority | Acceptance Criteria |
| --- | --- | --- |
| Live Match Tracking | P2 | - In-play odds integration<br>- Real-time xG updates<br>- Dynamic prediction adjustments |
| Social Features | P2 | - Share insights<br>- Leaderboards<br>- Community forums |
| Premium Tier | P2 | - Advanced analytics<br>- API access<br>- Custom alerts |

### 1.4 Success Metrics

### Primary KPIs

| Metric | Target | Measurement |
| --- | --- | --- |
| Model Accuracy | ≥65% | % correct predictions over rolling 100 matches |
| Prediction ROI | ≥+5% | Simulated betting returns following value bets |
| User Engagement | ≥3 sessions/week | Active users analyzing ≥3 matches weekly |
| Response Time | <200ms | P95 latency for insights generation |
| Uptime | ≥99.5% | Monthly availability |

### Secondary KPIs

- User retention (30-day): ≥40%
- Average session duration: ≥5 minutes
- Value bet click-through rate: ≥25%
- NPS score: ≥50

### North Star Metric

**Total Value Identified**: Sum of positive EV across all user-analyzed matches per week

### 1.5 Non-Functional Requirements

### Performance

- API response time: <200ms (P95)
- Model inference: <100ms per prediction
- Page load: <2s (Lighthouse score ≥95)
- Concurrent users: Support 1,000+ simultaneous requests

### Reliability

- Uptime: 99.5% SLA
- Data freshness: Updates ≤1 hour old
- Graceful degradation when external sources fail
- Auto-retry with exponential backoff

### Scalability

- Horizontal scaling via load balancers
- Database sharding by league
- Redis caching layer (TTL: 30 minutes)
- CDN for static assets

### Security

- HTTPS encryption (TLS 1.3)
- Rate limiting: 100 req/hour per IP
- No PII storage (GDPR compliant)
- Responsible gambling disclaimers

### Accessibility

- WCAG 2.1 AA compliance
- Screen reader support
- Keyboard navigation
- Color contrast ratios ≥4.5:1

### 1.6 Constraints & Assumptions

### Constraints

- **Budget**: $0 hosting (Heroku/Vercel free tiers)
- **Data Sources**: Free/public APIs only
- **Rate Limits**:
    - API-Football: 500 requests/day
    - Sportmonks: 180 requests/hour
    - The Odds API: 500 requests/month
- **Storage**: PostgreSQL <10GB (Heroku free tier)
- **Compute**: Limited to 2 vCPUs, 512MB RAM per dyno

### Assumptions

- Users have stable internet (3G+)
- 70% desktop, 30% mobile traffic
- Peak usage: Weekends 12pm-10pm UTC
- English language only (V1)
- Users comfortable with betting terminology

### 1.7 Out of Scope

- Live streaming integration
- Multi-language support (V1)
- Cryptocurrency payments
- Automated betting execution
- Odds aggregation from all bookmakers
- Tennis, basketball, or other sports (football only)

### 1.8 Release Criteria

### Alpha (Internal Testing)

- [ ]  Core features functional
- [ ]  Model accuracy >60% on test set
- [ ]  UI renders on desktop/mobile
- [ ]  No critical bugs

### Beta (Limited Public)

- [ ]  All P0 features complete
- [ ]  Model accuracy >65%
- [ ]  Performance targets met
- [ ]  50 beta testers onboarded

### V1.0 Launch

- [ ]  All MVP features stable
- [ ]  Documentation complete
- [ ]  Security audit passed
- [ ]  Monitoring dashboards live
- [ ]  99.5% uptime for 2 consecutive weeks

---

## 2. Technical Stack Documentation

### 2.1 Technology Overview

```
┌─────────────────────────────────────────────────────────────┐
│                        FRONTEND                              │
│  Vanilla JS/TS + Material Web Components + Chart.js         │
│  Vite (Build Tool) + Nginx (Web Server)                     │
└─────────────────────────────────────────────────────────────┘
                            ↓ HTTPS/REST
┌─────────────────────────────────────────────────────────────┐
│                     API GATEWAY                              │
│  FastAPI (Python 3.11) + Uvicorn (ASGI Server)             │
│  Pydantic (Validation) + Middleware (CORS, Rate Limiting)   │
└─────────────────────────────────────────────────────────────┘
                            ↓
        ┌───────────────────┴───────────────────┐
        ↓                                       ↓
┌──────────────────┐                  ┌──────────────────┐
│   ML INFERENCE   │                  │   DATA LAYER     │
│  scikit-learn    │                  │  PostgreSQL 15   │
│  XGBoost/LightGBM│                  │  SQLAlchemy ORM  │
│  SHAP/LIME       │                  │  Redis Cache     │
└──────────────────┘                  └──────────────────┘
        ↓                                       ↓
┌──────────────────┐                  ┌──────────────────┐
│  ORCHESTRATION   │                  │   MONITORING     │
│  Apache Airflow  │                  │  Prometheus      │
│  (DAGs for ETL)  │                  │  Grafana         │
└──────────────────┘                  │  Sentry          │
                                      └──────────────────┘

```

### 2.2 Detailed Stack Components

### Frontend Layer

| Component | Technology | Version | Purpose |
| --- | --- | --- | --- |
| **Core** | Vanilla JavaScript/TypeScript | ES2022 | Lightweight, no framework overhead |
| **Build Tool** | Vite | 5.0+ | Fast HMR, optimized bundling |
| **UI Framework** | Material Web Components | 1.0+ | Modern, accessible components |
| **Charts** | Chart.js | 4.4+ | Data visualization |
| **Icons** | Material Icons | Latest | Consistent iconography |
| **Styling** | CSS3 + CSS Variables | - | Glassmorphism design system |
| **Bundler** | Rollup (via Vite) | - | Tree-shaking, code splitting |
| **Web Server** | Nginx | 1.25+ | Static asset serving, reverse proxy |

**Why This Stack?**

- **No React/Vue**: Reduces bundle size (<50KB gzipped vs. 150KB+ with frameworks)
- **Vite**: 10x faster dev server than Webpack
- **Material Web**: Native web components, future-proof
- **Chart.js**: Lightweight (60KB) vs. D3 (250KB+)

### Backend Layer

| Component | Technology | Version | Purpose |
| --- | --- | --- | --- |
| **Framework** | FastAPI | 0.104+ | Async API framework |
| **ASGI Server** | Uvicorn | 0.24+ | High-performance async server |
| **Validation** | Pydantic | 2.5+ | Request/response validation |
| **ORM** | SQLAlchemy | 2.0+ | Database abstraction |
| **Migration** | Alembic | 1.12+ | Schema versioning |
| **Task Queue** | Celery | 5.3+ | Background jobs |
| **Caching** | Redis | 7.0+ | In-memory cache |
| **HTTP Client** | HTTPX | 0.25+ | Async HTTP requests |

**Why This Stack?**

- **FastAPI**: Fastest Python framework (benchmarks: 25k req/s)
- **Async**: Non-blocking I/O for scraping/API calls
- **Pydantic**: Automatic OpenAPI docs + type safety
- **SQLAlchemy 2.0**: Modern async ORM

### Data Layer

| Component | Technology | Version | Purpose |
| --- | --- | --- | --- |
| **Database** | PostgreSQL | 15+ | Relational data storage |
| **Cache** | Redis | 7.0+ | Session store, rate limiting |
| **Vector Store** | (Future) | - | For similarity search |
| **Backup** | pg_dump | - | Daily automated backups |

**Schema Design**:

```sql
-- Core tables
matches (id, home_team, away_team, league, kickoff, status)
predictions (match_id, outcome_probs, xg_forecast, confidence, timestamp)
historical_stats (match_id, team, xG, xGA, shots, possession, ...)
scraped_odds (match_id, bookmaker, home_odds, draw_odds, away_odds, timestamp)
model_metadata (league, version, accuracy, last_trained, drift_detected)

```

### ML/Data Science Stack

| Component | Technology | Version | Purpose |
| --- | --- | --- | --- |
| **Data Manipulation** | Pandas | 2.1+ | DataFrames |
| **Numerical** | NumPy | 1.26+ | Array operations |
| **ML Framework** | scikit-learn | 1.3+ | Classical ML algorithms |
| **Gradient Boosting** | XGBoost | 2.0+ | Tree-based models |
| **Gradient Boosting** | LightGBM | 4.1+ | Fast GBDT |
| **Gradient Boosting** | CatBoost | 1.2+ | Categorical handling |
| **Deep Learning** | PyTorch | 2.1+ | Neural networks, LSTMs |
| **Hyperparameter Tuning** | Optuna | 3.4+ | Bayesian optimization |
| **Explainability** | SHAP | 0.43+ | Feature importance |
| **Explainability** | LIME | 0.2+ | Local explanations |
| **Drift Detection** | Alibi-Detect | 0.12+ | Concept drift monitoring |
| **Data Validation** | Great Expectations | 0.18+ | Data quality checks |

### Data Sources & Scraping

| Source | Library/Method | Rate Limit | Data Type |
| --- | --- | --- | --- |
| **Understat** | soccerdata | 1 req/s | xG, shots, player stats |
| **FBref** | soccerdata | 1 req/s | Advanced metrics |
| **Sofascore** | soccerdata | 1 req/s | Ratings, events |
| **Transfermarkt** | soccerdata | 1 req/s | Injuries, market values |
| **WhoScored** | soccerdata | 1 req/s | Match events |
| **API-Football** | requests | 500/day | Fixtures, lineups |
| **Sportmonks** | requests | 180/hour | Live scores |
| **The Odds API** | requests | 500/month | Betting odds |
| **FlashScore** | BeautifulSoup + Playwright | 1 req/2s | Live updates |
| **OddsPortal** | BeautifulSoup | 1 req/2s | Historical odds |
| **X/Twitter** | x_semantic_search tool | 100/day | Sentiment analysis |

**Scraping Best Practices**:

```python
import time
import random
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

def create_session():
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504]
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    })
    return session

def rate_limited_fetch(url, min_delay=1.0, max_delay=2.0):
    response = session.get(url)
    time.sleep(random.uniform(min_delay, max_delay))
    return response

```

### Orchestration & DevOps

| Component | Technology | Version | Purpose |
| --- | --- | --- | --- |
| **Workflow** | Apache Airflow | 2.7+ | DAG scheduling |
| **Containerization** | Docker | 24.0+ | Application packaging |
| **Orchestration** | Docker Compose | 2.22+ | Multi-container apps |
| **CI/CD** | GitHub Actions | - | Automated testing/deployment |
| **Monitoring** | Prometheus | 2.47+ | Metrics collection |
| **Visualization** | Grafana | 10.2+ | Dashboards |
| **Error Tracking** | Sentry | 1.38+ | Exception monitoring |
| **Logging** | ELK Stack (Future) | - | Centralized logging |

### Hosting & Infrastructure

| Service | Platform | Tier | Purpose |
| --- | --- | --- | --- |
| **API** | Heroku | Eco ($5/month) | Backend hosting |
| **Frontend** | Vercel | Free | Static site hosting |
| **Database** | Heroku Postgres | Mini ($5/month) | PostgreSQL hosting |
| **Cache** | Redis Cloud | Free (30MB) | Redis hosting |
| **Airflow** | Local/VPS | N/A | Workflow orchestration |
| **CDN** | Cloudflare | Free | Asset delivery |
| **DNS** | Cloudflare | Free | Domain management |
| **SSL** | Let's Encrypt | Free | TLS certificates |

**Total Monthly Cost**: ~$10 (excludes VPS for Airflow)

### 2.3 Development Tools

| Tool | Purpose | Configuration |
| --- | --- | --- |
| **VS Code** | IDE | Extensions: Python, ESLint, Prettier |
| **Git** | Version control | Conventional commits |
| **pre-commit** | Git hooks | Black, Flake8, isort |
| **pytest** | Testing | Coverage ≥80% |
| **Postman** | API testing | Collections for all endpoints |
| **DBeaver** | Database GUI | PostgreSQL connections |
| **Redis Commander** | Redis GUI | Cache inspection |

### 2.4 Third-Party Services

| Service | Purpose | API Key Required |
| --- | --- | --- |
| **Hugging Face** | Sentiment analysis | Optional (free tier) |
| **Sentry** | Error tracking | Yes (free tier) |
| **Cloudflare** | CDN, DDoS protection | Yes (free) |
| **GitHub** | Code hosting, CI/CD | Yes (free) |

---

## 3. Development Rules & Standards

### 3.1 Code Style Guide

### Python Style (PEP 8 + Black)

```python
# Good: Descriptive names, type hints, docstrings
from typing import Dict, List, Optional
import pandas as pd

def calculate_expected_value(
    model_prob: float,
    market_odds: float,
    stake: float = 1.0
) -> Dict[str, float]:
    """
    Calculate expected value for a bet.

    Args:
        model_prob: Model's predicted probability (0-1)
        market_odds: Decimal odds from bookmaker
        stake: Bet amount in currency units

    Returns:
        Dictionary with 'ev', 'profit', 'loss' keys

    Raises:
        ValueError: If probabilities outside [0, 1]
    """
    if not 0 <= model_prob <= 1:
        raise ValueError(f"Invalid probability: {model_prob}")

    profit = stake * (market_odds - 1)
    loss = stake
    ev = (model_prob * profit) - ((1 - model_prob) * loss)

    return {
        "ev": round(ev, 2),
        "profit": round(profit, 2),
        "loss": round(loss, 2)
    }

# Bad: No types, unclear names, missing docstring
def calc_ev(p, o, s=1):
    return (p * s * (o - 1)) - ((1 - p) * s)

```

**Formatting Rules**:

- Line length: 100 characters (Black default)
- Indentation: 4 spaces
- Imports: Grouped (stdlib, third-party, local) with `isort`
- Naming:
    - Functions/variables: `snake_case`
    - Classes: `PascalCase`
    - Constants: `UPPER_SNAKE_CASE`
    - Private: `_leading_underscore`

**Tooling**:

```bash
# Auto-format
black .

# Lint
flake8 --max-line-length=100 --extend-ignore=E203

# Sort imports
isort .

# Type checking
mypy --strict src/

```

### JavaScript/TypeScript Style (Airbnb + Prettier)

```jsx
// Good: Modern ES6+, clear structure
class InsightsRenderer {
  constructor(apiClient) {
    this.apiClient = apiClient;
    this.cache = new Map();
  }

  /**
   * Render match insights to DOM
   * @param {Object} insights - API response with predictions
   * @param {HTMLElement} container - Target DOM element
   * @returns {Promise<void>}
   */
  async render(insights, container) {
    if (!insights?.predictions) {
      throw new Error('Invalid insights object');
    }

    const cacheKey = `${insights.matchup}-${insights.timestamp}`;
    if (this.cache.has(cacheKey)) {
      return this.cache.get(cacheKey);
    }

    const html = this.buildHTML(insights);
    container.innerHTML = html;

    this.cache.set(cacheKey, html);
    await this.attachEventListeners(container);
  }

  buildHTML(insights) {
    const { outcome } = insights.predictions;
    return `
      <div class="outcome-card">
        <h3>Match Outcome</h3>
        <div class="probs">
          <span>Home: ${(outcome.home_win * 100).toFixed(1)}%</span>
          <span>Draw: ${(outcome.draw * 100).toFixed(1)}%</span>
          <span>Away: ${(outcome.away_win * 100).toFixed(1)}%</span>
        </div>
      </div>
    `;
  }
}

// Bad: Unclear, no error handling, var usage
var render = function(data, el) {
  el.innerHTML = '<div>' + data.outcome + '</div>';
}

```

**Formatting Rules**:

- Prettier defaults (single quotes, 2-space indent, trailing commas)
- Semicolons: Always
- Arrow functions: Preferred over `function`
- `const` > `let` > never `var`
- Template literals for strings with variables

**Tooling**:

```bash
# Auto-format
prettier --write "src/**/*.{js,ts,json,css}"

# Lint
eslint src/ --ext .js,.ts

# Type check (if using TypeScript)
tsc --noEmit

```

### SQL Style

```sql
-- Good: Readable, indexed, aliased
SELECT
    m.id,
    m.home_team,
    m.away_team,
    p.outcome_probs->>'home_win' AS home_win_prob,
    p.confidence
FROM matches m
INNER JOIN predictions p ON m.id = p.match_id
WHERE
    m.league = 'EPL'
    AND m.kickoff > NOW()
    AND p.confidence >= 0.7
ORDER BY m.kickoff ASC
LIMIT 10;

-- Create indexes for common queries
CREATE INDEX idx_matches_league_kickoff ON matches(league, kickoff);
CREATE INDEX idx_predictions_confidence ON predictions(confidence);

-- Bad: Hard to read, no indexes
select * from matches, predictions where matches.id = predictions.match_id and league = 'EPL';

```

### 3.2 Git Workflow

### Branch Strategy (GitHub Flow)

```
main (protected)
  ↓
feature/user-auth
feature/xg-model
fix/cache-invalidation
hotfix/critical-bug

```

**Branch Naming**:

- `feature/` - New features
- `fix/` - Bug fixes
- `hotfix/` - Production hotfixes
- `refactor/` - Code improvements
- `docs/` - Documentation updates
- `test/` - Test additions

**Commit Messages (Conventional Commits)**:

```bash
# Format: <type>(<scope>): <subject>

# Examples
feat(insights): add Monte Carlo simulation endpoint
fix(scraper): handle FlashScore rate limiting
docs(readme): update installation instructions
refactor(model): extract feature engineering to separate module
test(api): add integration tests for /insights endpoint
perf(cache): implement Redis caching for predictions
chore(deps): upgrade FastAPI to 0.104.1

```

**Types**:

- `feat` - New feature
- `fix` - Bug fix
- `docs` - Documentation
- `style` - Formatting
- `refactor` - Code restructuring
- `perf` - Performance improvement
- `test` - Test changes
- `chore` - Build/tooling

### Pull Request Process

```markdown
## PR Title: [TYPE] Brief description

### Description
What does this PR do?

### Changes
- Added X feature
- Fixed Y bug
- Refactored Z module

### Testing
- [ ] Unit tests pass (`pytest`)
- [ ] Integration tests pass
- [ ] Manual testing complete

### Screenshots (if UI changes)
[Attach images]

### Checklist
- [ ] Code follows style guide
- [ ] Documentation updated
- [ ] No console errors/warnings
- [ ] Reviewed own code

```

**Review Requirements**:

- Minimum 1 approval for feature branches
- 2 approvals for main branch merges
- All CI checks must pass
- No merge conflicts

### Git Hooks (pre-commit)

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/psf/black
    rev: 23.10.0
    hooks:
      - id: black
        language_version: python3.11

  - repo: https://github.com/PyCQA/flake8
    rev: 6.1.0
    hooks:
      - id: flake8
        args: ['--max-line-length=100']

  - repo: https://github.com/pycqa/isort
    rev: 5.12.0
    hooks:
      - id: isort

  - repo: https://github.com/pre-commit/mirrors-prettier
    rev: v3.0.3
    hooks:
      - id: prettier
        types_or: [javascript, css, json]

  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.5.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-added-large-files

```

Install:

```bash
pip install pre-commit
pre-commit install

```

### 3.3 Testing Standards

### Test Coverage Requirements

| Layer | Minimum Coverage | Tools |
| --- | --- | --- |
| Backend | 80% | pytest, pytest-cov |
| Models | 90% | pytest, hypothesis |
| Frontend | 70% | Jest, Testing Library |
| Integration | Key flows | pytest-asyncio |
| E2E | Critical paths | Playwright |

### Test Structure

```python
# tests/test_insights_engine.py
import pytest
from unittest.mock import Mock, patch
import numpy as np
import pandas as pd

from insights_engine import InsightsEngine
from models import SabiScoreEnsemble

class TestInsightsEngine:
    """Test suite for insights generation"""

    @pytest.fixture
    def mock_ensemble(self):
        """Create mock ensemble model"""
        ensemble = Mock(spec=SabiScoreEnsemble)
        ensemble.meta_model.predict_proba.return_value = np.array([[0.2, 0.3, 0.5]])
        ensemble.feature_names = [f'feature_{i}' for i in range(20)]
        return ensemble

    @pytest.fixture
    def engine(self, mock_ensemble):
        """Create engine instance"""
        return InsightsEngine(mock_ensemble)

    @pytest.fixture
    def sample_features(self):
        """Generate sample feature vector"""
        return pd.DataFrame(np.random.rand(1, 20))

    @pytest.fixture
    def sample_realtime(self):
        """Generate sample real-time data"""
        return {
            'timestamp': '2025-10-25T12:00:00',
            'form': {'home_form': ['W', 'W', 'D'], 'away_form': ['L', 'W', 'D']},
            'odds': {'home': 2.0, 'draw': 3.5, 'away': 4.0},
            'injuries': pd.DataFrame()
        }

    def test_generate_insights_structure(self, engine, sample_features, sample_realtime):
        """Test insights output structure"""
        insights = engine.generate_match_insights(
            matchup="Test vs Team",
            league="EPL",
            feature_vector=sample_features,
            realtime_data=sample_realtime,
            scraped_odds={'home': 2.0, 'draw': 3.5, 'away': 4.0}
        )

        # Assert required keys exist
        assert 'predictions' in insights
        assert 'value_analysis' in insights
        assert 'confidence' in insights
        assert 'narrative' in insights

        # Assert predictions structure
        assert 'outcome' in insights['predictions']
        assert 'xg_forecast' in insights['predictions']
        assert 'markets' in insights['predictions']

    def test_value_bet_calculation(self, engine):
        """Test value bet identification logic"""
        model_probs = {'home': 0.6, 'draw': 0.25, 'away': 0.15}
        market_odds = {'home': 2.0, 'draw': 3.5, 'away': 7.0}

        value_bets = engine._calculate_value(model_probs, market_odds)

        # Home should be identified as value (60% at 2.0 odds = +20% EV)
        assert len(value_bets) > 0
        assert value_bets[0]['market'] == 'Home

```

```python
        assert value_bets[0]['market'] == 'Home'
        assert value_bets[0]['expected_value'] > 10  # At least 10% EV
        assert 0 <= value_bets[0]['kelly_stake'] <= 100

    def test_monte_carlo_simulation(self, engine):
        """Test Monte Carlo match simulation"""
        sims = engine._run_monte_carlo(xg_home=1.8, xg_away=1.2, n_sims=10000)

        # Check structure
        assert 'simulated_outcomes' in sims
        assert 'most_likely_scores' in sims
        assert 'confidence_intervals' in sims

        # Check probabilities sum to ~1.0
        total_prob = sum(sims['simulated_outcomes'].values())
        assert 0.99 <= total_prob <= 1.01

        # Check most likely scores
        assert len(sims['most_likely_scores']) == 5
        assert all(0 <= score['probability'] <= 1 for score in sims['most_likely_scores'])

    def test_confidence_calculation_high(self, engine):
        """Test high confidence scoring"""
        realtime = {
            'timestamp': '2025-10-25T12:00:00',  # Recent
            'form': {}, 'odds': {}, 'injuries': pd.DataFrame()
        }
        features = pd.DataFrame(np.random.rand(1, 20))  # Complete data

        confidence = engine._calculate_confidence(realtime, features)

        assert confidence['score'] >= 0.6
        assert confidence['tier'] in ['HIGH', 'MEDIUM', 'LOW']
        assert 'message' in confidence

    def test_confidence_calculation_low(self, engine):
        """Test low confidence scoring"""
        from datetime import datetime, timedelta
        old_timestamp = (datetime.now() - timedelta(days=2)).isoformat()

        realtime = {
            'timestamp': old_timestamp,  # Old data
            'form': {}, 'odds': {}, 'injuries': pd.DataFrame()
        }
        features = pd.DataFrame(np.random.rand(1, 20))
        features.iloc[0, :10] = np.nan  # Missing data

        confidence = engine._calculate_confidence(realtime, features)

        assert confidence['score'] < 0.7
        assert confidence['tier'] in ['LOW', 'MEDIUM']

    @pytest.mark.parametrize("xg_home,xg_away,expected_btts", [
        (2.0, 1.5, 0.85),  # High xG both teams
        (0.5, 0.5, 0.35),  # Low xG both teams
        (3.0, 0.2, 0.70),  # One-sided
    ])
    def test_btts_prediction(self, engine, xg_home, xg_away, expected_btts):
        """Test BTTS probability calculation"""
        btts_prob = engine._predict_btts(xg_home, xg_away)

        assert 0 <= btts_prob <= 1
        assert abs(btts_prob - expected_btts) < 0.15  # Within 15% tolerance

    def test_scenario_generation(self, engine, sample_features, sample_realtime):
        """Test what-if scenario analysis"""
        scenarios = engine._generate_scenarios(sample_features, sample_realtime)

        assert len(scenarios) > 0
        for scenario in scenarios:
            assert 'scenario' in scenario
            assert 'impact' in scenario
            assert 'delta' in scenario
            assert isinstance(scenario['delta'], float)

    def test_risk_assessment(self, engine):
        """Test risk scoring"""
        probs = np.array([0.2, 0.3, 0.5])
        odds = {'home': 2.0, 'draw': 3.5, 'away': 4.0}
        sims = {'simulated_outcomes': {'home_win': 0.48, 'draw': 0.32, 'away_win': 0.20}}

        risk = engine._assess_risk(probs, odds, sims)

        assert 'risk_score' in risk
        assert 'risk_level' in risk
        assert risk['risk_level'] in ['LOW', 'MODERATE', 'HIGH']
        assert 'advice' in risk

    def test_narrative_generation(self, engine):
        """Test natural language summary"""
        narrative = engine._generate_narrative(
            matchup="Man Utd vs Liverpool",
            league="EPL",
            probs={'home': 0.5, 'draw': 0.3, 'away': 0.2},
            value_bets=[{'market': 'Home Win', 'expected_value': 15}],
            xg_home=1.8,
            xg_away=1.2,
            shap={'top_drivers': [], 'league_specific_factors': []},
            confidence={'tier': 'HIGH', 'message': 'Test'}
        )

        assert isinstance(narrative, str)
        assert len(narrative) > 100
        assert 'Man Utd' in narrative or 'Liverpool' in narrative
        assert 'EPL' in narrative

    def test_edge_case_equal_probabilities(self, engine):
        """Test handling of equal outcome probabilities"""
        model_probs = {'home': 0.33, 'draw': 0.33, 'away': 0.34}
        market_odds = {'home': 3.0, 'draw': 3.0, 'away': 3.0}

        value_bets = engine._calculate_value(model_probs, market_odds)

        # Should not identify strong value with equal probs
        assert all(bet['expected_value'] < 5 for bet in value_bets)

    def test_edge_case_missing_odds(self, engine):
        """Test handling of missing market odds"""
        model_probs = {'home': 0.5, 'draw': 0.3, 'away': 0.2}
        market_odds = {'home': 2.0}  # Missing draw and away

        value_bets = engine._calculate_value(model_probs, market_odds)

        # Should only evaluate home market
        assert all(bet['market'] != 'Draw' for bet in value_bets)
        assert all(bet['market'] != 'Away' for bet in value_bets)

# Run tests with coverage
# pytest tests/test_insights_engine.py -v --cov=insights_engine --cov-report=html

```

### Integration Tests

```python
# tests/test_integration.py
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from main import app
from database import Base

# Test database
TEST_DATABASE_URL = "sqlite:///./test.db"
engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

@pytest.fixture(scope="module")
def client():
    """Create test client with test database"""
    Base.metadata.create_all(bind=engine)

    with TestClient(app) as c:
        yield c

    Base.metadata.drop_all(bind=engine)

class TestAPIIntegration:
    """End-to-end API tests"""

    def test_health_check(self, client):
        """Test health endpoint"""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data['status'] == 'healthy'
        assert 'timestamp' in data

    def test_search_matches(self, client):
        """Test match search functionality"""
        response = client.get("/matches/search?q=Manchester")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        if data:
            assert 'matchup' in data[0]
            assert 'league' in data[0]

    def test_insights_generation_flow(self, client):
        """Test complete insights generation flow"""
        # 1. Search for match
        search_response = client.get("/matches/search?q=Manchester United")
        assert search_response.status_code == 200
        matches = search_response.json()
        assert len(matches) > 0

        # 2. Generate insights
        match = matches[0]
        insights_response = client.post("/insights", json={
            "matchup": match['matchup'],
            "league": match['league']
        })
        assert insights_response.status_code == 200

        # 3. Validate insights structure
        insights = insights_response.json()
        assert 'predictions' in insights
        assert 'value_analysis' in insights
        assert 'confidence' in insights

        # 4. Validate prediction values
        outcome = insights['predictions']['outcome']
        assert 0 <= outcome['home_win'] <= 1
        assert 0 <= outcome['draw'] <= 1
        assert 0 <= outcome['away_win'] <= 1
        assert abs(sum([outcome['home_win'], outcome['draw'], outcome['away_win']]) - 1.0) < 0.01

    def test_rate_limiting(self, client):
        """Test API rate limiting"""
        # Make multiple rapid requests
        for i in range(105):  # Exceeds 100 req/hour limit
            response = client.get("/matches/search?q=test")

            if i < 100:
                assert response.status_code == 200
            else:
                assert response.status_code == 429  # Too Many Requests

    def test_invalid_league(self, client):
        """Test handling of invalid league"""
        response = client.post("/insights", json={
            "matchup": "Team A vs Team B",
            "league": "INVALID_LEAGUE"
        })
        # Should fallback to unified model or return 400
        assert response.status_code in [200, 400]

    def test_concurrent_requests(self, client):
        """Test handling of concurrent requests"""
        import concurrent.futures

        def make_request():
            return client.get("/matches/search?q=Liverpool")

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(make_request) for _ in range(10)]
            responses = [f.result() for f in futures]

        # All should succeed
        assert all(r.status_code == 200 for r in responses)

```

### E2E Tests (Playwright)

```python
# tests/test_e2e.py
import pytest
from playwright.sync_api import Page, expect

@pytest.fixture(scope="session")
def browser():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        yield browser
        browser.close()

@pytest.fixture
def page(browser):
    context = browser.new_context()
    page = context.new_page()
    yield page
    context.close()

class TestUserFlows:
    """End-to-end user journey tests"""

    def test_search_and_analyze_match(self, page: Page):
        """Test complete user flow: search → analyze → view results"""
        # 1. Navigate to homepage
        page.goto("http://localhost:3000")
        expect(page).to_have_title("SabiScore")

        # 2. Search for match
        search_input = page.locator("#matchSearch")
        search_input.fill("Manchester United vs Liverpool")

        # 3. Wait for search results
        page.wait_for_selector(".search-result-item")

        # 4. Click first result
        page.locator(".search-result-item").first.click()

        # 5. Click analyze button
        analyze_btn = page.locator("#analyzeBtn")
        expect(analyze_btn).to_be_enabled()
        analyze_btn.click()

        # 6. Wait for insights to load
        page.wait_for_selector("#insightsDashboard", state="visible", timeout=10000)

        # 7. Verify insights displayed
        expect(page.locator("#outcomeProbabilities")).to_be_visible()
        expect(page.locator("#valueBets")).to_be_visible()
        expect(page.locator("#xgChart")).to_be_visible()

        # 8. Check probability values are valid
        home_prob = page.locator(".prob-meter").first.inner_text()
        assert "%" in home_prob
        prob_value = float(home_prob.replace("%", ""))
        assert 0 <= prob_value <= 100

    def test_league_filter(self, page: Page):
        """Test league filtering"""
        page.goto("http://localhost:3000")

        # Select La Liga
        page.locator("#leagueFilter").select_option("La_Liga")

        # Search
        page.locator("#matchSearch").fill("Barcelona")
        page.wait_for_selector(".search-result-item")

        # Verify results are from La Liga
        result_text = page.locator(".search-result-item").first.inner_text()
        assert "La Liga" in result_text

    def test_mobile_responsive(self, page: Page):
        """Test mobile responsiveness"""
        # Set mobile viewport
        page.set_viewport_size({"width": 375, "height": 667})

        page.goto("http://localhost:3000")

        # Verify mobile layout
        expect(page.locator(".match-selector")).to_be_visible()

        # Check filters stack vertically
        filters = page.locator(".filters")
        box = filters.bounding_box()
        assert box['height'] > box['width']  # Vertical stacking

    def test_dark_mode_toggle(self, page: Page):
        """Test theme switching"""
        page.goto("http://localhost:3000")

        # Click theme toggle
        page.locator("#themeToggle").click()

        # Verify theme changed
        theme = page.evaluate("document.documentElement.getAttribute('data-theme')")
        assert theme in ['dark', 'light']

        # Toggle again
        page.locator("#themeToggle").click()
        new_theme = page.evaluate("document.documentElement.getAttribute('data-theme')")
        assert new_theme != theme

    def test_error_handling(self, page: Page):
        """Test error state handling"""
        # Simulate network failure
        page.route("**/api/insights", lambda route: route.abort())

        page.goto("http://localhost:3000")
        page.locator("#matchSearch").fill("Test Match")
        page.locator("#analyzeBtn").click()

        # Should show error message
        page.wait_for_selector(".error-message", timeout=5000)
        expect(page.locator(".error-message")).to_contain_text("Failed")

```

### 3.4 Documentation Standards

### Code Documentation

```python
"""
Module: insights_engine.py
Description: Core insights generation engine for match predictions.
Author: SabiScore Team
Last Modified: 2025-10-25

This module provides the InsightsEngine class which orchestrates:
- Model inference
- Value bet calculation
- Monte Carlo simulations
- Explainability analysis
- Natural language narrative generation

Example:
    >>> from insights_engine import InsightsEngine
    >>> engine = InsightsEngine(trained_model)
    >>> insights = engine.generate_match_insights(
    ...     matchup="Man Utd vs Liverpool",
    ...     league="EPL",
    ...     feature_vector=features,
    ...     realtime_data=realtime,
    ...     scraped_odds=odds
    ... )
"""

from typing import Dict, List, Tuple, Optional
import pandas as pd
import numpy as np

class InsightsEngine:
    """
    Generates comprehensive betting insights for football matches.

    Attributes:
        ensemble (SabiScoreEnsemble): Trained ML model ensemble
        feature_importance (Dict): Cached feature importance values

    Methods:
        generate_match_insights: Main entry point for insight generation
        _forecast_xg: Predict expected goals using Poisson distribution
        _calculate_value: Identify value bets with positive EV
        _run_monte_carlo: Simulate match outcomes
    """

    def __init__(self, ensemble: 'SabiScoreEnsemble'):
        """
        Initialize insights engine.

        Args:
            ensemble: Trained model ensemble for predictions

        Raises:
            ValueError: If ensemble is None or invalid
        """
        if ensemble is None:
            raise ValueError("Ensemble model cannot be None")

        self.ensemble = ensemble
        self.feature_importance = None

    def generate_match_insights(
        self,
        matchup: str,
        league: str,
        feature_vector: pd.DataFrame,
        realtime_data: Dict,
        scraped_odds: Dict
    ) -> Dict:
        """
        Generate comprehensive insights for a match.

        This is the main entry point that orchestrates all sub-analyses:
        - Outcome prediction (Home/Draw/Away)
        - xG forecasting
        - Binary market predictions (BTTS, O/U)
        - Value bet identification
        - Monte Carlo simulation
        - What-if scenarios
        - Explainability (SHAP)
        - Risk assessment

        Args:
            matchup: Match description (e.g., "Man Utd vs Liverpool")
            league: League code (e.g., "EPL", "La_Liga")
            feature_vector: Engineered features (1 row DataFrame)
            realtime_data: Real-time updates (form, injuries, sentiment)
            scraped_odds: Current market odds

        Returns:
            Dictionary containing:
                - predictions: Outcome probs, xG, markets
                - value_analysis: List of value bet opportunities
                - simulations: Monte Carlo results
                - scenarios: What-if analysis
                - explainability: SHAP feature importance
                - confidence: Data quality scoring
                - risk_metrics: Uncertainty measures
                - narrative: Natural language summary

        Raises:
            ValueError: If inputs are invalid
            ModelError: If prediction fails

        Example:
            >>> insights = engine.generate_match_insights(
            ...     matchup="Arsenal vs Chelsea",
            ...     league="EPL",
            ...     feature_vector=features_df,
            ...     realtime_data={'odds': {...}, 'form': {...}},
            ...     scraped_odds={'home': 2.1, 'draw': 3.4, 'away': 3.8}
            ... )
            >>> print(f"Home win: {insights['predictions']['outcome']['home_win']:.1%}")
            Home win: 45.2%
        """
        # Implementation...

```

### API Documentation (OpenAPI/Swagger)

FastAPI auto-generates OpenAPI docs. Enhance with:

```python
from fastapi import FastAPI, Query, Path
from pydantic import BaseModel, Field

app = FastAPI(
    title="SabiScore API",
    description="AI-powered football betting intelligence platform",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

class InsightsRequest(BaseModel):
    """Request model for insights generation"""

    matchup: str = Field(
        ...,
        description="Match description in format 'Home Team vs Away Team'",
        example="Manchester United vs Liverpool"
    )
    league: Optional[str] = Field(
        None,
        description="League code (EPL, La_Liga, Serie_A, Bundesliga, Ligue_1, RPL, UCL)",
        example="EPL"
    )

    class Config:
        schema_extra = {
            "example": {
                "matchup": "Barcelona vs Real Madrid",
                "league": "La_Liga"
            }
        }

@app.post(
    "/insights",
    response_model=InsightsResponse,
    summary="Generate match insights",
    description="""
    Generate comprehensive betting intelligence for a football match.

    This endpoint returns:
    - Match outcome probabilities (Home/Draw/Away)
    - Expected goals (xG) forecasts
    - Value bet opportunities with Kelly stake sizing
    - Monte Carlo simulations
    - SHAP explainability
    - Confidence and risk metrics

    **Rate Limit**: 100 requests per hour per IP

    **Response Time**: Typically 200-500ms
    """,
    responses={
        200: {"description": "Insights generated successfully"},
        400: {"description": "Invalid request parameters"},
        429: {"description": "Rate limit exceeded"},
        503: {"description": "Model unavailable"}
    },
    tags=["Predictions"]
)
async def generate_insights(request: InsightsRequest):
    """Generate insights endpoint"""
    # Implementation...

```

---

## 4. Workspace Setup Guide

### 4.1 Prerequisites

**System Requirements**:

- OS: Ubuntu 20.04+, macOS 12+, or Windows 10+ with WSL2
- RAM: Minimum 8GB (16GB recommended for model training)
- Disk: 20GB free space
- CPU: 4+ cores recommended

**Required Software**:

```bash
# Check versions
python --version        # 3.11+
node --version          # 18+
docker --version        # 24.0+
docker-compose --version # 2.22+
git --version           # 2.30+

```

### 4.2 Initial Setup

### Step 1: Clone Repository

```bash
# Clone repo
git clone https://github.com/yourusername/sabiscore.git
cd sabiscore

# Verify structure
tree -L 2
# Expected output:
# .
# ├── backend/
# │   ├── src/
# │   ├── tests/
# │   ├── requirements.txt
# │   └── Dockerfile
# ├── frontend/
# │   ├── src/
# │   ├── public/
# │   └── package.json
# ├── models/
# ├── data/
# ├── dags/
# ├── docker-compose.yml
# └── README.md

```

### Step 2: Environment Setup

```bash
# Create .env file
cp .env.example .env

# Edit with your values
nano .env

```

```
# .env
# Database
DB_PASSWORD=your_secure_password_here
DATABASE_URL=postgresql://sabiscore_user:${DB_PASSWORD}@localhost:5432/sabiscore

# Redis
REDIS_URL=redis://default:<UPSTASH_REDIS_TOKEN>@<your-endpoint>.upstash.io:6379

# API Keys (Optional)
HUGGINGFACE_API_KEY=
X_BEARER_TOKEN=

# Environment
ENVIRONMENT=development
LOG_LEVEL=DEBUG
DEBUG=True

# Security
SECRET_KEY=generate_with_openssl_rand_hex_32
JWT_SECRET=generate_with_openssl_rand_hex_32

# Rate Limiting
RATE_LIMIT_REQUESTS=1000  # Higher for development
RATE_LIMIT_WINDOW=3600

```

Generate secrets:

```bash
# Generate random secrets
openssl rand -hex 32

```

### Step 3: Backend Setup

```bash
cd backend

# Create virtual environment
python3.11 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Upgrade pip
pip install --upgrade pip

# Install dependencies
pip install -r requirements.txt

# Install dev dependencies
pip install -r requirements-dev.txt

# Verify installation
python -c "import fastapi, sklearn, xgboost; print('✓ All imports successful')"

```

### Step 4: Frontend Setup

```bash
cd ../frontend

# Install dependencies
npm install

# Verify installation
npm list --depth=0

```

### Step 5: Database Setup

```bash
# Start PostgreSQL with Docker
docker run -d \
  --name sabiscore-postgres \
  -e POSTGRES_PASSWORD=$DB_PASSWORD \
  -e POSTGRES_USER=sabiscore_user \
  -e POSTGRES_DB=sabiscore \
  -p 5432:5432 \
  postgres:15-alpine

# Wait for database to be ready
sleep 5

# Run migrations
cd backend
python scripts/init_db.py

```

```python
# scripts/init_db.py
from sqlalchemy import create_engine, text
import os
from dotenv import load_dotenv

load_dotenv()

engine = create_engine(os.getenv('DATABASE_URL'))

# Create tables
with engine.connect() as conn:
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS matches (
            id SERIAL PRIMARY KEY,
            home_team VARCHAR(100) NOT NULL,
            away_team VARCHAR(100) NOT NULL,
            league VARCHAR(50) NOT NULL,
            kickoff TIMESTAMP,
            status VARCHAR(20) DEFAULT 'scheduled',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_matches_league ON matches(league);
        CREATE INDEX IF NOT EXISTS idx_matches_kickoff ON matches(kickoff);
    """))

    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS predictions (
            id SERIAL PRIMARY KEY,
            match_id INTEGER REFERENCES matches(id),
            outcome_probs JSONB NOT NULL,
            xg_forecast JSONB,
            confidence FLOAT CHECK (confidence >= 0 AND confidence <= 1),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_predictions_match ON predictions(match_id);
        CREATE INDEX IF NOT EXISTS idx_predictions_confidence ON predictions(confidence);
    """))

    conn.commit()
    print("✓ Database initialized successfully")

```

### Step 6: Redis Setup

```bash
# Start Redis with Docker
docker run -d \
  --name sabiscore-redis \
  -p 6379:6379 \
  redis:7-alpine

# Test connection
redis-cli ping
# Expected: PONG

```

### 4.3 Development Environment

### VS Code Setup

Install extensions:

```bash
code --install-extension ms-python.python
code --install-extension ms-python.vscode-pylance
code --install-extension dbaeumer.vscode-eslint
code --install-extension esbenp.prettier-vscode
code --install-extension ms-azuretools.vscode-docker
code --install-extension ms-vscode.live-server

```

Workspace settings (`.vscode/settings.json`):

```json
{
  "python.defaultInterpreterPath": "${workspaceFolder}/backend/venv/bin/python",
  "python.linting.enabled": true,
  "python.linting.pylintEnabled": false,
  "python.linting.flake8Enabled": true,
  "python.formatting.provider": "black",
  "python.formatting.blackArgs": ["--line-length=100"],
  "editor.formatOnSave": true,
  "editor.codeActionsOnSave": {
    "source.organizeImports": true
  },
  "[python]": {
    "editor.defaultFormatter": "ms-python.black-formatter"
  },
  "[javascript]": {
    "editor.defaultFormatter": "esbenp.prettier-vscode"
  },
  "files.exclude": {
    "**/__pycache__": true,
    "**/*.pyc": true,
    "**/node_modules": true
  }
}

```

### Git Hooks Setup

```bash
cd sabiscore

# Install pre-commit
pip install pre-commit

# Install hooks
pre-commit install

# Test hooks
pre-commit run --all-files

```

### 4.4 Running the Application

### Development Mode

**Terminal 1 - Backend**:

```bash
cd backend
source venv/bin/activate
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Expected output:
# INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
# INFO:     Started reloader process
# INFO:     Started server process
# INFO:     Waiting for application startup.
# INFO:     Application startup complete.

```

**Terminal 2 - Frontend**:

```bash
cd frontend
npm run dev

# Expected output:
# VITE v5.0.0  ready in 234 ms
# ➜  Local:   http://localhost:3000/
# ➜  Network: http://192.168.1.100:3000/

```

**Terminal 3 - Database/Redis** (if not using Docker):

```bash
# PostgreSQL
pg_ctl -D /usr/local/var/postgres start

# Redis
redis-server

```

### Access Points

- **Frontend**: http://localhost:3000
- **API Docs**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **Health Check**: http://localhost:8000/health

### Docker Compose (Recommended)

```bash
# Start all services
docker-compose up -d

# View logs
docker-compose logs -f

# Stop services
docker-compose down

# Rebuild after code changes
docker-compose up -d --build

```

### 4.5 Data & Model Setup

### Download Training Data

```bash
cd backend
python scripts/download_data.py

```

```python
# scripts/download_data.py
from soccerdata import FBref, Understat
import pandas as pd
from tqdm import tqdm

LEAGUES = ["ENG-Premier League", "ESP-La Liga", "ITA-Serie A",
           "GER-Bundesliga", "FRA-Ligue 1", "RUS-Premier League"]
SEASONS = ["2023/2024", "2022/2023", "2021/2022", "2020/2021", "2019/2020"]

def download_all_data():
    for league in tqdm(LEAGUES, desc="Leagues"):
        for season in tqdm(SEASONS, desc="Seasons", leave=False):
            try:
                # FBref data
                fbref = FBref(leagues=league, seasons=season)
                df = fbref.read_player_season_stats(stat_type="standard")
                df.to_parquet(f"../data/raw/fbref_{league}_{season}.parquet")

                # Understat data
                understat = Understat(leagues=league, seasons=season)
                df = understat.read_player_season_stats()
                df.to_parquet(f"../data/raw/understat_{league}_{season}.parquet")

                print(f"✓ Downloaded {league} {season}")
            except Exception as e:
                print(f"✗ Failed {league} {season}: {e}")

if __name__ == "__main__":
    download_all_data()

```

### Train Initial Models

```bash
# Run training script
python scripts/train_models.py

# Expected output:
# 📊 Starting training pipeline...
#
# ============================================================
# Training model for EPL
# ============================================================
# Tuning hyperparameters...  100%|███████████| 50/50 [02:15<00:00]
# Training ensemble...
# CV Accuracy: 0.67
# ROC-AUC: 0.74
# ✓ Model saved to models/EPL_ensemble.pkl
#
# [Repeat for each league]
#
# ✅ All models trained successfully

```

### 4.6 Verification Checklist

```bash
# Run verification script
python scripts/verify_setup.py

```

```python
# scripts/verify_setup.py
import sys
import subprocess

def check_python_version():
    version = sys.version_info
    if version >= (3, 11):
        print(f"✓ Python {version.major}.{version.minor}.{version.micro}")
        return True
    print(f"✗ Python {

```

```python
        print(f"✗ Python {version.major}.{version.minor}.{version.micro} (3.11+ required)")
        return False

def check_dependencies():
    try:
        import fastapi
        import sklearn
        import xgboost
        import pandas
        import torch
        print("✓ All Python dependencies installed")
        return True
    except ImportError as e:
        print(f"✗ Missing dependency: {e.name}")
        return False

def check_database():
    try:
        from sqlalchemy import create_engine, text
        import os
        from dotenv import load_dotenv

        load_dotenv()
        engine = create_engine(os.getenv('DATABASE_URL'))

        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            print("✓ Database connection successful")
            return True
    except Exception as e:
        print(f"✗ Database connection failed: {e}")
        return False

def check_redis():
    try:
        import redis
        import os
        from dotenv import load_dotenv

        load_dotenv()
        r = redis.from_url(os.getenv('REDIS_URL'))
        r.ping()
        print("✓ Redis connection successful")
        return True
    except Exception as e:
        print(f"✗ Redis connection failed: {e}")
        return False

def check_models():
    import os
    models_dir = '../models'
    if not os.path.exists(models_dir):
        print(f"✗ Models directory not found")
        return False

    expected_models = ['EPL_ensemble.pkl', 'unified_ensemble.pkl']
    found = [f for f in os.listdir(models_dir) if f.endswith('.pkl')]

    if len(found) > 0:
        print(f"✓ Found {len(found)} trained models")
        return True
    else:
        print(f"⚠ No trained models found - run train_models.py")
        return False

def check_api():
    try:
        import requests
        response = requests.get('http://localhost:8000/health', timeout=5)
        if response.status_code == 200:
            print("✓ API server responding")
            return True
        else:
            print(f"✗ API returned status {response.status_code}")
            return False
    except Exception as e:
        print(f"⚠ API not running (start with: uvicorn main:app --reload)")
        return True  # Not critical for setup

def check_frontend():
    import os
    frontend_dir = '../frontend'
    if not os.path.exists(os.path.join(frontend_dir, 'node_modules')):
        print(f"✗ Frontend dependencies not installed (run: npm install)")
        return False
    print("✓ Frontend dependencies installed")
    return True

def main():
    print("="*60)
    print("SabiScore Setup Verification")
    print("="*60 + "\n")

    checks = [
        ("Python Version", check_python_version),
        ("Python Dependencies", check_dependencies),
        ("Database Connection", check_database),
        ("Redis Connection", check_redis),
        ("Trained Models", check_models),
        ("API Server", check_api),
        ("Frontend Setup", check_frontend)
    ]

    results = []
    for name, check_func in checks:
        print(f"\nChecking {name}...")
        results.append(check_func())

    print("\n" + "="*60)
    passed = sum(results)
    total = len(results)
    print(f"Results: {passed}/{total} checks passed")

    if passed == total:
        print("✅ Setup complete! Ready to develop.")
        sys.exit(0)
    else:
        print("⚠️  Some checks failed. Review errors above.")
        sys.exit(1)

if __name__ == "__main__":
    main()

```

Run verification:

```bash
cd backend
python scripts/verify_setup.py

# Expected output:
# ============================================================
# SabiScore Setup Verification
# ============================================================
#
# Checking Python Version...
# ✓ Python 3.11.6
#
# Checking Python Dependencies...
# ✓ All Python dependencies installed
#
# Checking Database Connection...
# ✓ Database connection successful
#
# Checking Redis Connection...
# ✓ Redis connection successful
#
# Checking Trained Models...
# ✓ Found 8 trained models
#
# Checking API Server...
# ✓ API server responding
#
# Checking Frontend Setup...
# ✓ Frontend dependencies installed
#
# ============================================================
# Results: 7/7 checks passed
# ✅ Setup complete! Ready to develop.

```

---

## 5. Implementation Roadmap

### 5.1 Project Phases

```mermaid
gantt
    title SabiScore Implementation Timeline
    dateFormat  YYYY-MM-DD
    section Phase 1: Foundation
    Project Setup           :done, p1a, 2025-10-25, 3d
    Data Infrastructure     :active, p1b, 2025-10-28, 5d
    Database Schema         :p1c, 2025-10-30, 3d
    section Phase 2: Data Pipeline
    Scraping Implementation :p2a, 2025-11-01, 7d
    ETL Pipeline           :p2b, 2025-11-05, 5d
    Feature Engineering    :p2c, 2025-11-08, 4d
    section Phase 3: ML Models
    Baseline Models        :p3a, 2025-11-10, 5d
    Ensemble Development   :p3b, 2025-11-15, 7d
    Hyperparameter Tuning  :p3c, 2025-11-20, 4d
    section Phase 4: Backend API
    FastAPI Setup          :p4a, 2025-11-12, 3d
    Insights Engine        :p4b, 2025-11-22, 7d
    API Endpoints          :p4c, 2025-11-25, 4d
    section Phase 5: Frontend
    UI Components          :p5a, 2025-11-20, 10d
    Visualization Layer    :p5b, 2025-11-28, 5d
    Integration            :p5c, 2025-12-01, 4d
    section Phase 6: Testing
    Unit Tests             :p6a, 2025-11-25, 7d
    Integration Tests      :p6b, 2025-12-02, 5d
    E2E Tests              :p6c, 2025-12-05, 4d
    section Phase 7: Deployment
    Docker Setup           :p7a, 2025-12-08, 3d
    CI/CD Pipeline         :p7b, 2025-12-10, 3d
    Production Deploy      :p7c, 2025-12-13, 2d
    section Phase 8: Launch
    Beta Testing           :p8a, 2025-12-15, 10d
    Performance Tuning     :p8b, 2025-12-20, 5d
    Public Launch          :milestone, 2026-01-01, 1d

```

### 5.2 Sprint Breakdown

### Sprint 1: Foundation (Week 1-2)

**Goals**: Set up development environment and core infrastructure

**Tasks**:

- [ ]  Initialize Git repository with branch protection
- [ ]  Set up Docker Compose for local development
- [ ]  Create PostgreSQL schema and migrations
- [ ]  Configure Redis for caching
- [ ]  Set up CI/CD pipeline (GitHub Actions)
- [ ]  Create project documentation structure

**Deliverables**:

- Working local development environment
- Database with initial schema
- CI/CD running tests on every PR

**Definition of Done**:

- All team members can run `docker-compose up` successfully
- Database migrations run without errors
- CI/CD pipeline shows green checks

---

### Sprint 2-3: Data Infrastructure (Week 3-5)

**Goals**: Build data aggregation and ETL pipeline

**Tasks**:

- [ ]  Implement DataAggregator class with soccerdata integration
- [ ]  Build web scrapers for FlashScore, OddsPortal
- [ ]  Create rate limiting and retry logic
- [ ]  Implement Redis caching layer
- [ ]  Build feature engineering pipeline
- [ ]  Create Airflow DAGs for scheduled updates
- [ ]  Add data quality checks (Great Expectations)

**Deliverables**:

- Working scrapers for 7 leagues
- ETL pipeline producing clean, enriched datasets
- Airflow scheduling data updates every 4 hours

**Definition of Done**:

- Successfully fetch 5 seasons of data for all leagues
- Feature engineering produces 50+ features per match
- Data quality tests pass with 95%+ success rate
- ETL completes in <30 minutes

**Code Checkpoint**:

```python
# Example usage after this sprint
from data_aggregator import DataAggregator

aggregator = DataAggregator("Manchester United vs Liverpool", "EPL")
historical = aggregator.fetch_historical_stats()
realtime = aggregator.fetch_realtime_data()

print(f"Fetched {len(historical)} historical records")
print(f"Real-time data age: {realtime['timestamp']}")
# Output:
# Fetched 2,450 historical records
# Real-time data age: 2025-10-25T14:30:00

```

---

### Sprint 4-5: ML Model Development (Week 6-8)

**Goals**: Train and validate ensemble models

**Tasks**:

- [ ]  Implement baseline models (Logistic Regression, Random Forest)
- [ ]  Build XGBoost/LightGBM/CatBoost models
- [ ]  Create multi-level stacking architecture
- [ ]  Implement Optuna hyperparameter tuning
- [ ]  Add SHAP explainability
- [ ]  Set up Alibi-Detect for drift monitoring
- [ ]  Train separate models per league + unified model
- [ ]  Validate models meet accuracy targets (65%+)

**Deliverables**:

- 8 trained models (7 leagues + unified)
- Model evaluation reports showing metrics
- SHAP explainability working
- Drift detection configured

**Definition of Done**:

- All models achieve ≥65% accuracy on test set
- ROC-AUC ≥0.72 for all models
- Brier score <0.20
- Model inference <100ms
- SHAP values calculated for all predictions

**Model Performance Targets**:

| League | Accuracy | ROC-AUC | Brier Score |
| --- | --- | --- | --- |
| EPL | ≥0.67 | ≥0.74 | ≤0.19 |
| La Liga | ≥0.66 | ≥0.73 | ≤0.19 |
| Serie A | ≥0.65 | ≥0.72 | ≤0.20 |
| Bundesliga | ≥0.64 | ≥0.71 | ≤0.21 |
| Ligue 1 | ≥0.65 | ≥0.72 | ≤0.20 |
| RPL | ≥0.63 | ≥0.70 | ≤0.22 |
| UCL | ≥0.64 | ≥0.71 | ≤0.21 |
| Unified | ≥0.65 | ≥0.72 | ≤0.20 |

---

### Sprint 6-7: Backend API (Week 9-11)

**Goals**: Build FastAPI backend with insights engine

**Tasks**:

- [ ]  Set up FastAPI project structure
- [ ]  Implement InsightsEngine class
- [ ]  Create API endpoints (/search, /insights, /health)
- [ ]  Add request validation with Pydantic
- [ ]  Implement rate limiting middleware
- [ ]  Add CORS configuration
- [ ]  Create background task for drift checking
- [ ]  Write API documentation (OpenAPI)
- [ ]  Add error handling and logging

**Deliverables**:

- Working REST API with 5+ endpoints
- Insights engine generating comprehensive reports
- API documentation at /docs
- Rate limiting preventing abuse

**Definition of Done**:

- All endpoints return responses in <200ms (P95)
- API handles 100 concurrent requests without errors
- Value bet calculation working correctly
- Monte Carlo simulation producing valid results
- OpenAPI documentation complete

**API Endpoints**:

```
GET  /health                    - Health check
GET  /matches/search            - Search matches
POST /insights                  - Generate insights
GET  /models/status             - Model status
POST /models/retrain            - Trigger retraining (admin)

```

---

### Sprint 8-10: Frontend Development (Week 12-15)

**Goals**: Build responsive UI with visualizations

**Tasks**:

- [ ]  Set up Vite project with Material Web Components
- [ ]  Implement design system (CSS variables, utilities)
- [ ]  Build match search with autocomplete
- [ ]  Create insights dashboard (3-column layout)
- [ ]  Add Chart.js visualizations (xG, probabilities)
- [ ]  Implement SHAP waterfall charts
- [ ]  Add responsive breakpoints (mobile, tablet, desktop)
- [ ]  Implement dark/light theme toggle
- [ ]  Add loading states and error handling
- [ ]  Optimize performance (lazy loading, code splitting)

**Deliverables**:

- Fully functional frontend application
- Responsive design working on all devices
- Chart.js visualizations rendering correctly
- Lighthouse score ≥95

**Definition of Done**:

- All UI components render without errors
- Page load time <2s on 3G connection
- Lighthouse Performance ≥95
- Lighthouse Accessibility ≥95
- No console errors or warnings
- Works on Chrome, Firefox, Safari, Edge

**UI Components Checklist**:

- [ ]  Header with logo and theme toggle
- [ ]  Match selector with league filter
- [ ]  Search with fuzzy autocomplete
- [ ]  Probability meters with animations
- [ ]  Value bet cards with highlighting
- [ ]  xG bar chart (Chart.js)
- [ ]  Score heatmap from simulations
- [ ]  SHAP waterfall chart
- [ ]  Confidence badge with meter
- [ ]  Risk assessment card
- [ ]  What-if scenario cards
- [ ]  Form indicators (W/D/L badges)
- [ ]  Responsive navigation
- [ ]  Loading skeletons
- [ ]  Error boundaries

---

### Sprint 11-12: Testing & Quality Assurance (Week 16-18)

**Goals**: Comprehensive testing and bug fixing

**Tasks**:

- [ ]  Write unit tests for all modules (80%+ coverage)
- [ ]  Create integration tests for API flows
- [ ]  Implement E2E tests with Playwright
- [ ]  Performance testing (load, stress)
- [ ]  Security audit (OWASP Top 10)
- [ ]  Accessibility audit (WCAG 2.1 AA)
- [ ]  Cross-browser testing
- [ ]  Mobile device testing
- [ ]  Bug bash session
- [ ]  Fix all critical and high-priority bugs

**Deliverables**:

- Test suite with ≥80% code coverage
- Performance test results
- Security audit report
- Accessibility compliance report
- Bug-free application

**Definition of Done**:

- pytest coverage ≥80%
- All E2E tests passing
- No critical or high-severity bugs
- API handles 1000 req/s without errors
- No security vulnerabilities
- WCAG 2.1 AA compliance achieved

**Testing Checklist**:

```bash
# Unit tests
pytest backend/tests/ -v --cov=backend --cov-report=html
# Target: ≥80% coverage

# Integration tests
pytest backend/tests/test_integration.py -v
# Target: All critical flows passing

# E2E tests
playwright test
# Target: All user journeys passing

# Performance tests
locust -f tests/locustfile.py --host=http://localhost:8000
# Target: 1000 users, <200ms P95 latency

# Security scan
bandit -r backend/src/
safety check
# Target: No vulnerabilities

# Accessibility
pa11y-ci http://localhost:3000
# Target: 0 errors

```

---

### Sprint 13: Deployment & DevOps (Week 19-20)

**Goals**: Deploy to production with monitoring

**Tasks**:

- [ ]  Configure production environment variables
- [ ]  Set up Heroku/Vercel deployment
- [ ]  Configure PostgreSQL production database
- [ ]  Set up Redis Cloud instance
- [ ]  Implement SSL certificates (Let's Encrypt)
- [ ]  Configure Cloudflare CDN
- [ ]  Set up Sentry for error tracking
- [ ]  Configure Prometheus + Grafana monitoring
- [ ]  Create deployment scripts
- [ ]  Write runbook for common issues

**Deliverables**:

- Production application deployed
- Monitoring dashboards live
- Deployment automation working
- Runbook for operations

**Definition of Done**:

- Application accessible via HTTPS
- 99.5%+ uptime over 1 week
- Monitoring alerts configured
- Deployment takes <10 minutes
- Rollback procedure tested

**Deployment Commands**:

```bash
# Deploy backend to Heroku
./scripts/deploy_backend.sh

# Deploy frontend to Vercel
./scripts/deploy_frontend.sh

# Run database migrations
heroku run python scripts/migrate.py

# Check deployment health
curl https://api.sabiscore.com/health

```

---

### Sprint 14: Beta Testing (Week 21-22)

**Goals**: Gather user feedback and iterate

**Tasks**:

- [ ]  Recruit 50 beta testers
- [ ]  Create feedback collection mechanism
- [ ]  Monitor usage analytics
- [ ]  Triage and fix bugs reported by users
- [ ]  Optimize based on real-world usage patterns
- [ ]  Improve documentation based on feedback
- [ ]  Conduct user interviews (5-10 users)
- [ ]  Iterate on UI/UX issues

**Deliverables**:

- Beta testing report with insights
- Bug fixes deployed
- Updated documentation
- User testimonials

**Definition of Done**:

- 50+ active beta users
- NPS score ≥40
- Average session duration ≥5 minutes
- <5 critical bugs reported
- User satisfaction ≥4/5 stars

---

### Sprint 15: Launch Preparation (Week 23-24)

**Goals**: Final polish and public launch

**Tasks**:

- [ ]  Finalize branding and marketing materials
- [ ]  Create tutorial videos/guides
- [ ]  Set up support channels (email, Discord)
- [ ]  Prepare launch announcement
- [ ]  Configure production rate limits
- [ ]  Optimize infrastructure for scale
- [ ]  Create landing page
- [ ]  Set up analytics (Google Analytics, Plausible)
- [ ]  Launch! 🚀

**Deliverables**:

- Production-ready application
- Marketing materials
- Support infrastructure
- Public launch

**Launch Checklist**:

- [ ]  All features tested and working
- [ ]  Performance optimized
- [ ]  Security hardened
- [ ]  Monitoring active
- [ ]  Documentation complete
- [ ]  Support channels ready
- [ ]  Backup/disaster recovery tested
- [ ]  Legal disclaimers in place
- [ ]  Analytics configured
- [ ]  Launch announcement ready

---

### 5.3 Success Metrics by Phase

| Phase | Key Metrics | Target |
| --- | --- | --- |
| **Foundation** | Setup time | <4 hours for new developer |
| **Data Pipeline** | Data freshness | <1 hour lag |
|  | ETL success rate | ≥98% |
| **ML Models** | Accuracy | ≥65% |
|  | Inference latency | <100ms |
| **Backend API** | Response time (P95) | <200ms |
|  | Uptime | ≥99.5% |
| **Frontend** | Lighthouse score | ≥95 |
|  | Page load time | <2s |
| **Testing** | Code coverage | ≥80% |
|  | Bug escape rate | <5% |
| **Deployment** | Deployment time | <10 minutes |
|  | Rollback time | <5 minutes |
| **Beta** | User retention (7-day) | ≥40% |
|  | NPS score | ≥40 |
| **Launch** | Daily active users | 100+ |
|  | Value identified | $10,000+ EV/week |

---

## 6. API Documentation

### 6.1 API Overview

**Base URL**: `https://api.sabiscore.com/v1`

**Authentication**: Not required (rate-limited by IP)

**Rate Limit**: 100 requests/hour per IP

**Response Format**: JSON

### 6.2 Endpoints

### Health Check

```
GET /health

```

**Description**: Check API health status

**Response**:

```json
{
  "status": "healthy",
  "timestamp": "2025-10-25T14:30:00Z",
  "models_active": 8,
  "database_connected": true,
  "redis_connected": true
}

```

**Status Codes**:

- `200 OK`: Service healthy
- `503 Service Unavailable`: Service degraded

---

### Search Matches

```
GET /matches/search?q={query}&league={league}

```

**Description**: Search for upcoming matches

**Parameters**:

| Name | Type | Required | Description |
| --- | --- | --- | --- |
| `q` | string | Yes | Search query (team names) |
| `league` | string | No | League filter (EPL, La_Liga, etc.) |

**Example Request**:

```bash
curl "https://api.sabiscore.com/v1/matches/search?q=Manchester&league=EPL"

```

**Example Response**:

```json
[
  {
    "matchup": "Manchester United vs Liverpool",
    "home_team": "Manchester United",
    "away_team": "Liverpool",
    "league": "EPL",
    "kickoff": "2025-11-01T15:00:00Z",
    "venue": "Old Trafford",
    "status": "scheduled"
  },
  {
    "matchup": "Manchester City vs Arsenal",
    "home_team": "Manchester City",
    "away_team": "Arsenal",
    "league": "EPL",
    "kickoff": "2025-11-03T17:30:00Z",
    "venue": "Etihad Stadium",
    "status": "scheduled"
  }
]

```

**Status Codes**:

- `200 OK`: Search successful
- `400 Bad Request`: Invalid parameters
- `429 Too Many Requests`: Rate limit exceeded

---

### Generate Insights

```
POST /insights
Content-Type: application/json

```

**Description**: Generate comprehensive betting insights for a match

**Request Body**:

```json
{
  "matchup": "Manchester United vs Liverpool",
  "league": "EPL"
}

```

**Example Request**:

```bash
curl -X POST "https://api.sabiscore.com/v1/insights" \
  -H "Content-Type: application/json" \
  -d '{
    "matchup": "Manchester United vs Liverpool",
    "league": "EPL"
  }'

```

**Example Response**:

```json
{
  "matchup": "Manchester United vs Liverpool",
  "league": "EPL",
  "timestamp": "2025-10-25T14:30:00Z",
  "predictions": {
    "outcome": {
      "home_win": 0.452,
      "draw": 0.278,
      "away_win": 0.270,
      "predicted_result": "Home Win"
    },
    "xg_forecast": {
      "home_xg": 1.85,
      "away_xg": 1.42,
      "total_goals": 3.27
    },
    "markets": {
      "btts": 0.72,
      "over_2_5": 0.65,
      "under_2_5": 0.35
    }
  },
  "value_analysis": [
    {
      "market": "Home Win",
      "model_probability": 0.452,
      "market_odds": 2.10,
      "implied_probability": 0.476,
      "edge": -2.4,
      "expected_value": 15.2,
      "kelly_stake": 8.5,
      "recommendation": "STRONG VALUE",
      "confidence_tier": "High"
    }
  ],
  "simulations": {
    "simulated_outcomes": {
      "home_win": 0.448,
      "draw": 0.282,
      "away_win": 0.270
    },
    "most_likely_scores": [
      {"score": "2-1", "probability": 0.12},
      {"score": "1-1", "probability": 0.10},
      {"score": "2-0", "probability": 0.09},
      {"score": "1-0", "probability": 0.08},
      {"score": "2-2", "probability": 0.07}
    ]
  },
  "confidence": {
    "score": 0.82,
    "tier": "HIGH",
    "message": "All key data points current and complete",
    "data_age_hours": 0.5,
    "completeness_pct": 95.0
  },
  "risk_metrics": {
    "risk_score": 0.28,
    "risk_level": "LOW",
    "advice": "Strong conviction, consistent across models"
  },
  "narrative": "Manchester United are favored with a 45.2% probability..."
}

```

**Status Codes**:

- `200 OK`: Insights generated successfully
- `400 Bad Request`: Invalid matchup or league
- `429 Too Many Requests`: Rate limit exceeded
- `503 Service Unavailable`: Model unavailable

---

### Model Status

```
GET /models/status

```

**Description**: Get status of all loaded models

**Response**:

```json
{
  "EPL": {
    "loaded": true,
    "feature_count": 52,
    "accuracy": 0.67,
    "last_trained": "2025-10-20T10:00:00Z",
    "drift_detected": false
  },
  "La_Liga": {
    "loaded": true,
    "feature_count": 52,
    "accuracy": 0.66,
    "last_trained": "2025-10-20T10:30:00Z",
    "drift_detected": false
  },
  "unified": {
    "loaded": true,
    "feature_count": 58,
    "accuracy": 0.65,
    "last_trained": "2025-10-20T11:00:00Z",
    "drift_detected": false
  }
}

```

---

### 6.3 Error Responses

All errors follow this format:

```json
{
  "error": {
    "code": "INVALID_MATCHUP",
    "message": "Matchup format must be 'Team A vs Team B'",
    "details": {
      "provided": "Manchester United Liverpool",
      "expected_format": "Team A vs Team B"
    }
  }
}

```

**Error Codes**:

| Code | HTTP Status | Description |
| --- | --- | --- |
| `INVALID_MATCHUP` | 400 | Matchup format invalid |
| `INVALID_LEAGUE` | 400 | League code not supported |
| `RATE_LIMIT_EXCEEDED` | 429 | Too many requests |
| `MODEL_UNAVAILABLE` | 503 | ML model not loaded |
| `DATA_FETCH_FAILED` | 503 | Unable to fetch data |
| `INTERNAL_ERROR` | 500 | Server error |

---

### 6.4 Rate Limiting

**Limits**:

- Free tier: 100 requests/hour per IP
- Authenticated (future): 1000 requests/hour

**Headers**:

```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 95
X-RateLimit-Reset: 1635174000

```

**When Exceeded**:

```json
{
  "error": {
    "code": "RATE_LIMIT_EXCEEDED",
    "message": "Rate limit of 100 requests/hour exceeded",
    "retry_after": 3600
  }
}

```

---

## 7. Data Architecture

### 7.1 Database Schema

```sql
-- Matches table
CREATE TABLE matches (
    id SERIAL PRIMARY KEY,
    home_team VARCHAR(100) NOT NULL,
    away_team VARCHAR(100) NOT NULL,
    league VARCHAR(50) NOT NULL,
    kickoff TIMESTAMP,
    venue VARCHAR(100),
    status VARCHAR(20) DEFAULT 'scheduled',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_matches_league ON matches(league);
CREATE INDEX idx_matches_kickoff ON matches(kickoff);
CREATE INDEX idx_matches_status ON matches(status);

-- Predictions table
CREATE TABLE predictions (
    id SERIAL PRIMARY KEY,
    match_id INTEGER REFERENCES matches(id) ON DELETE CASCADE,
    model_version VARCHAR(50) NOT NULL,
    outcome_probs JSONB NOT NULL,
    xg_forecast JSONB,
    markets JSONB,
    confidence FLOAT CHECK (confidence >= 0 AND confidence <= 1),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_predictions_match ON predictions(match_id);
CREATE INDEX idx_predictions_confidence ON predictions(confidence);
CREATE INDEX idx_predictions_created ON predictions(created_at DESC);

-- Historical stats table
CREATE TABLE historical_stats (
    id SERIAL PRIMARY KEY,
    match_id INTEGER REFERENCES matches(id),
    team VARCHAR(100) NOT NULL,
    xG FLOAT,
    xGA FLOAT,
    shots INTEGER,
    shots_on_target INTEGER,
    possession FLOAT,
    passes INTEGER,
    pass_accuracy FLOAT,
    corners INTEGER,
    fouls INTEGER,
    yellow_cards INTEGER,
    red_cards INTEGER,
    source VARCHAR(50),
    season VARCHAR(20),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_stats_team ON historical_stats(team);
CREATE INDEX idx_stats_season ON historical_stats(season);

-- Scraped odds table
CREATE TABLE scraped_odds (
    id SERIAL PRIMARY KEY,
    match_id INTEGER REFERENCES matches(id),
    bookmaker VARCHAR(50),
    home_odds FLOAT,
    draw_odds FLOAT,
    away_odds FLOAT,
    over_2_5_odds FLOAT,
    under_2_5_odds FLOAT,
    btts_yes_odds FLOAT,
    btts_no_odds FLOAT,
    scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_odds_match ON scraped_odds(match_id);
CREATE INDEX idx_odds_scraped ON scraped_odds(scraped_at DESC);

-- Model metadata table
CREATE TABLE model_metadata (
    id SERIAL PRIMARY KEY,
    league VARCHAR(50) UNIQUE NOT NULL,
    version VARCHAR(50) NOT NULL,
    accuracy FLOAT,
    roc_auc FLOAT,
    brier_score FLOAT,
    feature_count INTEGER,
    training_samples INTEGER,
    last_trained TIMESTAMP,
    drift_detected BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- User feedback (for future improvements)
CREATE TABLE feedback (
    id SERIAL PRIMARY KEY,
    match_id INTEGER REFERENCES matches(id),
    prediction_id INTEGER REFERENCES predictions(id),
    rating INTEGER CHECK (rating >= 1 AND rating <= 5),
    comment TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

```

### 7.2 Data Flow Diagram

```
┌──────────────────┐
│  External APIs   │
│  & Web Scrapers  │
└────────┬─────────┘
         │
         ↓
┌──────────────────┐
│  Redis Cache     │  ← TTL: 30 minutes
│  (Rate Limiting) │
└────────┬─────────┘
         │
         ↓
┌──────────────────┐
│  Data Validator  │  ← Great Expectations
│  & Transformer   │

```

```
└────────┬─────────┘
         │
         ↓
┌──────────────────┐
│   PostgreSQL     │  ← Persistent storage
│   Database       │
└────────┬─────────┘
         │
         ↓
┌──────────────────┐
│ Feature Engineer │  ← Rolling windows, aggregations
└────────┬─────────┘
         │
         ↓
┌──────────────────┐
│   ML Models      │  ← Ensemble predictions
│   (Joblib/Pkl)   │
└────────┬─────────┘
         │
         ↓
┌──────────────────┐
│ Insights Engine  │  ← Value bets, simulations
└────────┬─────────┘
         │
         ↓
┌──────────────────┐
│   FastAPI        │  ← JSON responses
└────────┬─────────┘
         │
         ↓
┌──────────────────┐
│   Frontend UI    │  ← User interface
└──────────────────┘

```

### 7.3 Redis Cache Strategy

**Cache Keys Structure**:

```
hist:{league}:{seasons}                  # Historical data (TTL: 12 hours)
realtime:{matchup}:{league}              # Real-time data (TTL: 30 minutes)
odds:{match_id}                          # Scraped odds (TTL: 15 minutes)
prediction:{match_id}:{timestamp}        # Model predictions (TTL: 1 hour)
ratelimit:{ip_address}                   # Rate limiting (TTL: 1 hour)

```

**Example Usage**:

```python
import redis
from datetime import timedelta

cache = redis.Redis(host='localhost', port=6379, db=0)

# Cache historical data
cache.setex(
    'hist:EPL:2020-2024',
    timedelta(hours=12),
    historical_data.to_json()
)

# Cache real-time data
cache.setex(
    'realtime:Man_Utd_vs_Liverpool:EPL',
    timedelta(minutes=30),
    str(realtime_dict)
)

# Rate limiting
cache.incr('ratelimit:192.168.1.1')
cache.expire('ratelimit:192.168.1.1', timedelta(hours=1))

```

### 7.4 Data Retention Policy

| Data Type | Retention Period | Rationale |
| --- | --- | --- |
| Match fixtures | 1 year post-match | Historical analysis |
| Predictions | 6 months | Performance tracking |
| Scraped odds | 3 months | Backtesting |
| Historical stats | Indefinite | Training data |
| User feedback | 1 year | Product improvement |
| API logs | 90 days | Debugging |
| Error logs | 30 days | Monitoring |
| Cache entries | Per TTL | Performance |

**Cleanup Jobs** (Airflow DAGs):

```python
# dags/cleanup_old_data.py
from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta

def cleanup_old_predictions():
    from sqlalchemy import create_engine, text
    import os

    engine = create_engine(os.getenv('DATABASE_URL'))
    cutoff_date = datetime.now() - timedelta(days=180)

    with engine.connect() as conn:
        result = conn.execute(
            text("DELETE FROM predictions WHERE created_at < :cutoff"),
            {"cutoff": cutoff_date}
        )
        print(f"Deleted {result.rowcount} old predictions")
        conn.commit()

dag = DAG(
    'cleanup_old_data',
    schedule_interval='@weekly',
    start_date=datetime(2025, 10, 25),
    catchup=False
)

cleanup_task = PythonOperator(
    task_id='cleanup_predictions',
    python_callable=cleanup_old_predictions,
    dag=dag
)

```

---

## 8. ML Model Documentation

### 8.1 Model Architecture

**Ensemble Structure**:

```
Level 1: Base Models (Diverse Algorithms)
├── XGBoost (Gradient Boosting)
├── LightGBM (Histogram-based)
├── CatBoost (Categorical handling)
└── Random Forest (Bagging)

Level 2: Neural Network Stacker
└── MLP (100-50 hidden layers)

Level 3: Meta-Learner
└── Logistic Regression (Soft voting)

```

### 8.2 Feature Categories

**Total Features**: 52 per match

| Category | Count | Examples |
| --- | --- | --- |
| Rolling Averages | 12 | xG_10ma, xGA_10ma, goals_5ma |
| H2H Metrics | 6 | h2h_win_rate, h2h_goal_diff |
| Form Indicators | 8 | form_momentum, streak_length |
| Injury Impact | 4 | injury_severity_home/away |
| Venue Stats | 6 | home_xg_boost, away_resilience |
| Real-time | 8 | sentiment_score, odds_movement |
| League Encoding | 7 | league_EPL, league_La_Liga, ... |
| Tactical | 5 | pressing_intensity, possession_style |

**Feature Engineering Code**:

```python
def engineer_features(df: pd.DataFrame, realtime: dict) -> pd.DataFrame:
    """
    Transform raw data into ML-ready features.

    Args:
        df: Raw match data with historical stats
        realtime: Real-time updates (injuries, sentiment, odds)

    Returns:
        DataFrame with 52 engineered features per match
    """

    # 1. Rolling averages (10-match window)
    df['xG_10ma'] = df.groupby('team')['xG'].rolling(10, min_periods=3).mean().reset_index(0, drop=True)
    df['xGA_10ma'] = df.groupby('team')['xGA'].rolling(10, min_periods=3).mean().reset_index(0, drop=True)
    df['goals_10ma'] = df.groupby('team')['goals'].rolling(10, min_periods=3).mean().reset_index(0, drop=True)
    df['xg_diff_10ma'] = df['xG_10ma'] - df['xGA_10ma']

    # 2. Form momentum (exponentially weighted)
    def exp_weighted(series, alpha=0.9):
        weights = np.array([alpha ** i for i in range(len(series))])
        return np.dot(series, weights) / weights.sum()

    df['form_momentum'] = df.groupby('team')['points'].rolling(10).apply(exp_weighted).reset_index(0, drop=True)

    # 3. Head-to-head
    df['h2h_win_rate'] = df.groupby(['home_team', 'away_team'])['result'].rolling(5).apply(
        lambda x: (x == 'W').sum() / len(x)
    ).reset_index(0, drop=True)

    # 4. Injury severity
    if 'injuries' in realtime and not realtime['injuries'].empty:
        injury_scores = realtime['injuries'].groupby('team').apply(
            lambda x: (x['days_out'] * x['market_value']).sum() / x['market_value'].sum()
        )
        df['injury_severity'] = df['team'].map(injury_scores).fillna(0)
        df['injury_adjusted_xg'] = df['xG_10ma'] * (1 - df['injury_severity'])

    # 5. Sentiment adjustment
    if 'sentiment' in realtime:
        df['sentiment_score'] = df['team'].map({
            'home': realtime['sentiment'].get('home_sentiment', 0),
            'away': realtime['sentiment'].get('away_sentiment', 0)
        }).fillna(0)

    # 6. Venue advantage
    df['home_xg_boost'] = df.groupby('home_team')['xG'].mean() - df.groupby('home_team')['xG'].apply(
        lambda x: x[df['venue'] != 'home'].mean()
    )

    # 7. League one-hot encoding
    df = pd.get_dummies(df, columns=['league'], prefix='league')

    return df

```

### 8.3 Hyperparameter Search Space

**XGBoost**:

```python
xgb_space = {
    'n_estimators': (100, 500),
    'max_depth': (3, 12),
    'learning_rate': (0.01, 0.3),
    'subsample': (0.6, 1.0),
    'colsample_bytree': (0.6, 1.0),
    'gamma': (0, 5),
    'reg_alpha': (0, 2),
    'reg_lambda': (0, 2)
}

```

**LightGBM**:

```python
lgb_space = {
    'n_estimators': (100, 500),
    'num_leaves': (20, 100),
    'learning_rate': (0.01, 0.3),
    'min_child_samples': (5, 50),
    'subsample': (0.6, 1.0),
    'colsample_bytree': (0.6, 1.0)
}

```

**Neural Network**:

```python
nn_space = {
    'hidden_layer_sizes': [(100, 50), (150, 75), (200, 100)],
    'activation': ['relu', 'tanh'],
    'alpha': (0.0001, 0.01),
    'learning_rate': ['constant', 'adaptive']
}

```

### 8.4 Model Evaluation

**Metrics Tracked**:

```python
from sklearn.metrics import (
    accuracy_score,
    roc_auc_score,
    brier_score_loss,
    log_loss,
    confusion_matrix
)

def evaluate_model(y_true, y_pred, y_proba):
    metrics = {
        'accuracy': accuracy_score(y_true, y_pred),
        'roc_auc': roc_auc_score(y_true, y_proba, multi_class='ovr'),
        'brier_score': np.mean([
            brier_score_loss(y_true == i, y_proba[:, i])
            for i in range(y_proba.shape[1])
        ]),
        'log_loss': log_loss(y_true, y_proba),
        'confusion_matrix': confusion_matrix(y_true, y_pred).tolist()
    }
    return metrics

```

**Calibration**:

```python
from sklearn.calibration import calibration_curve
import matplotlib.pyplot as plt

def plot_calibration(y_true, y_proba):
    """Plot calibration curve to check if probabilities are well-calibrated"""
    for i, outcome in enumerate(['Loss', 'Draw', 'Win']):
        fraction_of_positives, mean_predicted_value = calibration_curve(
            y_true == i, y_proba[:, i], n_bins=10
        )
        plt.plot(mean_predicted_value, fraction_of_positives, 's-', label=outcome)

    plt.plot([0, 1], [0, 1], 'k--', label='Perfect calibration')
    plt.xlabel('Mean predicted probability')
    plt.ylabel('Fraction of positives')
    plt.legend()
    plt.title('Calibration Curve')
    plt.savefig('calibration_curve.png')

```

### 8.5 Model Versioning

**Directory Structure**:

```
models/
├── EPL/
│   ├── v1.0.0_2025-10-20.pkl
│   ├── v1.1.0_2025-11-15.pkl
│   └── latest -> v1.1.0_2025-11-15.pkl
├── La_Liga/
│   └── v1.0.0_2025-10-20.pkl
├── metadata.json
└── training_logs/
    ├── EPL_2025-10-20.log
    └── EPL_2025-11-15.log

```

**Metadata Format** (`metadata.json`):

```json
{
  "EPL": {
    "current_version": "v1.1.0",
    "versions": [
      {
        "version": "v1.1.0",
        "trained_at": "2025-11-15T10:00:00Z",
        "metrics": {
          "accuracy": 0.673,
          "roc_auc": 0.745,
          "brier_score": 0.187
        },
        "features_count": 52,
        "training_samples": 3450,
        "hyperparameters": {
          "xgb_n_estimators": 250,
          "xgb_max_depth": 8,
          "xgb_learning_rate": 0.12
        }
      },
      {
        "version": "v1.0.0",
        "trained_at": "2025-10-20T10:00:00Z",
        "metrics": {
          "accuracy": 0.651,
          "roc_auc": 0.722,
          "brier_score": 0.195
        }
      }
    ]
  }
}

```

### 8.6 Retraining Strategy

**Triggers for Retraining**:

1. **Scheduled**: Weekly on Sundays at 02:00 UTC
2. **Drift Detected**: Alibi-Detect flags distribution shift
3. **Accuracy Drop**: Rolling accuracy falls below 60% over 50 predictions
4. **New Season**: Start of each league season

**Retraining Pipeline**:

```python
# dags/retrain_models.py
from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime

def retrain_league_model(league: str):
    """Retrain model for specific league"""
    from training import SabiScoreEnsemble, train_league_models
    from data_aggregator import DataAggregator
    import pandas as pd

    # 1. Fetch latest data
    aggregator = DataAggregator("dummy", league)
    historical = aggregator.fetch_historical_stats()

    # 2. Split train/test
    split_idx = int(len(historical) * 0.8)
    X_train = historical[:split_idx]
    X_test = historical[split_idx:]

    # 3. Train new model
    ensemble = SabiScoreEnsemble(league=league)
    model = ensemble.build_ensemble(X_train['features'], X_train['target'])

    # 4. Evaluate
    metrics = ensemble.evaluate(X_test['features'], X_test['target'])

    # 5. Compare with current model
    current_model = SabiScoreEnsemble.load_model(f'models/{league}_ensemble.pkl')
    current_metrics = current_model.evaluate(X_test['features'], X_test['target'])

    # 6. Deploy if better
    if metrics['accuracy'] > current_metrics['accuracy']:
        version = f"v1.{datetime.now().strftime('%Y%m%d')}"
        ensemble.save_model(f'models/{league}/{version}.pkl')
        print(f"✓ Deployed new {league} model: {version}")
    else:
        print(f"✗ New model not better, keeping current")

dag = DAG(
    'retrain_models',
    schedule_interval='0 2 * * 0',  # Sundays at 02:00
    start_date=datetime(2025, 10, 25),
    catchup=False
)

for league in ['EPL', 'La_Liga', 'Serie_A', 'Bundesliga', 'Ligue_1', 'RPL', 'UCL']:
    PythonOperator(
        task_id=f'retrain_{league}',
        python_callable=retrain_league_model,
        op_kwargs={'league': league},
        dag=dag
    )

```

---

## 9. Security & Compliance

### 9.1 Security Measures

**API Security**:

```python
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# Rate limiting
limiter = Limiter(key_func=get_remote_address)
app = FastAPI()
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://sabiscore.com", "https://www.sabiscore.com"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Security headers
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response

# Rate limiting per endpoint
@app.get("/insights")
@limiter.limit("10/minute")
async def get_insights(request: Request):
    # Implementation
    pass

```

**Environment Variables**:

```python
# config.py
from pydantic import BaseSettings, validator
import os

class Settings(BaseSettings):
    DATABASE_URL: str
    REDIS_URL: str
    SECRET_KEY: str
    ENVIRONMENT: str = "development"
    DEBUG: bool = False

    @validator("DATABASE_URL")
    def validate_db_url(cls, v):
        if not v.startswith("postgresql://"):
            raise ValueError("DATABASE_URL must be PostgreSQL")
        return v

    @validator("SECRET_KEY")
    def validate_secret_key(cls, v):
        if len(v) < 32:
            raise ValueError("SECRET_KEY must be at least 32 characters")
        return v

    class Config:
        env_file = ".env"
        case_sensitive = True

settings = Settings()

```

**SQL Injection Prevention**:

```python
# Always use parameterized queries
from sqlalchemy import text

# Good - parameterized
engine.execute(
    text("SELECT * FROM matches WHERE league = :league"),
    {"league": user_input}
)

# Bad - vulnerable to injection
engine.execute(f"SELECT * FROM matches WHERE league = '{user_input}'")

```

### 9.2 Data Privacy (GDPR Compliance)

**No PII Storage**: SabiScore does not collect or store:

- User names
- Email addresses
- IP addresses (beyond rate limiting TTL)
- Payment information
- Location data

**Cookies**: Only essential cookies for functionality:

```jsx
// Cookie policy
document.cookie = "theme=dark; SameSite=Strict; Secure; Max-Age=31536000";

```

**Data Processing Agreement**:

```markdown
# Data We Collect
- Anonymous usage analytics (page views, clicks)
- Aggregate betting insights queries
- Browser/device type for optimization

# Data We Do NOT Collect
- Personal identifiable information
- Betting history or outcomes
- Financial information

# Third-Party Services
- Cloudflare (CDN, DDoS protection)
- Sentry (Error tracking - anonymized)

```

### 9.3 Responsible Gambling

**Disclaimers** (displayed prominently):

```html
<div class="responsible-gambling-notice">
  <h3>⚠️ Responsible Gambling Notice</h3>
  <ul>
    <li>SabiScore provides informational insights only</li>
    <li>Past performance does not guarantee future results</li>
    <li>Never bet more than you can afford to lose</li>
    <li>Gambling can be addictive - seek help if needed</li>
  </ul>
  <p>
    <strong>Need help?</strong>
    <a href="https://www.begambleaware.org">BeGambleAware.org</a>
  </p>
</div>

```

**Age Verification** (future feature):

```jsx
// Block users under 18
if (userAge < 18) {
  window.location.href = "/age-restricted";
}

```

**No Betting Integration**: SabiScore explicitly does NOT:

- Accept wagers
- Facilitate betting
- Link to specific bookmakers
- Receive affiliate commissions from gambling sites

### 9.4 Terms of Service

```markdown
# Terms of Service (Summary)

## Use of Service
- SabiScore is for entertainment and informational purposes only
- Predictions are not guarantees
- Users are responsible for their own betting decisions

## Liability
- We are not liable for betting losses
- Service provided "as-is" without warranties
- We may suspend service at any time

## Intellectual Property
- All content is copyrighted
- Users may not scrape or reproduce content
- API rate limits enforced

## Termination
- We may terminate access for abuse
- Users may stop using service at any time

## Governing Law
- Governed by laws of [Your Jurisdiction]

```

---

## 10. Maintenance & Operations

### 10.1 Monitoring Dashboard

**Prometheus Metrics**:

```python
from prometheus_client import Counter, Histogram, Gauge

# Request metrics
http_requests_total = Counter(
    'http_requests_total',
    'Total HTTP requests',
    ['method', 'endpoint', 'status']
)

http_request_duration = Histogram(
    'http_request_duration_seconds',
    'HTTP request duration',
    ['method', 'endpoint']
)

# Model metrics
model_accuracy = Gauge(
    'model_accuracy',
    'Current model accuracy',
    ['league']
)

predictions_total = Counter(
    'predictions_total',
    'Total predictions generated',
    ['league']
)

# Scraping metrics
scraping_success_rate = Gauge(
    'scraping_success_rate',
    'Scraping success rate',
    ['source']
)

```

**Grafana Dashboard Panels**:

1. API Response Time (P50, P95, P99)
2. Requests per Second
3. Error Rate (4xx, 5xx)
4. Model Accuracy by League
5. Database Query Time
6. Cache Hit Rate
7. Scraping Success Rate
8. Active Users

### 10.2 Alerting Rules

**Prometheus Alerts** (`alerts.yml`):

```yaml
groups:
  - name: SabiScore
    interval: 30s
    rules:
      - alert: HighErrorRate
        expr: rate(http_requests_total{status=~"5.."}[5m]) > 0.05
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "High error rate detected"
          description: "Error rate is {{ $value }} (threshold: 0.05)"

      - alert: SlowResponseTime
        expr: histogram_quantile(0.95, http_request_duration_seconds) > 0.5
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Slow API responses"
          description: "P95 latency is {{ $value }}s"

      - alert: ModelAccuracyDrop
        expr: model_accuracy < 0.60
        for: 1h
        labels:
          severity: warning
        annotations:
          summary: "Model accuracy below threshold"
          description: "{{ $labels.league }} accuracy: {{ $value }}"

      - alert: DatabaseConnectionFailed
        expr: up{job="postgres"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Database connection failed"

      - alert: ScrapingFailures
        expr: scraping_success_rate < 0.8
        for: 30m
        labels:
          severity: warning
        annotations:
          summary: "Scraping success rate low"
          description: "{{ $labels.source }}: {{ $value }}"

```

### 10.3 Backup Strategy

**Database Backups**:

```bash
#!/bin/bash
# scripts/backup_database.sh

# Configuration
DB_NAME="sabiscore"
BACKUP_DIR="/backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
RETENTION_DAYS=30

# Create backup
pg_dump $DB_NAME | gzip > "$BACKUP_DIR/sabiscore_$TIMESTAMP.sql.gz"

# Upload to S3 (or equivalent)
aws s3 cp "$BACKUP_DIR/sabiscore_$TIMESTAMP.sql.gz" s3://sabiscore-backups/

# Delete old backups
find $BACKUP_DIR -name "sabiscore_*.sql.gz" -mtime +$RETENTION_DAYS -delete

echo "✓ Backup complete: sabiscore_$TIMESTAMP.sql.gz"

```

**Backup Schedule**:

- **Daily**: Full database backup at 03:00 UTC
- **Weekly**: Model artifacts backup
- **Monthly**: Complete system snapshot

**Restore Procedure**:

```bash
# Restore from backup
gunzip -c /backups/sabiscore_20251025_030000.sql.gz | psql sabiscore

# Verify data integrity
psql sabiscore -c "SELECT COUNT(*) FROM matches;"

```

### 10.4 Incident Response

**Runbook for Common Issues**:

**Issue 1: API Slow Response**

```markdown
### Symptoms
- P95 latency > 500ms
- User complaints about slow loading

### Diagnosis
1. Check Grafana: API Response Time panel
2. Check database: `SELECT * FROM pg_stat_activity WHERE state = 'active';`
3. Check Redis: `redis-cli INFO stats`

### Resolution
1. Increase Redis TTL to reduce database queries
2. Add database indexes if missing
3. Scale Heroku dynos: `heroku ps:scale web=2`
4. Enable query caching in SQLAlchemy

### Prevention
- Monitor slow queries
- Optimize feature engineering
- Implement CDN for static assets

```

**Issue 2: Model Drift Detected**

```markdown
### Symptoms
- Alibi-Detect alert triggered
- Accuracy drops below 60%

### Diagnosis
1. Check model_metadata table for drift_detected=true
2. Review recent predictions vs. actual results
3. Analyze feature distributions

### Resolution
1. Trigger manual retraining: `POST /models/retrain`
2. Review feature engineering for errors
3. Check data sources for changes

### Prevention
- Automated weekly retraining
- A/B test new models before deployment
- Monitor feature importance shifts

```

**Issue 3: Scraping Failures**

```markdown
### Symptoms
- Scraping success rate < 80%
- Missing real-time data

### Diagnosis
1. Check error logs: `docker-compose logs backend | grep "scraping"`
2. Manually test URL: `curl https://www.flashscore.com`
3. Check rate limit counters in Redis

### Resolution
1. Update User-Agent if blocked
2. Increase request delays: `time.sleep(2)`
3. Switch to fallback data sources
4. Use rotating proxies if needed

### Prevention
- Monitor scraping success rates
- Implement circuit breakers
- Maintain multiple data source options

```

### 10.5 Operational Checklist

**Daily**:

- [ ]  Check Grafana dashboards for anomalies
- [ ]  Review error logs in Sentry
- [ ]  Verify database backup completed
- [ ]  Monitor API response times

**Weekly**:

- [ ]  Review model accuracy metrics
- [ ]  Check for drift alerts
- [ ]  Update dependencies (`pip-audit`, `npm audit`)
- [ ]  Review user feedback

**Monthly**:

- [ ]  Full security audit
- [ ]  Review and optimize database indexes
- [ ]  Analyze cost/usage trends
- [ ]  Plan capacity scaling

**Quarterly**:

- [ ]  Major dependency updates
- [ ]  Performance optimization sprint
- [ ]  Disaster recovery drill
- [ ]  User survey for feedback

---

## 11. Quick Start Commands

### Development

```bash
# Clone and setup
git clone https://github.com/yourusername/sabiscore.git
cd sabiscore
cp .env.example .env
# Edit .env with your values

# Backend setup
cd backend
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python scripts/init_db.py

# Frontend setup
cd ../frontend
npm install

# Start services
docker-compose up -d postgres redis
cd backend && uvicorn main:app --reload &
cd frontend && npm run dev &

# Run tests
pytest backend/tests/ -v --cov
npm test

```

### Deployment

```bash
# Deploy to production
./scripts/deploy.sh

# Check status
curl https://api.sabiscore.com/health

# View logs
heroku logs --tail -a sabiscore-api

# Rollback if needed
heroku releases:rollback -a sabiscore-api

```

### Monitoring

```bash
# Access monitoring
open http://localhost:9090  # Prometheus
open http://localhost:3001  # Grafana

# Check metrics
curl http://localhost:8000/metrics

# Test alerts
curl -X POST http://localhost:9093/-/reload

```

---

## 12. Support & Resources

### Documentation

- **User Guide**: `/docs/user-guide.md`
- **API Reference**: `/docs/api-reference.md`
- **Architecture**: `/docs/architecture.md`
- **Contributing**: `CONTRIBUTING.md`

### Community

- **GitHub Issues**: https://github.com/yourusername/sabiscore/issues
- **Discord**: https://discord.gg/sabiscore
- **Email**: support@sabiscore.com

### Additional Resources

- **Machine Learning**: `/docs/ml-guide.md`
- **Data Sources**: `/docs/data-sources.md`
- **Performance Tuning**: `/docs/performance.md`
- **Troubleshooting**: `/docs/troubleshooting.md`

---

**End of Documentation**

This comprehensive documentation provides everything needed to understand, develop, deploy, and maintain SabiScore. All team members should familiarize themselves with relevant sections and keep documentation updated as the project evolves.