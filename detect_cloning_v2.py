import argparse
from pathlib import Path
import hashlib
import sqlite3

import pandas as pd
import pyreadstat


OUTPUT_DIR = Path("outputs")
TEMP_DB = OUTPUT_DIR / "_cloning_v2_temp.sqlite"
CHUNK_SIZE = 100_000

# Atribut pembanding tanpa kode prosedur.
BASE_COLS = [
    "FKL03",
    "FKL05_NEW",
    "FKL06",
    "FKL07",
    "FKL08",
    "FKL09",
    "FKL16",
    "FKL18",
    "FKL19",
    "FKL47",
]

FULL_COLS = BASE_COLS + ["FKL30"]
READ_COLS = ["PSTV01"] + FULL_COLS

TEXT_COLS = [
    "PSTV01",
    "FKL05_NEW",
    "FKL06",
    "FKL07",
    "FKL08",
    "FKL09",
    "FKL16",
    "FKL18",
    "FKL19",
    "FKL30",
]


def normalize_chunk(df):
    df = df.copy()

    # Tanggal disamakan ke format tahun-bulan-tanggal.
    df["FKL03"] = pd.to_datetime(
        df["FKL03"], errors="coerce"
    ).dt.strftime("%Y-%m-%d")

    # Nilai biaya dipertahankan sebagai numerik.
    df["FKL47"] = pd.to_numeric(
        df["FKL47"], errors="coerce"
    )

    # String kosong diperlakukan sebagai nilai kosong.
    for col in TEXT_COLS:
        df[col] = (
            df[col]
            .astype("string")
            .str.strip()
            .replace("", pd.NA)
        )

    return df


def add_signatures(conn, df, signature_cols, mode):
    if df.empty:
        return

    # Fingerprint pola layanan, tidak mencakup token peserta.
    fp = (
        pd.util.hash_pandas_object(
            df[signature_cols],
            index=False,
        )
        .astype("uint64")
        .astype(str)
    )

    frequencies = fp.value_counts(sort=False)

    conn.executemany(
        """
        INSERT INTO signature_counts (mode, fp, n_rows)
        VALUES (?, ?, ?)
        ON CONFLICT(mode, fp)
        DO UPDATE SET
            n_rows = n_rows + excluded.n_rows
        """,
        [
            (mode, str(key), int(value))
            for key, value in frequencies.items()
        ],
    )

    # Hash token peserta untuk menghitung peserta unik
    # tanpa menyimpan token tersebut ke database sementara.
    person_hash = df["PSTV01"].map(
        lambda value: hashlib.sha256(
            str(value).encode("utf-8")
        ).hexdigest()
    )

    pairs = pd.DataFrame({
        "mode": mode,
        "fp": fp.to_numpy(),
        "person_hash": person_hash.to_numpy(),
    }).drop_duplicates()

    conn.executemany(
        """
        INSERT OR IGNORE INTO signature_people
            (mode, fp, person_hash)
        VALUES (?, ?, ?)
        """,
        pairs.itertuples(index=False, name=None),
    )


def get_summary(conn, mode, min_people):
    result = conn.execute(
        """
        SELECT
            COUNT(*),
            COALESCE(SUM(s.n_rows), 0)
        FROM signature_counts s
        JOIN (
            SELECT mode, fp
            FROM signature_people
            WHERE mode = ?
            GROUP BY mode, fp
            HAVING COUNT(*) >= ?
        ) p
        ON p.mode = s.mode AND p.fp = s.fp
        WHERE s.mode = ? AND s.n_rows >= ?
        """,
        (mode, min_people, mode, min_people),
    ).fetchone()

    return result


