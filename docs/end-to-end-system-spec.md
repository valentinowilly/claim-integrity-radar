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

**Implementasi aktual.** backend/app/main.py mendaftarkan health, analytics, dan review routers. backend/app/services/analytics.py membangun snapshot dari adapter 12 record artifisial, menjalankan enam detektor, scoring, dan priority. API tidak memanggil benchmark generator. Endpoint evaluation API mengembalikan insufficient_data. Evaluator offline berada di backend/app/analytics/evaluation.py dan evaluate_synthetic.py. Review workflow disimpan di SQLite lokal terpisah. Frontend memiliki halaman Overview, Analysis, Cases, Detail, Evaluation, serta review UI.

**Belum diimplementasikan.** Tidak ditemukan login/account provisioning/role enforcement, import batch, schema profile API, AnalysisRun tersimpan, status proses batch, persistensi snapshot analitik, atau review outcome auditor yang terpisah. API tidak menyediakan jalur hijau/kuning/merah dan risk_level tetap null. Metadata review bukan audit log keamanan dan bukan identitas pengguna terautentikasi.

## 3. Aktor dan user journey

**Fakta proposal — hlm. 6 dan 19.** Pengguna yang disebut adalah verifikator dan Tim Anti Kecurangan; auditor melakukan pemeriksaan dan manusia menentukan tindak lanjut. Proposal menyebut RBAC tetapi tidak menetapkan role, permission, onboarding, atau separation of duties.

**Implementasi aktual.** Autentikasi/kontrol akses tidak tersedia. Review API menerima request tanpa identitas terverifikasi; label demo_reviewer (unauthenticated) dibuat server.

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

**Implementasi aktual:** hanya alur kandidat → detail → review status yang berjalan pada fixture synthetic_demo. Auth, import, batch run, supervisor outcome, dan ekspor belum tersedia.

## 4. Empat kelompok proposal dan enam modul

**Fakta proposal — hlm. 4, 7, 11–13.** Empat sudut pemeriksaan adalah kapasitas, klaim kembar, pola waktu/pengulangan, dan kelengkapan bukti. Phantom billing dan cloning adalah modus/skenario; bukan kategori checker kelima/keenam.

| Kelompok proposal | Modul implementasi | Status aktual | Batas |
|---|---|---|---|
| Kewajaran kapasitas | capacity.py / synthetic_capacity_candidate | Aturan sintetis; runtime 12 klaim tidak memiliki metadata fasilitas sehingga not applicable. | Kapasitas simulasi bukan standar klinis/BPJS. |
| Klaim kembar/cloning | similar_claim_pattern.py exact match; near_duplicate_claims.py blocking dan pembandingan terbatas | Keduanya ada dalam run_detector_suite; merupakan dua modul terpisah. | Proposal menyebut MinHash/LSH (hlm. 11–12); implementasi near duplicate bukan MinHash/LSH. |
| Waktu/pengulangan | repeat_billing.py exact match; temporal_patterns.py | Berjalan bila prasyarat fitur dipenuhi; coverage parsial tetap dilaporkan. | Tanggal tidak sama dengan jam/menit. |
| Kelengkapan bukti | evidence_completeness.py | Checker berbasis fixture sintetis dengan inventaris/status pencatatan. | Tidak membuktikan layanan dilakukan atau tidak dilakukan. |

**Implementasi aktual.** risk_scoring.py memakai bobot awal sama (1) pada versi rule-risk-index-v1-provisional; satu indikator berkontribusi paling banyak sekali per klaim. Indeks ini bukan probabilitas fraud. audit_priority.py mengagregasi klaim terpicu per facility_id, menjumlah billed_amount valid per klaim unik, dan mengestimasi berkas (default satu per klaim, batas 20). Formula aktual adalah risk_score × known indicated claim value ÷ recommended record files. Satuan nilai adalah satuan billed_amount sintetis. Unit hanya dapat dibentuk jika facility_id ada; adapter runtime tidak memberi facility ID/metadata.

**Rekomendasi.** Jangan mengubah score menjadi risk_level atau action lane sebelum threshold/policy divalidasi dan disahkan. Bedakan triggered, not_triggered hanya pada scope selesai, not_applicable, not_assessed, partial, unavailable, dan truncation. Coverage hilang tidak boleh diperlakukan sebagai negatif.

## 5. Dimensi keluaran yang berbeda

