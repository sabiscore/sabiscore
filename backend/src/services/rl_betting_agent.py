"""Reward-shaped betting recommendation service (Phase 6-C).

Primary inference path: SAC model loaded from settings.rl_agent_path (stable-baselines3).
Fallback: deterministic Kelly-fraction policy (always available, no dependencies).

The SAC model is written to rl_agent_path ONLY by scripts/train_rl_agent.py after all
four production gates pass on 500 held-out episodes (C16).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Mapping, Optional, Tuple

import numpy as np

from ..core.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional stable-baselines3 import — graceful fallback if not installed
# ---------------------------------------------------------------------------
try:
    from stable_baselines3 import SAC as _SB3_SAC  # type: ignore

    _SB3_AVAILABLE = True
except Exception:
    _SB3_AVAILABLE = False

# Outcome indices in the SAC action vector
_IDX_HOME = 0
_IDX_DRAW = 1
_IDX_AWAY = 2
_IDX_ABSTAIN = 3

# Mapping from market keys to outcome indices
_MARKET_TO_IDX: Dict[str, int] = {
    "home_win": _IDX_HOME,
    "draw": _IDX_DRAW,
    "away_win": _IDX_AWAY,
}


@dataclass(frozen=True)
class RLRecommendationPayload:
    stake_fraction: float
    abstain: bool
    reward_components: Dict[str, float]
    reason: str


class RLBettingAgent:
    """Generate stake recommendations, SAC-backed when a trained model is available.

    Inference flow:
    1. If `settings.rl_agent_path` exists AND stable-baselines3 is installed,
       load the SAC model and use it to derive outcome + stake.
    2. Otherwise fall back to the deterministic Kelly policy.

    State vector (16 dims, normalized) fed to SAC:
      [home_prob, draw_prob, away_prob, epistemic_unc, aleatoric_unc,
       edge_home, edge_draw, edge_away,
       home_odds, draw_odds, away_odds,
       bankroll_pct, current_drawdown, rolling_sharpe, win_rate_20, rolling_ece_20]

    Action vector (5 dims, continuous [-2, 2]):
      [logit_home, logit_draw, logit_away, logit_abstain, stake_raw]
      outcome      = argmax(action[:4])
      stake_fraction = clip(sigmoid(action[4]) * max_kelly_cap, 0, max_kelly_cap)
    """

    def __init__(
        self,
        epistemic_threshold: Optional[float] = None,
        max_kelly_cap: Optional[float] = None,
        abstention_enabled: Optional[bool] = None,
    ) -> None:
        self.epistemic_threshold = (
            settings.epistemic_threshold
            if epistemic_threshold is None
            else epistemic_threshold
        )
        self.max_kelly_cap = (
            settings.rl_max_kelly_cap if max_kelly_cap is None else max_kelly_cap
        )
        self.abstention_enabled = (
            settings.rl_abstention_enabled
            if abstention_enabled is None
            else abstention_enabled
        )
        self._sac_model = self._load_sac_model()

    # ------------------------------------------------------------------
    # SAC model loading
    # ------------------------------------------------------------------

    def _load_sac_model(self):
        if not _SB3_AVAILABLE:
            return None
        model_path = Path(settings.rl_agent_path)
        if not model_path.exists():
            logger.debug(
                "SAC model not found at %s; using deterministic fallback", model_path
            )
            return None
        try:
            model = _SB3_SAC.load(str(model_path))
            logger.info("SAC betting model loaded from %s", model_path)
            return model
        except Exception as exc:
            logger.warning("Failed to load SAC model from %s: %s", model_path, exc)
            return None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def recommend(
        self,
        probabilities: Mapping[str, float],
        odds: Mapping[str, float],
        confidence: float,
        epistemic_unc: float,
        aleatoric_unc: float = 0.0,
        bankroll_pct: float = 1.0,
        current_drawdown: float = 0.0,
        rolling_sharpe: float = 0.0,
        win_rate_20: float = 0.5,
        rolling_ece_20: float = 0.0,
    ) -> RLRecommendationPayload:
        """Return a stake recommendation and reward decomposition.

        When a SAC model is loaded, derives recommendation from the 16-dim state.
        Otherwise uses the deterministic Kelly policy.
        """
        if self._sac_model is not None:
            return self._recommend_sac(
                probabilities=probabilities,
                odds=odds,
                epistemic_unc=epistemic_unc,
                aleatoric_unc=aleatoric_unc,
                bankroll_pct=bankroll_pct,
                current_drawdown=current_drawdown,
                rolling_sharpe=rolling_sharpe,
                win_rate_20=win_rate_20,
                rolling_ece_20=rolling_ece_20,
                confidence=confidence,
            )
        return self._recommend_kelly(probabilities, odds, confidence, epistemic_unc)

    # ------------------------------------------------------------------
    # SAC inference path
    # ------------------------------------------------------------------

    def _build_state(
        self,
        probabilities: Mapping[str, float],
        odds: Mapping[str, float],
        epistemic_unc: float,
        aleatoric_unc: float,
        bankroll_pct: float,
        current_drawdown: float,
        rolling_sharpe: float,
        win_rate_20: float,
        rolling_ece_20: float,
    ) -> np.ndarray:
        home_prob = float(probabilities.get("home_win", 0.333))
        draw_prob = float(probabilities.get("draw", 0.333))
        away_prob = float(probabilities.get("away_win", 0.333))

        home_odds = max(float(odds.get("home_win", 2.0)), 1.01)
        draw_odds = max(float(odds.get("draw", 3.2)), 1.01)
        away_odds = max(float(odds.get("away_win", 2.5)), 1.01)

        mkt_home = 1.0 / home_odds
        mkt_draw = 1.0 / draw_odds
        mkt_away = 1.0 / away_odds

        edge_home = home_prob - mkt_home
        edge_draw = draw_prob - mkt_draw
        edge_away = away_prob - mkt_away

        state = np.array(
            [
                home_prob,
                draw_prob,
                away_prob,
                float(epistemic_unc),
                float(aleatoric_unc),
                edge_home,
                edge_draw,
                edge_away,
                home_odds,
                draw_odds,
                away_odds,
                float(bankroll_pct),
                float(current_drawdown),
                float(rolling_sharpe),
                float(win_rate_20),
                float(rolling_ece_20),
            ],
            dtype=np.float32,
        )
        return state

    def _recommend_sac(
        self,
        probabilities: Mapping[str, float],
        odds: Mapping[str, float],
        epistemic_unc: float,
        aleatoric_unc: float,
        bankroll_pct: float,
        current_drawdown: float,
        rolling_sharpe: float,
        win_rate_20: float,
        rolling_ece_20: float,
        confidence: float,
    ) -> RLRecommendationPayload:
        state = self._build_state(
            probabilities,
            odds,
            epistemic_unc,
            aleatoric_unc,
            bankroll_pct,
            current_drawdown,
            rolling_sharpe,
            win_rate_20,
            rolling_ece_20,
        )
        try:
            action, _ = self._sac_model.predict(state, deterministic=True)
        except Exception as exc:
            logger.warning("SAC predict failed: %s — falling back to Kelly", exc)
            return self._recommend_kelly(probabilities, odds, confidence, epistemic_unc)

        # Decode action: first 4 dims = outcome logits, 5th = stake signal
        outcome_logits = action[:4]
        outcome_idx = int(np.argmax(outcome_logits))
        stake_raw = float(action[4]) if len(action) > 4 else 0.0

        # Scale stake: sigmoid maps [-2,2] → roughly [0.12, 0.88]; rescale to [0, max_kelly]
        stake_fraction = float(
            np.clip(
                1.0 / (1.0 + np.exp(-stake_raw)) * self.max_kelly_cap,
                0.0,
                self.max_kelly_cap,
            )
        )

        abstain = outcome_idx == _IDX_ABSTAIN
        if abstain:
            stake_fraction = 0.0

        market_map = {_IDX_HOME: "home_win", _IDX_DRAW: "draw", _IDX_AWAY: "away_win"}
        market = market_map.get(outcome_idx, "home_win")
        market_odds = max(float(odds.get(market, 2.0)), 1.01)

        reward_components = self._reward_components(
            confidence=confidence,
            epistemic_unc=epistemic_unc,
            stake_fraction=stake_fraction,
            abstain=abstain,
            market_odds=market_odds,
        )

        reason = (
            f"SAC ABSTAIN (epistemic={epistemic_unc:.3f})"
            if abstain
            else f"SAC: {market} stake={stake_fraction:.4f} (odds={market_odds:.2f})"
        )
        return RLRecommendationPayload(
            stake_fraction=stake_fraction,
            abstain=abstain,
            reward_components=reward_components,
            reason=reason,
        )

    # ------------------------------------------------------------------
    # Deterministic Kelly fallback (always-available path)
    # ------------------------------------------------------------------

    def _recommend_kelly(
        self,
        probabilities: Mapping[str, float],
        odds: Mapping[str, float],
        confidence: float,
        epistemic_unc: float,
    ) -> RLRecommendationPayload:
        market, market_prob, market_odds = self._pick_market(probabilities, odds)

        should_abstain = (
            self.abstention_enabled and epistemic_unc > self.epistemic_threshold
        )
        raw_kelly = self._kelly_fraction(market_prob, market_odds)
        stake_fraction = 0.0 if should_abstain else min(raw_kelly, self.max_kelly_cap)

        reward_components = self._reward_components(
            confidence=confidence,
            epistemic_unc=epistemic_unc,
            stake_fraction=stake_fraction,
            abstain=should_abstain,
            market_odds=market_odds,
        )

        reason = (
            f"Abstained: epistemic={epistemic_unc:.3f} > threshold={self.epistemic_threshold:.3f}"
            if should_abstain
            else f"Kelly: {market} stake={stake_fraction:.4f} (cap={self.max_kelly_cap:.4f})"
        )
        return RLRecommendationPayload(
            stake_fraction=stake_fraction,
            abstain=should_abstain,
            reward_components=reward_components,
            reason=reason,
        )

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _pick_market(
        self,
        probabilities: Mapping[str, float],
        odds: Mapping[str, float],
    ) -> Tuple[str, float, float]:
        candidate = "home_win"
        max_prob = max(float(probabilities.get("home_win", 0.0)), 0.0)

        for market in ("draw", "away_win"):
            current = max(float(probabilities.get(market, 0.0)), 0.0)
            if current > max_prob:
                candidate = market
                max_prob = current

        market_odds = max(float(odds.get(candidate, 0.0)), 0.0)
        return candidate, max_prob, market_odds

    @staticmethod
    def _kelly_fraction(probability: float, decimal_odds: float) -> float:
        if decimal_odds <= 1.0:
            return 0.0
        edge = (probability * decimal_odds) - 1.0
        if edge <= 0:
            return 0.0
        denominator = decimal_odds - 1.0
        if denominator <= 0:
            return 0.0
        return max(0.0, edge / denominator)

    def _reward_components(
        self,
        confidence: float,
        epistemic_unc: float,
        stake_fraction: float,
        abstain: bool,
        market_odds: float,
    ) -> Dict[str, float]:
        r_pnl = (
            0.0 if abstain else min(1.0, stake_fraction * max(market_odds - 1.0, 0.0))
        )
        r_ic = max(-1.0, min(1.0, (confidence * 2.0) - 1.0))
        r_cal = -abs(epistemic_unc)
        r_risk = 0.0 if abstain else max(-1.0, min(1.0, r_pnl - stake_fraction))
        r_abs = 0.05 if abstain and epistemic_unc > self.epistemic_threshold else 0.0
        return {
            "R_pnl": round(r_pnl, 6),
            "R_ic": round(r_ic, 6),
            "R_cal": round(r_cal, 6),
            "R_risk": round(r_risk, 6),
            "R_abs": round(r_abs, 6),
        }
