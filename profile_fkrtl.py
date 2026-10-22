
import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import pyreadstat

CHUNK_SIZE = 100_000

# Hanya mengambil kolom yang diperlukan untuk profiling.
USECOLS = [
    "FKL02",
    "PSTV01",
    "FKL03",
    "FKL04",
    "FKL05_NEW",
    "FKL06",
    "FKL16",
    "FKL18",
    "FKL19A",
    "FKL30",
    "FKL47",
    "FKL48",
]

CATEGORY_COLS = [
    "FKL05_NEW",
    "FKL08",
    "FKL10",
    "FKL19A",
    "FKL30",
]

def main():
    parser = argparse.ArgumentParser(description='Profil agregat file FKRTL Stata lokal.')
    parser.add_argument("--input", type=Path, required=True, help="Path file .dta lokal sebagai input.")
    args = parser.parse_args()
    input_path = args.input
    if not input_path.is_file():
        parser.error("File input tidak tersedia; periksa nilai --input.")

    # Baca metadata untuk memastikan kolom yang dipilih tersedia.
    _, metadata = pyreadstat.read_dta(
        str(input_path),
        metadataonly=True,
    )

    available = set(metadata.column_names)
    missing_cols = [
        c for c in USECOLS if c not in available
    ]

    if missing_cols:
        raise ValueError(
            f"Kolom tidak ditemukan: {missing_cols}"
        )

    row_count = 0
    missing_counts = {c: 0 for c in USECOLS}

    date_min = None
    date_max = None

    cost_arrays = {
        "FKL47": [],
        "FKL48": [],
    }

    relation_counts = {
        "tagih_lebih_besar": 0,
        "tagih_lebih_kecil": 0,
        "sama": 0,
        "bisa_dibandingkan": 0,
    }

    category_counts = {
        c: {} for c in CATEGORY_COLS
    }

    reader = pyreadstat.read_file_in_chunks(
        pyreadstat.read_dta,
        str(input_path),
        chunksize=CHUNK_SIZE,
        usecols=USECOLS,
        apply_value_formats=False,
    )

    for chunk_number, (df, _) in enumerate(reader, start=1):
        row_count += len(df)

        for col in USECOLS:
            missing_counts[col] += int(
                df[col].isna().sum()
            )

        # Rentang tanggal, tanpa menampilkan data individual.
        dates = pd.to_datetime(
            df["FKL03"], errors="coerce"
        ).dropna()

        if not dates.empty:
            current_min = dates.min()
            current_max = dates.max()

            date_min = (
                current_min if date_min is None
                else min(date_min, current_min)
            )
            date_max = (
                current_max if date_max is None
                else max(date_max, current_max)
            )

        # Statistik biaya.
        billed = pd.to_numeric(
            df["FKL47"], errors="coerce"
        )
        verified = pd.to_numeric(
            df["FKL48"], errors="coerce"
        )

        cost_arrays["FKL47"].append(
            billed.to_numpy(dtype="float64")
        )
        cost_arrays["FKL48"].append(
            verified.to_numpy(dtype="float64")
        )

        valid = billed.notna() & verified.notna()
        relation_counts["bisa_dibandingkan"] += int(
            valid.sum()
        )
        relation_counts["tagih_lebih_besar"] += int(
            ((billed > verified) & valid).sum()
        )
        relation_counts["tagih_lebih_kecil"] += int(
            ((billed < verified) & valid).sum()
        )
        relation_counts["sama"] += int(
            ((billed == verified) & valid).sum()
        )

        # Distribusi kategori saja, bukan baris mentah.
        for col in CATEGORY_COLS:
            if col not in df.columns:
                continue

            counts = df[col].dropna().value_counts()

            for value, count in counts.items():
                key = str(value)
                category_counts[col][key] = (
                    category_counts[col].get(key, 0)
                    + int(count)
                )

        print(
            f"Potongan {chunk_number}: "
            f"{row_count:,} baris telah diperiksa"
        )

    print("\n" + "=" * 60)
    print("RINGKASAN DATA FKRTL")
    print("=" * 60)
    print(f"Total baris: {row_count:,}")
    print(f"Tanggal paling awal: {date_min}")
    print(f"Tanggal paling akhir: {date_max}")

    print("\nNILAI KOSONG")
    for col, count in missing_counts.items():
        print(f"{col:15} : {count:,}")

    # Statistik biaya dihitung setelah proses selesai.
    for col in ["FKL47", "FKL48"]:
        values = np.concatenate(cost_arrays[col])
        values = values[~np.isnan(values)]

        print(f"\nSTATISTIK {col}")
        print(f"Data numerik tersedia: {len(values):,}")

        if len(values):
            print(
                pd.Series(values).describe(
                    percentiles=[0.25, 0.50, 0.75, 0.95]
                ).to_string()
            )
            print(f"Nilai negatif: {(values < 0).sum():,}")
            print(f"Nilai nol: {(values == 0).sum():,}")

    print("\nPERBANDINGAN BIAYA TAGIH DAN VERIFIKASI")
    for label, count in relation_counts.items():
        print(f"{label:25}: {count:,}")

    print("\n10 KATEGORI TERBANYAK PER KOLOM")
    for col, counts in category_counts.items():
        print(f"\n{col}:")
        for value, count in sorted(
            counts.items(),
            key=lambda item: item[1],
            reverse=True,
        )[:10]:
            print(f"  {value}: {count:,}")

    print("\nProfiling selesai.")
    print("Tidak ada baris data individual yang ditampilkan.")


if __name__ == "__main__":
    main()
