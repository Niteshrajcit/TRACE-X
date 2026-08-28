"""
Batch-mode synthetic data seeding (docs/DEMO_ARCHITECTURE.md §2).

Usage:
    python scripts/seed_synthetic.py

Run this once against a fresh database (local SQLite or the Docker Compose
Postgres) before using the Investigator Command Center, so there are real
jurisdictions/users/exit-channels/response-units/mule rings to look at.
Safe to re-run - every seed function checks for existing rows first.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.session import Base, SessionLocal, engine  # noqa: E402
from app.db import models  # noqa: E402  (import registers all tables on Base.metadata)
from app.synthetic.generator import run_full_seed  # noqa: E402


def main() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        summary = run_full_seed(db)
    finally:
        db.close()
    print("Synthetic base data seeded:")
    for key, value in summary.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