| Dimensi | Makna | Implementasi |
|---|---|---|
| Sinyal indikator | Output detector, alasan dan coverage. | Ada di snapshot/API. |
| risk_score | Indeks aturan 0–1 atas checker yang dapat dinilai; bukan probabilitas. | Ada dan bisa null. |
| risk_level | Kategori kebijakan high/medium/low. | Selalu null; threshold belum ditetapkan. |
| Action lane | Rekomendasi proses hijau/kuning/merah. | Proposal saja; belum diimplementasikan. |
| review_status | Tahap pekerjaan: `pending_review`, `in_review`, `awaiting_evidence`, `escalated`, `closed` (target model). | API lama memakai `pending_review`, `needs_more_evidence`, `not_substantiated`, `escalated`; target model belum diimplementasikan. |
| review_outcome | Hasil substantif setelah tinjauan manusia, dipisahkan dari tahap pekerjaan. Kategori final harus disahkan pemilik proses. | Belum ada field outcome terpisah. |

**Catatan migrasi desain:** status legacy `not_substantiated` bermakna hasil, bukan tahap pekerjaan. Saat memigrasikan data demo, pertahankan history aslinya; petakan status saat ini ke `review_status=closed` dan `review_outcome=not_substantiated` hanya jika kebijakan outcome disetujui. Jangan melakukan migrasi otomatis tanpa tes dan rencana kompatibilitas API.

## 6. Impor dan profil sumber

**Fakta proposal — hlm. 11–12, 17–18.** Prototype menggunakan data sintetis. Produksi dibayangkan menggunakan klaim teranonimkan dengan izin resmi, adapter format, minimisasi, pseudonimisasi, kontrol akses, audit log, dan enkripsi. Proposal menyatakan arsitektur/skala besar masih rancangan dan belum diuji pada volume BPJS.

**Fakta panduan — hlm. 6–7, 18–25, 30–31.** Panduan menguraikan lima dataset sampel dan hubungan dataset serta kamus FKRTL dan diagnosis sekunder. Kamus bukan bukti file aktual lengkap, konsisten, boleh digabung, atau mencukupi detector.

**Implementasi aktual.** Belum ada importer, upload endpoint, DataBatch store, mapping registry, profiling endpoint, atau batch validation API.

**Rekomendasi kontrak import.**

1. DataBatch menyimpan ID internal, profil (synthetic_complete atau bpjs_fkrtl_sample_compatible), dataset role, sumber/otorisasi tercatat, periode, mapping version, digest terbatas akses, pembuat, waktu, jumlah agregat, validasi, dan status.
2. File sumber hanya di lokasi terkontrol/terenkripsi yang disetujui; bukan repository, log, response, atau review DB. Error per baris tidak mengembalikan identitas/nilai klaim; API hanya mengeluarkan agregat dan kode error.
3. Mapping sumber → canonical eksplisit dan berversi; catat rujukan kamus, parser, serta status konfirmasi. Nama kolom sendiri tidak membuktikan semantik.
4. Rekomendasi gate pengenalan FKRTL: FKL02 (visit key) dan FKL03 (tanggal datang), dengan validasi key/null/date. PSTV01 hanya untuk checker yang perlu membandingkan peserta; batasi dan tokenisasi sesuai tujuan. Field lain tidak wajib untuk menerima batch dasar; checker hanya berjalan saat semua prasyarat terpenuhi.
5. FKL05_NEW tidak tercantum pada kamus yang dibaca (panduan menyebut FKL05 sebagai provinsi). Panduan hlm. 25 menamai FKL47 sebagai biaya tagih provider dan FKL48 sebagai biaya verifikasi setelah verifikasi. Formula komponen FKL47 pada teks tampak sirkular; klarifikasi rumus, satuan, tipe, dan waktu ketersediaan diperlukan sebelum mapping.
6. Diagnosis sekunder adalah add-on; FKL02 join hanya setelah relasi/cardinality resmi dikonfirmasi. FKL24 bukan persyaratan FKRTL utama.

### State DataBatch — rekomendasi, bukan fitur aktual

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

## 7. AnalysisRun, versioning, persistensi

