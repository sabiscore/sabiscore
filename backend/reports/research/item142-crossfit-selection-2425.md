# Item 142 — cross-fitted season-2425 selection evidence

Generated 2026-09-24T04:07:26Z at `45e8a23606`; generation `v5_phase7-20260922`, schema `apex_v1_68`. Season 2425 only; no 2526 file was opened (fd_D1_2526.csv, fd_E0_2526.csv, fd_F1_2526.csv, fd_I1_2526.csv, fd_N1_2526.csv, fd_SP1_2526.csv).

Measurement only. Nothing here recommends a composition; that decision belongs to the operator.
Post-hoc layers were refit out-of-fold on 5 contiguous chronological blocks of 2425; base learners and the inner SoftmaxMetaModel were fitted on seasons ≤ 2324 and are used as shipped.

## Checks

| artifact | 2425 rows rebuilt / pickle | columns | refit Δ scale layer | refit Δ sigmoid | parity (rounded / unrounded) |
| --- | --- | --- | --- | --- | --- |
| bundesliga | 296 / 296 (match) | match | 1.2e-14 | 0.0e+00 | pass (0.0e+00 / 1.1e-16) |
| epl | 375 / 375 (match) | match | 8.8e-12 | 0.0e+00 | pass (0.0e+00 / 2.2e-16) |
| eredivisie | 1732 / 1732 (match) | match | 1.7e-14 | 0.0e+00 | pass (0.0e+00 / 2.2e-16) |
| la_liga | 380 / 380 (match) | match | 3.9e-11 | 0.0e+00 | pass (0.0e+00 / 1.1e-16) |
| ligue_1 | 306 / 306 (match) | match | 2.4e-05 | 0.0e+00 | pass (0.0e+00 / 1.1e-16) |
| serie_a | 375 / 375 (match) | match | 1.2e-13 | 0.0e+00 | pass (0.0e+00 / 1.1e-16) |

## Mean RPS — 5-block chronological cross-fit (all 2425 rows)

Lower is better. REF columns are IN-SAMPLE (shipped layers were fitted on these rows).

| artifact | n | C1 avg | C2 avg+sigmoid(cf) | C3 stacked_raw | C4 stacked+scale(cf) | C5 served(cf) | REF served (in-sample) | REF stacked+scale (in-sample) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| bundesliga | 296 | 0.2092 | 0.2121 | 0.2122 | 0.2135 | 0.2197 | 0.2119 | 0.2107 |
| epl | 375 | 0.2054 | 0.2070 | 0.1963 | 0.1970 | 0.2046 | 0.2011 | 0.1962 |
| eredivisie | 1732 | 0.1973 | 0.1984 | 0.1963 | 0.1966 | 0.1982 | 0.1971 | 0.1963 |
| la_liga | 380 | 0.2004 | 0.2040 | 0.1918 | 0.1937 | 0.2019 | 0.1975 | 0.1918 |
| ligue_1 | 306 | 0.2110 | 0.2112 | 0.2073 | 0.2060 | 0.2133 | 0.2103 | 0.2035 |
| serie_a | 375 | 0.1889 | 0.1935 | 0.1863 | 0.1865 | 0.1927 | 0.1904 | 0.1862 |
| POOLED (5 dedicated) | 1732 | 0.2024 | 0.2050 | 0.1978 | 0.1984 | 0.2055 | 0.2015 | 0.1968 |

ΔRPS vs C5 served(cf), candidate − C5; 95% CI from a paired calendar-week (ISO) block bootstrap, 2000 replicates, seed 42. "beats" = CI entirely below zero.

