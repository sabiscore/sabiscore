import math

import numpy as np
import pandas as pd
from typing import Dict, List, Any
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class MatchSimulationResult:
    """Result of a single match simulation"""

    home_score: int
    away_score: int
    result: str  # 'home_win', 'draw', 'away_win'
    total_goals: int
    goal_difference: int


class MatchSimulator:
    """Monte Carlo match simulator"""

    def __init__(self, random_seed: int = 42):
        self.rng = np.random.RandomState(random_seed)

    def run_match_simulation(
        self, home_xg: float, away_xg: float, n_sims: int = 10000, max_goals: int = 10
    ) -> Dict[str, Any]:
        """
        Run Monte Carlo simulation for match outcomes

        Args:
            home_xg: Expected goals for home team
            away_xg: Expected goals for away team
            n_sims: Number of simulations to run
            max_goals: Maximum goals to consider per team

        Returns:
            Dictionary with simulation results
        """
        logger.info(
            f"Running {n_sims} simulations for xG {home_xg:.2f} vs {away_xg:.2f}"
        )

        # Pre-calculate Poisson probabilities for efficiency
        home_poisson = self._calculate_poisson_probs(home_xg, max_goals)
        away_poisson = self._calculate_poisson_probs(away_xg, max_goals)

        # Run simulations
        results = []
        for _ in range(n_sims):
            sim_result = self._simulate_single_match(
                home_poisson, away_poisson, max_goals
            )
            results.append(sim_result)

        # Analyze results
        analysis = self._analyze_simulation_results(results, home_xg, away_xg)

        logger.info("Simulation completed")
        return analysis

    def _calculate_poisson_probs(self, xg: float, max_goals: int) -> np.ndarray:
        """Calculate Poisson probabilities for goals 0 to max_goals"""
        probs = np.zeros(max_goals + 1)
        for goals in range(max_goals + 1):
            # `math.factorial`, not `np.math.factorial`: `np.math` was a private
            # alias for the stdlib module and was REMOVED in NumPy 2.0. This line
            # raised AttributeError on every call under the installed NumPy
            # (2.5.0), which no test or caller ever surfaced because nothing in
            # the repository imports this module — see docs/DEBT.md item 73.
            probs[goals] = np.exp(-xg) * (xg**goals) / math.factorial(goals)

        # Normalize to ensure sum = 1 (due to factorial approximation)
        probs = probs / probs.sum()

        return probs

    def _simulate_single_match(
        self, home_poisson: np.ndarray, away_poisson: np.ndarray, max_goals: int
    ) -> MatchSimulationResult:
        """Simulate a single match"""
        # Sample goals from Poisson distributions
        home_goals = self.rng.choice(len(home_poisson), p=home_poisson)
        away_goals = self.rng.choice(len(away_poisson), p=away_poisson)

        # Determine result
        if home_goals > away_goals:
            result = "home_win"
        elif away_goals > home_goals:
            result = "away_win"
        else:
            result = "draw"

        return MatchSimulationResult(
            home_score=home_goals,
            away_score=away_goals,
            result=result,
            total_goals=home_goals + away_goals,
            goal_difference=home_goals - away_goals,
        )

    def _analyze_simulation_results(
        self, results: List[MatchSimulationResult], home_xg: float, away_xg: float
    ) -> Dict[str, Any]:
        """Analyze simulation results"""
        # Convert to DataFrame for easier analysis
        df = pd.DataFrame(
            [
                {
                    "home_score": r.home_score,
                    "away_score": r.away_score,
                    "result": r.result,
                    "total_goals": r.total_goals,
                    "goal_difference": r.goal_difference,
                }
                for r in results
            ]
        )

        # Basic outcome probabilities
        outcome_counts = df["result"].value_counts()
        total_sims = len(df)

        outcomes = {
            "home_win_prob": outcome_counts.get("home_win", 0) / total_sims,
            "draw_prob": outcome_counts.get("draw", 0) / total_sims,
            "away_win_prob": outcome_counts.get("away_win", 0) / total_sims,
        }

        # Scoreline probabilities (most common)
        scorelines = (
            df.groupby(["home_score", "away_score"]).size().reset_index(name="count")
        )
        scorelines["probability"] = scorelines["count"] / total_sims
        scorelines = scorelines.sort_values("probability", ascending=False)

        most_likely_scorelines = scorelines.head(5).to_dict("records")

        # Goal statistics
        goal_stats = {
            "avg_home_goals": df["home_score"].mean(),
            "avg_away_goals": df["away_score"].mean(),
            "avg_total_goals": df["total_goals"].mean(),
            "home_goals_std": df["home_score"].std(),
            "away_goals_std": df["away_score"].std(),
            "total_goals_std": df["total_goals"].std(),
        }

        # Goal distribution
        home_goal_dist = (df["home_score"].value_counts() / total_sims).to_dict()
        away_goal_dist = (df["away_score"].value_counts() / total_sims).to_dict()
        total_goal_dist = (df["total_goals"].value_counts() / total_sims).to_dict()

        # Confidence intervals (95%)
        conf_intervals = {}
        for outcome in ["home_win", "draw", "away_win"]:
            count = outcome_counts.get(outcome, 0)
            prob = count / total_sims
            se = np.sqrt(prob * (1 - prob) / total_sims)
            margin = 1.96 * se
            conf_intervals[outcome] = {
                "prob": prob,
                "lower": max(0, prob - margin),
                "upper": min(1, prob + margin),
            }

        # Over/under probabilities
        ou_lines = [0.5, 1.5, 2.5, 3.5, 4.5]
        over_under = {}
        for line in ou_lines:
            over_count = (df["total_goals"] > line).sum()
            under_count = (df["total_goals"] < line).sum()
            over_under[f"over_{line}"] = over_count / total_sims
            over_under[f"under_{line}"] = under_count / total_sims

        # Both teams to score (BTTS)
        btts_prob = ((df["home_score"] > 0) & (df["away_score"] > 0)).sum() / total_sims

        # Clean sheet probabilities
        home_clean_sheet = (df["away_score"] == 0).sum() / total_sims
        away_clean_sheet = (df["home_score"] == 0).sum() / total_sims

        return {
            "simulations_run": total_sims,
            "input_xg": {"home": home_xg, "away": away_xg},
            "outcome_probabilities": outcomes,
            "confidence_intervals": conf_intervals,
            "most_likely_scorelines": most_likely_scorelines,
            "goal_statistics": goal_stats,
            "goal_distributions": {
                "home": home_goal_dist,
                "away": away_goal_dist,
                "total": total_goal_dist,
            },
            "over_under_probabilities": over_under,
            "btts_probability": btts_prob,
            "clean_sheet_probabilities": {
                "home": home_clean_sheet,
                "away": away_clean_sheet,
            },
        }


