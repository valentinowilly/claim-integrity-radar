"""Build demo-4: the claims of demo-3 delivered the way a verification team receives them during the RME transition.

* ``klaim-eklaim.csv``: most claims, exported from E-Klaim in the BPJS column format;
* ``rme-satusehat.json``: the claims of some provinces as an HL7 FHIR collection bundle (RME/SATUSEHAT route);
* ``berkas/*.pdf``: facility documents (SEP, resume medis, rincian tagihan, resep, bukti penyerahan, catatan sesi
  terapi, ...) for a sample of claims; about a third are scans (image only, read by OCR). For these claims the CSV
  carries no clinical note and no evidence inventory: they must come from the PDFs. A few claims exist only as
  PDFs, and a few PDFs disagree with the claim data on purpose (the cross-check must find them).

Everything is synthetic (participants start with SYN; every page says "CONTOH SINTETIS"). The answer file lists,
per PDF, the type and the values printed on it, so reading accuracy can be measured.

    python -m scripts.make_multisource_demo
"""

from __future__ import annotations

import csv
import io
import json
import random
import textwrap
from collections import defaultdict
from pathlib import Path

from app.data_sources.bpjs_csv import UPLOAD_PSEUDONYM_SECRET
from app.data_sources.bpjs_fkrtl_adapter import pseudonymous_case_id
from app.intake.fhir import rows_to_bundle

ROOT = Path(__file__).resolve().parents[2] / "demo-data"
SOURCE = ROOT / "demo-3-operasional.csv"
OUT = ROOT / "demo-4-multisumber"
SEED = 2026
FHIR_PROVINCES = ("51", "52")  # Bali, NTB: their facilities already send RME through SATUSEHAT
EVIDENCE_DOCS = {"clinical_note": "resume_medis", "therapy_session_log": "catatan_sesi_terapi", "prescription": "resep",
                 "dispensing_record": "bukti_penyerahan_obat", "device_order": "permintaan_alat",
                 "delivery_record": "bukti_pemasangan_alat"}
TITLES = {"sep": "SURAT ELIGIBILITAS PESERTA", "resume_medis": "RESUME MEDIS PASIEN PULANG",
          "rincian_tagihan": "RINCIAN TAGIHAN INA-CBG", "resep": "RESEP OBAT / ALKES",
          "bukti_penyerahan_obat": "BUKTI PENYERAHAN OBAT", "permintaan_alat": "PERMINTAAN ALAT KESEHATAN",
          "bukti_pemasangan_alat": "BUKTI PEMASANGAN ALAT", "catatan_sesi_terapi": "CATATAN SESI TERAPI"}
SERVICE_NAMES = {"physiotherapy": "Fisioterapi", "special_drug": "Obat khusus", "special_device": "Alat kesehatan khusus"}
TOPUPS = (("FKL33", "Top Up Sub Akut"), ("FKL35", "Top Up Prosedur"), ("FKL38", "Top Up Prostesis"),
          ("FKL41", "Top Up Investigasi"), ("FKL44", "Top Up Obat"))
MISMATCHES = (("FKL47", "total_tagihan"), ("FKL19", "ina_cbg"), ("FKL04", "tanggal_pulang"))


def _d(iso: str | None) -> str:
    return f"{iso[8:10]}-{iso[5:7]}-{iso[:4]}" if iso else "-"


def _rp(value: str | None) -> str:
    return "Rp " + f"{int(float(value)):,}".replace(",", ".") if value else "-"