**Implementasi aktual.** GET routes memanggil service untuk menghitung ulang snapshot sintetis kecil pada setiap permintaan. Response punya generated_at dan versi scoring/priority, tetapi tidak punya run ID, run history, result store, atau link ke source batch. Evaluator offline menerima feature records dan ground truth secara terpisah; ini bukan endpoint evaluation runtime. Review SQLite menyimpan workflow terpisah dari sumber analitik.

**Rekomendasi.** AnalysisRun mereferensikan DataBatch ID/digest, schema mapping/canonicalization version, detector/config/threshold, scoring weights/version, priority/effort config, initiator, timestamps, status, coverage, dan output references. Satu DetectorRun per checker; hasil/group membership, reasons, scores dan facility priorities terkait run. Ground truth disimpan pada ruang eksperimen terpisah dan tidak tersedia untuk operational detector/API. Retry membuat run baru; hasil lama immutable. Endpoint pembacaan run harus mengambil snapshot tersimpan berdasarkan run ID; GET tidak boleh menjalankan ulang analisis tanpa menyatakan pembuatan run baru. Simpan status gagal/parsial dan coverage per checker; kandidat hasil run dan review harus memakai kunci run-scoped agar history tidak berpindah ke run lain.

~~~mermaid
stateDiagram-v2
  [*] --> queued
  queued --> running
  queued --> cancelled
  running --> completed
  running --> completed_with_warnings
  running --> failed
  running --> cancelled
~~~

Run yang `failed` bersifat terminal. Retry membuat AnalysisRun baru dengan `retry_of_run_id` yang menunjuk run gagal; jangan menghidupkan kembali atau menimpa hasil run lama. Run selesai tetap immutable. Jika ada run lebih baru, relasi `supersedes_run_id` atau penanda “versi terbaru” disimpan terpisah tanpa mengubah keluaran historis. `completed` berarti pekerjaan terkonfigurasi selesai dalam eligible scope, bukan akurasi/validasi. Not applicable, partial, unassessed, unavailable dan truncated tetap terpisah.

### Konsep domain dan penyimpanan MVP

Konsep yang harus dapat ditelusuri adalah akun/role, DataBatch, laporan validasi, versi mapping/profil, AnalysisRun, hasil/finding, skor/prioritas, Review, outcome, riwayat review, dan security audit event. **Daftar konsep ini bukan perintah membuat satu tabel database untuk setiap nama.** Untuk MVP lokal, role dapat berupa enum tetap pada akun; detail konfigurasi dan ringkasan hasil dapat disimpan sebagai JSON berversi pada run selama validasi schema dan ukuran payload diuji.

Skema penyimpanan MVP yang masuk akal: `UserAccount`, `DataBatch`, `AnalysisRun`, `CaseResult` (jika perlu pagination/filter query), `Review`, `ReviewHistoryEvent`, dan `SecurityAuditEvent`; validation report dan version/config manifest dapat berupa kolom/JSON pada `DataBatch`/`AnalysisRun` sebelum volume/kueri membenarkan normalisasi lebih lanjut. `BatchFile` dapat ditambahkan bila batch benar-benar mendukung beberapa file. Jangan membuat tabel `Role`, `Permission`, `DetectorRun`, `RiskLevelAssignment`, atau `ActionRecommendation` terpisah tanpa kebutuhan query, audit, dan lifecycle yang jelas.

Semua finding, score, priority, review, dan history harus terikat ke `analysis_run_id`; ID kasus harus stabil dalam satu run. Jangan menyimpan salinan row sumber yang berisi data sensitif di tabel review.

**Gap aktual:** case IDs seperti syn-pattern-001 stabil pada fixture tetap. SQLite saat ini menggunakan case_id; jika dataset/run berubah dan ID dipakai ulang, history dapat terhubung ke temuan berbeda. Gunakan run-scoped case key sebelum batch nyata.

## 8. API dan batas kontrak

**Implementasi aktual.** docs/api-contracts.md mencakup GET /health; dashboard summary; analysis; cases (filter/sort/page); case detail; evaluation; review GET/POST. Belum ada auth, import/profile/batch/run/status/outcome/export/security audit API. Error terstruktur. Health tidak menginisialisasi review SQLite.

**Rekomendasi.** Pertahankan kontrak pembacaan untuk prototipe. API mendatang perlu session/account, schema profile, batch, run, run-specific results, dan coverage/provenance. Review writes harus menggunakan authenticated subject yang ditetapkan server. Review outcome perlu endpoint terpisah setelah kebijakan disetujui.

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
