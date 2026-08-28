"""
Rebuilds the entire Neo4j graph from PostgreSQL (docs/ARCHITECTURE.md:
"Neo4j is a derived/rebuildable intelligence graph"; docs/API_CONTRACT.md
§1b). PostgreSQL is never touched - this only wipes and re-derives Neo4j.

Use this after any Neo4j outage/drift, or to prove the "PostgreSQL -> rebuild
Neo4j -> same graph structure" property (Phase 2A exit criterion #10). The
actual logic lives in app/graph/rebuild.py (importable, and reused directly
by the per-complaint tests in tests/test_graph_rebuild.py) - this script is
just the CLI entry point for the full, destructive, whole-instance rebuild.

Usage:
    python scripts/rebuild_neo4j_graph.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.session import SessionLocal  # noqa: E402
from app.graph.rebuild import rebuild_all  # noqa: E402


def main() -> None:
    db = SessionLocal()
    try:
        summary = rebuild_all(db, wipe=True)
    finally:
        db.close()
    print("Neo4j graph rebuilt from PostgreSQL:")
    for key, value in summary.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
