# Claim Integrity Radar — Release Candidate (cakupan dan status)

Dokumen otoritatif untuk cakupan release candidate (RC). Rincian teknis ada di dokumen yang dirujuk; dokumen ini tidak menggantikannya. Narasi presentasi/demo: `docs/demo-alignment-brief.md`. Usulan model operasional dan adopsi (bukan business case finansial tervalidasi): `docs/business-model.md`. Status per 2026-10-26, working tree branch `coverage-contract` (belum di-commit).

## 1. Cakupan produk dan pengguna

Prototipe **audit decision support**: membentuk kandidat peninjauan dari data klaim, menjelaskan alasan dan cakupan pemeriksaan, mengurutkan antrean, dan mencatat keputusan tinjauan manusia serta hasil audit berwenang. **Bukan** sistem penetapan fraud. Pengguna: `data_operator` (impor/run), `verifikator` (status tinjauan), `audit_lead` (outcome, hasil audit), `platform_admin` (demo lokal). Hak akses: `docs/role-permission-matrix.md`.

Sumber data: batch CSV **sintetis** dan sampel **FKRTL BPJS lokal** yang dikonfigurasi di server (jendela tanggal masuk FKL03, batas baris yang menolak alih-alih memotong). Model AI dari salinan eksperimen **tidak** dipindahkan ke sistem ini.

## 2. Matriks kapabilitas detektor (dibekukan untuk RC)

Status: **R** = didukung field nyata yang terverifikasi; **E** = sinyal kandidat eksploratif, tidak tervalidasi sebagai fraud; **S** = synthetic-only; **U** = tidak dinilai karena bukti hilang; **O** = di luar cakupan RC.

| Modus | Pemeriksaan & kode | Status di FKRTL | Input wajib | Missingness | Penjelasan ke reviewer | Tes | Batasan |
|---|---|---|---|---|---|---|---|
| Repeat Billing (skrining pola layanan berulang) | `repeat_billing.py` profil `repeat-service-v1` (FKRTL); `repeat-billing-exact-v1` (sintetis) | **R + E** | peserta (HMAC), FKL03, FKL18, FKL19, FKL30 | FKL30 kosong → **tidak dinilai** (41,7% file); konteks FKL05–09/16 tidak menentukan eligibility | atribut sama/berbeda/tidak tercatat (nama field saja), definisi repeat_service_v1, saran pemeriksaan | `test_repeat_service_profile`, `test_repeat_definitions`, `test_fkrtl_date_window`, `test_fkrtl_local_source` | tidak menunjukkan bahwa klaim sebelumnya sudah ditagih dan dibayar; tidak membedakan pengajuan ulang dari layanan ulang sah; tanpa riwayat pengajuan; FKL47 tidak dibandingkan |
| Cloning | `near_duplicate_claims.py` "Similar-claim screening (exploratory)" | **E** | atribut administrasi/kode, tanggal | atribut kurang dari minimum → tidak dinilai; pencarian dibatasi anggaran → `not_reached_by_search`/truncation ditandai | atribut cocok/berbeda, rasio kemiripan, label exploratory | `test_near_duplicate_benchmark`, `test_near_duplicate_allocation`, `test_coverage_correctness`, `test_workbench_integration` | tanpa ID fasilitas tidak membedakan salinan dari klaim rutin; terpotong pada data nyata |
| Cloning (pola persis lintas peserta) | `similar_claim_pattern.py` | **U** (tidak berlaku: butuh nominal terverifikasi) | + nominal tagih terverifikasi | FKRTL: dinyatakan tidak berlaku | — | `test_coverage_correctness` | FKL47 belum terverifikasi |
| Phantom Billing | `evidence_completeness.py`, `capacity.py`, `temporal_patterns.py` | **S** (FKRTL: tidak berlaku) | inventaris bukti, ID fasilitas & kapasitas, timestamp (sintetis) | bukti belum tersinkron → tidak dinilai; tanpa aturan → tidak berlaku | dokumen yang tidak tercantum menurut aturan sintetis | `test_additional_detectors`, `test_analytics` | data bukti pelaksanaan, kapasitas, dan ID fasilitas tidak ada di sumber BPJS lokal; pola waktu memakai jendela 3 hari **kalender** dan klaster **menit** yang sama dari timestamp sintetis — FKRTL hanya memuat tanggal |
| Obat/alkes (proposal: "Klaim Fiktif Obat/Alkes") | — (tidak ada detektor di sistem ini) | **O** | rincian item & penyerahan (tidak tersedia) | — | — | — | hanya kode tambahan tarif FKL38/FKL44 (≤ 0,09% klaim); tanpa kuantitas/penyerahan; pemetaan ke modus resmi lihat §2.1 |
| Anomali umum | `ml_anomaly.py` (Isolation Forest, `isolation-forest-categorical-v1`); `length_of_stay.py` (durasi vs pembanding) | **E** | kode, tanggal, kunjungan (tanpa identifier, nominal, FKL48) | durasi: tanggal tidak valid/peer group kecil → tidak dinilai | persentil penyimpangan; label exploratory; ranking ML **tidak** terbukti lebih baik dari sinyal transparan | `test_ml_anomaly`, `test_ml_ranking`, `test_length_of_stay` | relatif per run; tidak memengaruhi indeks aturan atau prioritas |

