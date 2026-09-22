"""
Batch prediction script for upcoming matches
Run: python -m src.scripts.batch_predict --date 2025-11-10
"""

import argparse
from datetime import datetime, timedelta
from src.core.database import SessionLocal, Match
from src.models.orchestrator import orchestrator


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=str, help="Date for predictions (YYYY-MM-DD)")
    parser.add_argument("--league", type=str, help="Specific league (optional)")
    args = parser.parse_args()

    target_date = (
        datetime.strptime(args.date, "%Y-%m-%d") if args.date else datetime.utcnow()
    )

    print(f"\n🔮 Generating predictions for {target_date.strftime('%Y-%m-%d')}\n")

    db = SessionLocal()

    try:
        # Query upcoming matches
        matches = db.query(Match).filter(
            Match.match_date >= target_date,
            Match.match_date < target_date + timedelta(days=1),
            Match.home_score.is_(None),  # Only unplayed matches
        )

        if args.league:
            matches = matches.filter(Match.league.ilike(f"%{args.league}%"))

        matches = matches.all()

        print(f"Found {len(matches)} matches\n")

        value_bets = []

        for match in matches:
            # Build match data
            match_data = orchestrator._build_match_features(match, db)
            match_data["match_id"] = str(match.id)

            # Mock odds (replace with actual odds fetcher)
            odds = {"home_win": 2.10, "draw": 3.40, "away_win": 3.20}

            # Get prediction
            result = orchestrator.predict(match.league, match_data, odds)

            if result.get("has_edge"):
                print(f"⚡ {match.home_team} vs {match.away_team}")
                print(f"   League: {match.league}")
                print(
                    f"   Predictions: H:{result['predictions']['home_win']:.2%} "
                    + f"D:{result['predictions']['draw']:.2%} "
                    + f"A:{result['predictions']['away_win']:.2%}"
                )

                for outcome, edge in result["value_bets"].items():
                    print(
                        f"   💰 {outcome.upper()}: +{edge['edge_pct']:.1f}% edge, "
                        + f"Kelly: {edge['kelly_stake_pct']:.1f}%, "
                        + f"CLV: +{edge['clv_cents']:.1f}¢"
                    )

                    value_bets.append(
                        {
                            "match": f"{match.home_team} vs {match.away_team}",
                            "outcome": outcome,
                            "edge": edge,
                        }
                    )

                print()

        print(f"\n📊 Summary: {len(value_bets)} value bets found")

        # Sort by edge
        value_bets.sort(key=lambda x: x["edge"]["edge_pct"], reverse=True)

        print("\nTop 5 Value Bets:")
        for i, bet in enumerate(value_bets[:5], 1):
            print(
                f"{i}. {bet['match']} - {bet['outcome']}: +{bet['edge']['edge_pct']:.1f}%"
            )

    finally:
        db.close()


if __name__ == "__main__":
    main()
