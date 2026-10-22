import argparse
from pathlib import Path
import pyreadstat


FILES_TO_INSPECT = [
    "202403_fkrtl.dta",
    "202405_diagnosissekunder.dta",
]

def inspect_file(filename: str, data_dir: Path) -> None:
    path = data_dir / filename

    if not path.is_file():
        print(f"\nFile metadata yang diminta tidak tersedia: {filename}")
        return

    print(f"\n{'=' * 70}")
    print(f"FILE: {filename}")

    # Baca metadata saja, bukan isi baris dataset.
    _, meta = pyreadstat.read_dta(
        str(path),
        metadataonly=True,
    )

    print(f"Jumlah baris    : {meta.number_rows:,}")
    print(f"Jumlah kolom    : {meta.number_columns}")
    print("\nDAFTAR KOLOM:")

    for name, label in zip(
        meta.column_names,
        meta.column_labels,
    ):
        print(f"{name:15} | {label or '-'}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Inspeksi metadata file Stata dalam direktori lokal.")
    parser.add_argument("--data-dir", type=Path, required=True, help="Direktori lokal yang berisi file .dta yang akan diperiksa.")
    args = parser.parse_args()
    if not args.data_dir.is_dir():
        parser.error("Direktori input tidak tersedia; periksa nilai --data-dir.")
    for filename in FILES_TO_INSPECT:
        inspect_file(filename, args.data_dir)
