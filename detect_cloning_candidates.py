import argparse
from pathlib import Path
import hashlib
import sqlite3

import pandas as pd
import pyreadstat


OUTPUT_DIR = Path("outputs")
TEMP_DB = OUTPUT_DIR / "_cloning_screen_temp.sqlite"
CHUNK_SIZE = 100_000

# Sengaja tidak memasukkan PSTV01.
# Kunci ini mengidentifikasi pola layanan, bukan peserta.
SIGNATURE_COLS = [
    "FKL03",       # Tanggal kunjungan
    "FKL05_NEW",   # Kode provinsi
    "FKL06",       # Kabupaten/kota
    "FKL07",       # Kepemilikan faskes
    "FKL08",       # Jenis faskes
    "FKL09",       # Tipe faskes
    "FKL16",       # Diagnosis masuk
    "FKL18",       # Diagnosis primer
    "FKL19",       # Kelompok INA-CBG
    "FKL30",       # Jenis prosedur
    "FKL47",       # Biaya tagih
]

READ_COLS = ["PSTV01"] + SIGNATURE_COLS


def normalize_chunk(df):
    df = df.copy()

    # Normalisasi tanggal agar konsisten antarbaris.
    df["FKL03"] = pd.to_datetime(
        df["FKL03"], errors="coerce"
    ).dt.strftime("%Y-%m-%d")

    # Normalisasi biaya ke bilangan bulat.
    # Biaya yang gagal dikonversi akan dikeluarkan.
    df["FKL47"] = pd.to_numeric(
        df["FKL47"], errors="coerce"
    ).astype("Int64").astype("string")

    # Rapikan kode dan teks; string kosong menjadi nilai kosong.
    for col in [
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
    ]:
        df[col] = (
            df[col]
            .astype("string")
            .str.strip()
            .replace("", pd.NA)
        )

    return df


def main():
    parser = argparse.ArgumentParser(description='Skrining pola klaim serupa dari file Stata lokal.')
    parser.add_argument("--input", type=Path, required=True, help="Path file .dta lokal sebagai input.")
    args = parser.parse_args()
    input_path = args.input
    if not input_path.is_file():
        parser.error("File input tidak tersedia; periksa nilai --input.")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if TEMP_DB.exists():
        TEMP_DB.unlink()

    _, meta = pyreadstat.read_dta(
        str(input_path), metadataonly=True
    )

    missing_cols = set(READ_COLS) - set(meta.column_names)
    if missing_cols:
        raise ValueError(
            f"Kolom tidak ditemukan: {sorted(missing_cols)}"
        )

    conn = None
    total_rows = 0
    eligible_rows = 0

    try:
        conn = sqlite3.connect(TEMP_DB)

        conn.execute("""
            CREATE TABLE signature_counts (
                fp TEXT PRIMARY KEY,
                n_rows INTEGER NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE signature_people (
                fp TEXT NOT NULL,
                person_hash TEXT NOT NULL,
                PRIMARY KEY (fp, person_hash)
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
            total_rows += len(df)
            df = normalize_chunk(df)

            # Hindari membuat pola dari data yang tidak lengkap.
            valid = df[
                ["PSTV01"] + SIGNATURE_COLS
            ].notna().all(axis=1)

            sub = df.loc[valid]
            eligible_rows += len(sub)

            if sub.empty:
                print(
                    f"Potongan {chunk_no}: "
                    f"{total_rows:,} baris diperiksa"
                )
                continue

            # Fingerprint pola layanan tanpa identitas peserta.
            fingerprints = (
                pd.util.hash_pandas_object(
                    sub[SIGNATURE_COLS],
                    index=False,
                )
                .astype("uint64")
                .astype(str)
            )

            counts = fingerprints.value_counts(sort=False)

            conn.executemany(
                """
                INSERT INTO signature_counts (fp, n_rows)
                VALUES (?, ?)
                ON CONFLICT(fp) DO UPDATE SET
                    n_rows = n_rows + excluded.n_rows
                """,
                [
                    (str(fp), int(n))
                    for fp, n in counts.items()
                ],
            )

            # Hash token peserta untuk menghitung peserta unik,
            # tanpa menyimpan token peserta dalam tabel sementara.
            person_hashes = sub["PSTV01"].map(
                lambda x: hashlib.sha256(
                    str(x).encode("utf-8")
                ).hexdigest()
            )

            pairs = pd.DataFrame({
                "fp": fingerprints.to_numpy(),
                "person_hash": person_hashes.to_numpy(),
            }).drop_duplicates()

            conn.executemany(
                """
                INSERT OR IGNORE INTO signature_people
                    (fp, person_hash)
                VALUES (?, ?)
                """,
                pairs.itertuples(index=False, name=None),
            )

            conn.commit()

            print(
                f"Potongan {chunk_no}: "
                f"{total_rows:,} baris diperiksa"
            )

        # Kelompok berulang dengan minimal 2 peserta berbeda.
        repeated = conn.execute("""
            SELECT
                COUNT(*),
                COALESCE(SUM(s.n_rows), 0)
            FROM signature_counts s
            JOIN (
                SELECT fp
                FROM signature_people
                GROUP BY fp
                HAVING COUNT(*) >= 2
            ) p ON p.fp = s.fp
            WHERE s.n_rows >= 2
        """).fetchone()

        # Kelompok berulang dengan minimal 3 peserta berbeda.
        stronger = conn.execute("""
            SELECT
                COUNT(*),
                COALESCE(SUM(s.n_rows), 0)
            FROM signature_counts s
            JOIN (
                SELECT fp
                FROM signature_people
                GROUP BY fp
                HAVING COUNT(*) >= 3
            ) p ON p.fp = s.fp
            WHERE s.n_rows >= 3
        """).fetchone()

        print("\n" + "=" * 58)
        print("RINGKASAN KANDIDAT POLA CLONING")
        print("=" * 58)
        print(f"Total baris diperiksa       : {total_rows:,}")
        print(f"Baris dengan kunci lengkap  : {eligible_rows:,}")
        print(
            f"Baris tidak memenuhi syarat: "
            f"{total_rows - eligible_rows:,}"
        )
        print("\nKelompok dengan >= 2 peserta berbeda:")
        print(f"  Kelompok pola             : {repeated[0]:,}")
        print(f"  Baris yang terlibat       : {repeated[1]:,}")

        print("\nKelompok dengan >= 3 peserta berbeda:")
        print(f"  Kelompok pola             : {stronger[0]:,}")
        print(f"  Baris yang terlibat       : {stronger[1]:,}")

        print(
            "\nIni adalah pola layanan yang perlu ditinjau, "
            "bukan bukti fraud atau cloning."
        )
        print(
            "Pencocokan masih exact-match dan belum memastikan "
            "identitas faskes yang sama."
        )

    finally:
        if conn is not None:
            conn.close()

        if TEMP_DB.exists():
            TEMP_DB.unlink()


if __name__ == "__main__":
    main()
