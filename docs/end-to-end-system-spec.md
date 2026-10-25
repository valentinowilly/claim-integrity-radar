# Spesifikasi Sistem End-to-End Claim Integrity Radar

**Status:** spesifikasi untuk ditinjau; belum menjadi kontrak implementasi baru.
**Batas:** prototipe saat ini memakai sumber synthetic_demo. Profil BPJS FKRTL di sini adalah rancangan kompatibilitas dari panduan, bukan validasi pada file data.

## 1. Kategori sumber kebenaran

- **Fakta proposal:** rancangan/angka yang tertulis di proposal; angka pada slide dummy tetap ilustrasi.
- **Fakta panduan:** definisi yang tertulis di panduan sample. Kamus tidak membuktikan seluruh file/observasi berisi kolom dengan kualitas seragam.
- **Implementasi aktual:** perilaku yang dapat diperiksa di source atau tes.
- **Rekomendasi:** rancangan baru untuk dibahas, bukan fitur yang sudah ada.
- **Perlu konfirmasi:** keputusan yang memerlukan BPJS, pemilik data, verifikator, auditor, ahli klinis/koder, atau keamanan.

PDF yang diperiksa: proposal-healthkathon.pdf (20 halaman) dan panduan-data-sample-bpjs.pdf (31 halaman). Teks layout diekstrak lokal; tabel FKRTL diekstrak dengan mode table. proposal-page14.png tidak ditemukan di lokasi referensi maupun root/docs repository. Angka halaman 14 di bawah berasal dari transkripsi visual pengguna, bukan verifikasi PNG independen.

## 2. Positioning dan kematangan

**Fakta proposal — hlm. 2, 6–13, 17–19.** Radar diposisikan sebagai alat bantu verifikator dan Tim Anti Kecurangan: mencari sinyal, menjelaskan alasan, dan membantu menentukan berkas yang diperiksa. Keputusan akhir tetap di tangan manusia. Proposal menjabarkan empat kelompok pemeriksa, jalur hijau/kuning/merah, prioritas berdasarkan risiko/nilai/usaha, RBAC sebagai rancangan, serta validasi/pilot sebagai fase mendatang. Proposal hlm. 13 menyebut pengujian internal menggunakan data sintetis dan belum ada pilot atau pengguna nyata.

**Fakta proposal — hlm. 14, transkripsi visual pengguna.** Setup ilustratif: 200 faskes sintetis, 120.000 klaim, Januari–Desember 2024, injeksi sintetis 3–5%, lima skenario. Metode yang ditampilkan: audit acak, satu aturan sederhana, dan gabungan Radar. Angka Precision@K 20/45/78%, Recall Fraud 20/45/75%, fraud per 100 berkas 4/9/16, klaim sah tetap hijau 95/88/92%, dan klaim sah ke kuning/merah 5/12/8% diberi label dummy simulasi; slide menyatakan hasil kuantitatif belum tersedia dan belum divalidasi pada data riil. Angka itu bukan hasil terukur, target kinerja, baseline wajib, atau acceptance threshold.

**Implementasi aktual setelah P0 Stage 7 dan provider/run integration.** `backend/app/main.py` mendaftarkan health, auth, synthetic batch, runs, analytics, legacy review, dan run-scoped review routers. Route analytics lama tetap menghitung snapshot adapter `synthetic_demo`; `POST /api/v1/runs` memilih provider `SyntheticBatchProvider` dari batch synthetic CSV yang dipatok dan memanggil `execute_provider_snapshot` sekali melalui canonical feature contract. Run menyimpan source type/classification deklaratif, schema profile, mapping version, coverage per indikator, konfigurasi, serta snapshot hasil dan reason. GET run hanya membaca snapshot tersimpan. `source_type` yang belum didukung ditolak; tidak ada fallback provider. Run-scoped review/outcome disimpan terpisah dari snapshot; review lama tetap berada di database legacy. Evaluasi API tetap `insufficient_data`; evaluator offline terpisah. UI Data Klaim menampilkan klasifikasi sumber dan versi mapping. Klaim `synthetic_only_declared` berasal dari deklarasi importer, bukan validasi independen isi file.

