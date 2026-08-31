"""``python -m app.seed`` — load the harvested Stanford corpus into Postgres.

    python -m app.seed                    # load (or re-load) the corpus
    python -m app.seed --reset            # drop what a previous load wrote first
    python -m app.seed --root /some/path  # load a different harvest tree
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.core.config import get_settings
from app.db.session import session_scope
from app.seed.load_harvest import default_harvest_root, load_all, reset_loaded


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m app.seed",
        description="Load data/harvest into the configured database. Idempotent.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="harvest directory (default: <repo>/data/harvest)",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="delete rows written by a previous load first (dev tool: no confirmation)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="run the load and print the report, then roll the transaction back",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    settings = get_settings()
    root = args.root or default_harvest_root()

    print(f"database: {settings.database_url}")
    print(f"harvest:  {root}")
    print()

    with session_scope() as db:
        if args.reset:
            deleted = reset_loaded(db)
            print("reset:")
            for entity, count in sorted(deleted.items()):
                print(f"  {entity:<22}{count:>9} deleted")
            print()

        report = load_all(db, root)
        print(report.render())

        if args.dry_run:
            db.rollback()
            print("\ndry run: transaction rolled back, nothing was written.")
            return 0

    unreadable = [s for s in report.skipped if s.entity == "harvest"]
    return 1 if unreadable else 0


if __name__ == "__main__":
    sys.exit(main())