Fakta yang mengikat: tidak ada pengembangan AI tambahan dengan fitur saat ini (gate Fase 6); FKL30 kosong tetap tidak dinilai; FKL47 tidak dipakai pra-verifikasi; **FKL48 tidak pernah dibaca**; tautan FKTP (FKP02) adalah konteks rujukan dan tidak dipakai sebagai bukti layanan; diagnosis sekunder tidak di-join (tidak menggandakan klaim); 694 pasangan nyata yang mirip dari analisis gate bersifat eksploratif, bukan label. Semantik rinci: `docs/detection-semantics.md`; field FKRTL: `docs/bpjs-sample-compatibility.md`.

### 2.1 Crosswalk proposal → taksonomi resmi → kapabilitas RC

Proposal yang diajukan (`proposal-healthkathon.pdf`) dipertahankan sebagai arsip dan tidak diubah. Kategori proposal: *Efisiensi Risiko pada Fasilitas Kesehatan*. Definisi modus resmi di bawah dicek terhadap Participant Guide Healthkathon 2026 (§6 Kategori Lomba; nomor = urutan modus pada kategori Fasilitas Kesehatan). Setiap tim memilih satu kategori dan boleh mengangkat beberapa modus di dalamnya.

| Proposal | Modus resmi (Participant Guide) | Kapabilitas RC aktual | Status FKRTL | Yang boleh disimpulkan reviewer | Yang tidak diklaim |
|---|---|---|---|---|---|
| Repeat Billing (pola waktu & pengulangan) | #11 Repeat billing: klaim diulang pada kasus yang sama yang sudah ditagihkan dan dibayarkan | skrining pola layanan berulang `repeat-service-v1` (peserta, FKL03, FKL18, FKL19, FKL30) | R + E; FKL30 kosong → tidak dinilai | kandidat skrining untuk potensi Repeat Billing yang perlu dibandingkan berkasnya | bahwa klaim sebelumnya sudah ditagih/dibayar; tagihan ganda; fraud |
| Cloning (klaim kembar, MinHash/LSH) | #5 Cloning: klaim dibuat dengan menyalin klaim/rekam medis pasien lain | similar-claim screening eksploratif: blocking deterministik berbatas (`near_duplicate_claims.py`); **bukan** MinHash/LSH | E; pencarian terpotong (`not_reached_by_search`) | pasangan klaim lintas peserta yang mirip pada atribut yang dibandingkan | penyalinan klaim; fasilitas yang sama; cakupan lengkap |
| Phantom Billing (kapasitas, pola waktu jam, kelengkapan bukti) | #6 Phantom billing: klaim atas layanan yang tidak pernah diberikan | kapasitas, pola waktu, kelengkapan bukti pada data sintetis | S (FKRTL: tidak berlaku) | perilaku pemeriksa pada skenario sintetis yang ditanam | deteksi tervalidasi pada FKRTL nyata; pola jam/menit pada data nyata |
| Klaim Fiktif Obat/Alkes | #17 Klaim fiktif obat/alkes/tindakan: ditagihkan namun tidak diberikan kepada pasien (modus resmi yang sama dengan istilah proposal). Berbeda dari #7/#19 *Inflated bills* (biaya lebih besar dari sebenarnya) dan #18 pengurangan jumlah obat | tidak ada detektor | O | — | deteksi klaim fiktif obat/alkes, inflated bills, atau pengurangan jumlah obat |
| — (tidak disebut proposal) | #12 Prolonged length of stay: klaim lebih besar akibat perpanjangan rawat inap bukan karena indikasi medis | layar durasi rawat eksploratif `los-peer-p99-v1` (FKL03/04, FKL19, FKL13) | E; peer group kecil → tidak dinilai | rawat inap jauh lebih panjang dari klaim sebanding, perlu dicek indikasi medisnya | bahwa perpanjangan tidak berindikasi medis; batas klinis atau BPJS |
| — | #16 Readmisi, #4 Upcoding, #8/#9 pemecahan episode/unbundling, modus lain | tidak ada detektor (pola Repeat hanya tanggal masuk yang sama, bukan admisi berulang lintas hari) | O | — | deteksi modus tersebut |
| Skor gabungan: aturan berbobot vs gradient boosting, penjelasan SHAP/jejak aturan | — | indeks aturan provisional (`rule-risk-index-v2-provisional`) dengan jejak alasan; ranking Isolation Forest eksploratif terpisah; **tidak ada** gradient boosting atau SHAP di sistem ini | indeks ditahan di FKRTL (< 3 pemeriksaan dinilai); ranking ML E | alasan per pemeriksaan; urutan eksploratif | probabilitas fraud; AI lebih baik dari sinyal transparan |
| Prioritas = Risiko × Nilai Klaim × Usaha Audit; jalur hijau/kuning/merah | — | konsep desain; `audit-priority-v1-synthetic-assumption` dan lane `action-policy-demo-v1-provisional` (batas 1/3, 2/3) hanya pada data sintetis | prioritas fasilitas tidak dapat dinilai (tanpa ID fasilitas dan nominal pra-verifikasi) | rekomendasi provisional CIR | kebijakan resmi BPJS; ambang tervalidasi |