**Belum diimplementasikan setelah P0 Stage 6.** Schema profile/API untuk sumber BPJS dan UI batch/run/review run-scoped belum tersedia. `risk_level` tetap null; action lane hanya policy demo dalam snapshot AnalysisRun dan tidak terintegrasi dengan UI. CSV DataBatch hanya pertukaran sintetis lokal; deklarasi `synthetic_only` tidak memverifikasi independen provenance konten.

## 3. Aktor dan user journey

**Fakta proposal — hlm. 6 dan 19.** Pengguna yang disebut adalah verifikator dan Tim Anti Kecurangan; auditor melakukan pemeriksaan dan manusia menentukan tindak lanjut. Proposal menyebut RBAC tetapi tidak menetapkan role, permission, onboarding, atau separation of duties.

**Implementasi aktual setelah P0 Stage 2?4.** Auth cookie/session dan RBAC backend tersedia sebagai baseline prototype; review/import/run actor berasal dari principal tervalidasi. DataBatch dan run read/write memakai permission terpisah; hasil run hanya dapat dibaca verifikator/audit lead, sedangkan operator dapat membuat run dan membaca metadata/status. Role dan akses batch/run masih shared-synthetic tanpa assignment; ini bukan kebijakan akses operasional.

**Rekomendasi untuk MVP.** Gunakan empat role operasional pada `docs/role-permission-matrix.md`: `platform_admin`, `data_operator`, `verifikator`, dan `audit_lead`. Operator mencakup impor/validasi serta memulai run; jangan membuat `analyst`, `data_steward`, `review_supervisor`, `read_only_auditor`, atau `evaluation_steward` sebagai role aplikasi terpisah sebelum ada kebutuhan dan approval organisasi. Akses baca-saja adalah kombinasi permission, sedangkan evaluasi ground truth tetap offline/terisolasi. Tidak ada registrasi publik. Akses data BPJS tetap diblokir sampai otorisasi, mapping, dan kontrol data disetujui.

~~~mermaid
flowchart TD
  A[Admin mengundang akun dan menetapkan role] --> B[Pengguna login]
  B --> C[Operator memilih profil dan membuat DataBatch]
  C --> D[Validasi format, skema, kualitas, otorisasi, periode]
  D -->|Gagal| E[Batch ditolak dengan error agregat aman]
  D -->|Lulus/peringatan diterima| F[Batch tervalidasi dan dibekukan]
  F --> G[Operator berizin membuat AnalysisRun dengan versi aturan]
  G --> H[Enam pemeriksa; status cakupan dicatat]
  H --> I[Risk score bila dapat dinilai]
  I --> J[Risk level/action lane hanya jika disahkan]
  J --> K[Prioritas audit dan alasan beserta cakupan]
  K --> L[Reviewer membuka kandidat sesuai izin]
  L --> M[Verifikator menulis status proses dan catatan]
  M --> N[Audit lead mencatat outcome manusia terpisah]
  N --> O[Riwayat dan audit keamanan sesuai kebijakan]
~~~

**Implementasi aktual:** alur login, akses RBAC, kandidat → detail → review status pada fixture synthetic_demo, serta import/list/detail metadata batch CSV sintetis tersedia. Batch belum memulai run dan belum menggantikan synthetic_demo pada analytics. Supervisor outcome, AnalysisRun, dan ekspor batch belum tersedia.

## 4. Empat kelompok proposal dan enam modul

**Fakta proposal — hlm. 4, 7, 11–13.** Empat sudut pemeriksaan adalah kapasitas, klaim kembar, pola waktu/pengulangan, dan kelengkapan bukti. Phantom billing dan cloning adalah modus/skenario; bukan kategori checker kelima/keenam.

