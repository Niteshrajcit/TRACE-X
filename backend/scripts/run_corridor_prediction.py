"""
Manually triggers corridor prediction for one complaint's already-detected
rings (docs/AI_ML_ARCHITECTURE.md §3). Normally this runs automatically off
RING_DETECTED (app/graph/handlers.py) - this script exists for direct,
deterministic control during verification/demo, mirroring
scripts/run_ring_detection.py's role for the Ring Detector.

Usage:
    python scripts/run_corridor_prediction.py <complaint_id>
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.session import SessionLocal  # noqa: E402
from app.graph.corridor import run_corridor_prediction_for_complaint  # noqa: E402


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python scripts/run_corridor_prediction.py <complaint_id>")
        sys.exit(1)
    complaint_id = sys.argv[1]

    db = SessionLocal()
    try:
        results = run_corridor_prediction_for_complaint(db, complaint_id)
    finally:
        db.close()

    if not results:
        print("No corridor predictions produced (no rings for this complaint, or no ring had usable geolocation).")
        return

    for result in results:
        print(f"ring {result['ring_id'][:12]}... -> prediction {result['prediction_id']}")
        print(f"  exit_vector: {result['exit_vector']}")
        print(f"  model_version_corridor: {result['model_version_corridor']}")
    print(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    main()
