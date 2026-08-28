"""
Held-out evaluation of the Phase 2C Corridor/Exit-Vector Predictor -
docs/AI_ML_ARCHITECTURE.md §3's "HOW EVALUATED": bearing-cone hit-rate at
+/-30deg and +/-60deg against held-out synthetic ground-truth rings, never
rings the classifier was trained on.

If the synthetic ground truth currently in the database is too small (fewer
than 10 rings with usable geolocation) or has fewer than 2 distinct bearing
buckets, this script fails loudly and explains why, rather than reporting a
fabricated number - the exact "stop and report that limitation" case named
in this phase's evaluation-integrity requirement.

Usage (seed synthetic ground truth first if the database doesn't already
have enough, e.g. via scripts/seed_synthetic.py, then):
    python scripts/evaluate_corridor_predictor.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.session import SessionLocal  # noqa: E402
from app.graph.corridor import evaluate_corridor_predictor  # noqa: E402


def main() -> None:
    db = SessionLocal()
    try:
        try:
            result = evaluate_corridor_predictor(db)
        except ValueError as exc:
            print(f"EVALUATION NOT PERFORMED: {exc}")
            sys.exit(1)
    finally:
        db.close()

    print(f"Total ground-truth rings (with usable geolocation): {result['total_rings']}")
    print(f"Train / test split: {result['train_size']} / {result['test_size']}")
    print(f"Bearing-bucket distribution: {result['bucket_distribution']}")
    print()
    print(f"Hit rate within +/-30deg: {result['hit_rate_30deg']:.1%}" if result["hit_rate_30deg"] is not None else "Hit rate within +/-30deg: n/a")
    print(f"Hit rate within +/-60deg: {result['hit_rate_60deg']:.1%}" if result["hit_rate_60deg"] is not None else "Hit rate within +/-60deg: n/a")
    print()
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