| Kelompok proposal | Modul implementasi | Status aktual | Batas |
|---|---|---|---|
| Kewajaran kapasitas | capacity.py / synthetic_capacity_candidate | Aturan sintetis; runtime 12 klaim tidak memiliki metadata fasilitas sehingga not applicable. | Kapasitas simulasi bukan standar klinis/BPJS. |
| Klaim kembar/cloning | similar_claim_pattern.py exact match; near_duplicate_claims.py blocking dan pembandingan terbatas | Keduanya ada dalam run_detector_suite; merupakan dua modul terpisah. | Proposal menyebut MinHash/LSH (hlm. 11–12); implementasi near duplicate bukan MinHash/LSH. |
| Waktu/pengulangan | repeat_billing.py exact match; temporal_patterns.py | Berjalan bila prasyarat fitur dipenuhi; coverage parsial tetap dilaporkan. | Tanggal tidak sama dengan jam/menit. |
| Kelengkapan bukti | evidence_completeness.py | Checker berbasis fixture sintetis dengan inventaris/status pencatatan. | Tidak membuktikan layanan dilakukan atau tidak dilakukan. |

**Implementasi aktual setelah P0 Stage 5.** `risk_scoring.py` mempertahankan bobot awal sama (1) pada versi `rule-risk-index-v1-provisional`; satu indikator berkontribusi paling banyak sekali per klaim. Indeks ini bukan probabilitas fraud. `audit_priority.py` mengagregasi klaim terpicu per `facility_id`, menjumlah `billed_amount` valid per klaim unik, dan mengestimasi berkas (default satu per klaim, batas 20). Formula tetap `risk_score × known indicated claim value ÷ recommended record files`. Prioritas hanya diberi indeks jika semua nilai klaim terindikasi valid, skor dan coverage unit dapat dinilai lengkap, keanggotaan grup tidak terpotong, facility ID tersedia, dan usaha positif; selain itu indeks null dengan alasan. `not_applicable` tidak menghalangi bila pemeriksaan relevan lain lengkap. Satuan nilai hanya satuan sintetis; FKL47 dan unit resmi belum disahkan. Adapter runtime tidak memberi facility ID/metadata.

`risk_level` tetap null. `backend/app/analytics/action_policy.py` kini menyediakan policy terpisah `action-policy-demo-v1-provisional` untuk kandidat kasus dalam AnalysisRun. Rentang skor 0–1 dibagi sama besar: `green <= 1/3`, `yellow <= 2/3` setelah batas hijau, dan `red > 2/3`. Batas itu konfigurasi demo sementara, bukan threshold operasional atau hasil kalibrasi. Skor null/parsial, cakupan kasus tak lengkap, indikator relevan unavailable, atau pencarian relevan truncated menghasilkan `cannot_recommend`; `not_applicable` sendiri diabaikan. Policy result dan konfigurasi disimpan dalam snapshot run immutable. `action_lane` bukan `risk_level`, prioritas fasilitas, review status/outcome, probabilitas fraud, atau keputusan pelanggaran. Request run dapat memilih versi server-side yang terdaftar; perubahan konfigurasi perlu versi baru. Identifier `detector-suite-v1-manual` dipelihara manual dan bukan hash source/build.

## 5. Dimensi keluaran yang berbeda

| Dimensi | Makna | Implementasi |
|---|---|---|
| Sinyal indikator | Output detector, alasan dan coverage. | Ada di snapshot/API. |
| risk_score | Indeks aturan 0–1 atas checker yang dapat dinilai; bukan probabilitas. | Ada dan bisa null. |
| risk_level | Kategori kebijakan high/medium/low. | Selalu null; threshold belum ditetapkan. |
| Action lane | Saran proses demo yang terpisah dari skor, risk level dan review. | Diimplementasikan hanya dalam AnalysisRun melalui policy provisional berversi; UI belum mengintegrasikannya. |
| review_status | Tahap pekerjaan run-scoped: `pending_review`, `in_review`, `awaiting_evidence`, `escalated`, `closed`. | Diimplementasikan pada P0 Stage 6; API legacy tetap menggunakan enum lama dan tidak dimigrasikan. |
| review_outcome | Hasil substantif setelah tinjauan manusia, terpisah dari tahap pekerjaan, skor, lane, dan sinyal. | Field run-scoped nullable; kosakata sementara `signal_supported`, `signal_not_supported`, `inconclusive`, belum disahkan pemilik proses. Dicatat eksplisit oleh `audit_lead`, tidak diinferensikan. |

