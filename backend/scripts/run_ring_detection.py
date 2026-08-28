"""
Manually triggers one full ring-detection run (docs/AI_ML_ARCHITECTURE.md
§2). Normally this runs automatically off `graph.updated`
(app/graph/handlers.py) - this script exists for direct, deterministic
control during testing/demo, and for re-running detection without
submitting a new transaction (e.g. after `scripts/rebuild_neo4j_graph.py`).

Usage:
    python scripts/run_ring_detection.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.session import SessionLocal  # noqa: E402
from app.graph.ring_service import run_ring_detection  # noqa: E402


def main() -> None:
    db = SessionLocal()
    try:
        summary = run_ring_detection(db)
    finally:
        db.close()

    print(f"Graph: {summary['graph_nodes']} nodes, {summary['graph_edges']} edges")
    print(f"Algorithm: {summary['algorithm']}")
    print(f"Modularity: {summary['modularity']}")
    print(f"Communities detected (>=2 members): {summary['communities_detected']}")
    print(f"Source graph fingerprint: {summary['source_graph_fingerprint']}")
    for ring in summary["rings"]:
        print(
            f"  ring {ring['ring_id'][:12]}... "
            f"members={ring['member_count']} cohesion={ring['cohesion_score']:.3f} "
            f"complaints={len(ring['complaint_ids'])}"
        )
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