def _lines(doc: str, row: dict[str, str], printed: dict[str, str]) -> tuple[list[str], str | None]:
    """Printed field lines (label: value) and the narrative, from the values ``printed`` will hold."""
    visit = row["FKL02"]
    common = [("No. Kunjungan", visit, "nomor_kunjungan", visit), ("No. Kartu", row["PSTV01"], "nomor_peserta", row["PSTV01"])]
    fields: list[tuple[str, str, str, str | None]] = []
    narrative = None
    if doc == "sep":
        fields = [("No. SEP", "SEP" + visit[-9:], "", None), *common, ("Tgl. SEP", _d(row.get("FKL03")), "tanggal_masuk", row.get("FKL03")),
                  ("Kode Faskes", row.get("ID_FASKES") or "-", "kode_faskes", row.get("ID_FASKES")),
                  ("Kode Provinsi", row.get("FKL05") or "-", "provinsi", row.get("FKL05")),
                  ("Kode Kab/Kota", row.get("FKL06") or "-", "kab_kota", row.get("FKL06")),
                  ("Kepemilikan Faskes", row.get("FKL07") or "-", "kepemilikan", row.get("FKL07")),
                  ("Jenis Faskes", row.get("FKL08") or "-", "jenis_faskes", row.get("FKL08")),
                  ("Kelas Faskes", row.get("FKL09") or "-", "kelas_faskes", row.get("FKL09")),
                  ("Kelas Rawat", row.get("FKL13") or "-", "kelas_rawat", row.get("FKL13")),
                  ("Diagnosis Awal", row.get("FKL16") or "-", "diagnosis_masuk", row.get("FKL16"))]
        if row.get("JENIS_LAYANAN"):
            fields.append(("Jenis Layanan", SERVICE_NAMES[row["JENIS_LAYANAN"]], "jenis_layanan", row["JENIS_LAYANAN"]))
    elif doc == "resume_medis":
        fields = [*common, ("Tanggal Masuk", _d(row.get("FKL03")), "tanggal_masuk", row.get("FKL03")),
                  ("Tanggal Pulang", _d(row.get("FKL04")), "tanggal_pulang", row.get("FKL04")),
                  ("Diagnosis Utama", row.get("FKL18") or "-", "diagnosis_utama", row.get("FKL18")),
                  ("Diagnosis Sekunder", (row.get("FKL24") or "-").replace(";", ", "), "diagnosis_sekunder", row.get("FKL24")),
                  ("Tindakan", row.get("FKL30") or "-", "prosedur", row.get("FKL30"))]
        narrative = row.get("CATATAN_KLINIS") or None
    elif doc == "rincian_tagihan":
        fields = [*common, ("Kode INA-CBG", row.get("FKL19") or "-", "ina_cbg", row.get("FKL19")),
                  ("Regional Tarif", row.get("FKL31") or "-", "regional_tarif", row.get("FKL31")),
                  ("Kelompok Tarif", row.get("FKL32") or "-", "kelompok_tarif", row.get("FKL32"))]
        names = {"FKL33": "topup_subakut", "FKL35": "topup_prosedur", "FKL38": "topup_prostesis",
                 "FKL41": "topup_investigasi", "FKL44": "topup_obat"}
        fields += [(label, row[column], names[column], row[column]) for column, label in TOPUPS if row.get(column)]
        fields.append(("Total Tagihan", _rp(row.get("FKL47")), "total_tagihan", row.get("FKL47")))
    else:  # supporting documents: who, when, what
        code = next((row[column] for column, _label in TOPUPS if row.get(column)), None)
        fields = [*common, ("Tanggal Layanan", _d(row.get("FKL03")), "tanggal_masuk", row.get("FKL03"))]
        if doc == "catatan_sesi_terapi":
            fields += [("Jenis Layanan", "Fisioterapi", "jenis_layanan", "physiotherapy"),
                       ("Jam Layanan", row.get("JAM_LAYANAN") or "-", "jam_layanan", row.get("JAM_LAYANAN")),
                       ("Jumlah Sesi", row.get("JUMLAH_LAYANAN") or "-", "jumlah_sesi", row.get("JUMLAH_LAYANAN")),
                       ("Terapis", "Fisioterapis (contoh sintetis)", "", None), ("Paraf pasien", "ada", "", None)]
        else:
            if code:
                fields.append(("Kode Obat/Alkes", code, "", None))
            fields.append({"resep": ("Diresepkan oleh", "Dokter (contoh sintetis)", "", None),
                           "bukti_penyerahan_obat": ("Diserahkan oleh", "Apoteker (contoh sintetis)", "", None),
                           "permintaan_alat": ("Diminta oleh", "Dokter (contoh sintetis)", "", None),
                           "bukti_pemasangan_alat": ("Dipasang oleh", "Dokter (contoh sintetis)", "", None)}[doc])
    lines = []
    for label, shown, name, value in fields:
        lines.append(f"{label}: {shown}")
        if name and value:
            printed[name] = value
    if narrative:
        printed["catatan_klinis"] = narrative
    return lines, narrative


