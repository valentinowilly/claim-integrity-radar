"""A migration file is the same migration whatever its line endings (a Windows checkout turns LF into CRLF)."""

import hashlib

from app.db_migrations import MIGRATIONS_DIRECTORY, migration_files, unchanged


def test_line_endings_do_not_make_an_applied_migration_look_changed():
    for version, _sql, recorded in migration_files():
        raw = (MIGRATIONS_DIRECTORY / f"{version}.sql").read_bytes()
        lf = raw.replace(b"\r\n", b"\n")
        crlf = lf.replace(b"\n", b"\r\n")
        for variant in (raw, lf, crlf):
            assert unchanged(version, hashlib.sha256(variant).hexdigest()), version
        assert recorded == hashlib.sha256(lf).hexdigest()
        # A real change in content is still refused.
        assert not unchanged(version, hashlib.sha256(lf + b"-- edited\n").hexdigest()), version
