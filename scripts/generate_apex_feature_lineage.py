#!/usr/bin/env python3
"""Generate canonical apex-feature-lineage.json for all 68 APEX features.

Directive V18.0 Section 2.3.
"""

import json
from pathlib import Path

FEATURES_68 = [
    # 1-8: Form
    ("home_form_last5_home", "form", ["football-data.org"], ["api-football"], 86400, "t_match <= t_cutoff - 2h", 0.95, "critical", "points_avg", "points", [0.0, 3.0], "low"),
    ("home_wins_last5_home", "form", ["football-data.org"], ["api-football"], 86400, "t_match <= t_cutoff - 2h", 0.95, "advisory", "sum", "wins", [0, 5], "low"),
    ("home_draws_last5_home", "form", ["football-data.org"], ["api-football"], 86400, "t_match <= t_cutoff - 2h", 0.95, "advisory", "sum", "draws", [0, 5], "low"),
    ("home_losses_last5_home", "form", ["football-data.org"], ["api-football"], 86400, "t_match <= t_cutoff - 2h", 0.95, "advisory", "sum", "losses", [0, 5], "low"),
    ("away_form_last5_away", "form", ["football-data.org"], ["api-football"], 86400, "t_match <= t_cutoff - 2h", 0.95, "critical", "points_avg", "points", [0.0, 3.0], "low"),
    ("away_wins_last5_away", "form", ["football-data.org"], ["api-football"], 86400, "t_match <= t_cutoff - 2h", 0.95, "advisory", "sum", "wins", [0, 5], "low"),
    ("away_draws_last5_away", "form", ["football-data.org"], ["api-football"], 86400, "t_match <= t_cutoff - 2h", 0.95, "advisory", "sum", "draws", [0, 5], "low"),
    ("away_losses_last5_away", "form", ["football-data.org"], ["api-football"], 86400, "t_match <= t_cutoff - 2h", 0.95, "advisory", "sum", "losses", [0, 5], "low"),
    # 9-13: Goals
    ("home_goals_for_avg", "scoring", ["football-data.org"], ["api-football"], 86400, "t_match <= t_cutoff - 2h", 0.95, "critical", "mean", "goals/match", [0.0, 5.0], "low"),
    ("home_goals_against_avg", "scoring", ["football-data.org"], ["api-football"], 86400, "t_match <= t_cutoff - 2h", 0.95, "critical", "mean", "goals/match", [0.0, 5.0], "low"),
    ("away_goals_for_avg", "scoring", ["football-data.org"], ["api-football"], 86400, "t_match <= t_cutoff - 2h", 0.95, "critical", "mean", "goals/match", [0.0, 5.0], "low"),
    ("away_goals_against_avg", "scoring", ["football-data.org"], ["api-football"], 86400, "t_match <= t_cutoff - 2h", 0.95, "critical", "mean", "goals/match", [0.0, 5.0], "low"),
    ("total_goals_expected", "scoring", ["derived"], ["football-data.org"], 86400, "t_match <= t_cutoff - 2h", 0.95, "advisory", "bivariate_poisson", "expected_goals", [0.5, 6.0], "low"),
    # 14-15: Goal Difference
    ("home_gd_recent", "goal_diff", ["football-data.org"], ["api-football"], 86400, "t_match <= t_cutoff - 2h", 0.95, "advisory", "diff", "goals", [-15, 15], "low"),
    ("away_gd_recent", "goal_diff", ["football-data.org"], ["api-football"], 86400, "t_match <= t_cutoff - 2h", 0.95, "advisory", "diff", "goals", [-15, 15], "low"),
    # 16-17: Strength
    ("combined_attack", "strength", ["derived"], ["football-data.org"], 86400, "t_match <= t_cutoff - 2h", 0.95, "advisory", "additive_ratio", "index", [0.2, 5.0], "low"),
    ("combined_defense_weakness", "strength", ["derived"], ["football-data.org"], 86400, "t_match <= t_cutoff - 2h", 0.95, "advisory", "additive_ratio", "index", [0.2, 5.0], "low"),
    # 18-31: Market Features
    ("market_prob_home", "market", ["the-odds-api"], ["football-data.org"], 3600, "t_quote <= t_cutoff", 0.90, "critical", "shin_devig", "probability", [0.01, 0.99], "medium_if_post_close"),
    ("market_prob_draw", "market", ["the-odds-api"], ["football-data.org"], 3600, "t_quote <= t_cutoff", 0.90, "critical", "shin_devig", "probability", [0.01, 0.99], "medium_if_post_close"),
    ("market_prob_away", "market", ["the-odds-api"], ["football-data.org"], 3600, "t_quote <= t_cutoff", 0.90, "critical", "shin_devig", "probability", [0.01, 0.99], "medium_if_post_close"),
    ("market_edge_home", "market", ["derived"], ["the-odds-api"], 3600, "t_quote <= t_cutoff", 0.90, "advisory", "prob_minus_implied", "probability_delta", [-0.5, 0.5], "low"),
    ("market_favorite", "market", ["the-odds-api"], ["football-data.org"], 3600, "t_quote <= t_cutoff", 0.90, "advisory", "argmin_odds", "categorical_int", [-1, 1], "low"),
    ("odds_ratio", "market", ["the-odds-api"], ["football-data.org"], 3600, "t_quote <= t_cutoff", 0.90, "advisory", "ratio", "ratio", [0.05, 20.0], "low"),
    ("log_odds_home", "market", ["the-odds-api"], ["football-data.org"], 3600, "t_quote <= t_cutoff", 0.90, "advisory", "log1p", "log_odds", [0.01, 4.0], "low"),
    ("log_odds_draw", "market", ["the-odds-api"], ["football-data.org"], 3600, "t_quote <= t_cutoff", 0.90, "advisory", "log1p", "log_odds", [0.01, 4.0], "low"),
    ("log_odds_away", "market", ["the-odds-api"], ["football-data.org"], 3600, "t_quote <= t_cutoff", 0.90, "advisory", "log1p", "log_odds", [0.01, 4.0], "low"),
    ("draw_probability", "market", ["the-odds-api"], ["football-data.org"], 3600, "t_quote <= t_cutoff", 0.90, "advisory", "shin_devig_draw", "probability", [0.05, 0.60], "low"),
    ("market_confidence", "market", ["the-odds-api"], ["football-data.org"], 3600, "t_quote <= t_cutoff", 0.90, "advisory", "entropy_inverse", "confidence_index", [0.0, 1.0], "low"),
    ("ev_home", "market", ["derived"], ["the-odds-api"], 3600, "t_quote <= t_cutoff", 0.90, "advisory", "p_times_odds_minus_1", "ratio", [-1.0, 3.0], "low"),
    ("ev_draw", "market", ["derived"], ["the-odds-api"], 3600, "t_quote <= t_cutoff", 0.90, "advisory", "p_times_odds_minus_1", "ratio", [-1.0, 3.0], "low"),
    ("ev_away", "market", ["derived"], ["the-odds-api"], 3600, "t_quote <= t_cutoff", 0.90, "advisory", "p_times_odds_minus_1", "ratio", [-1.0, 3.0], "low"),
    # 32-36: H2H
    ("h2h_home_wins", "h2h", ["football-data.org"], ["api-football"], 604800, "t_h2h <= t_cutoff - 2h", 0.80, "advisory", "count", "matches", [0, 20], "low"),
    ("h2h_away_wins", "h2h", ["football-data.org"], ["api-football"], 604800, "t_h2h <= t_cutoff - 2h", 0.80, "advisory", "count", "matches", [0, 20], "low"),
    ("h2h_draws", "h2h", ["football-data.org"], ["api-football"], 604800, "t_h2h <= t_cutoff - 2h", 0.80, "advisory", "count", "matches", [0, 20], "low"),
    ("h2h_matches", "h2h", ["football-data.org"], ["api-football"], 604800, "t_h2h <= t_cutoff - 2h", 0.80, "advisory", "count", "matches", [0, 30], "low"),
    ("h2h_dominance", "h2h", ["derived"], ["football-data.org"], 604800, "t_h2h <= t_cutoff - 2h", 0.80, "advisory", "win_rate_diff", "index", [-1.0, 1.0], "low"),
    # 37-40: Venue
    ("home_venue_win_rate", "venue", ["football-data.org"], ["api-football"], 86400, "t_match <= t_cutoff - 2h", 0.95, "advisory", "rate", "probability", [0.0, 1.0], "low"),
    ("home_venue_draw_rate", "venue", ["football-data.org"], ["api-football"], 86400, "t_match <= t_cutoff - 2h", 0.95, "advisory", "rate", "probability", [0.0, 1.0], "low"),
    ("home_venue_loss_rate", "venue", ["football-data.org"], ["api-football"], 86400, "t_match <= t_cutoff - 2h", 0.95, "advisory", "rate", "probability", [0.0, 1.0], "low"),
    ("home_advantage_strength", "venue", ["derived"], ["football-data.org"], 86400, "t_match <= t_cutoff - 2h", 0.95, "advisory", "home_ppg_minus_away_ppg", "points", [-2.0, 3.0], "low"),
    # 41-44: Calendar
    ("day_of_week", "calendar", ["fixture_schedule"], [], 0, "deterministic", 1.0, "critical", "weekday_int", "day", [0, 6], "zero"),
    ("is_weekend", "calendar", ["fixture_schedule"], [], 0, "deterministic", 1.0, "advisory", "boolean_int", "flag", [0, 1], "zero"),
    ("month", "calendar", ["fixture_schedule"], [], 0, "deterministic", 1.0, "advisory", "month_int", "month", [1, 12], "zero"),
    ("season_phase", "calendar", ["fixture_schedule"], [], 0, "deterministic", 1.0, "advisory", "matchday_fraction", "progress", [0.0, 1.0], "zero"),
    # 45-47: League
    ("league_home_rate", "league", ["football-data.org"], ["historical_corpus"], 86400, "t_matches <= t_cutoff - 2h", 0.98, "critical", "rate", "probability", [0.25, 0.65], "low"),
    ("league_avg_goals", "league", ["football-data.org"], ["historical_corpus"], 86400, "t_matches <= t_cutoff - 2h", 0.98, "critical", "mean", "goals/match", [1.8, 3.8], "low"),
    ("league_draw_rate", "league", ["football-data.org"], ["historical_corpus"], 86400, "t_matches <= t_cutoff - 2h", 0.98, "critical", "rate", "probability", [0.15, 0.40], "low"),
    # 48-53: Composites
    ("form_market_agreement_home", "composite", ["derived"], [], 3600, "t_quote <= t_cutoff", 0.90, "advisory", "sign_concordance", "indicator", [-1, 1], "low"),
    ("form_market_disagreement", "composite", ["derived"], [], 3600, "t_quote <= t_cutoff", 0.90, "advisory", "abs_diff", "index", [0.0, 1.0], "low"),
    ("home_attack_vs_away_defense", "composite", ["derived"], [], 86400, "t_match <= t_cutoff - 2h", 0.95, "advisory", "multiplication", "ratio", [0.1, 5.0], "low"),
    ("away_attack_vs_home_defense", "composite", ["derived"], [], 86400, "t_match <= t_cutoff - 2h", 0.95, "advisory", "multiplication", "ratio", [0.1, 5.0], "low"),
    ("venue_market_combo", "composite", ["derived"], [], 3600, "t_quote <= t_cutoff", 0.90, "advisory", "weighted_sum", "index", [-1.0, 1.0], "low"),
    ("h2h_market_agreement", "composite", ["derived"], [], 3600, "t_quote <= t_cutoff", 0.80, "advisory", "sign_concordance", "indicator", [-1, 1], "low"),
    # 54-58: One-Hot League Indicators
    ("league_Bundesliga", "onehot", ["fixture_schedule"], [], 0, "deterministic", 1.0, "critical", "onehot_int", "flag", [0, 1], "zero"),
    ("league_EPL", "onehot", ["fixture_schedule"], [], 0, "deterministic", 1.0, "critical", "onehot_int", "flag", [0, 1], "zero"),
    ("league_La_Liga", "onehot", ["fixture_schedule"], [], 0, "deterministic", 1.0, "critical", "onehot_int", "flag", [0, 1], "zero"),
    ("league_Ligue_1", "onehot", ["fixture_schedule"], [], 0, "deterministic", 1.0, "critical", "onehot_int", "flag", [0, 1], "zero"),
    ("league_Serie_A", "onehot", ["fixture_schedule"], [], 0, "deterministic", 1.0, "critical", "onehot_int", "flag", [0, 1], "zero"),
    # 59-68: Phase 7 Features
    ("elo_difference", "elo", ["elo_replay"], ["historical_results"], 86400, "t_match <= t_cutoff - 2h", 0.95, "critical", "elo_home_minus_away", "elo_points", [-600.0, 600.0], "low"),
    ("elo_home_trend_5", "elo", ["elo_replay"], ["historical_results"], 86400, "t_match <= t_cutoff - 2h", 0.95, "advisory", "elo_delta_last5", "elo_points", [-200.0, 200.0], "low"),
    ("elo_away_trend_5", "elo", ["elo_replay"], ["historical_results"], 86400, "t_match <= t_cutoff - 2h", 0.95, "advisory", "elo_delta_last5", "elo_points", [-200.0, 200.0], "low"),
    ("elo_league_adjusted", "elo", ["permanent_data_gap"], [], 0, "permanent_gap_slot", 0.0, "advisory", "registry_default_0.0", "elo_points", [0.0, 0.0], "zero"),
    ("elo_momentum_cross", "elo", ["elo_replay"], ["historical_results"], 86400, "t_match <= t_cutoff - 2h", 0.95, "advisory", "trend_difference", "elo_points", [-300.0, 300.0], "low"),
    ("home_pressing_intensity", "tactical", ["permanent_data_gap"], [], 0, "permanent_gap_slot", 0.0, "advisory", "registry_default_0.55", "ppda_ratio", [0.55, 0.55], "zero"),
    ("progressive_carry_diff", "tactical", ["permanent_data_gap"], [], 0, "permanent_gap_slot", 0.0, "advisory", "registry_default_0.0", "carries", [0.0, 0.0], "zero"),
    ("shot_quality_diff", "tactical", ["permanent_data_gap"], [], 0, "permanent_gap_slot", 0.0, "advisory", "registry_default_0.0", "xg_diff", [0.0, 0.0], "zero"),
    ("key_passes_under_pressure_diff", "tactical", ["permanent_data_gap"], [], 0, "permanent_gap_slot", 0.0, "advisory", "registry_default_0.0", "passes", [0.0, 0.0], "zero"),
    ("set_piece_xg_diff", "tactical", ["permanent_data_gap"], [], 0, "permanent_gap_slot", 0.0, "advisory", "registry_default_0.0", "xg_diff", [0.0, 0.0], "zero"),
]

def main():
    lineage_records = []
    for row in FEATURES_68:
        name, family, prio, fallbacks, fresh, cutoff, min_cov, crit_adv, trans, unit, exp_range, leak = row
        lineage_records.append({
            "feature_name": name,
            "feature_family": family,
            "source_priority": prio,
            "fallback_sources": fallbacks,
            "freshness_limit_seconds": fresh,
            "information_cutoff_rule": cutoff,
            "minimum_coverage": min_cov,
            "critical_or_advisory": crit_adv,
            "transformation": trans,
            "unit": unit,
            "expected_range": exp_range,
            "leakage_risk": leak,
        })
    
    output = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "feature_schema": "apex_v1_68",
        "total_features": len(lineage_records),
        "generated_at": "2026-10-01T00:34:00Z",
        "directive": "V18.0 Section 2.3",
        "features": lineage_records
    }
    
    dest = Path("reports/evidence/apex-feature-lineage.json")
    dest.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(f"Generated {len(lineage_records)} APEX feature lineage definitions in {dest}")

if __name__ == "__main__":
    main()
