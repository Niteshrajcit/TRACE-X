"""
Compares persisted detected rings against the synthetic generator's planted
ground truth (docs/AI_ML_ARCHITECTURE.md §2's "HOW EVALUATED", this phase's
explicit evaluation requirement). Never exposed via the API - this is a
developer/ops script, and accounts.ring_id (the ground truth it reads) must
never reach an investigator-facing response (docs/PRODUCT.md §5).

Usage (after running scripts/run_ring_detection.py at least once):
    python scripts/evaluate_ring_detection.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.session import SessionLocal  # noqa: E402
from app.graph.evaluation import evaluate_against_ground_truth  # noqa: E402


def main() -> None:
    db = SessionLocal()
    try:
        result = evaluate_against_ground_truth(db)
    finally:
        db.close()

    if not result["evaluable"]:
        print(result["reason"])
        sys.exit(1)

    print(f"Planted rings: {result['planted_ring_count']} ({result['planted_account_count']} accounts)")
    print(f"Detected communities: {result['detected_community_count']}")
    print(f"Adjusted Rand Index: {result['ari']}")
    print(f"Adjusted Mutual Information: {result['ami']}")
    print(f"Detection coverage: {result['detection_coverage']:.1%}")
    print(f"False community rate (Jaccard < {result.get('false_community_threshold')}): {result['false_community_rate']}")
    print()
    print("Per-ring precision/recall (best-matching detected community):")
    for row in result["per_ring"]:
        print(
            f"  {row['planted_ring_id'][:12]}... (n={row['planted_size']}) -> "
            f"{str(row['best_matching_detected_ring_id'])[:12]}... "
            f"precision={row['precision']:.2f} recall={row['recall']:.2f} jaccard={row['jaccard']:.2f}"
        )
    print()
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
