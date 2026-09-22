# Phase D & E Independent Repository Audit

| Area | Current implementation | Evidence | Status |
|---|---|---|---|
| Market baseline | `scripts/compare_candidate_vs_incumbent.py` using `shin_devig()` | Evaluated on holdout per match. BUNDESLIGA, EPL, etc. | PASS (with Shin de-vigging) |
| Residual model | `src/models/ensemble.py:LogOddsResidualWrapper` | Fails to apply `base_margin` on LGBM; acts as binary wrapper on XGB. Multinomial log-ratio not used. | FAIL (Needs multinomial log-ratio wrapper) |
| Calibration | `CalibratedClassifierCV(method='sigmoid')` used in `train_on_real_matches.py` | Isotonic/Temperature scaling not compared/used out-of-sample properly. | FAIL (Needs multiclass temperature scaling baseline) |
| RAPS | Deliberately disabled in `scripts/evaluate_split_conformal.py` | Reports LAC only due to previous §21 policy. | FAIL (Needs LAC, APS, RAPS evaluation at 0.10) |
| Error association | `measure_epistemic_danger_zone.py` & `diagnose_decoupled_uncertainty.py` | Item 50 records 1/5 leagues pass. | FAIL (Gate blocked) |
| Feature PIT | Target encoding & feature generation in `train_on_real_matches.py` | TimeSeriesSplit chronological split implemented. | PASS (But needs verification during retrain) |
| Serving parity | `test_prediction_engine.py` offline/online checks | Artifacts loaded and matched against offline. | PASS |
| Artifact identity | `scripts/audit_release_identity.py` | Tested, PASS on v5_phase7. | PASS |
| Live data | `scripts/ingest_fbref_sources.py` | Data gaps exist, fail-closed guards it. | PASS (Fail-closed implemented) |
