"""See which accounts exist and set a new password for one, on the server (for a forgotten password).

Run it in the same environment as the API (the same CIR_DATABASE_URL or CIR_AUTH_DB_PATH), so it reaches the same
accounts the sign-in page checks:

    python -m scripts.reset_password --list
    python -m scripts.reset_password --username admin
    python -m scripts.reset_password --username admin --activate

``--list`` shows which database is used (address without its password) and every account with its role and whether
it is active; never password data. ``--username`` asks the new password twice (or reads CIR_RESET_PASSWORD for an
unattended run), never prints it, ends the account's open sessions and records "password_reset_by_admin" in the
security log. ``--activate`` also reactivates a deactivated account.
"""

from __future__ import annotations

import argparse
import getpass
import os
from urllib.parse import urlsplit

from app.security.auth import AuthStore, AuthenticationError, configured_auth_db_path, configured_session_ttl
from app.services.reviews import configured_review_db_path

ACTOR = "setup-script"


def describe_database() -> str:
    url = os.environ.get("CIR_DATABASE_URL", "").strip()
    if url:
        parts = urlsplit(url)
        return f"PostgreSQL {parts.hostname}:{parts.port or 5432}{parts.path}"
    return f"SQLite {configured_auth_db_path(configured_review_db_path())}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--list", action="store_true", help="tampilkan basis data yang dipakai dan semua akun")
    parser.add_argument("--username", help="akun yang kata sandinya diatur ulang")
    parser.add_argument("--activate", action="store_true", help="aktifkan juga akun yang nonaktif")
    args = parser.parse_args()
    if not args.list and not args.username:
        parser.error("pilih --list atau --username")
    store = AuthStore(configured_auth_db_path(configured_review_db_path()), configured_session_ttl())
    print(f"Basis data akun: {describe_database()}")
    users = store.list_users()
    if args.list:
        if not users:
            print("Belum ada akun di basis data ini.")
        for user in users:
            print(f"- {user['username']} | {user['role']} | {'aktif' if user['is_active'] else 'NONAKTIF'}"
                  f" | terakhir masuk: {user['last_login_at'] or 'belum pernah'}")
        if not args.username:
            return 0
    target = next((user for user in users if user["username"].lower() == args.username.strip().lower()), None)
    if target is None:
        raise SystemExit(f"Akun '{args.username}' tidak ada di basis data ini. Jalankan dengan --list untuk melihat daftarnya.")
    password = os.environ.get("CIR_RESET_PASSWORD")
    if not password:
        password = getpass.getpass("Kata sandi baru (min. 12 karakter): ")
        if password != getpass.getpass("Ulangi kata sandi baru: "):
            raise SystemExit("Konfirmasi kata sandi tidak cocok.")
    try:
        store.reset_password(target["user_id"], password, ACTOR)
        if args.activate and not target["is_active"]:
            store.update_user(target["user_id"], ACTOR, is_active=True)
    except (AuthenticationError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    state = "aktif" if (target["is_active"] or args.activate) else "NONAKTIF (tambahkan --activate untuk mengaktifkan)"
    print(f"Kata sandi {target['username']} diatur ulang. Akun {state}. Sesi lamanya diakhiri.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