Pengembangan obat/alkes ke depan menargetkan #17 (ditagihkan tetapi tidak diberikan) dan membutuhkan rincian item, kuantitas tagih, serta catatan penyerahan/dispensing yang tertaut ke kunjungan; *Inflated bills* (#7/#19) juga membutuhkan harga tagih per item dan acuan harga. *Penyalahgunaan obat/alkes* termasuk kategori Peserta, di luar kategori tim. Data tersebut tidak tersedia di sampel lokal.

### 2.2 Prioritas, nominal, dan jalur

Rumus prioritas proposal tetap **konsep desain**: komponen nilai klaim belum dapat diisi karena FKL48 adalah biaya pasca-verifikasi (tidak pernah dipakai sebagai prediktor) dan semantik serta ketersediaan pra-verifikasi FKL47 belum dikonfirmasi (tidak dipakai untuk prioritas moneter). Batas lane hijau/kuning/merah adalah **rekomendasi provisional CIR**, bukan kebijakan resmi BPJS, dan hanya bermakna pada run sintetis.

### 2.3 Dataset lain dalam panduan data sampel

Panduan data sampel mendefinisikan dataset FKTP Non Kapitasi dengan ID kunjungan sendiri (`PNK02`) dan tanggal kunjungan (`PNK03`). RC ini tidak memproses dataset tersebut. Belum ada kunci lintas dataset yang tervalidasi antara `PNK02` dan ID kunjungan FKRTL (`FKL02`); hubungan yang terdokumentasi hanya melalui peserta (`PSTV01`). Tidak ada join baru yang dibuat.

### 2.4 Posisi AI/ML pada RC