| artifact | C1 avg | C2 avg+sigmoid(cf) | C3 stacked_raw | C4 stacked+scale(cf) |
| --- | --- | --- | --- | --- |
| bundesliga | -0.0105 [-0.0271, 0.0080] | -0.0076 [-0.0129, -0.0022] (beats) | -0.0076 [-0.0199, 0.0065] | -0.0062 [-0.0158, 0.0050] |
| epl | +0.0008 [-0.0085, 0.0096] | +0.0024 [-0.0014, 0.0062] | -0.0084 [-0.0145, -0.0016] (beats) | -0.0077 [-0.0133, -0.0013] (beats) |
| eredivisie | -0.0009 [-0.0028, 0.0012] | +0.0002 [-0.0009, 0.0014] | -0.0018 [-0.0031, -0.0006] (beats) | -0.0016 [-0.0028, -0.0004] (beats) |
| la_liga | -0.0015 [-0.0085, 0.0061] | +0.0021 [-0.0010, 0.0052] | -0.0100 [-0.0163, -0.0034] (beats) | -0.0082 [-0.0149, -0.0007] (beats) |
| ligue_1 | -0.0023 [-0.0150, 0.0095] | -0.0021 [-0.0065, 0.0019] | -0.0060 [-0.0157, 0.0033] | -0.0073 [-0.0143, -0.0006] (beats) |
| serie_a | -0.0038 [-0.0097, 0.0019] | +0.0008 [-0.0019, 0.0037] | -0.0064 [-0.0097, -0.0031] (beats) | -0.0062 [-0.0110, -0.0014] (beats) |
| POOLED (5 dedicated) | -0.0032 [-0.0069, 0.0007] | -0.0005 [-0.0024, 0.0016] | -0.0077 [-0.0104, -0.0050] (beats) | -0.0071 [-0.0095, -0.0047] (beats) |

In-sample vs cross-fitted gap (RPS, positive = in-sample looks worse):

- bundesliga: served -0.0078; stacked+scale -0.0028
- epl: served -0.0035; stacked+scale -0.0008
- eredivisie: served -0.0010; stacked+scale -0.0003
- la_liga: served -0.0043; stacked+scale -0.0019
- ligue_1: served -0.0029; stacked+scale -0.0025
- serie_a: served -0.0023; stacked+scale -0.0004
- POOLED (5 dedicated): served -0.0041; stacked+scale -0.0016

Candidates whose CI vs served(cf) excludes zero:

- C1_avg: beats in 0/6 (none); worse in 0/6 (none); pooled beats: False, pooled worse: False
- C2_avg+sigmoid(cf): beats in 1/6 (bundesliga); worse in 0/6 (none); pooled beats: False, pooled worse: False
- C3_stacked_raw: beats in 4/6 (epl, eredivisie, la_liga, serie_a); worse in 0/6 (none); pooled beats: True, pooled worse: False
- C4_stacked+scale(cf): beats in 5/6 (epl, eredivisie, la_liga, ligue_1, serie_a); worse in 0/6 (none); pooled beats: True, pooled worse: False

## Mean RPS — Robustness: forward expanding window (blocks 2–5 scored; block 1 only trains)

Lower is better. REF columns are IN-SAMPLE (shipped layers were fitted on these rows).

| artifact | n | C1 avg | C2 avg+sigmoid(cf) | C3 stacked_raw | C4 stacked+scale(cf) | C5 served(cf) | REF served (in-sample) | REF stacked+scale (in-sample) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| bundesliga | 236 | 0.2144 | 0.2153 | 0.2188 | 0.2198 | 0.2200 | 0.2143 | 0.2160 |
| epl | 300 | 0.2099 | 0.2116 | 0.2013 | 0.2027 | 0.2101 | 0.2043 | 0.2010 |
| eredivisie | 1385 | 0.2000 | 0.2016 | 0.1994 | 0.1999 | 0.2014 | 0.1998 | 0.1994 |
| la_liga | 304 | 0.2039 | 0.2090 | 0.1956 | 0.1978 | 0.2078 | 0.2007 | 0.1958 |
| ligue_1 | 244 | 0.2122 | 0.2172 | 0.2107 | 0.2122 | 0.2192 | 0.2140 | 0.2079 |
| serie_a | 300 | 0.1865 | 0.1987 | 0.1840 | 0.1844 | 0.1986 | 0.1890 | 0.1835 |
| POOLED (5 dedicated) | 1384 | 0.2047 | 0.2099 | 0.2010 | 0.2023 | 0.2104 | 0.2036 | 0.1998 |