**Kompatibilitas:** API legacy mempertahankan `not_substantiated` sebagai status lama. P0 Stage 6 menambahkan tabel run-scoped yang tidak memigrasikan baris/history legacy. Status awal run-scoped adalah `pending_review`; outcome null. Tidak ada mapping otomatis dari `not_substantiated` ke status baru/outcome.

## 6. Impor dan profil sumber

**Fakta proposal — hlm. 11–12, 17–18.** Prototype menggunakan data sintetis. Produksi dibayangkan menggunakan klaim teranonimkan dengan izin resmi, adapter format, minimisasi, pseudonimisasi, kontrol akses, audit log, dan enkripsi. Proposal menyatakan arsitektur/skala besar masih rancangan dan belum diuji pada volume BPJS.

**Fakta panduan — hlm. 6–7, 18–25, 30–31.** Panduan menguraikan lima dataset sampel dan hubungan dataset serta kamus FKRTL dan diagnosis sekunder. Kamus bukan bukti file aktual lengkap, konsisten, boleh digabung, atau mencukupi detector.

**Implementasi aktual setelah P0 Stage 4.** Backend menyediakan `synthetic-claims-v1` CSV exporter/parser, validasi sintetis agregat, DataBatch SQLite immutable, dan endpoint metadata/import. AnalysisRun dapat dijalankan hanya dari batch sintetis siap. Tidak ada schema profile BPJS, mapping BPJS, atau pembacaan `.dta`. Versi skema/mapping yang diterima hanya versi sintetis yang disebut dalam kontrak API.

**Rekomendasi kontrak import.**

1. DataBatch menyimpan ID internal, profil (synthetic_complete atau bpjs_fkrtl_sample_compatible), dataset role, sumber/otorisasi tercatat, periode, mapping version, digest terbatas akses, pembuat, waktu, jumlah agregat, validasi, dan status.
2. File sumber hanya di lokasi terkontrol/terenkripsi yang disetujui; bukan repository, log, response, atau review DB. Error per baris tidak mengembalikan identitas/nilai klaim; API hanya mengeluarkan agregat dan kode error.
3. Mapping sumber → canonical eksplisit dan berversi; catat rujukan kamus, parser, serta status konfirmasi. Nama kolom sendiri tidak membuktikan semantik.
4. Rekomendasi gate pengenalan FKRTL: FKL02 (visit key) dan FKL03 (tanggal datang), dengan validasi key/null/date. PSTV01 hanya untuk checker yang perlu membandingkan peserta; batasi dan tokenisasi sesuai tujuan. Field lain tidak wajib untuk menerima batch dasar; checker hanya berjalan saat semua prasyarat terpenuhi.
5. FKL05_NEW tidak tercantum pada kamus yang dibaca (panduan menyebut FKL05 sebagai provinsi). Panduan hlm. 25 menamai FKL47 sebagai biaya tagih provider dan FKL48 sebagai biaya verifikasi setelah verifikasi. Formula komponen FKL47 pada teks tampak sirkular; klarifikasi rumus, satuan, tipe, dan waktu ketersediaan diperlukan sebelum mapping.
6. Diagnosis sekunder adalah add-on; FKL02 join hanya setelah relasi/cardinality resmi dikonfirmasi. FKL24 bukan persyaratan FKRTL utama.

### State DataBatch

Prototype importer mengimplementasikan status `rejected`, `ready`, dan `ready_with_warnings`. Validasi format/isi yang gagal tersimpan sebagai batch `rejected` tanpa record anak parsial; penghilangan kolom opsional memberi warning. Versi ready immutable. Kontrol ini hanya untuk profil CSV sintetis v1, bukan lifecycle BPJS. Status `created`, `validating`, `archived`, dan expiry pada diagram berikut masih rekomendasi bagi fase lanjutan.