* **Yang ada:** satu ranking Isolation Forest eksploratif (`isolation-forest-categorical-v1`) yang tidak mengubah antrean, indeks aturan, lane, atau keputusan reviewer; layar durasi statistik; detektor aturan transparan.
* **Temuan evaluasi (sintetis, terpra-registrasi):** dalam Task M salinan eksperimen: 30 seed uji akhir yang sama (101–130), generator sintetis terkalibrasi (Amandemen 3), unit = klaim, P@25 = proporsi target berlabel di antara 25 klaim teratas per seed, dirata-rata antar seed, model tidak mengungguli sinyal transparan sederhana (IF v1 0,32; IF v2 0,46; jumlah kunjungan 0,82; deviasi lama rawat 0,81). Angka ini hanya dapat dibandingkan di dalam konteks Task M tersebut, bukan dengan benchmark v2 di `docs/detection-semantics.md` (generator berbeda), dan bukan kinerja pada data BPJS nyata. Model supervised gagal uji ketahanan pada subtipe yang ditahan dari training. Karena itu produk mengandalkan sinyal yang dapat dijelaskan; temuan ini dilaporkan apa adanya.
* **Tidak dipindahkan:** `isolation-forest-conditional-v2` dan model supervised tetap di salinan eksperimen. Peningkatan v2 atas v1 adalah temuan eksperimen, bukan bukti nilai tambah terhadap baseline transparan atau ketahanan terhadap modus yang belum dilatih.
* **Penjelasan reviewer:** deterministik dari reason code, evidence, status cakupan, dan aturan detektor; record dengan bukti tidak cukup dinyatakan tidak dinilai, bukan disimpulkan.
* **Kreativitas/AI sebagai pertimbangan:** bobot dan rubrik penilaian resmi tidak dipublikasikan; penilaian tim atas aspek AI adalah pertimbangan kompetitif internal, bukan penilaian resmi atas kriteria mana pun.
* **GenAI/LLM:** tidak ada pada RC dan tidak ada data (termasuk turunan sampel BPJS tanpa ID) yang dikirim ke LLM. Opsi pengembangan lanjutan hanya setelah ada kebutuhan yang jelas, persetujuan penggunaan data, serta evaluasi manfaat, keamanan, dan risikonya.

### 2.5 Istilah baku

| Istilah | Makna | UI (Inggris) |
|---|---|---|
| sinyal kandidat | hasil pemeriksaan yang perlu ditinjau manusia; bukan temuan | flagged / review lead |
| hasil audit terkonfirmasi | rekaman terpisah dari audit berwenang dengan rujukan | Authorized audit result |
| dinilai / tidak dinilai | pemeriksaan berjalan pada record / data wajib hilang atau pencarian tidak menjangkau | assessed / not assessed |
| tidak berlaku | sumber tidak mendukung pemeriksaan | not applicable |
| eksploratif | berjalan pada data nyata tetapi belum tervalidasi | exploratory |
| synthetic-only | hanya bermakna pada data sintetis | synthetic data only |
| rekomendasi provisional | usulan CIR, belum disahkan pemilik kebijakan | provisional |

## 3. Input dan semantik cakupan

Setiap pemeriksaan melaporkan per record: **ditandai**, **dinilai tidak ditandai**, **tidak dinilai** (dengan `unassessed_reason_counts`; jumlahnya = record tidak dinilai), atau **tidak berlaku**. Nol kandidat bukan kegagalan dan bukan ketiadaan risiko. Kontrak API: `docs/api-contracts.md`.

## 4. Workflow tinjauan dan taksonomi outcome

Run → hasil tersimpan (immutable; membuka run tidak menjalankan ulang) → cakupan dan alasan → antrean (filter, urutan, status tinjauan) → Case Review → status (`pending_review`, `in_review`, `awaiting_evidence`, `escalated`, `closed`) → outcome reviewer (`signal_supported`, `signal_not_supported`, `inconclusive`) → **hasil audit berwenang** terpisah (`confirmed_issue`, `confirmed_no_issue`, rujukan audit wajib, `review:manage`, append-only). Protokol pilot: `docs/audit-pilot-protocol.md`.

## 5. Instalasi dan operasi lokal

