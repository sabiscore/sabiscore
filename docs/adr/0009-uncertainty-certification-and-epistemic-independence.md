# ADR 0009: Uncertainty certification and epistemic independence

Status: Accepted. Gates remain closed; this ADR authorises no promotion.
Date: 2026-08-31.

Supersedes nothing. Extends ADR 0007 (evidence authority and Apex promotion),
which established FastAPI as the sole certification and staking authority.

## Context

Two critical gaps stand between the platform and any executable verdict. Both
were re-confirmed live this session against `sabiscore-api-bav1.onrender.com`
(backend `sha b995612`) on real fixtures — not inferred from code:

```
GET /api/v1/matches/upcoming/fd-560557/full-analysis?league=EPL
  prediction_status : AVAILABLE
  verdict           : PARTIAL
  stake_permitted   : false
  critical_gaps     : ["MODEL_GENERATION_UNCERTIFIED",
                       "MODEL_UNCERTAINTY_UNAVAILABLE"]
```

The second gap is emitted unconditionally whenever measured uncertainty is
absent (`api/endpoints/full_analysis.py:734-736`), because
`UncertaintyService.decompose_measured()` short-circuits when
`self._bnn_model is None or torch is None`. `torch` appears in no
`requirements*.txt`, and no trained BNN artifact exists in the repository.

**Certifying the model does not unlock staking.** `stake_permitted` requires
`not partial`, and any entry in `critical_gaps` forces `partial`. Clearing
`MODEL_GENERATION_UNCERTIFIED` therefore leaves `MODEL_UNCERTAINTY_UNAVAILABLE`
standing, and a fixture remains no-bet regardless of model quality. The two
gates are independent and both must be satisfied on their own evidence.

## Decision

The gate is **not** modified. Recorded state:

```
MODEL_GENERATION_UNCERTIFIED    = CRITICAL
MODEL_UNCERTAINTY_UNAVAILABLE   = CRITICAL
stake_permitted                 = false
operating_mode                  = research-only
```

### Rejected approach — probability-derived epistemic uncertainty

The following is rejected as an epistemic uncertainty source, permanently:

```
prediction -> confidence transformation -> "epistemic uncertainty"
```

Concretely this covers `1 - max(p)`, `entropy(p)`, `1 - confidence`, and the
expected Brier score `1 - sum_c p_c^2`.

**Why it is invalid: it is self-referential.** Each of these is a deterministic
function of the model's own final probability vector. It therefore contains no
information the prediction does not already carry, and cannot distinguish a
forecast the model is *well-supported* in making from one it is *guessing* at.
A model would be certifying its own confidence using its own answer. Two
fixtures with identical output probabilities would receive identical
"uncertainty" even if one sits deep inside the training distribution and the
other is entirely out of support.

`UncertaintyService.decompose_from_probabilities()` implements exactly this
shape (`epistemic_unc = 1 - confidence`, `aleatoric_unc = normalised entropy`).
It already exists and is already correctly excluded from the public path:
`_uncertainty_from_features()` is documented *"Return measured BNN uncertainty,
never a probability-derived proxy"* and calls `decompose_measured()` alone.
That exclusion is deliberate and is preserved. These quantities may remain
**descriptive prediction statistics**; they must never satisfy the epistemic
gate.

This ADR does not delete `decompose_from_probabilities()`. It has legitimate
non-gate uses and removing it is a separate decision; what is fixed here is
that it can never authorise a stake.

### Rejected approach — introducing Torch to satisfy the historical shape

The gap exists because a BNN was the original implementation. That is not a
reason to add a ~800 MB GPU-oriented dependency to a free-tier CPU service.
Any prior `bnn_ensemble.pt` artifact is treated as invalid and must not be
loaded: it was label-derived and has never passed leakage testing.

### Chosen approach — ensemble dispersion

Epistemic uncertainty will be derived from **disagreement between independently
trained ensemble members**, using the Depeweg/BALD decomposition:

```
total      = H( mean_m p_m )      predictive entropy of the ensemble mean
aleatoric  = mean_m H( p_m )      average within-member entropy
epistemic  = total - aleatoric    mutual information; >= 0, zero iff members agree
```

This is not a transform of the aggregate prediction. Two fixtures with the same
mean probability vector receive different epistemic values when their members
disagree by different amounts — which is precisely the information a
probability-derived proxy cannot carry.