class ScenarioSimulator:
    """Simulator for different match scenarios"""

    def __init__(self, base_simulator: MatchSimulator = None):
        self.base_simulator = base_simulator or MatchSimulator()

    def simulate_scenario(
        self,
        base_xg: Dict[str, float],
        scenario_modifiers: Dict[str, Any],
        n_sims: int = 5000,
    ) -> Dict[str, Any]:
        """
        Simulate a specific scenario with modifiers

        Args:
            base_xg: Base expected goals {'home': float, 'away': float}
            scenario_modifiers: Modifiers to apply {'home_xg_multiplier': float, etc.}
            n_sims: Number of simulations

        Returns:
            Scenario simulation results
        """
        # Apply modifiers
        modified_xg = base_xg.copy()

        if "home_xg_multiplier" in scenario_modifiers:
            modified_xg["home"] *= scenario_modifiers["home_xg_multiplier"]

        if "away_xg_multiplier" in scenario_modifiers:
            modified_xg["away"] *= scenario_modifiers["away_xg_multiplier"]

        if "home_xg_add" in scenario_modifiers:
            modified_xg["home"] += scenario_modifiers["home_xg_add"]

        if "away_xg_add" in scenario_modifiers:
            modified_xg["away"] += scenario_modifiers["away_xg_add"]

        # Run simulation with modified xG
        results = self.base_simulator.run_match_simulation(
            modified_xg["home"], modified_xg["away"], n_sims
        )

        results["scenario"] = scenario_modifiers
        results["modified_xg"] = modified_xg

        return results

    def compare_scenarios(
        self,
        base_xg: Dict[str, float],
        scenarios: List[Dict[str, Any]],
        n_sims: int = 3000,
    ) -> Dict[str, Any]:
        """
        Compare multiple scenarios against base case

        Args:
            base_xg: Base expected goals
            scenarios: List of scenario modifiers
            n_sims: Simulations per scenario

        Returns:
            Comparison results
        """
        # Base case
        base_results = self.base_simulator.run_match_simulation(
            base_xg["home"], base_xg["away"], n_sims
        )
        base_results["scenario_name"] = "Base Case"

        # Scenario results
        scenario_results = []
        for i, scenario_modifiers in enumerate(scenarios):
            result = self.simulate_scenario(base_xg, scenario_modifiers, n_sims)
            result["scenario_name"] = f"Scenario {i + 1}"
            scenario_results.append(result)

        # Compare outcomes
        comparison = {
            "base_case": base_results,
            "scenarios": scenario_results,
            "comparison": self._compare_results(base_results, scenario_results),
        }

        return comparison

    def _compare_results(
        self, base_results: Dict[str, Any], scenario_results: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Compare scenario results against base case"""
        base_outcomes = base_results["outcome_probabilities"]

        comparisons = []
        for scenario in scenario_results:
            scenario_outcomes = scenario["outcome_probabilities"]

            comparison = {
                "scenario_name": scenario["scenario_name"],
                "home_win_diff": scenario_outcomes["home_win_prob"]
                - base_outcomes["home_win_prob"],
                "draw_diff": scenario_outcomes["draw_prob"]
                - base_outcomes["draw_prob"],
                "away_win_diff": scenario_outcomes["away_win_prob"]
                - base_outcomes["away_win_prob"],
                "total_goals_diff": scenario["goal_statistics"]["avg_total_goals"]
                - base_results["goal_statistics"]["avg_total_goals"],
            }

            comparisons.append(comparison)

        return comparisons


# Convenience functions
def run_match_simulation(
    home_xg: float, away_xg: float, n_sims: int = 10000
) -> Dict[str, Any]:
    """Convenience function for match simulation"""
    simulator = MatchSimulator()
    return simulator.run_match_simulation(home_xg, away_xg, n_sims)


def simulate_scenarios(
    base_xg: Dict[str, float], scenarios: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """Convenience function for scenario comparison"""
    simulator = ScenarioSimulator()
    return simulator.compare_scenarios(base_xg, scenarios)
