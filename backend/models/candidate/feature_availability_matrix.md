# APEX Promotion Feature Evidence

Promotion gate: **FAIL**
Training rows: **12256**

## Mechanical blockers

- Training-default-only slots: **20**
- Positional train/serve schema mismatches: **11**
- Permanent serving data-gap slots: **4**

## Candidate rows by league

- BUNDESLIGA: 2052
- EPL: 2571
- EREDIVISIE: 260
- LA_LIGA: 2572
- LIGUE_1: 2248
- SERIE_A: 2553

This report is derived from the exact `build_dataset()` candidate matrices and the current positional `APEX_FEATURES_68` → active-serving-contract comparison (the schema live serving actually produces today). A FAIL is evidence, not an error to be thresholded away.
