"""Delete abandoned incident drafts.

Run from the repository root, for example from a daily scheduled job:

    python -m scripts.purge_stale_drafts --days 7
"""

import argparse

from app.db.database import SessionLocal
from app.services.incident import purge_stale_drafts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Delete DRAFT incidents older than this many days (default: 7).",
    )
    args = parser.parse_args()

    with SessionLocal() as db:
        deleted = purge_stale_drafts(db, older_than_days=args.days)

    print(f"Deleted {deleted} stale draft incident(s).")


if __name__ == "__main__":
    main()
