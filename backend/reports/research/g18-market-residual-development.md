# G18 market-residual track — development folds

Generated 2026-09-24T04:40:13+00:00 at `45e8a23606`. Protocol `reports/research/g18-market-residual-protocol.json` sha256 `57d1704976e1ed878a8e4765a850158e32260bec641b48d38eedde3fe6d62cca` (frozen before this run). Test seasons 2122, 2223, 2324, 2425; 2526 never opened (6 files excluded).

## Mean RPS (lower is better)

| group | n | M0 market | M0 Shin (sensitivity) | R1 intercepts | R2 longshot | R3 residual |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| POOLED | 7027 | 0.19526 | 0.19510 | 0.19535 | 0.19515 | 0.19516 |
| EPL | 1500 | 0.19273 | 0.19255 | 0.19289 | 0.19276 | 0.19280 |
| LA_LIGA | 1500 | 0.19202 | 0.19166 | 0.19221 | 0.19182 | 0.19163 |
| SERIE_A | 1485 | 0.19060 | 0.19036 | 0.19046 | 0.19004 | 0.19012 |
| BUNDESLIGA | 1194 | 0.20010 | 0.20019 | 0.20030 | 0.20038 | 0.20053 |
| LIGUE_1 | 1348 | 0.20255 | 0.20248 | 0.20258 | 0.20251 | 0.20252 |

## ΔRPS vs market (candidate − market), 95% CI, ISO-week cluster bootstrap

"beats" = CI entirely below zero; "worse" = CI entirely above zero.

| group | R1 intercepts | R2 longshot | R3 residual |
| --- | --- | --- | --- |
| POOLED | +0.00008 [-0.00005, +0.00021] | -0.00012 [-0.00029, +0.00007] | -0.00010 [-0.00036, +0.00015] |
| EPL | +0.00016 [-0.00013, +0.00046] | +0.00003 [-0.00036, +0.00041] | +0.00007 [-0.00050, +0.00062] |
| LA_LIGA | +0.00018 [-0.00012, +0.00047] | -0.00020 [-0.00058, +0.00019] | -0.00040 [-0.00084, +0.00006] |
| SERIE_A | -0.00014 [-0.00037, +0.00008] | -0.00056 [-0.00092, -0.00020] (beats) | -0.00047 [-0.00100, +0.00003] |
| BUNDESLIGA | +0.00020 [-0.00010, +0.00052] | +0.00028 [-0.00012, +0.00071] | +0.00043 [-0.00008, +0.00099] |
| LIGUE_1 | +0.00002 [-0.00031, +0.00038] | -0.00005 [-0.00043, +0.00036] | -0.00003 [-0.00062, +0.00058] |
| season 2122 | +0.00002 [-0.00032, +0.00039] | -0.00002 [-0.00040, +0.00040] | -0.00009 [-0.00060, +0.00045] |
| season 2223 | +0.00033 [-0.00003, +0.00066] | +0.00035 [-0.00006, +0.00076] | +0.00049 [-0.00012, +0.00109] |
| season 2324 | +0.00000 [-0.00007, +0.00007] | -0.00037 [-0.00055, -0.00018] (beats) | -0.00041 [-0.00075, -0.00007] (beats) |
| season 2425 | -0.00003 [-0.00014, +0.00007] | -0.00044 [-0.00079, -0.00006] (beats) | -0.00043 [-0.00088, +0.00004] |

## Decision (pre-registered rule)

- Promising (pooled CI below zero): none
- Selected for 2526 confirmation: none
- No candidate's pooled development CI is below zero: negative result, 2526 stays unread (protocol decision_rule.if_none_promising).

Eredivisie is not in development: the corpus holds no Eredivisie season before 2526.
Full numbers, eligibility funnel and per-fold coefficients: `g18-market-residual-development.json`.
