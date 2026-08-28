"""
Manually triggers exit-channel + time-window scoring for one complaint's
already corridor-scored rings (docs/AI_ML_ARCHITECTURE.md §4). Normally
this runs automatically off CORRIDOR_PREDICTION_COMPLETED
(app/graph/handlers.py) - this script exists for direct, deterministic
control during verification/demo, mirroring
scripts/run_corridor_prediction.py's role for the Corridor Predictor.

Usage:
    python scripts/run_exit_scoring.py <complaint_id>
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.session import SessionLocal  # noqa: E402
from app.graph.exit_scorer import run_exit_scoring_for_complaint  # noqa: E402


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python scripts/run_exit_scoring.py <complaint_id>")
        sys.exit(1)
    complaint_id = sys.argv[1]

    db = SessionLocal()
    try:
        results = run_exit_scoring_for_complaint(db, complaint_id)
    finally:
        db.close()

    if not results:
        print("No exit-channel scores produced (no corridor-scored rings for this complaint, or scoring failed).")
        return

    for result in results:
        print(f"ring {result['ring_id'][:12]}... -> prediction {result['prediction_id']}")
        for entry in result["ranked_locations"]:
            print(f"  {entry['channel_type']} {entry['exit_channel_id'][:12]}... p={entry['probability']} window={entry['time_window_min']}min")
        print(f"  model_version_location: {result['model_version_location']}")
        print(f"  model_version_time: {result['model_version_time']}")
    print(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    main()
