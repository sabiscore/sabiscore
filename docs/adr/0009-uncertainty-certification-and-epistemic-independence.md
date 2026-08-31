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

## References

- `docs/adr/0007-evidence-authority-and-apex-promotion.md`
- `backend/src/models/certification_policy.py` — v1.1.0,
  sha256 `7e1e238456df14de182d957a0351485c63892c7980746d3a72488f248697d07a`
- `backend/models/feature_contract.json` — `phase7_68`,
  sha256 `7681886093e33af49f1efcca2880e76d1fa66732fc26e2796f56a6c0ee6d6d13`
- `backend/reports/evaluation/metric-contract.json` — metric contract v1.0.0
- Depeweg et al. (2018), *Decomposition of Uncertainty in Bayesian Deep Learning*
- Houlsby et al. (2011), BALD — mutual information as epistemic uncertainty
