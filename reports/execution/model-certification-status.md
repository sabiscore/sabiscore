# SabiScore — Quantitative Model Certification Status Report

**Date**: 2026-09-30  
**Authority**: Multi-Agent Engineering Council (Quantitative Modeling Specialist)  
**Governing Directive**: Directive V15.0 (`docs/PRODUCTION_EXECUTIVE_DIRECTIVE_V15.md`)  
**Status**: `UNVERIFIED` · Staking Withheld (`stake_permitted = false`)

---

## 1. Active Generation Identity & Serving Footprint

- **Served Generation**: `v5_phase7-20260922@417b9b8ff7ce563d`
- **Active Generation Manifest**: `backend/models/active_generation.json`
- **Feature Contract**: `apex_v1_68` (68 canonical point-in-time features)
- **Target Competitions**: Exactly 6 domestic leagues:
  1. `EPL`: `epl_ensemble_v5_phase7.pkl`
  2. `LA_LIGA`: `la_liga_ensemble_v5_phase7.pkl`
  3. `BUNDESLIGA`: `bundesliga_ensemble_v5_phase7.pkl`
  4. `SERIE_A`: `serie_a_ensemble_v5_phase7.pkl`
  5. `LIGUE_1`: `ligue_1_ensemble_v5_phase7.pkl`
  6. `EREDIVISIE`: `eredivisie_ensemble_v5_phase7.pkl`
- **Serving Architecture**:
  - Base Classifiers: `RandomForestClassifier`, `XGBClassifier`, `LGBMClassifier`
  - Meta-Learner: Multinomial Logistic Regression meta-model
  - Calibration: Closed-form Platt scaling sigmoid arithmetic ($\text{logit} = \text{clip}(w \cdot p + b, -30, 30)$)
  - Memory Footprint: 11 MB on disk, ~55 MB resident heap, bounded 8-model in-memory LRU cache (`MAX_CACHED_MODELS=8`).

---

## 2. Frozen C6 Market Baseline Protocol

Model sharpness is evaluated strictly against the Pinnacle closing line via the pre-registered, frozen C6 Protocol:

- **Protocol Path**: `reports/research/c6-served-generation-vs-close-protocol.json`
- **Immutability Hash (SHA-256)**: `9d63da25324a79f4f08416d79991281bd45155064ec33fd8f67284b28be46ba7`
- **Population Definition**: Settled fixtures where the prediction was captured pre-kickoff ($t_{\text{capture}} < t_{\text{closing}} < t_{\text{kickoff}}$) under the served generation with `capture_trigger = "interactive_full_analysis"`.
- **Primary Metric**: Paired Ranked Probability Score difference:
  $$\Delta RPS_i = RPS_{\text{model}, i} - RPS_{\text{pinnacle}, i}$$
- **Statistical Inference**:
  - ISO-week cluster bootstrapping (10,000 replicates, random seed 42)
  - Pre-registered looks at sample milestones: $N \in \{200, 500, 1000\}$
  - Family-wise error control (Bonferroni): $\alpha = \frac{0.05}{3} \approx 0.016667 \implies 98.33\% \text{ CI}$

---

## 3. Current Empirical Evidence & Sample Progress

| Metric / Attribute | Measured Production Value | Operational Rule / Invariant |
| :--- | :---: | :--- |
| **Settled Joined Forecasts** | **0** | Minimum required sample floor is $N = 200$. |
| **Interim Metric Display** | `METRICS_UNAVAILABLE` | Under DEBT 157 & 161, endpoints withhold mean $\Delta RPS$ and CI until $N \ge 200$. |
| **Certification State** | `UNVERIFIED` | Point estimates cannot certify models. Statistical CI must establish superiority. |
| **Staking Permission** | `WITHHELD` (`false`) | Zero customer stakes permitted while certification state is `UNVERIFIED`. |
| **Counter-Case Panel** | **ACTIVE** | Discloses that model has not passed market certification and edge is not evidence of value. |

---

## 4. Promotion Governance & Prohibitions

1. **Zero Autonomous Promotion**: No agent, CI job, or automated script may alter `certification_state` in `backend/models/active_generation.json`.
2. **Milestone Protocol**: Promotion requires:
   - At least 200 verified settled fixtures under generation `v5_phase7`.
   - Upper bound of the 98.33% cluster bootstrap CI strictly below 0.0 ($\Delta RPS < 0$).
   - Formal sign-off and review by human operators.
3. **UEFA Champions League (UCL) Cap**: UCL is structurally capped at `ACTIONABLE`; public forecasts and staking for UCL remain withheld until a dedicated cross-league model is trained and certified.
