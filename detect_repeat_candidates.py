import argparse
from pathlib import Path
import sqlite3

import pandas as pd
import pyreadstat


OUTPUT_DIR = Path("outputs")
TEMP_DB = OUTPUT_DIR / "_repeat_screen_temp.sqlite"

CHUNK_SIZE = 100_000

# FKL02 tidak dimasukkan dalam signature karena digunakan
# untuk membedakan kunjungan yang memiliki pola serupa.
KEY_COLS = [
    "PSTV01",
    "FKL03",
    "FKL05_NEW",
    "FKL06",
    "FKL07",
    "FKL08",
    "FKL09",
    "FKL16",
    "FKL18",
    "FKL19",
    "FKL30",
    "FKL47",
]

READ_COLS = ["FKL02"] + KEY_COLS


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Normalisasi hanya untuk pencocokan internal."""
    df = df.copy()

    for col in df.columns:
        # Samakan representasi tanggal agar konsisten.
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            df[col] = df[col].dt.strftime("%Y-%m-%d")

        # Perlakukan string kosong sebagai nilai yang tidak tersedia.
        df[col] = (
            df[col]
            .astype("string")
            .str.strip()
            .replace("", pd.NA)
            .fillna("<MISSING>")
        )

    return df


def main():
    parser = argparse.ArgumentParser(description='Skrining signature klaim berulang dari file Stata lokal.')
    parser.add_argument("--input", type=Path, required=True, help="Path file .dta lokal sebagai input.")
    args = parser.parse_args()
    input_path = args.input
    if not input_path.is_file():
        parser.error("File input tidak tersedia; periksa nilai --input.")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if TEMP_DB.exists():
        TEMP_DB.unlink()

    # Pastikan nama kolom memang ada dalam dataset.
    _, meta = pyreadstat.read_dta(
        str(input_path),
        metadataonly=True,
    )

    missing = set(READ_COLS) - set(meta.column_names)

    if missing:
        raise ValueError(
            f"Kolom tidak ditemukan: {sorted(missing)}"
        )

    conn = None

    try:
        conn = sqlite3.connect(TEMP_DB)

        conn.execute("""
            CREATE TABLE signatures (
                fingerprint TEXT PRIMARY KEY,
                n_rows INTEGER NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE signature_visits (
                fingerprint TEXT NOT NULL,
                visit_id TEXT NOT NULL,
                PRIMARY KEY (fingerprint, visit_id)
            )
        """)

        reader = pyreadstat.read_file_in_chunks(
            pyreadstat.read_dta,
            str(input_path),
            chunksize=CHUNK_SIZE,
            usecols=READ_COLS,
        )

        total_rows = 0

        for chunk_number, (df, _) in enumerate(
            reader, start=1
        ):
            total_rows += len(df)

            # Bersihkan format untuk pencocokan.
            visit_ids = normalize_columns(
                df[["FKL02"]]
            )["FKL02"]

            signature_data = normalize_columns(
                df[KEY_COLS]
            )

            # Fingerprint hanya dipakai untuk pencocokan lokal.
            fingerprints = (
                pd.util.hash_pandas_object(
                    signature_data,
                    index=False,
                )
                .astype("uint64")
                .astype(str)
            )

            # Gabungkan jumlah pola dari semua chunk.
            frequencies = fingerprints.value_counts(
                sort=False
            )

            conn.executemany(
                """
                INSERT INTO signatures
                    (fingerprint, n_rows)
                VALUES (?, ?)
                ON CONFLICT(fingerprint)
                DO UPDATE SET
                    n_rows = n_rows + excluded.n_rows
                """,
                [
                    (str(fp), int(count))
                    for fp, count in frequencies.items()
                ],
            )

            # Catat ID kunjungan unik per pola, bukan
            # isi baris lengkap atau identitas peserta.
            pairs = pd.DataFrame({
                "fingerprint": fingerprints.to_numpy(),
                "visit_id": visit_ids.to_numpy(),
            }).drop_duplicates()

            conn.executemany(
                """
                INSERT OR IGNORE INTO signature_visits
                    (fingerprint, visit_id)
                VALUES (?, ?)
                """,
                pairs.itertuples(index=False, name=None),
            )

            conn.commit()

            print(
                f"Potongan {chunk_number}: "
                f"{total_rows:,} baris diperiksa"
            )

        # Hanya ambil statistik agregat.
        repeated_groups = conn.execute("""
            SELECT COUNT(*)
            FROM signatures
            WHERE n_rows > 1
        """).fetchone()[0]

        repeated_rows = conn.execute("""
            SELECT COALESCE(SUM(n_rows), 0)
            FROM signatures
            WHERE n_rows > 1
        """).fetchone()[0]

        excess_rows = conn.execute("""
            SELECT COALESCE(SUM(n_rows - 1), 0)
            FROM signatures
            WHERE n_rows > 1
        """).fetchone()[0]

        max_repeat = conn.execute("""
            SELECT COALESCE(MAX(n_rows), 0)
            FROM signatures
        """).fetchone()[0]

        multi_visit_groups = conn.execute("""
            SELECT COUNT(*)
            FROM (
                SELECT fingerprint
                FROM signature_visits
                GROUP BY fingerprint
                HAVING COUNT(*) > 1
            )
        """).fetchone()[0]

        print("\n" + "=" * 56)
        print("RINGKASAN KANDIDAT POLA BERULANG")
        print("=" * 56)
        print(f"Total baris diperiksa: {total_rows:,}")
        print(f"Kelompok signature berulang: {repeated_groups:,}")
        print(f"Baris dalam kelompok berulang: {repeated_rows:,}")
        print(f"Baris tambahan di atas satu per kelompok: {excess_rows:,}")
        print(f"Frekuensi maksimum satu signature: {max_repeat:,}")
        print(
            "Kelompok dengan lebih dari satu ID kunjungan: "
            f"{multi_visit_groups:,}"
        )

        print(
            "\nHasil ini adalah kandidat pola untuk ditinjau, "
            "bukan bukti fraud."
        )

    finally:
        if conn is not None:
            conn.close()

        # Hapus database sementara setelah analisis selesai.
        if TEMP_DB.exists():
            TEMP_DB.unlink()


if __name__ == "__main__":
    main()