~~~mermaid
stateDiagram-v2
  [*] --> created
  created --> validating
  validating --> rejected: format/schema/authorization gagal
  validating --> ready: semua gate wajib lulus
  validating --> ready_with_warnings: gate wajib lulus, warning non-blocking tercatat
  ready --> archived
  ready_with_warnings --> archived
  rejected --> expired_or_deleted: sesuai retention dan referential checks
  archived --> expired_or_deleted: sesuai retention dan referential checks
~~~

`ready` dan `ready_with_warnings` adalah versi batch yang telah dibekukan. Satu versi batch dapat menjadi sumber lebih dari satu AnalysisRun; memulai run tidak mengubah status batch menjadi terkunci. Perubahan isi atau mapping menghasilkan versi batch baru. Penghapusan ditolak selama ada run/review yang masih mereferensikan batch, kecuali kebijakan retensi/erasure yang disetujui menangani dependensi terkait.

Untuk implementasi saat ini, `created` dan `validating` hanya fase sinkron dalam request, bukan status persisted; tabel menyimpan terminal `rejected`, `ready`, atau `ready_with_warnings`. `archived`/expiry dan penghapusan mengikuti diagram rekomendasi dan belum diimplementasikan. Import identik pada `batch_key`, checksum, schema version, dan mapping version mengembalikan versi tersimpan; perubahan salah satu komponen membuat ID/version baru. Batch key adalah label dataset sintetis yang operator tetapkan, bukan identitas peserta atau klaim.

## 7. AnalysisRun, versioning, persistensi

**Implementasi aktual setelah P0 Stage 5.** Route dashboard/analysis/cases yang lama tetap menghitung snapshot `synthetic_demo`. Route `POST /api/v1/runs` menjalankan pipeline koordinasi yang sama atas record fitur hasil adapter DataBatch sintetis dan menyimpan snapshot termasuk scoring, audit priority, serta action policy. GET run mengambil manifest dan hasil tersimpan tanpa menjalankan ulang pipeline. Manifest mengunci `batch_id`, versi, checksum, schema dan mapping; mencatat versi scoring, priority, detector suite manual, serta action policy dan configuration snapshot. Ground truth tidak diimpor oleh CSV dan tidak diteruskan ke pipeline. Policy config disimpan immutable per identifier; konflik config untuk versi yang sama ditolak. Manifest, result, policy registry, dan security events berada pada SQLite batch yang sama (`CIR_BATCH_DB_PATH`); tabel ditambahkan tanpa reset tabel batch/auth/review. Auth/review database tetap tidak disentuh oleh run storage.

Run sinkron merekam `running` terlebih dahulu, lalu status terminal `completed`, `partial`, atau `failed`. `not_applicable` sendiri tidak membuat run parsial/gagal. Run gagal terminal; retry hanya untuk `failed` dan membuat run baru dengan `retry_of_run_id` serta batch version/checksum identik. Retry tanpa pemilihan policy baru mewarisi versi/config policy asal. Trigger SQLite melindungi manifest/result terminal. Kegagalan exception hanya menyimpan kategori aman; hasil all-detectors-unavailable dapat tersimpan sebagai diagnostik berstatus failed. Proses yang terputus meninggalkan status `running`; recovery otomatis belum ada. Hasil menghapus token peserta dan atribut token dari penjelasan, tidak menyimpan row mentah atau label eksperimen. Untuk demo sintetis, `platform_admin` memiliki permission operasional penuh; `data_operator` tetap dapat menulis batch/run dan membaca metadata tetapi tidak hasil; verifikator/audit lead dapat membaca hasil; outcome memerlukan `review:manage` yang dimiliki audit lead dan Admin. Akses hasil dan batch masih `shared_synthetic`, tanpa assignment scope. Review run-scoped memerlukan run `completed`/`partial` dengan result tersimpan dan kandidat `case_id` yang cocok; status/outcome dan security events tidak mengubah snapshot. Frontend workspace persisted-run tersedia; akses Admin ini asumsi demo, bukan role policy yang disahkan atau izin untuk data BPJS.