Backend: `backend/README.md` (Python ≥ 3.10, `pip install -r requirements.txt`, `uvicorn app.main:app`, bootstrap admin, konfigurasi FKRTL lokal lewat environment). Frontend: `frontend/README.md` (Node ≥ 18, `npm install`, `npm run dev` / `npm run build`).

## 6. Privasi dan keamanan

Data BPJS tetap di luar repository dan dibaca server-side dari path environment; identifier di-HMAC dengan kunci lokal; respons/UI tidak memuat nilai identifier mentah; catatan tinjauan dan rujukan audit divalidasi terhadap pola identifier (rujukan: deret ≥ 9 digit termasuk yang dipisah tanda baca, kata kunci rahasia, segmen > 20 karakter ditolak); rujukan audit disimpan sebagaimana diketik pengguna `review:manage` dan **tidak diverifikasi** ke sistem audit eksternal; output agregat di `backend/outputs/` (di-ignore Git); tidak ada ekspor per kasus.

## 7. Keterbatasan diketahui

* Tidak ada label fraud terverifikasi; tidak ada klaim akurasi pada data BPJS.
* Phantom hanya sintetis; obat/alkes di luar cakupan (tidak ada detektor).
* Pola Repeat tidak menunjukkan status ditagih/dibayar klaim sebelumnya.
* Angka proposal hlm. 14 dan 16 (mis. Precision@K 78%, 16 per 100 berkas) adalah dummy simulasi dan bukan hasil sistem ini.
* Similar-claim screening terpotong pada data nyata dan tidak dapat memisahkan klon dari klaim rutin.
* Ranking ML eksploratif; dalam evaluasi sintetis terpisah kalah dari sinyal transparan.
* Case Review hanya untuk kasus kandidat; tinjauan kontrol (tidak ditandai) dilakukan di luar aplikasi.
* Tidak ada penugasan (assignment) reviewer.
* Rujukan audit tidak diverifikasi ke sistem audit; trigger append-only dapat dilewati oleh pihak yang memiliki akses langsung ke file database; tidak ada rate limiting; rujukan terlihat oleh pengguna `review:read`.

## 8. Tes dan hasil terakhir (state kode final setelah closeout, 2026-10-26)

| Perintah | Hasil |
|---|---|
| `cd backend; .venv\Scripts\python -m pytest -q` | 342 passed (332 + 10 regresi keamanan closeout) |
| `cd frontend; npm run build` | exit 0 |
| `cd frontend; npx playwright test -c e2e/playwright.config.ts` | 4 passed, exit 0 (output lokal `backend/outputs/e2e/closeout-e2e-final.txt`) |
| Regresi target: `pytest tests/test_audit_confirmation.py tests/test_run_scoped_reviews.py tests/test_workbench_integration.py` | 39 passed |
| Pemeriksaan privasi (file sensitif ter-track, path absolut di source, pola identifier di dokumen) | bersih |

Smoke test FKRTL aktual lewat UI dijalankan ulang pada kode final (termasuk panel hasil audit); lihat §11.

## 9. Checklist penerimaan RC

Checklist ini adalah **kriteria penerimaan internal tim**. Menurut bukti yang tercatat (§8, §11), kriteria tersebut terpenuhi; ini bukan pernyataan bahwa CIR memenuhi standar penilaian Healthkathon. Penilaian kompetisi sepenuhnya menjadi wewenang juri.

| # | Kriteria | Status |
|---|---|---|
| A | Status kapabilitas semua detektor final | Lulus (§2) |
| B | Klaim produk sesuai bukti | Lulus (teks ML dikoreksi; label exploratory/synthetic-only) |
| C | Workflow run → tinjauan konsisten | Lulus (E2E) |
| D | Semantik missingness dan cakupan benar | Lulus (`test_workbench_integration`, `test_coverage_correctness`) |
| E | Isu kebenaran/privasi berdampak tinggi diselesaikan | Lulus |
| F | Dokumentasi dan instruksi sesuai sistem | Lulus |
| G | Tes state final lulus | Lulus (§8) |
| H | Workflow outcome audit dan protokol pilot | Lulus (panel hasil audit + protokol; pelaksanaan pilot = prasyarat eksternal) |
| I | Tidak ada model AI tak terdukung dipindahkan | Lulus |
| J | Perubahan lokal dan data dipertahankan, tanpa commit/push | Lulus |