def main():
    parser = argparse.ArgumentParser(description='Skrining variasi pola klaim dari file Stata lokal.')
    parser.add_argument("--input", type=Path, required=True, help="Path file .dta lokal sebagai input.")
    args = parser.parse_args()
    input_path = args.input
    if not input_path.is_file():
        parser.error("File input tidak tersedia; periksa nilai --input.")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if TEMP_DB.exists():
        TEMP_DB.unlink()

    _, meta = pyreadstat.read_dta(
        str(input_path),
        metadataonly=True,
    )

    missing = set(READ_COLS) - set(meta.column_names)
    if missing:
        raise ValueError(
            f"Kolom tidak tersedia: {sorted(missing)}"
        )

    conn = None
    total = 0
    base_valid_rows = 0
    full_rows = 0
    partial_rows = 0

    try:
        conn = sqlite3.connect(TEMP_DB)

        conn.execute("""
            CREATE TABLE signature_counts (
                mode TEXT NOT NULL,
                fp TEXT NOT NULL,
                n_rows INTEGER NOT NULL,
                PRIMARY KEY (mode, fp)
            )
        """)

        conn.execute("""
            CREATE TABLE signature_people (
                mode TEXT NOT NULL,
                fp TEXT NOT NULL,
                person_hash TEXT NOT NULL,
                PRIMARY KEY (mode, fp, person_hash)
            ) WITHOUT ROWID
        """)

        reader = pyreadstat.read_file_in_chunks(
            pyreadstat.read_dta,
            str(input_path),
            chunksize=CHUNK_SIZE,
            usecols=READ_COLS,
            apply_value_formats=False,
        )

        for chunk_no, (df, _) in enumerate(reader, start=1):
            total += len(df)
            df = normalize_chunk(df)

            # Untuk kedua jenis pencocokan, seluruh kolom
            # dasar dan token peserta harus tersedia.
            valid_base = df[
                ["PSTV01"] + BASE_COLS
            ].notna().all(axis=1)

            full_mask = valid_base & df["FKL30"].notna()
            partial_mask = valid_base & df["FKL30"].isna()

            full = df.loc[full_mask]
            partial = df.loc[partial_mask]

            full_rows += len(full)
            partial_rows += len(partial)
            base_valid_rows += int(valid_base.sum())

            # Pencocokan lengkap dengan kode prosedur.
            add_signatures(
                conn, full, FULL_COLS, "lengkap"
            )

            # Pencocokan parsial tanpa kode prosedur.
            # Hasilnya akan dilaporkan terpisah.
            add_signatures(
                conn, partial, BASE_COLS, "parsial"
            )

            conn.commit()

            print(
                f"Potongan {chunk_no}: "
                f"{total:,} baris diperiksa"
            )

        print("\n" + "=" * 60)
        print("RINGKASAN CLONING V2")
        print("=" * 60)
        print(f"Total baris                 : {total:,}")
        print(f"Baris dengan kolom dasar    : {base_valid_rows:,}")
        print(f"Pencocokan lengkap          : {full_rows:,}")
        print(f"Pencocokan parsial          : {partial_rows:,}")
        print(
            "Tidak memenuhi kolom dasar: "
            f"{total - base_valid_rows:,}"
        )

        for mode, description in [
            ("lengkap", "LENGKAP (kode prosedur tersedia)"),
            ("parsial", "PARSIAL (kode prosedur kosong)"),
        ]:
            for min_people in [2, 3]:
                groups, rows = get_summary(
                    conn, mode, min_people
                )

                print(f"\n{description}; minimal {min_people} peserta")
                print(f"  Kelompok pola: {groups:,}")
                print(f"  Baris terlibat: {rows:,}")

        print(
            "\nInterpretasi: hasil menunjukkan kemiripan pola "
            "lintas peserta, bukan bukti cloning."
        )
        print(
            "Dataset ini belum memastikan faskes yang sama "
            "karena ID unik fasilitas tidak tersedia."
        )

    finally:
        if conn is not None:
            conn.close()

        if TEMP_DB.exists():
            TEMP_DB.unlink()


if __name__ == "__main__":
    main()
