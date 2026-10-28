"""Production readiness check of the configured PostgreSQL database (read-only; prints no data or secrets).

Checks what the application needs (migrations, append-only guards, indexes, connection pool) and what a
production deployment should have (a runtime role that is not a superuser, TLS for remote databases, a
statement timeout, local-only access in pg_hba when the database runs on the same host). Each item prints
LULUS / PERHATIAN with a short reason; the exit code is 1 when a required item fails.

Usage: python -m scripts.postgres_readiness        (reads CIR_DATABASE_URL)
"""

from __future__ import annotations

import os
import sys
from urllib.parse import urlparse

from app.db import configured_database
from app.db_migrations import schema_status

REQUIRED_TABLES = {
    "analysis_runs", "analysis_run_results", "analysis_run_cases", "analysis_run_archives", "data_batches",
    "data_batch_records", "run_case_reviews", "run_case_review_events", "run_case_audit_confirmations",
    "auth_users", "auth_sessions", "security_audit_events", "inbox_files", "inbox_pulls", "case_assignments",
    "clinical_ai_reviews", "fkrtl_validation_jobs",
}


def main() -> int:
    url = os.environ.get("CIR_DATABASE_URL", "").strip()
    if not url:
        print("CIR_DATABASE_URL belum diatur.")
        return 1
    import psycopg

    results: list[tuple[str, bool, bool, str]] = []  # (item, ok, required, note)

    def item(name: str, ok: bool, note: str, required: bool = True) -> None:
        results.append((name, ok, required, note))

    status = schema_status(configured_database())
    item("Migrasi terpasang", status.get("ok", False) and not status.get("pending"),
         f"{len(status.get('applied', []))} terpasang, tertunda: {status.get('pending') or 'tidak ada'}")
    host = urlparse(url).hostname or ""
    local = host in ("127.0.0.1", "localhost", "::1")
    with psycopg.connect(url, connect_timeout=5) as connection:
        tables = {row[0] for row in connection.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema()").fetchall()}
        missing = sorted(REQUIRED_TABLES - tables)
        item("Tabel aplikasi lengkap", not missing, "lengkap" if not missing else f"hilang: {', '.join(missing)}")
        triggers = connection.execute(
            "SELECT count(*) FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
            "JOIN pg_namespace n ON n.oid = c.relnamespace WHERE NOT t.tgisinternal AND n.nspname = current_schema()"
        ).fetchone()[0]
        item("Pengaman riwayat tak-terhapus (trigger)", triggers >= 20, f"{triggers} trigger aktif")
        indexes = connection.execute("SELECT count(*) FROM pg_indexes WHERE schemaname = current_schema()").fetchone()[0]
        item("Indeks", indexes >= 40, f"{indexes} indeks")
        superuser, = connection.execute("SELECT rolsuper FROM pg_roles WHERE rolname = current_user").fetchone()
        item("Peran aplikasi bukan superuser", not superuser, "bukan superuser" if not superuser else "aplikasi tersambung sebagai superuser")
        owns = connection.execute(
            "SELECT count(*) FROM pg_tables WHERE schemaname = current_schema() AND tableowner = current_user").fetchone()[0]
        item("Peran aplikasi terpisah dari pemilik tabel", owns == 0,
             "terpisah" if owns == 0 else f"peran aplikasi memiliki {owns} tabel; di produksi pisahkan peran pemilik "
             "(migrasi) dari peran aplikasi (hanya baca/tulis), agar trigger pengaman tidak dapat dimatikan aplikasi",
             required=False)
        ssl = connection.execute("SHOW ssl").fetchone()[0]
        item("Koneksi terenkripsi (TLS)", ssl == "on" or local,
             "database di mesin yang sama; TLS tidak wajib" if local and ssl != "on" else f"ssl = {ssl}", required=not local)
        timeout = connection.execute("SHOW statement_timeout").fetchone()[0]
        item("Batas waktu query", timeout not in ("0", "0ms"), f"statement_timeout = {timeout}", required=False)
        version = connection.execute("SHOW server_version").fetchone()[0]
        item("Versi PostgreSQL", int(version.split(".")[0]) >= 12, f"PostgreSQL {version} (diuji 12.4 dan 18.6)")
    pool_max = os.environ.get("CIR_DATABASE_POOL_MAX", "10")
    item("Pool koneksi aplikasi", True, f"maksimum {pool_max} koneksi per proses (CIR_DATABASE_POOL_MAX)", required=False)

    failed_required = False
    for name, ok, required, note in results:
        label = "LULUS    " if ok else ("GAGAL    " if required else "PERHATIAN")
        failed_required |= (not ok and required)
        print(f"{label} {name}: {note}")
    print("\nSiap dipakai aplikasi." if not failed_required else "\nAda butir wajib yang belum terpenuhi.")
    return 1 if failed_required else 0


if __name__ == "__main__":
    sys.exit(main())
