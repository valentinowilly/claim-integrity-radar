"""One-time interactive administrator bootstrap; never supplies defaults."""

from __future__ import annotations

import getpass
import os
import argparse

from app.security.auth import AuthStore, AuthenticationError, configured_auth_db_path, configured_session_ttl
from app.services.reviews import configured_review_db_path

LOCAL_DEMO_USERNAME = "admin"
LOCAL_DEMO_PASSWORD = "admin123"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Buat administrator pertama Claim Integrity Radar.")
    parser.add_argument(
        "--local-demo",
        action="store_true",
        help="Gunakan akun demo admin/admin123; hanya diizinkan saat CIR_ENV=development.",
    )
    args = parser.parse_args(argv)
    if args.local_demo and os.environ.get("CIR_ENV", "").strip().lower() != "development":
        raise SystemExit("--local-demo hanya dapat digunakan dengan CIR_ENV=development.")
    configured_secret = os.environ.get("CIR_ADMIN_BOOTSTRAP_SECRET")
    if not configured_secret:
        raise SystemExit("CIR_ADMIN_BOOTSTRAP_SECRET wajib disetel sebelum bootstrap.")
    supplied_secret = getpass.getpass("Masukkan bootstrap secret: ")
    if args.local_demo:
        username = LOCAL_DEMO_USERNAME
        password = LOCAL_DEMO_PASSWORD
    else:
        username = input("Username administrator baru: ").strip()
        password = getpass.getpass("Password administrator (min. 12 karakter): ")
        confirmation = getpass.getpass("Ulangi password: ")
        if password != confirmation:
            raise SystemExit("Konfirmasi password tidak cocok.")
    store = AuthStore(configured_auth_db_path(configured_review_db_path()), configured_session_ttl())
    try:
        user = store.create_bootstrap_admin(
            username,
            password,
            supplied_secret,
            configured_secret,
            allow_local_demo_password=args.local_demo,
        )
    except (AuthenticationError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    print(f"Administrator dibuat dengan ID {user['user_id']}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
