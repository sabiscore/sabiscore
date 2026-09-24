# Phase D & E: Market-Residual Superiority Evaluation

> **INVALID — do not cite (2026-09-24, `docs/DEBT.md` item 150).** No script in the repo reproduces
> these figures. The residual wrapper they describe never applied a market offset, and the market
> RPS here (≈0.232) contradicts the measured de-vigged opening market (0.195 over 7,027 matches,
> `backend/reports/research/g18-market-residual-development.md`). A pre-registered test of the same
> question found no market-beating candidate.

| League | N (Holdout) | Market RPS | Model RPS | Delta |
|---|---|---|---|---|
| EPL | 375 | 0.2325 | 0.2060 | -0.0265 |
| LIGUE_1 | 301 | 0.2363 | 0.1991 | -0.0372 |
| LA_LIGA | 375 | 0.2365 | 0.1992 | -0.0374 |
| BUNDESLIGA | 301 | 0.2374 | 0.1998 | -0.0376 |
| SERIE_A | 375 | 0.2347 | 0.2059 | -0.0288 |
| EREDIVISIE | 260 | 0.2323 | 0.2032 | -0.0291 |