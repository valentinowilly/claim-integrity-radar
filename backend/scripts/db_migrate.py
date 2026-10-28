"""Create or upgrade the PostgreSQL schema named by CIR_DATABASE_URL.

    python -m scripts.db_migrate            # apply pending migrations
    python -m scripts.db_migrate --check    # report status only, exit 1 if not up to date

Additive only: it never drops or resets tables. Prints versions and counts, never the URL.
"""

from __future__ import annotations

import argparse
import json
import sys

from app.db import DatabaseConfigurationError, configured_database
from app.db_migrations import schema_status, upgrade


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        database = configured_database()
    except DatabaseConfigurationError as exc:
        print(f"error: {exc}")
        return 2
    if database is None:
        print("error: CIR_DATABASE_URL is not set; there is no PostgreSQL database to migrate.")
        return 2
    try:
        if not args.check:
            applied = upgrade(database)
            print(json.dumps({"applied_now": applied}))
        status = schema_status(database)
    except DatabaseConfigurationError as exc:
        print(f"error: {exc}")
        return 1
    except Exception as exc:  # connection or SQL failure: type only, no URL or credentials
        print(f"error: database migration failed ({type(exc).__name__})")
        return 1
    print(json.dumps(status))
    return 0 if status["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