**Feasibility was measured before this ADR was written**, against the real
shipped `epl_ensemble_v5_phase7.pkl` and the real 12,765-match corpus
(2,571 EPL rows, features in the artifact's own `CANONICAL_FEATURES_68` order):

| Property | Measured |
|---|---|
| `epistemic >= 0` everywhere | true |
| `corr(epistemic, 1 - max(p))` | −0.28 across 3 base learners; −0.10 across 300 RF bootstrap members |
| `corr(epistemic, entropy(p))` | −0.36 |
| `corr(epistemic, 1 - sum p^2)` | −0.34 |
| Spread within a tight confidence band (`max(p)` ∈ 0.497–0.506, n=80) | epistemic 0.0007 … 0.0884 — a 119× range |

The final row is the decisive one. Where the model is *equally confident*,
epistemic uncertainty still varies 119-fold. Any `1 - confidence` proxy is
constant across that band by construction. The signal is independent.

The shipped artifacts already contain the members required: three base learners
(`random_forest`, `xgboost`, `lightgbm`), each exposing `predict_proba`, and the
random forest additionally exposes 300 bootstrap-resampled trees via
`estimators_`. No retraining and no new dependency are needed to compute it.

## Consequences

- Staking stays disabled until **both** gates pass on their own evidence.
- `MODEL_UNCERTAINTY_UNAVAILABLE` continues to fire whenever the certified
  computation does not succeed. `available = true` is permitted only when it
  actually ran; there is no fallback value.
- A feasibility measurement is not a certification. The numbers above establish
  that the approach *can* work; Stage 11 validation (determinism, error
  association, robustness across leagues/regimes) is still required before the
  gate may open.
- The correlations reported here are from the current v5_phase7 artifacts. They
  must be re-derived for any future generation — a differently-trained ensemble
  can have differently-correlated dispersion.

## Addendum — 2026-08-31 (M2 implementation and validation)

`src/models/ensemble_uncertainty.py` implements `ensemble_dispersion` exactly
as specified above, over the shipped `random_forest` member's 300 bootstrap
trees (`estimators_`) — the "bootstrap variants preferred over distinct
algorithms" design `UNCERTAINTY_GATES.sufficient_members` already called for.
`tests/unit/test_uncertainty_contract.py` is the validation test cited
throughout `uncertainty_policy.py`; it genuinely runs, against the full real
2,571-row EPL corpus scored by the real shipped `epl_ensemble_v5_phase7.pkl`
artifact — not a synthetic stand-in, for the same reason a synthetic corpus
could trivially be constructed to pass any of these gates.

**Five of six gates pass on that real evidence:**

| Gate | Measured |
|---|---|
| `method_is_authorised` | `ensemble_dispersion`, bootstrap trees |
| `sufficient_members` | 300 members (preferred floor: 30) |
| `non_negative` | `epistemic >= 0` and `epistemic <= total` on all 2,571 rows |
| `determinism` | 0.0 deviation (repeated calls, identical input) |
| `independence_from_confidence` | `corr(epistemic, 1-confidence) = -0.003` (bar: `\|corr\| <= 0.70`) |
| `informative_within_confidence_band` | spread_ratio 3.47 in a 281-row band (bar: `>= 2.0`) |

**One does not: `error_association`.** The gate requires the
highest-epistemic quartile to show *worse* mean RPS than the lowest. Measured,
it is the reverse — monotonically, across all four quartiles:

```text
bucket 0 (lowest epistemic,  mean 0.070): mean RPS 0.2134
bucket 1                    (mean 0.084): mean RPS 0.2024
bucket 2                    (mean 0.094): mean RPS 0.2002
bucket 3 (highest epistemic, mean 0.113): mean RPS 0.1905
```

This was cross-checked against a second, independent member-selection design
— the 3 distinct base learners (random_forest / xgboost / lightgbm) instead of
the RF's bootstrap trees — as a design-finalisation step, not post-hoc
threshold shopping: both designs were already named as candidates in this
ADR's own feasibility table before any Stage 11 test was written. The
base-learner design reproduces `corr(epistemic, 1-confidence) = -0.281`,
matching the `-0.28` this ADR reported almost exactly (independent
confirmation the implementation is faithful to the measurement that motivated
it) — and shows the *same* RPS reversal, more strongly (gap −0.070 vs the
bootstrap-tree design's −0.023). Two independent designs agreeing rules out
"wrong member selection" as the explanation; this is a real property of the
current `v5_phase7` EPL artifact against this corpus, not an implementation
artifact.

**Reading:** for this specific model, rows where trees/learners disagree most
tend to be rows the ensemble mean already handles *better*, not worse —
plausibly because disagreement here correlates with a more evenly-spread
predicted distribution, and RPS (a proper scoring rule) rewards a
well-calibrated spread over an overconfident call that occasionally misses
badly. Plausible, but not yet established; not investigated further this
session, since `UNCERTAINTY_REQUIRES_ALL_GATES = True` already settles the
certification question regardless of the mechanism.

**Decision: the gate is not opened.** `MODEL_UNCERTAINTY_UNAVAILABLE` stays
unconditionally CRITICAL in `full_analysis.py::_uncertainty_from_features`,
which returns `None` regardless of whether the underlying computation would
succeed — per this ADR's own "no fallback, no partial pass" semantics and the
certification directive's stop conditions. `uncertainty_policy.py`'s
`IMPLEMENTATION_STATUS` is updated to `IMPLEMENTED_VALIDATION_FAILED`
(`gates_exercised: true`, `gates_failed: ["error_association"]`) rather than
`SPECIFIED_NOT_IMPLEMENTED` — the method is built and genuinely tested; it is
tested-and-failing, not untested. `docs/DEBT.md` item 50 records this as an
open finding: whether the reversal is inherent to this artifact (in which case
a future `v5_phase7`-successor generation may simply pass) or is fixable by a
methodological change (e.g. weighting members, a different epistemic
aggregation) is not yet known and is out of this session's scope to resolve.

## References

- `docs/adr/0007-evidence-authority-and-apex-promotion.md`
- `backend/src/models/certification_policy.py` — v1.1.0,
  sha256 `7e1e238456df14de182d957a0351485c63892c7980746d3a72488f248697d07a`
- `backend/models/feature_contract.json` — `phase7_68`,
  sha256 `7681886093e33af49f1efcca2880e76d1fa66732fc26e2796f56a6c0ee6d6d13`
- `backend/reports/evaluation/metric-contract.json` — metric contract v1.0.0
- Depeweg et al. (2018), *Decomposition of Uncertainty in Bayesian Deep Learning*
- Houlsby et al. (2011), BALD — mutual information as epistemic uncertainty
