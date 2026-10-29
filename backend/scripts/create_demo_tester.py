"""Create the shared "Penguji demo" account (role demo_tester) on the configured database.

The account can use every workflow of the application (upload, intake, analysis, queue, AI reading, reviews,
archive) but cannot manage accounts or read the security log. Run it on the server, once:

    python -m scripts.create_demo_tester --username juri-demo

The password is asked twice (or read from CIR_DEMO_TESTER_PASSWORD for an unattended setup) and never printed.
"""

from __future__ import annotations

import argparse
import getpass
import os

from app.security.auth import AuthStore, AuthenticationError, configured_auth_db_path, configured_session_ttl
from app.services.reviews import configured_review_db_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--username", required=True)
    args = parser.parse_args()
    password = os.environ.get("CIR_DEMO_TESTER_PASSWORD")
    if not password:
        password = getpass.getpass("Password akun penguji (min. 12 karakter): ")
        if password != getpass.getpass("Ulangi password: "):
            raise SystemExit("Konfirmasi password tidak cocok.")
    store = AuthStore(configured_auth_db_path(configured_review_db_path()), configured_session_ttl())
    try:
        user = store.create_user(args.username, password, "demo_tester", "setup-script")
    except (AuthenticationError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    print(f"Akun penguji demo dibuat: {user['username']}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