## 10. Prasyarat operasional eksternal (bukan pekerjaan engineering)

Auditor berwenang dan pelaksanaan pilot; label hasil audit terverifikasi; persetujuan penggunaan data untuk tinjauan per kasus; konfirmasi makna FKL30 kosong dan semantik FKL47; ID fasilitas, bukti kehadiran/registrasi, riwayat pengajuan, dan data penyerahan obat bila modus terkait ingin divalidasi; infrastruktur produksi (hosting, TLS, manajemen kunci/secrets, backup, monitoring); persetujuan kebijakan ambang, lane, dan taksonomi outcome oleh pemilik proses; tinjauan keamanan independen.

## 11. Closeout RC (2026-10-26)

**Smoke FKRTL pada kode final** (sumber lokal, jendela FKL03; agregat saja, DB sementara dihapus):

| Jendela | Batas baris | Record dalam jendela | Durasi run / buka | Repeat (dinilai / tidak dinilai FKL30) | Similar-claim (dinilai / tidak dinilai, truncation) | Workflow |
|---|---|---|---|---|---|---|
| 2024-03-04..10 | 50.000 | 35.565 dari 1.699.219 baris dipindai | 38,2 s / 1,7 s | 20.296 / 15.269; 0 grup | 13.462 / 22.103 `not_reached_by_search`; terpotong | reviewer + hasil audit lulus |
| 2024-03-01..31 | 200.000 | 137.833 | 78,5 s / 1,9 s | 78.789 / 59.044; 1 grup | 35.006 / 102.827; terpotong | reviewer + hasil audit lulus; hasil run tidak berubah |

Jumlah alasan tidak dinilai = record tidak dinilai pada semua pemeriksaan; tidak ada identifier mentah di respons/UI.

**Kegagalan E2E historis:** satu run (tes 1–3 gagal, tes 4 lulus; tes 2–3 bergantung pada tes 1) setelah smoke Maret. Output run tersebut tidak tersimpan dan `.last-run.json` tertimpa, sehingga **penyebabnya tidak dapat ditelusuri**. Reproduksi pada kondisi yang sama (E2E langsung setelah smoke Maret, dengan trace) lulus 4/4; run final juga 4/4. Tidak ada asersi yang dilemahkan dan tidak ada retry ditambahkan. Status: **belum terjelaskan**.

**Tinjauan keamanan internal hasil audit** (bukan pentest/sign-off independen): `review:manage` + CSRF, prasyarat rekaman tinjauan, transaksi `BEGIN IMMEDIATE`, tabel aditif dengan CHECK dan trigger append-only, aktor dari sesi (`extra=forbid` menolak field pemalsuan aktor), rendering ter-escape — sesuai dan teruji. **Cacat ditemukan dan diperbaiki:** validator rujukan menerima deret digit yang dipisah tanda baca, kata kunci rahasia, dan token panjang; kini ditolak (`test_audit_confirmation.py`). Rujukan tidak diverifikasi eksternal — dinyatakan di UI dan dokumen.

**Gate kualitas (definisi tetap, 8 gate) saat closeout:** lulus G1 backend, G2 build, G3 E2E, G4 regresi target, G5 privasi, G6 smoke data nyata kode final = **6/8 (75%)**. Belum: G7 stabilitas E2E (kegagalan historis tidak terjelaskan), G8 tinjauan keamanan independen. Diperbarui di §12.

## 12. Penutupan gate kualitas (2026-10-26)

**G7 — stabilitas E2E saat ini.** Kriteria ditetapkan sebelum run: 10 run Playwright berturut-turut, semuanya lulus, retries dinonaktifkan (`--retries=0`), trace disimpan bila gagal, satu direktori artefak per run, berhenti pada kegagalan pertama tanpa menimpa artefak. Lingkungan: fixture sintetis dan DB sementara per run (`mkdtemp`), path FKRTL selalu diarahkan ke fixture sintetis.

