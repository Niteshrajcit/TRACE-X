"""Runs the Neo4j schema constraints/indexes (docs/DATA_MODEL.md §3). Not
required for Phase 1 (nothing writes to the graph yet) - provided so
connectivity and schema setup are proven ahead of Phase 2's Graph Builder.

Usage: python scripts/init_neo4j.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.neo4j_client import check_connectivity, initialize_schema  # noqa: E402


def main() -> None:
    if not check_connectivity():
        print("Neo4j is not reachable - check NEO4J_URI/NEO4J_USER/NEO4J_PASSWORD.")
        sys.exit(1)
    initialize_schema()
    print("Neo4j schema constraints/indexes applied.")


if __name__ == "__main__":
    main()