def _digital_pdf(doc: str, row: dict[str, str], lines: list[str], narrative: str | None) -> bytes:
    from fpdf import FPDF

    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(True, margin=18)
    pdf.add_page()
    pdf.set_font("Helvetica", size=8)
    pdf.cell(0, 5, "CONTOH SINTETIS - bukan dokumen asli", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", style="B", size=10)
    pdf.cell(0, 6, f"Rumah Sakit {row.get('ID_FASKES') or 'Contoh'} (data sintetis)", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)
    pdf.set_font("Helvetica", style="B", size=14)
    pdf.cell(0, 9, TITLES[doc], new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    pdf.set_font("Helvetica", size=11)
    for line in lines:
        pdf.multi_cell(0, 7, line.encode("latin-1", "replace").decode("latin-1"), new_x="LMARGIN", new_y="NEXT")
    if narrative:
        pdf.ln(2)
        pdf.cell(0, 7, "Ringkasan Perawatan:", new_x="LMARGIN", new_y="NEXT")
        pdf.multi_cell(0, 6, narrative.encode("latin-1", "replace").decode("latin-1"), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)
        pdf.cell(0, 7, "Kondisi Pulang: sesuai ringkasan", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 7, "Dokter Penanggung Jawab: dr. Contoh (sintetis)", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)
    pdf.set_font("Helvetica", size=9)
    pdf.cell(0, 6, "Tanda tangan elektronik: (contoh sintetis)", new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())


def _scanned_pdf(doc: str, row: dict[str, str], lines: list[str], narrative: str | None, rng: random.Random) -> bytes:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont

    width, height = 1240, 1754  # A4 at 150 dpi
    page = Image.new("L", (width, height), 246)
    draw = ImageDraw.Draw(page)
    small, normal, title = (ImageFont.load_default(size=size) for size in (19, 25, 33))
    y = 70
    draw.text((90, y), "CONTOH SINTETIS - bukan dokumen asli", fill=60, font=small); y += 40
    draw.text((90, y), f"Rumah Sakit {row.get('ID_FASKES') or 'Contoh'} (data sintetis)", fill=25, font=normal); y += 70
    draw.text((90, y), TITLES[doc], fill=10, font=title); y += 75
    for line in lines:
        for part in textwrap.wrap(line, 74) or [""]:
            draw.text((90, y), part, fill=20, font=normal); y += 44
    if narrative:
        y += 10
        draw.text((90, y), "Ringkasan Perawatan:", fill=20, font=normal); y += 44
        for part in textwrap.wrap(narrative, 78):
            draw.text((90, y), part, fill=25, font=normal); y += 38
        y += 14
        draw.text((90, y), "Kondisi Pulang: sesuai ringkasan", fill=20, font=normal); y += 44
        draw.text((90, y), "Dokter Penanggung Jawab: dr. Contoh (sintetis)", fill=20, font=normal); y += 44
    draw.text((90, y + 40), "Tanda tangan: (contoh sintetis)", fill=40, font=small)
    for _ in range(1800):  # paper speckle
        x, yy = rng.randrange(width), rng.randrange(height)
        draw.point((x, yy), fill=rng.randrange(150, 220))
    page = page.rotate(rng.uniform(-1.2, 1.2), expand=False, fillcolor=246, resample=Image.BICUBIC)
    page = page.filter(ImageFilter.GaussianBlur(rng.uniform(0.4, 0.8)))
    buffer = io.BytesIO()
    page.convert("RGB").save(buffer, format="PDF", resolution=150.0)
    return buffer.getvalue()


def build(rng: random.Random | None = None) -> dict[str, object]:
    rng = rng or random.Random(SEED)
    rows = list(csv.DictReader(SOURCE.open(encoding="utf-8")))
    header = list(rows[0].keys())
    labels = json.loads((ROOT / "demo-3-operasional.answers.json").read_text(encoding="utf-8"))["labels"]
    label_of = {row["FKL02"]: labels.get(pseudonymous_case_id(row["PSTV01"], row["FKL02"], secret=UPLOAD_PSEUDONYM_SECRET), "")
                for row in rows}

    # Claims with documents: every evidence story of demo-3, plus ordinary claims for contrast.
    by_label: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        if row["FKL05"] not in FHIR_PROVINCES:
            by_label[label_of[row["FKL02"]]].append(row)
    wanted = {"phantom_physiotherapy": 12, "honest_busy_physiotherapy": 6, "fictitious_drug_device": 10, "special_topup": 3,
              "upcoding": 6, "prolonged_stay": 6, "readmission_split": 4, "cloning": 6, "repeat_billing": 3, "": 14}
    chosen: list[dict[str, str]] = []
    for label, count in wanted.items():
        pool = sorted(by_label[label], key=lambda row: row["FKL02"])
        chosen += rng.sample(pool, min(count, len(pool)))
    # The cloned note must appear on several participants' documents to be found again after reading.
    clone_rows = [row for row in chosen if label_of[row["FKL02"]] == "cloning"]
    if clone_rows:
        twins = [row for row in by_label["cloning"] if row["CATATAN_KLINIS"] == clone_rows[0]["CATATAN_KLINIS"]]
        chosen += [row for row in twins if row not in chosen][:3]
    honest_inpatient = [row for row in chosen if label_of[row["FKL02"]] == "" and not row.get("JENIS_LAYANAN") and row.get("FKL04")]
    pdf_only = {row["FKL02"] for row in honest_inpatient[:5]}
    mismatch_rows = [row for row in chosen if row["FKL02"] not in pdf_only and not row.get("JENIS_LAYANAN")][:3]
    mismatch_plan = {row["FKL02"]: MISMATCHES[index % len(MISMATCHES)] for index, row in enumerate(mismatch_rows)}

    chosen_ids = {row["FKL02"] for row in chosen}
    (OUT / "berkas").mkdir(parents=True, exist_ok=True)
    for old in (OUT / "berkas").glob("*.pdf"):
        old.unlink()
    answers: dict[str, object] = {"documents": {}, "pdf_only": sorted(pdf_only), "mismatches": {}, "with_documents": sorted(chosen_ids)}
    scan_counter = 0
    for row in sorted(chosen, key=lambda row: row["FKL02"]):
        docs = ["sep", "rincian_tagihan"]
        docs += [EVIDENCE_DOCS[code] for code in (row.get("BUKTI_TERCATAT") or "").split(";") if code in EVIDENCE_DOCS]
        if "resume_medis" not in docs and row.get("CATATAN_KLINIS"):
            docs.insert(1, "resume_medis")
        for doc in dict.fromkeys(docs):
            printed_row = dict(row)
            plan = mismatch_plan.get(row["FKL02"])
            if plan and doc in ("rincian_tagihan", "resume_medis") and (doc == "rincian_tagihan") == (plan[0] != "FKL04"):
                column, field = plan
                if column == "FKL47":
                    printed_row["FKL47"] = str(int(float(row["FKL47"])) + 2_500_000)
                elif column == "FKL19":
                    base, _, severity = row["FKL19"].rpartition("-")
                    printed_row["FKL19"] = f"{base}-{'III' if severity != 'III' else 'II'}"
                else:  # the document states a later discharge than the claim data
                    from datetime import date, timedelta
                    printed_row["FKL04"] = (date.fromisoformat(row["FKL04"]) + timedelta(days=3)).isoformat()
                answers["mismatches"][row["FKL02"]] = {"column": column, "field": field, "data": row[column],
                                                       "document": printed_row[column]}
            printed: dict[str, str] = {}
            lines, narrative = _lines(doc, printed_row, printed)
            scanned = rng.random() < 0.35
            if scanned:
                scan_counter += 1
                name = f"scan_{scan_counter:04d}.pdf"
                raw = _scanned_pdf(doc, printed_row, lines, narrative, rng)
            else:
                name = f"{row['FKL02']}_{doc}.pdf"
                raw = _digital_pdf(doc, printed_row, lines, narrative)
            (OUT / "berkas" / name).write_bytes(raw)
            answers["documents"][name] = {"doc_type": doc, "visit": row["FKL02"], "scanned": scanned, "values": printed}

    # Claim data: FHIR for two provinces, CSV for the rest; claims with documents lose note and evidence in the
    # data (the documents carry them); PDF-only claims are in no data file.
    fhir_rows, csv_rows = [], []
    for row in rows:
        if row["FKL02"] in pdf_only:
            continue
        out = dict(row)
        if row["FKL02"] in chosen_ids:
            out["CATATAN_KLINIS"] = ""
            out["BUKTI_TERCATAT"] = ""  # the recording status stays: it is a flag of the claim system, not a document
        (fhir_rows if row["FKL05"] in FHIR_PROVINCES else csv_rows).append(out)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=header, lineterminator="\n")
    writer.writeheader()
    writer.writerows(csv_rows)
    (OUT / "klaim-eklaim.csv").write_text(buffer.getvalue(), encoding="utf-8", newline="")
    bundle = rows_to_bundle([{key: value for key, value in row.items() if value} for row in fhir_rows])
    (OUT / "rme-satusehat.json").write_text(json.dumps(bundle, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    answers.update({"csv_claims": len(csv_rows), "fhir_claims": len(fhir_rows), "total_claims": len(rows),
                    "pdf_files": len(answers["documents"]),
                    "scanned_files": sum(item["scanned"] for item in answers["documents"].values())})
    (OUT / "demo-4-multisumber.answers.json").write_text(json.dumps(answers, ensure_ascii=False, indent=1), encoding="utf-8")
    return answers


if __name__ == "__main__":
    result = build()
    print({key: result[key] for key in ("csv_claims", "fhir_claims", "total_claims", "pdf_files", "scanned_files")},
          "pdf_only:", len(result["pdf_only"]), "mismatches:", len(result["mismatches"]))