~~~mermaid
stateDiagram-v2
  [*] --> running: manifest committed before synchronous execution
  running --> completed: all assessed pipeline checks terminal
  running --> partial: material coverage incomplete/unavailable/truncated
  running --> failed: fatal error or all detectors unavailable
  completed --> [*]
  partial --> [*]
  failed --> [*]
~~~

Retry membuat entitas AnalysisRun baru berstatus `running` dengan `retry_of_run_id`; state terminal run gagal tidak dibuka kembali.

Run yang `failed` bersifat terminal. Retry membuat AnalysisRun baru dengan `retry_of_run_id` yang menunjuk run gagal; jangan menghidupkan kembali atau menimpa hasil run lama. Run selesai tetap immutable. Jika ada run lebih baru, relasi `supersedes_run_id` atau penanda “versi terbaru” disimpan terpisah tanpa mengubah keluaran historis. `completed` berarti pekerjaan terkonfigurasi selesai dalam eligible scope, bukan akurasi/validasi. Not applicable, partial, unassessed, unavailable dan truncated tetap terpisah.

### Konsep domain dan penyimpanan MVP

Konsep yang harus dapat ditelusuri adalah akun/role, DataBatch, laporan validasi, versi mapping/profil, AnalysisRun, hasil/finding, skor/prioritas, Review, outcome, riwayat review, dan security audit event. **Daftar konsep ini bukan perintah membuat satu tabel database untuk setiap nama.** Untuk MVP lokal, role dapat berupa enum tetap pada akun; detail konfigurasi dan ringkasan hasil dapat disimpan sebagai JSON berversi pada run selama validasi schema dan ukuran payload diuji.

Skema penyimpanan MVP yang masuk akal: `UserAccount`, `DataBatch`, `AnalysisRun`, `CaseResult` (jika perlu pagination/filter query), `Review`, `ReviewHistoryEvent`, dan `SecurityAuditEvent`; validation report dan version/config manifest dapat berupa kolom/JSON pada `DataBatch`/`AnalysisRun` sebelum volume/kueri membenarkan normalisasi lebih lanjut. `BatchFile` dapat ditambahkan bila batch benar-benar mendukung beberapa file. Jangan membuat tabel `Role`, `Permission`, `DetectorRun`, `RiskLevelAssignment`, atau `ActionRecommendation` terpisah tanpa kebutuhan query, audit, dan lifecycle yang jelas.

Semua finding, score, priority, review, dan history harus terikat ke `analysis_run_id`; ID kasus harus stabil dalam satu run. Jangan menyimpan salinan row sumber yang berisi data sensitif di tabel review.

**Gap aktual:** case IDs seperti syn-pattern-001 stabil pada fixture tetap. SQLite saat ini menggunakan case_id; jika dataset/run berubah dan ID dipakai ulang, history dapat terhubung ke temuan berbeda. Gunakan run-scoped case key sebelum batch nyata.

## 8. API dan batas kontrak

**Implementasi aktual setelah P0 Stage 4.** `docs/api-contracts.md` mencakup health, dashboard, analysis, cases, case detail, evaluation, review, auth/provisioning, DataBatch sintetis, dan AnalysisRun (`POST/GET /api/v1/runs`). Tidak ada profile BPJS atau ekspor batch API. Error terstruktur; health tidak menginisialisasi auth, review, batch, atau run database.

**P0 Stage 6 aktual.** `GET /api/v1/runs/{run_id}/cases/{case_id}/review`, `PATCH` pada path yang sama untuk status, dan `POST .../review/outcome` untuk outcome terpisah memvalidasi kandidat dari result run tersimpan. GET tidak membuat state; mutasi menambah history event dan security audit event yang berbeda. Review tables berada pada SQLite batch/run (`CIR_BATCH_DB_PATH`); legacy review DB dan semantik endpoint lamanya tidak diubah. Outcome taxonomy dan RBAC masih asumsi prototipe; assignment scope belum tersedia.

**Pekerjaan tersisa.** UI belum terhubung ke endpoint run-scoped. Browser E2E belum diverifikasi. Pemetaan status legacy tidak dilakukan; jika diperlukan kelak, harus melalui desain migrasi dan tes eksplisit. Profil BPJS hanya setelah hard gate otorisasi/mapping/privacy dipenuhi.

