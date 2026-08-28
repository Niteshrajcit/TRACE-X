"""
Held-out evaluation of the Phase 2D Exit-Channel + Time-Window Scorer -
docs/AI_ML_ARCHITECTURE.md §4's "HOW EVALUATED": top-K hit rate (K=5, K=10),
Brier score (aggregate + per channel_type), and time-window coverage,
against held-out synthetic ground-truth rings never seen during training.

If the synthetic ground truth currently in the database is too small (fewer
than 20 candidate-channel rows, or fewer than 2 distinct labels), this
script fails loudly and explains why, rather than reporting a fabricated
number.

Usage (seed synthetic ground truth first if the database doesn't already
have enough - exit channels AND mule rings, in that order, e.g. via
scripts/seed_synthetic.py, then):
    python scripts/evaluate_exit_scorer.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.session import SessionLocal  # noqa: E402
from app.graph.exit_scorer import evaluate_exit_scorer  # noqa: E402


def main() -> None:
    db = SessionLocal()
    try:
        try:
            result = evaluate_exit_scorer(db)
        except ValueError as exc:
            print(f"EVALUATION NOT PERFORMED: {exc}")
            sys.exit(1)
    finally:
        db.close()

    print(f"Total candidate-channel rows: {result['total_rows']} (train {result['train_rows']} / test {result['test_rows']})")
    print(f"Test rings: {result['test_rings']}")
    print(result["candidate_set_size_note"])
    print()
    print(f"Top-5 hit rate: {result['top5_hit_rate']:.1%}" if result["top5_hit_rate"] is not None else "Top-5 hit rate: n/a")
    print(f"Top-10 hit rate: {result['top10_hit_rate']:.1%}" if result["top10_hit_rate"] is not None else "Top-10 hit rate: n/a")
    print(f"Brier score (aggregate): {result['brier_score']:.4f}" if result["brier_score"] is not None else "Brier score: n/a")
    print("Brier score by channel_type:")
    for ct, score in result["brier_score_by_channel_type"].items():
        print(f"  {ct}: {score:.4f}")
    print(
        f"Time-window coverage: {result['time_window_coverage']:.1%} (n={result['time_window_coverage_n']})"
        if result["time_window_coverage"] is not None
        else f"Time-window coverage: n/a (n={result['time_window_coverage_n']})"
    )
    print()
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
