"""Hand-written clinical notes for measuring the note reader (independent of the demo generator's phrasing).

Each case is one claim with a free-text note written in the varied style of real discharge summaries:
abbreviations, numbers as words, "2x24 jam", honest severe cases with real comorbidities. The label says
whether the note contradicts the bill. Example text only; no patient data.
"""

from __future__ import annotations

# (label, INA-CBG, stay in days on the claim, primary diagnosis, note)
CASES: list[tuple[str, str, int, str, str]] = [
    # Honest: the note supports the bill.
    ("honest", "I-4-12-III", 7, "I50.0",
     "Tn. 67 th, sesak memberat sejak 3 hari, riwayat gagal jantung dan DM tipe 2 dengan nefropati. Saat masuk TD 90/60, "
     "SpO2 88% dengan O2 nasal 4 lpm. Ro thorax: edema paru. Dirawat di HCU, diuretik iv dan insulin. Hari ke-6 sesak berkurang, "
     "pulang hari ke-7 dengan kondisi membaik."),
    ("honest", "A-4-10-I", 3, "A91",
     "An. P, 9 th, demam 4 hari disertai mual. Trombosit 98 rb, Ht 41%. Tidak ada tanda syok maupun perdarahan. "
     "Cairan iv, observasi tanda vital. Rawat 3 hari, pulang dalam perbaikan."),
    ("honest", "J-4-16-II", 5, "J18.9",
     "Ny. 54 th dengan DM tipe 2 terkontrol, datang batuk berdahak dan demam 5 hari. Ronki basah paru kanan bawah, "
     "leukosit 15 rb. Antibiotik iv 4 hari, gula darah dipantau. Pulang hari ke-5, afebris."),
    ("honest", "K-4-17-III", 9, "K72.9",
     "Tn. 58 th, sirosis hati dekompensata dengan asites dan ensefalopati grade 2, disertai CKD. Kesadaran menurun saat masuk. "
     "Laktulosa, albumin iv, parasentesis. Dirawat 9 hari, pulang sadar penuh."),
    # Upcoding: a mild course under a severity II/III INA-CBG.
    ("upcoding", "A-4-14-III", 2, "A09",
     "Tn. 45 th diare cair 2 hari, dehidrasi ringan. KU baik, tidak ada penyulit maupun penyakit penyerta. "
     "Rehidrasi oral dan infus 1 kolf. Pulang hari ke-2."),
    ("upcoding", "N-4-15-III", 3, "N39.0",
     "Ny. 30 th, nyeri saat berkemih dan demam ringan. Tidak ada riwayat penyakit lain. Urinalisis leukosit positif. "
     "Antibiotik, pulang setelah 3 hari dirawat."),
    ("upcoding", "J-4-15-III", 3, "J18.0",
     "An. R 6 th bronkopneumonia ringan, SpO2 97% tanpa oksigen, makan dan minum baik, tidak sesak. Rawat 3 hari."),
    ("upcoding", "K-4-12-II", 4, "K30",
     "Ny. 41 th nyeri ulu hati dan mual. Sebelumnya sehat, tanpa penyakit penyerta. Endoskopi dalam batas normal. "
     "PPI iv, pulang hari ke-4."),
    # Prolonged stay: the note describes a shorter stay than billed.
    ("prolonged_stay", "A-4-10-I", 9, "A91",
     "Pasien wanita 25 th dengan demam dengue, trombosit 110 rb. Observasi 2x24 jam, kondisi stabil, diizinkan pulang."),
    ("prolonged_stay", "J-4-16-I", 11, "J18.9",
     "Tn. 36 th pneumonia. Rawat inap 3 hari dengan antibiotik iv; hari ketiga afebris dan nafsu makan baik, pulang."),
    ("prolonged_stay", "K-4-13-I", 12, "K35.8",
     "Ny. 29 th pasca apendektomi laparoskopi tanpa komplikasi. Pasien dirawat selama empat hari lalu pulang."),
    ("prolonged_stay", "N-4-15-I", 8, "N39.0",
     "Tn. 50 th ISK. Respons baik dengan antibiotik, pulang pada hari perawatan kedua."),
    # Split readmission: the note says it continues an earlier admission.
    ("readmission_split", "A-4-14-I", 2, "A09",
     "Masuk kembali 2 hari setelah pulang dari rawat inap dengan keluhan yang sama (diare). Infus, pulang hari ke-2."),
    ("readmission_split", "K-4-12-I", 2, "K29.7",
     "Rawat ulang: nyeri perut masih ada sejak perawatan minggu lalu yang belum tuntas. Terapi dilanjutkan 2 hari."),
    ("readmission_split", "J-4-16-I", 3, "J18.9",
     "Pasien baru keluar RS 3 hari lalu dengan diagnosis yang sama, kini kembali dirawat untuk melanjutkan antibiotik."),
    ("readmission_split", "N-4-15-I", 2, "N39.0",
     "Readmisi; episode perawatan sebelumnya belum selesai, keluhan berkemih menetap. Rawat 2 hari."),
]


def claims() -> list[tuple[str, dict]]:
    return [(label, {"primary_diagnosis": diagnosis, "admission_diagnosis": diagnosis, "claim_group": group,
                     "stay_days": stay, "clinical_note": note, "findings": [], "ai_score": None, "ai_factors": [],
                     "service_date": None, "discharge_date": None, "procedure_code": None, "care_class": None})
            for label, group, stay, diagnosis, note in CASES]