## 9. Dua profil data

Detail kompatibilitas kolom ada di docs/bpjs-sample-compatibility.md.

| Aspek | Demo Sintetis Lengkap | BPJS FKRTL Sample-Compatible |
|---|---|---|
| ID | ID klaim, token peserta, facility ID dibuat artifisial. | Panduan menyebut FKL02 visit ID dan PSTV01 participant number terdeidentifikasi; tetap batasi/re-tokenisasi. |
| Fasilitas | Benchmark generator punya facility ID/capacity buatan; API runtime tidak. | ID fasilitas unik, staff, equipment, capacity tidak terbukti pada kamus yang ditinjau. |
| Waktu | Benchmark memiliki timestamp/date sintetis; runtime hanya date. | Tanggal datang/pulang, tidak ada jam/menit di kamus. |
| Bukti | Evidence inventory/status sintetis. | Inventaris dokumen/bukti tidak ditemukan pada kamus yang ditinjau. |
| Detector | Enam modul dapat diuji sesuai prasyarat; hasil dapat partial. | Capacity tidak dapat dinilai; repeat/similarity/near-duplicate conditional pada mapping dan prasyarat; temporal saat ini tidak dapat dinilai karena aturan memerlukan facility ID/service type dan pola menit memerlukan timestamp; evidence tidak dapat dinilai. |
| Scoring/priority | Scoring sintetis berjalan; facility priority memerlukan facility metadata. | Tanpa facility ID valid tidak ada prioritas/ranking tingkat fasilitas. Kandidat kunjungan dapat disajikan terpisah tanpa mengklaim ranking fasilitas. |
| Evaluation | Evaluator offline dengan ground truth terpisah. | Tidak ada claim performa riil tanpa outcome acuan dan protokol berizin. |

## 10. Roadmap

- **P0 — Functional synthetic E2E:** autentikasi/RBAC dasar, DataBatch dan validasi, AnalysisRun persisten, hasil run-scoped, policy action lane demo yang eksplisit/provisional/berversi, review dengan aktor terautentikasi, serta tes UI/API dari login sampai review. P0 tidak mengizinkan pemrosesan sampel BPJS hanya karena alur sintetik sudah jalan.
- **Hard gate sebelum profil BPJS sample-compatible:** otorisasi penggunaan, tujuan dan lingkungan pemrosesan, mapping/version skema yang disetujui, semantik/validasi field biaya, persetujuan join, perlindungan identitas, retensi/penghapusan, logging aman, dan kontrol akses yang memadai. Gate ini dapat tetap tertutup saat MVP sintetik dikembangkan.
- **P1 — Observability and workflow hardening:** assignment kasus, riwayat beberapa run, notifikasi, ekspor terkontrol, recovery/retention operasional, serta pemisahan tambahan untuk role bila kebutuhan organisasi terbukti.
- **P2 — Decision support tervalidasi/produksi:** persetujuan pakar terhadap aturan/threshold, action policy untuk penggunaan nyata, pilot berizin, bias/false-positive review, evaluasi dengan label acuan yang sesuai, pengujian skala, deployment dan dukungan operasional.

## 11. Rujukan

- Proposal hlm. 2 positioning; hlm. 4 modus dan catatan periode; hlm. 6–10 solusi, checker, action lane, formula/effort; hlm. 11–12 data/algoritma/skenario/privacy; hlm. 13 status prototype; hlm. 14 transkripsi visual pengguna (dummy/unverified); hlm. 16 angka ilustratif; hlm. 17–19 fase, skala dan etika.
- Panduan hlm. 6–7 hubungan datasets; hlm. 18–25 FKRTL; hlm. 30–31 secondary diagnosis.
- Repository: AGENTS.md, docs/api-contracts.md, analytics-spec.md, synthetic-data-spec.md, evaluation-spec.md; backend/app/main.py, services, api, schemas, analytics, data_sources, tests; frontend/src/App.tsx, api/client.ts, pages dan README.