ΔRPS vs C5 served(cf), candidate − C5; 95% CI from a paired calendar-week (ISO) block bootstrap, 2000 replicates, seed 42. "beats" = CI entirely below zero.

| artifact | C1 avg | C2 avg+sigmoid(cf) | C3 stacked_raw | C4 stacked+scale(cf) |
| --- | --- | --- | --- | --- |
| bundesliga | -0.0056 [-0.0197, 0.0109] | -0.0047 [-0.0092, 0.0003] | -0.0012 [-0.0103, 0.0087] | -0.0002 [-0.0108, 0.0114] |
| epl | -0.0002 [-0.0101, 0.0091] | +0.0015 [-0.0021, 0.0049] | -0.0087 [-0.0158, -0.0011] (beats) | -0.0074 [-0.0145, 0.0003] |
| eredivisie | -0.0014 [-0.0038, 0.0011] | +0.0001 [-0.0011, 0.0015] | -0.0020 [-0.0034, -0.0007] (beats) | -0.0015 [-0.0033, 0.0003] |
| la_liga | -0.0039 [-0.0135, 0.0068] | +0.0012 [-0.0012, 0.0037] | -0.0122 [-0.0207, -0.0025] (beats) | -0.0100 [-0.0194, 0.0010] |
| ligue_1 | -0.0070 [-0.0232, 0.0082] | -0.0020 [-0.0063, 0.0019] | -0.0085 [-0.0220, 0.0046] | -0.0070 [-0.0182, 0.0038] |
| serie_a | -0.0122 [-0.0222, -0.0027] (beats) | +0.0000 [-0.0029, 0.0032] | -0.0146 [-0.0221, -0.0078] (beats) | -0.0143 [-0.0215, -0.0074] (beats) |
| POOLED (5 dedicated) | -0.0057 [-0.0106, -0.0010] (beats) | -0.0005 [-0.0026, 0.0017] | -0.0094 [-0.0128, -0.0060] (beats) | -0.0081 [-0.0116, -0.0046] (beats) |

In-sample vs cross-fitted gap (RPS, positive = in-sample looks worse):

- bundesliga: served -0.0057; stacked+scale -0.0038
- epl: served -0.0057; stacked+scale -0.0017
- eredivisie: served -0.0016; stacked+scale -0.0005
- la_liga: served -0.0070; stacked+scale -0.0020
- ligue_1: served -0.0052; stacked+scale -0.0043
- serie_a: served -0.0097; stacked+scale -0.0009
- POOLED (5 dedicated): served -0.0068; stacked+scale -0.0024

Candidates whose CI vs served(cf) excludes zero:

- C1_avg: beats in 1/6 (serie_a); worse in 0/6 (none); pooled beats: True, pooled worse: False
- C2_avg+sigmoid(cf): beats in 0/6 (none); worse in 0/6 (none); pooled beats: False, pooled worse: False
- C3_stacked_raw: beats in 4/6 (epl, eredivisie, la_liga, serie_a); worse in 0/6 (none); pooled beats: True, pooled worse: False
- C4_stacked+scale(cf): beats in 1/6 (serie_a); worse in 0/6 (none); pooled beats: True, pooled worse: False

## Caveats

- The scale-layer TYPE per league (temperature; vector for Ligue 1) was chosen by _select_calibrator, which consulted 2526. It is held fixed as shipped; only its parameters are refit out-of-fold here.
- The Eredivisie artifact is the pooled model. Its 2425 population is the five other leagues' rows (Eredivisie has no pre-2526 season), so it is reported separately and excluded from the pooled row, which would otherwise score those rows twice.
- Each out-of-fold layer is fitted on 4/5 of one season (forward: as little as 1/5), while the shipped layers used all of it; cross-fitted scores carry that small-sample cost.
- Local runtime is Python 3.14 / scikit-learn 1.8; production is 3.11 / 1.3.2. The sigmoid calibrator is applied from coefficients (calibration._platt_probability), so the served numbers do not depend on the scikit-learn version.
- No recommendation is made. Item 142's options remain an operator decision.

Full numbers (log loss, Brier, ECE, per-fold parameters): `item142-crossfit-selection-2425.json`.