| Run | Exit | Hasil | Retry |
|---|---|---|---|
| 01–10 | 0 (semua) | 4 passed per run (38,1–40,1 s); 0 unexpected, 0 flaky, 0 skipped | 0 |

Artefak lokal (di-ignore Git): `backend/outputs/e2e/qualification-2026-10-26/attempt-1/` (`summary.tsv`, `run-NN/output.txt`, `exit_code.txt`, `report.json`). **G7 lulus.** Penyebab kegagalan historis tetap **tidak diketahui**; kualifikasi ini tidak menjelaskan penyebab tersebut.

**G8 — tinjauan keamanan independen: BELUM.** Tinjauan internal selesai (temuan di `docs/security-review-package.md` §6); tidak ada bypass otorisasi/CSRF/pemalsuan pencatat ditemukan, tidak ada kode aplikasi yang diubah, dan dua tes regresi ditambahkan (jalur sesi endpoint hasil audit; rujukan tidak terbaca tanpa `review:read`). Paket tinjauan siap pakai; sign-off peninjau kosong.

**Tes setelah perubahan terakhir (dijalankan sesi ini):**

| Perintah | Hasil |
|---|---|
| `pytest -q` (backend penuh) | 344 passed |
| `pytest -q tests/test_audit_confirmation.py tests/test_run_scoped_reviews.py tests/test_workbench_integration.py` | 41 passed |
| `npm run build` | exit 0 |
| Playwright E2E, 10 run kualifikasi | 10/10 exit 0, 4 passed per run |

Perubahan sesudah kualifikasi hanya menambah file tes backend dan dokumen; kode aplikasi tidak berubah.

**Skor gate kualitas: 7/8 (87,5%).** Lulus G1–G7. G8 tertutup hanya setelah peninjau independen menyelesaikan tinjauan, temuan pemblokir rilis diselesaikan atau diterima formal oleh pemilik, dan verifikasi lanjutan lulus.

## 13. Kontrol keamanan tambahan dan persiapan demo (2026-10-26)

**Perubahan kode:**

* Rate limit per proses (`backend/app/security/rate_limit.py`): login per alamat klien dan per jumlah gagal per username, hasil audit dan penulisan review per pengguna; `429 RATE_LIMITED` + `Retry-After`. Kebijakan, konfigurasi, dan asumsi penerapan: `docs/api-contracts.md`. Tidak melindungi dari penyalahgunaan terdistribusi.
* Least privilege rujukan audit: rujukan, catatan audit, dan pencatat hanya untuk `review:manage`; peran lain melihat status hasil audit saja (`audit_details_visible: false`). Dipangkas di server; UI menampilkan keterangan pembatasan.
* Batas basis data didokumentasikan: trigger append-only tidak melindungi dari akses tulis langsung ke file; izin OS adalah kontrol utama (`docs/demo-deployment.md` §4).

**Tes setelah perubahan terakhir (dijalankan sesi ini):**

| Perintah | Hasil |
|---|---|
| `pytest -q` (backend penuh) | 353 passed |
| `pytest -q tests/test_rate_limit.py tests/test_audit_confirmation.py tests/test_run_scoped_reviews.py tests/test_workbench_integration.py tests/test_auth_rbac.py` | 64 passed |
| `npm run build` | exit 0 |
| Playwright E2E, satu run setelah perubahan (`--retries=0`) | 4 passed |
| Kualifikasi ulang 10 run (alur E2E berubah), `attempt-2` | 10/10 exit 0; 4 passed per run; 0 flaky, 0 retry |

Artefak: `backend/outputs/e2e/qualification-2026-10-26/attempt-2/` (lokal, di-ignore Git); `attempt-1` tetap disimpan.

**Persiapan demo:** `docs/demo-deployment.md` (topologi, konfigurasi/rahasia, izin file DB, backup, TLS, pembatasan akses, log, data sintetis, checklist smoke, rollback). Perintah pembuatan CSV sintetis diuji: 250 baris, 0 error validasi. Belum ada host demo yang dideploy.

**Skor gate kualitas tetap 7/8 (87,5%).** G8 (tinjauan keamanan independen) belum: paket `docs/security-review-package.md` diperbarui, sign-off kosong.
