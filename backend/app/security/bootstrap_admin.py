"""One-time interactive administrator bootstrap; never supplies defaults."""

from __future__ import annotations

import getpass
import os

from app.security.auth import AuthStore, AuthenticationError, configured_auth_db_path, configured_session_ttl
from app.services.reviews import configured_review_db_path


def main() -> int:
    configured_secret = os.environ.get("CIR_ADMIN_BOOTSTRAP_SECRET")
    if not configured_secret:
        raise SystemExit("CIR_ADMIN_BOOTSTRAP_SECRET wajib disetel sebelum bootstrap.")
    username = input("Username administrator baru: ").strip()
    supplied_secret = getpass.getpass("Masukkan bootstrap secret: ")
    password = getpass.getpass("Password administrator (min. 12 karakter): ")
    confirmation = getpass.getpass("Ulangi password: ")
    if password != confirmation:
        raise SystemExit("Konfirmasi password tidak cocok.")
    store = AuthStore(configured_auth_db_path(configured_review_db_path()), configured_session_ttl())
    try:
        user = store.create_bootstrap_admin(username, password, supplied_secret, configured_secret)
    except (AuthenticationError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    print(f"Administrator dibuat dengan ID {user['user_id']}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
