# Kontrak API Awal

Dokumen ini menetapkan kontrak awal untuk frontend dan backend Claim Integrity Radar. Semua contoh JSON di bawah adalah **ilustrasi kontrak**, bukan hasil analisis nyata, bukan data BPJS, dan bukan metrik demo. Implementasi harus mengambil angka dari sumber data yang dinyatakan dalam respons; jika belum tersedia, gunakan status ketersediaan yang sesuai.

## Ketentuan umum

- Prefix API versi: `/api/v1`; health check berada di `/health`.
- Tanggal dan waktu menggunakan ISO 8601. Waktu menyertakan zona waktu bila tersedia.
- `data_source.kind` bernilai `synthetic`, `local`, atau `none`. `label` menjelaskan sumber secara aman dan tidak memuat path lokal atau identitas sensitif.
- Implementasi demo tahap integrasi menggunakan `data_source: {"kind":"synthetic","label":"synthetic_demo"}`. Semua angka pada respons bertanda ini dihitung dari record artifisial runtime, bukan dataset BPJS.
- `availability` bernilai `available`, `not_configured`, `insufficient_data`, atau `unavailable`. `available` hanya boleh dipakai bila hasil memang dihitung dari sumber yang terhubung.
- Respons yang menjalankan pipeline (`dashboard/summary`, `analysis`, `cases`, dan detail kasus) juga membawa `execution_status`: `completed`, `partial`, atau `failed`. Ini terpisah dari `availability` (ketersediaan sumber/hasil), coverage tiap detektor, dan hasil deteksi per kasus. `failed` berarti semua pemeriksaan tidak tersedia; satu atau lebih pemeriksaan parsial/tidak tersedia menghasilkan `partial`.
- Nilai agregat boleh `null` bila belum dapat dihitung. Jangan mengganti nilai yang tidak tersedia dengan nol.
- Kasus adalah kandidat peninjauan. Indikator risiko bukan bukti fraud dan tidak menggantikan keputusan auditor.
- Kode indikator aktif saat ini: `repeat_billing_candidate`, `similar_claim_pattern_candidate`, `near_duplicate_claim_candidate`, `synthetic_capacity_candidate`, `temporal_pattern_candidate`, dan `supporting_evidence_completeness_candidate`.
- Respons tidak boleh mengekspos baris mentah, identitas peserta, token/hash identitas, atau fingerprint internal.

## Format error

Error memakai bentuk konsisten berikut. `request_id` membantu penelusuran log tanpa memasukkan data sensitif. Payload tidak valid menghasilkan HTTP `422` dengan `code: INVALID_PAYLOAD`; detail hanya berisi lokasi dan sebab validasi, tanpa menggemakan nilai input.

```json
{
  "error": {
    "code": "INVALID_FILTER",
    "message": "Parameter risk_level tidak dikenal.",
    "request_id": "req_example_01",
    "details": {"parameter": "risk_level"}
  }
}
```

Status HTTP yang disarankan: `400` parameter tidak valid, `404` kasus tidak ditemukan, `422` parameter valid secara sintaks tetapi tidak dapat diproses, `500` kesalahan internal, dan `503` layanan atau sumber data sementara tidak tersedia. Jangan mengirim stack trace atau nilai data sensitif pada `message` maupun `details`.

## `GET /health`

Tidak menerima parameter. Endpoint ini memeriksa proses aplikasi saja dan **tidak** membuka dataset.

```json
{
  "status": "ok",
  "service": "claim-integrity-radar-api",
  "version": "0.1.0"
}
```

`200` menunjukkan aplikasi merespons; bukan jaminan bahwa sumber data/analitik tersedia. Bila proses tidak dapat merespons, gunakan kegagalan koneksi atau `503`.

## `GET /api/v1/dashboard/summary`

Parameter query opsional: `period_from`, `period_to` (tanggal ISO `YYYY-MM-DD`). Tolak rentang terbalik dengan `400`. Filter periode diterapkan konsisten pada seluruh agregat.

```json
{
  "availability": "not_configured",
  "data_source": {"kind": "none", "label": null},
  "generated_at": null,
  "period": {"from": null, "to": null},
  "summary": {
    "claims_reviewed": null,
    "cases_in_queue": null,
    "risk_level_counts": {"high": null, "medium": null, "low": null},
    "indicator_counts": []
  },
  "notice": "Belum ada sumber data terkonfigurasi; tidak ada metrik yang dihitung."
}
```

`summary` berisi agregat terhitung saja. Pada respons yang tersedia, `claims_reviewed` berarti jumlah record sumber yang diproses, sedangkan `cases_in_queue` berarti jumlah case ID unik yang muncul pada sedikitnya satu kelompok kandidat. Setiap `indicator_counts` memiliki `indicator`, `candidate_groups`, dan `candidate_records` (case ID unik untuk indikator tersebut). Jangan menampilkan metrik sintetis sebagai temuan nyata; UI wajib menandai data sintetis dengan jelas.

Setiap hitungan indikator juga memiliki coverage `status`: `complete`, `partial`, `unavailable`, atau `not_applicable`. Bila detektor tidak tersedia, jumlah kandidat/kelompok bernilai null, bukan nol. `not_applicable` hanya untuk ruang lingkup yang secara eksplisit tidak dicakup oleh profil/rule; record dengan prasyarat hilang atau tidak valid adalah `not_assessed` (dihitung pada `records_unassessed`), bukan negatif atau otomatis `not_applicable`. `partial` berarti ada record belum dinilai atau pencarian terbatas; `complete` berarti detektor menyelesaikan pencarian pada input yang dapat dinilai, bukan bukti bahwa metode tervalidasi.

`risk_level_counts` tetap menggunakan nilai `null` per tingkat sampai definisi level risiko disetujui. Jangan menggantinya dengan nol karena tidak tersedia bukan berarti tidak ada kasus.

## `GET /api/v1/analysis`

Parameter query opsional: `period_from`, `period_to`, `indicator` (kode indikator yang didukung). Filter tidak dikenal menghasilkan `400`.

```json
{
  "availability": "not_configured",
  "data_source": {"kind": "none", "label": null},
  "generated_at": null,
  "filters": {"period_from": null, "period_to": null, "indicator": null},
  "coverage": {"records_considered": null, "records_eligible": null},
  "indicators": [],
  "limitations": ["Belum ada hasil analisis dari sumber data terhubung."]
}
```

Setiap elemen `indicators` yang tersedia memuat `code`, `name`, `status` (`complete`, `partial`, `unavailable`), `candidate_count` (case ID unik atau `null` bila pemeriksaan gagal), `candidate_group_count`, `eligible_count` (record yang benar-benar dinilai), `not_applicable_count`, `unassessed_count`, `search_truncated`, `definition`, dan `limitations`. `planned_indicators` memisahkan indikator yang belum diimplementasikan. `coverage.records_eligible` berarti jumlah record yang dinilai oleh sedikitnya satu indikator. `indicator_coverage` menyajikan hitungan dinilai/tidak berlaku/belum dinilai per indikator, batas pencarian, dan keterbatasan.

`risk_scoring` memuat versi, bobot yang sedang digunakan, dasar bobot, jumlah case yang tidak dapat dinilai, dan batas interpretasi. Indeks aturan `risk_score` adalah rentang 0–1 yang hanya memakai indikator yang dapat dinilai. Nilai null berarti tidak ada dasar penilaian yang cukup; nilai 0 hanya berarti tidak ada sinyal pada indikator yang telah dinilai. Indeks ini bukan probabilitas fraud, kerugian, atau level risiko tervalidasi. Level `risk_level` tetap null.

`audit_priority` memuat versi, status `available`/`partial`/`not_assessable`, unit fasilitas yang benar-benar dapat dibentuk, hitungan sinyal tanpa fasilitas untuk diagregasi, alasan kelayakan, komponen nilai klaim/upaya, cakupan, dan keterbatasan. Indeks per unit hanya tersedia bila ID fasilitas sumber, seluruh nilai `billed_amount` sintetis pada klaim terindikasi, skor, usaha positif, serta cakupan unit yang memadai tersedia. Unit dengan prasyarat tak lengkap tetap dapat memuat alasan dan komponen yang diketahui, tetapi `priority_index` null. Adapter `synthetic_demo` tidak menyuplai metadata fasilitas/ID fasilitas; karena itu antrean prioritas fasilitasnya kosong dan sinyal kasus dilaporkan sebagai belum terpetakan, bukan ditempelkan pada fasilitas buatan. Filter `indicator` hanya memfilter daftar indikator yang ditampilkan; scoring dan antrean prioritas tetap dihitung dari keenam indikator pada periode yang sama.

Setiap status cakupan indikator pada respons analisis membedakan `complete`, `partial`, `unavailable`, dan `not_applicable`, beserta jumlah `records_assessed`, `records_not_applicable`, `records_unassessed`, `search_truncated`, dan keterbatasan. Pada detail kasus, `indicator_coverage[].status` bernilai `triggered`, `not_triggered`, `not_applicable`, atau `not_assessed` (`not_assessed` adalah istilah API yang setara dengan unassessed); alasan prasyarat/status belum dinilai dicantumkan bila tersedia. `not_triggered` hanya sah pada record eligible ketika pemeriksaan berhasil selesai untuk cakupannya. Pencarian yang terpotong menandai record tanpa sinyal sebagai belum dinilai; temuan yang memang ditemukan tetap `triggered`. Skor hanya memakai indikator yang dapat dinilai. Indikator yang tidak berlaku tidak dimasukkan ke denominator; pemeriksaan belum tuntas juga tidak dianggap negatif.

## `GET /api/v1/cases`

Parameter query:

- `page` integer mulai `1`, default `1`.
- `page_size` integer `1..100`, default `25`.
- `risk_level` opsional: `high`, `medium`, `low`.
- `indicator` opsional: kode indikator yang didukung.
- `status` opsional: `pending`, `in_review`, `resolved`.
- `review_status` opsional: `pending_review`, `needs_more_evidence`, `not_substantiated`, `escalated`.
- `sort_by` opsional: `risk_score`, `detected_at`; default `risk_score`.
- `sort_order` opsional: `asc` atau `desc`; default `desc`.

Parameter enum/nilai di luar rentang menghasilkan `400`. Urutan harus deterministik untuk halaman yang sama (gunakan pemutus seri stabil). Bila belum ada data, kembalikan daftar kosong dan metadata pagination yang valid, bukan kasus contoh.

```json
{
  "availability": "not_configured",
  "data_source": {"kind": "none", "label": null},
  "items": [],
  "pagination": {"page": 1, "page_size": 25, "total_items": null, "total_pages": null},
  "applied_filters": {"risk_level": null, "indicator": null, "status": null, "review_status": null, "sort_by": "risk_score", "sort_order": "desc"}
}
```

`total_items` dan `total_pages` bernilai `null` jika sumber belum dapat dihitung; saat tersedia, `total_pages` dapat bernilai `0` untuk hasil kosong. Elemen kasus yang tersedia memakai bentuk ringkas:

`risk_level` dan `detected_at` tetap null karena level tidak ditetapkan dan waktu peristiwa deteksi tidak dicatat. `risk_score` memuat indeks aturan hanya jika ada pemeriksaan yang dapat dinilai. Item menyertakan `score_status`, `scoring_version`, daftar indikator yang dinilai/tidak berlaku/belum dinilai, status cakupan per indikator, `reasons`, serta `limitations`. Alasan bersumber dari output detektor; `supporting_values` hanya memuat field aman yang diizinkan dan tidak berisi token atau signature lengkap. Filter `risk_level` tetap menerima enum kontrak, tetapi tidak menghasilkan item selama level belum ditetapkan. Status antrean awal adalah `pending`; filter status valid lain dapat menghasilkan daftar kosong.

Semua sort key kontrak diterima. `risk_score` mengurutkan indeks aturan provisional, null selalu diletakkan terakhir, dan `case_id` menjadi tie-break stabil. `detected_at` belum tersedia sehingga urutannya deterministik menurut ID kasus. Ini bukan level risiko atau peringkat fraud tervalidasi. `status` lama tetap dipertahankan untuk kompatibilitas. Field tambahan `review_status` pada tiap item menggunakan status alur auditor di bawah dan default `pending_review`; filter `review_status` hanya memfilter tindak lanjut auditor, bukan status fraud.

```json
{
  "case_id": "case_example",
  "risk_level": null,
"risk_score": 0.25,
  "indicators": ["repeat_billing_candidate"],
  "status": "pending",
  "review_status": "pending_review",
  "detected_at": null
}
```

Nilai contoh `case_example` hanya penanda bentuk, bukan identitas kasus yang ada.

## `GET /api/v1/cases/{case_id}/review`

Tidak menerima parameter. `case_id` harus merupakan kandidat yang ada pada snapshot analitik aktif; ID tidak dikenal menghasilkan `404 CASE_NOT_FOUND`. Untuk kasus yang belum pernah ditinjau, endpoint mengembalikan status awal `pending_review`, `note: null`, `reviewer_label: null`, `updated_at: null`, dan riwayat kosong. Pembacaan status awal tidak menulis baris kasus ke database.

```json
{
  "availability": "available",
  "data_source": {"kind": "synthetic", "label": "synthetic_demo"},
  "case_id": "case_example",
  "status": "pending_review",
  "status_label": "Menunggu Tinjauan",
  "note": null,
  "reviewer_label": null,
  "updated_at": null,
  "history": []
}
```

## `POST /api/v1/cases/{case_id}/review`

Payload hanya menerima `status` dan `note`. Status yang diizinkan:

| Nilai | Label UI |
|---|---|
| `pending_review` | Menunggu Tinjauan |
| `needs_more_evidence` | Perlu Bukti Tambahan |
| `not_substantiated` | Selesai — indikasi tidak cukup setelah peninjauan |
| `escalated` | Dieskalasikan |

`note` opsional dan maksimal 1000 karakter setelah trim; string kosong dinormalisasi menjadi `null`. Field arbitrer ditolak. Respons memiliki struktur GET dan riwayat bertambah. Setiap POST valid dicatat sebagai event, termasuk jika status sama tetapi catatan diperbarui. Event pertama memakai `pending_review` sebagai `previous_status` implisit. Perubahan bebas di antara status yang diizinkan; tidak ada transisi yang menyatakan fraud terbukti.

```json
{"status": "needs_more_evidence", "note": "Mohon lengkapi dokumen pendukung yang relevan."}
```

Setiap entri riwayat memuat `changed_at`, `previous_status`, `status`, `note`, dan `reviewer_label`. Label demo tetap `demo_reviewer (unauthenticated)` dibuat server; nama dari request tidak diterima dan tidak ada autentikasi. Status merupakan metadata proses review, bukan label fraud terverifikasi atau keputusan yang divalidasi independen.

Penyimpanan memakai SQLite standard library, terpisah dari sumber analitik, default `backend/outputs/review_workflow.sqlite3`; override lokal melalui `CIR_REVIEW_DB_PATH`. Database dibuat saat endpoint review atau antrean yang membutuhkan status dipanggil, bukan saat health check. Jangan memasukkan identitas nyata, token peserta, signature klaim, atau informasi kesehatan ke catatan. API demo tidak memiliki autentikasi dan tidak dapat memvalidasi kewenangan atau mengklasifikasikan semua teks sensitif; penyimpanan ini tidak sesuai untuk data operasional nyata.

## `GET /api/v1/cases/{case_id}`

Path parameter `case_id` adalah ID internal aplikasi yang tidak mengandung identitas peserta atau fingerprint. ID tidak ditemukan menghasilkan `404`.

```json
{
  "availability": "not_configured",
  "data_source": {"kind": "none", "label": null},
  "case": null,
  "notice": "Kasus tidak tersedia karena sumber data belum dikonfigurasi."
}
```

Saat tersedia, `case` memiliki `case_id`, `risk_level`, `risk_score`, `score_status`, `scoring_version`, indikator pemicu, indikator yang dinilai/tidak berlaku/belum dinilai, `indicator_coverage`, `status`, `detected_at`, `reasons`, `limitations`, dan `review`. `reasons` menyertakan ringkasan detektor, bukti/atribut aman, batasan, dan `supporting_values` yang diminimalkan. Jangan sertakan nilai identitas, token peserta, signature lengkap, atau detail baris yang tidak perlu. Contoh bentuk alasan (ilustrasi saja):

```json
{
  "case_id": "case_example",
  "risk_level": null,
  "risk_score": null,
  "status": "pending",
  "detected_at": null,
  "reasons": [{"indicator": "repeat_billing_candidate", "summary": "Pola atribut klaim teramati berulang.", "evidence": ["matched_attributes: ..."], "limitations": ["Sinyal memerlukan tinjauan auditor."], "supporting_values": {"candidate_record_count": 2}}],
  "limitations": ["Pola berulang adalah sinyal untuk ditinjau, bukan bukti fraud."],
  "review": {"decision": null, "reviewed_at": null}
}
```

Field `case.review` pada respons detail ini dipertahankan untuk kompatibilitas kontrak lama. Status proses auditor yang berlaku dan riwayatnya dibaca dari endpoint `/api/v1/cases/{case_id}/review`.

## `GET /api/v1/evaluation`

Parameter opsional: `period_from`, `period_to`, `evaluation_version`. Endpoint hanya menghitung evaluasi bila label acuan, cakupan data, dan metode yang terdokumentasi tersedia.

```json
{
  "availability": "insufficient_data",
  "data_source": {"kind": "none", "label": null},
  "generated_at": null,
  "evaluation": null,
  "requirements_missing": ["Label acuan yang tervalidasi", "Protokol evaluasi yang ditetapkan"],
  "notice": "Metrik evaluasi belum dihitung."
}
```

Jika tersedia, `evaluation` harus mencakup `method`, `label_source`, `sample_count`, `period`, `metrics`, dan batasan interpretasi. Jangan membuat angka contoh untuk metrik. Ketiadaan label atau data memadai menghasilkan `insufficient_data`, bukan metrik nol.

Pada sumber `synthetic_demo`, evaluasi tetap `insufficient_data` dengan `evaluation: null`: fixture software bukan label acuan dan bukan sampel representatif untuk validasi performa.

## Konsistensi status ketersediaan

`not_configured`: sumber belum disetel. `insufficient_data`: sumber ada tetapi prasyarat atau jumlah data belum cukup. `unavailable`: sumber gagal diakses atau proses gagal; sertakan error terkontrol. `available`: hasil berhasil dihitung dan `data_source.kind` bukan `none`. Status pada dashboard, analisis, kasus, dan evaluasi menggambarkan ketersediaan masing-masing, bukan sekadar status proses API.

## Review kandidat yang terikat ke AnalysisRun (P0 Stage 6)

Route lama `/api/v1/cases/{case_id}/review` tetap merupakan workflow snapshot legacy dengan status lama (`pending_review`, `needs_more_evidence`, `not_substantiated`, `escalated`). Tidak ada migrasi otomatis dari tabel atau riwayat legacy. Workflow baru selalu memerlukan `run_id` eksplisit dan hanya menerima kasus yang tersimpan sebagai kandidat pada hasil run `completed` atau `partial` dengan result tersedia. Kasus pada run berbeda memiliki review terpisah walaupun `case_id` sama.

### `GET /api/v1/runs/{run_id}/cases/{case_id}/review`

Memerlukan sesi autentikasi dan permission `review:read`. GET memvalidasi pasangan terhadap hasil run persisten dan tidak membuat review/event. Kasus/run yang tidak ada atau kasus yang bukan kandidat pada run tersebut menghasilkan `404 RUN_CASE_REVIEW_NOT_FOUND`. Run yang masih berjalan, gagal, atau tidak mempunyai result yang dapat ditinjau menghasilkan `409 RUN_NOT_REVIEWABLE`.

Kasus valid yang belum pernah dimutasi menghasilkan `review_id: null`, `review_status: pending_review`, `review_outcome: null`, dan `history: []`.

### `PATCH /api/v1/runs/{run_id}/cases/{case_id}/review`

Memerlukan `review:write`, cookie sesi, dan CSRF cookie/header yang valid. Payload hanya menerima `review_status` dan `note` (maksimum 1000 karakter; trim; string kosong menjadi null). Catatan multi-baris, baris CSV-like, serta pola umum identifier/credential ditolak dengan pesan generik; pemeriksaan pola tidak dapat menjamin semua informasi sensitif terdeteksi. Field lain termasuk actor, role, outcome, dan ID reviewer ditolak (`422 INVALID_PAYLOAD`). Status proses yang diizinkan: `pending_review`, `in_review`, `awaiting_evidence`, `escalated`, `closed`. Setiap request valid menambah event `status_changed`, termasuk pengiriman status yang sama; status mutakhir dan event menyimpan aktor dari principal server.

```json
{"review_status":"awaiting_evidence","note":"Mohon periksa bukti pada fixture sintetis."}
```

### `POST /api/v1/runs/{run_id}/cases/{case_id}/review/outcome`

Memerlukan `review:manage` (baseline: `audit_lead`), sesi, dan CSRF valid. Payload hanya menerima `review_outcome` dan `note` (maksimum 1000 karakter dengan validasi pola sensitif terbatas seperti endpoint status). Outcome nullable sampai tindakan eksplisit; kosakata prototipe sementara adalah `signal_supported`, `signal_not_supported`, `inconclusive`. Ini mendeskripsikan kesimpulan tinjauan atas sinyal tertentu, bukan status fraud/legal/operasional. Persetujuan pemilik proses masih diperlukan. Outcome tidak diturunkan dari skor, lane, indikator, atau status.

```json
{"review_outcome":"inconclusive","note":"Bukti fixture belum cukup untuk menyimpulkan."}
```

Respons ketiga endpoint memakai bentuk berikut (ilustrasi kontrak, bukan hasil nyata):

```json
{
  "availability":"available","data_source":"synthetic_data_batch",
  "review_id":"rvr_example","run_id":"run_example","case_id":"case_example",
  "review_status":"awaiting_evidence","review_status_label":"Menunggu Bukti Tambahan",
  "review_outcome":null,"review_outcome_label":null,
  "note":"Mohon periksa bukti pada fixture sintetis.",
  "created_at":"2026-01-01T00:00:00+00:00","updated_at":"2026-01-01T00:00:00+00:00",
  "updated_by_user_id":"usr_example",
  "history":[{"event_id":"rve_example","event_type":"status_changed",
    "occurred_at":"2026-01-01T00:00:00+00:00","actor_user_id":"usr_example",
    "previous_status":"pending_review","new_status":"awaiting_evidence",
    "previous_outcome":null,"new_outcome":null,"note":"Mohon periksa bukti pada fixture sintetis."}],
  "notice":"Status dan outcome adalah metadata tinjauan manusia, bukan penetapan fraud. Jangan masukkan informasi peserta atau klaim sensitif ke catatan."
}
```

Tabel `run_case_reviews`, `run_case_review_events`, dan `run_review_security_audit_events` ditambahkan secara aditif pada SQLite batch/run yang ditunjuk `CIR_BATCH_DB_PATH`; path default dan konfigurasinya mengikuti DataBatch/AnalysisRun. Legacy review DB tidak diubah. Review history append-only dan berbeda dari security audit event (yang tidak menyimpan isi note). Keduanya ditulis pada transaksi store run yang sama. Tidak tersedia assignment/object scope: akses hanya `shared_synthetic`, bukan kontrol untuk data terbatas atau operasional. Semua catatan harus berupa teks sintetis tanpa identitas atau informasi klaim sensitif; filter pola umum hanya perlindungan tambahan dan tidak menjamin pendeteksian seluruh informasi sensitif.

## Autentikasi dan sesi (P0 Stage 2, prototipe lokal)

Endpoint operasional dashboard, analisis, kasus, evaluasi, dan review memerlukan sesi server yang valid. `GET /health` tetap publik dan tidak menginisialisasi database autentikasi atau review.

### `POST /api/v1/auth/login`

Menerima `{"username":"operator","password":"..."}`. Permintaan tambahan ditolak. Saat berhasil, respons JSON berisi `user` (`user_id`, `username`, `role`, `is_active`), `permissions`, `expires_at`, dan `csrf_token`. Token sesi acak dikirim hanya melalui cookie `cir_session` (`HttpOnly`, `SameSite=Lax`, `Path=/api/v1`, `Secure` mengikuti konfigurasi) dan database hanya menyimpan hash-nya. Token CSRF tersedia di cookie `cir_csrf` yang tidak `HttpOnly`, respons login, dan harus dikirim kembali melalui header `X-CSRF-Token` untuk POST/PATCH terlindungi. Username/password salah menghasilkan error generik `401 INVALID_CREDENTIALS`; pesan tidak membedakan akun yang tidak ada atau nonaktif.

### `GET /api/v1/auth/me` dan `POST /api/v1/auth/logout`

`/me` memvalidasi sesi server dan mengembalikan struktur sesi di atas; endpoint ini menerbitkan ulang cookie CSRF bila diperlukan. Logout memerlukan sesi dan CSRF valid, mencabut sesi di server dan menghapus kedua cookie; respons sukses `204`.

### Provisioning akun

Tidak ada registrasi publik. `POST /api/v1/auth/users` dan `PATCH /api/v1/auth/users/{user_id}` hanya dapat dipanggil `platform_admin` dengan CSRF valid. Role harus salah satu dari empat enum; payload tambahan ditolak. Administrator pertama dibuat satu kali lewat `python -m app.security.bootstrap_admin` dari folder `backend`, dengan `CIR_ADMIN_BOOTSTRAP_SECRET` yang operator setel di environment dan secret/password yang dimasukkan lewat prompt. Tidak ada credential default. Path database autentikasi mengikuti `CIR_AUTH_DB_PATH`; bila tidak disetel, mengikuti path review (`CIR_REVIEW_DB_PATH` atau default lokal). Masa berlaku sesi default 8 jam, dapat diatur melalui `CIR_SESSION_TTL_SECONDS` (60 detik sampai 7 hari). `CIR_COOKIE_SECURE` default `true`; hanya set `false` untuk pengembangan lokal HTTP yang terisolasi. Deployment selain lokal wajib memakai HTTPS dan `Secure`.

### Permission prototipe

Untuk demo sintetis, `platform_admin` memiliki seluruh permission yang sudah digunakan aplikasi: `dashboard:read`, `analytics:read`, `cases:read`, `batches:read`, `batches:write`, `runs:read`, `runs:write`, `runs:results:read`, `review:read`, `review:write`, `review:manage`, `users:manage`, dan `security_audit:read`. `data_operator` tetap dapat membaca metadata batch/run, mengimpor batch dan membuat run, tetapi tidak membaca hasil run atau mengelola review. `verifikator` tetap dapat membaca hasil serta mengubah status review; `audit_lead` memiliki hak yang sama ditambah outcome. Permission diperiksa backend pada setiap route terlindungi; penyembunyian navigasi frontend hanya affordance UI. Akses Admin penuh adalah asumsi demo sintetis, belum persetujuan operasional, dan tidak memberi otorisasi untuk data BPJS. Scope assignment/batch belum tersedia. Permission `security_audit:read` telah didefinisikan, tetapi endpoint baca audit event belum tersedia.

Update review mengambil `actor_user_id` dari principal tervalidasi, bukan request. Security events yang benar-benar dicatat saat ini mencakup bootstrap admin, login berhasil/gagal, logout/revocation, expiry, pencabutan sesi saat akun dinonaktifkan, perubahan akun, perubahan review legacy, import batch, serta pembuatan/retry dan status terminal AnalysisRun. Event login tidak menyimpan username maupun kredensial. Review legacy event ditulis bersama riwayat pada database review; event autentikasi berada di database autentikasi; event batch/run berada pada database batch/run. Run-scoped review history dan security event adalah tabel berbeda di database batch/run yang sama. Status/outcome legacy tetap mengikuti kontrak lama; route run-scoped menggunakan field status/outcome terpisah, dan tidak ada yang merupakan label fraud.

Error autentikasi mengikuti envelope error API (`error.code`, `error.message`, `error.details`, `error.request_id`) dan tidak mengembalikan password, token, path database, atau isi klaim. Sesi berbasis cookie memerlukan perlindungan CSRF untuk mutasi. Kebijakan role, TTL, bootstrap secret delivery, keamanan browser, dan pengelolaan audit lokal masih asumsi prototipe yang perlu persetujuan pemilik proses/security sebelum penggunaan selain demo sintetis.

## DataBatch sintetis dan CSV (P0 Stage 3)

Endpoint berikut hanya menerima pertukaran **CSV sintetis** dengan skema allowlist `synthetic-claims-v1` dan mapping `synthetic-canonical-v1`. Ini bukan importer `.dta`, pemetaan BPJS, atau bukti bahwa isi berlabel sintetis benar-benar artifisial. Header `X-Data-Classification: synthetic_only` adalah deklarasi pemanggil, bukan verifikasi independen.

### Skema CSV `synthetic-claims-v1`

Kolom wajib: `claim_id`, `case_id`, `facility_id`, `participant_token`, `service_date`, `province_code`, `municipality_code`, `facility_ownership`, `facility_type`, `facility_class`, `admission_diagnosis`, `primary_diagnosis`, `claim_group`, `procedure_code`, `billed_amount`, `service_type`, `service_units`, `facility_daily_capacity`, `supporting_evidence_required`, `supporting_evidence_types`, `supporting_evidence_present`.

Kolom opsional: `service_timestamp`, `supporting_evidence_recording_status`, `facility_daily_claim_count`. Kolom array bukti memakai item dipisahkan titik koma; boolean menerima `true`/`false`; tanggal dan timestamp memakai ISO 8601; amount berupa angka desimal non-negatif. Nilai kosong pada kolom opsional dinormalisasi menjadi `null`; array bukti kosong sah. ID harus memakai prefiks sintetis `syn-claim-`, `syn-facility-`, dan `syn-participant-` sesuai jenis ID. `claim_id` dan `case_id` unik dalam satu batch. Record dengan atribut layanan sama namun ID berbeda tidak ditolak hanya karena kemiripannya. Kolom label ground truth tidak termasuk skema dan ditolak sebagai kolom tak didukung.

### `POST /api/v1/batches/import`

Memerlukan sesi terautentikasi, permission `batches:write`, dan CSRF cookie/header valid. Kirim byte CSV sebagai `Content-Type: text/csv; charset=utf-8`, beserta header `X-Batch-Key` (label harus berawalan `synthetic-`, huruf kecil/angka/tanda hubung saja), `X-Synthetic-Schema-Version`, `X-Synthetic-Mapping-Version`, dan `X-Data-Classification: synthetic_only`. Jangan masukkan nama, identitas, path, atau informasi sensitif ke label. Batas default lokal 50 MiB dan 120.000 baris; dapat diatur melalui `CIR_BATCH_MAX_BYTES` dan `CIR_BATCH_MAX_ROWS` dalam rentang yang divalidasi aplikasi. Encoding UTF-8 (termasuk BOM) diterima.

```json
{
  "batch": {
    "batch_id": "bat_illustrative_only",
    "batch_key": "synthetic-fixture",
    "batch_version": 1,
    "created_at": "2026-01-01T00:00:00+00:00",
    "creator_user_id": "usr_illustrative_only",
    "source_type": "synthetic_csv",
    "schema_version": "synthetic-claims-v1",
    "mapping_version": "synthetic-canonical-v1",
    "row_count": 1,
    "status": "ready",
    "validation": {
      "error_count": 0,
      "error_counts": {},
      "errors": [],
      "errors_truncated": false,
      "row_count": 1,
      "warning_counts": {}
    }
  },
  "reused_existing": false,
  "notice": "Ilustrasi kontrak; bukan hasil impor data nyata."
}
```

Contoh tersebut hanya ilustrasi kontrak, bukan hasil impor. Impor baru menghasilkan `201`; pengulangan identik pada `batch_key` + checksum konten + versi skema + versi mapping mengembalikan versi yang sama (`200`, `reused_existing: true`). Perubahan konten/skema/mapping yang didukung menghasilkan `batch_version` berikutnya untuk `batch_key` itu dan `batch_id` berbeda. Versi ready immutable; batch yang sama dapat direferensikan oleh beberapa AnalysisRun mendatang. Versi schema/mapping dengan format valid tetapi belum didukung disimpan sebagai versi `rejected` baru tanpa record; header yang hilang atau format versinya tidak valid ditolak sebelum penyimpanan.

CSV yang valid menjadi `ready`, atau `ready_with_warnings` bila kolom opsional tidak disediakan. Import yang diterima tetapi memiliki kesalahan validasi tersimpan sebagai `rejected` dengan error agregat dan tanpa child record parsial; response tetap `201` karena rekaman upaya impor berhasil. Batas ukuran transport yang terlampaui mengembalikan `413 UPLOAD_TOO_LARGE` sebelum database dibuka. Kesalahan skema/encoding/row menghasilkan count menurut kategori dan paling banyak 20 referensi baris/kolom/kode aman; nilai input tidak dikembalikan. Kesalahan header request menggunakan envelope error standar.

### `GET /api/v1/batches` dan `GET /api/v1/batches/{batch_id}`

Keduanya memerlukan sesi dan `batches:read`. Daftar memakai `limit` 1–100 (default 50) serta `offset` non-negatif. Detail tidak ditemukan menghasilkan `404 BATCH_NOT_FOUND`. Respons hanya memuat metadata dan ringkasan validasi; tidak menyajikan checksum, CSV, token peserta, atau record klaim.

Permission sementara: `batches:write` pada `platform_admin` dan `data_operator`; `batches:read` pada empat role untuk metadata batch sintetis. Data bersama dapat dibaca oleh role tersebut karena prototipe belum memiliki assignment/scope. Ini bukan access control yang layak untuk data terbatas/operasional. Event `batch_imported`/`batch_import_rejected` tersimpan dalam SQLite batch terpisah bersama transaksi import; belum ada API baca audit event.

Contoh respons berikut juga ilustratif, bukan hasil batch nyata:

```json
{
  "items": [], "total_items": 0, "limit": 50, "offset": 0,
  "availability": "available"
}
```

Daftar `items` memakai `BatchMetadata` seperti pada contoh import. `GET /api/v1/batches/{batch_id}` membungkus metadata dengan `availability: "available"` dan `notice`; batch yang tidak ditemukan mengembalikan error standar `404 BATCH_NOT_FOUND`.

Kategori error validasi impor yang digunakan mencakup `empty_input`, `empty_file`, `invalid_encoding`, `malformed_csv`, `duplicate_header`, `missing_required_column`, `unexpected_column`, `ground_truth_column_forbidden`, `malformed_row_width`, `required_value_missing`, `text_value_too_long`, `invalid_identifier`, `duplicate_identifier`, `invalid_amount`, `invalid_non_negative_integer`, `invalid_boolean`, `invalid_iso_date`, `invalid_iso_datetime`, `unsupported_enum_value`, `row_limit_exceeded`, `unsupported_schema_version`, dan `unsupported_mapping_version`. Kesalahan menolak seluruh batch; record parsial tidak disimpan. Tidak ada kategori peringatan konten selain kolom opsional yang tidak disediakan. Error transport 413/415 serta header/versi yang hilang atau formatnya tidak sah tidak membuat DataBatch. Query daftar yang secara sintaks tidak berupa integer mengikuti envelope 422 FastAPI; nilai integer di luar rentang menghasilkan 400 `INVALID_FILTER`.

Database default `backend/outputs/data_batches.sqlite3` (diabaikan Git), dapat dioverride dengan `CIR_BATCH_DB_PATH`. Database dibuat saat route batch pertama kali digunakan; `GET /health` tidak menginisialisasi database batch, auth, atau review. Penyimpanan child record hanya berisi record fitur hasil normalisasi untuk skema sintetis, bukan byte CSV atau label ground truth. AnalysisRun sintetis dijelaskan pada bagian berikut.

## AnalysisRun persisten (P0 Stage 4)

AnalysisRun hanya menerima batch `synthetic_csv` dengan schema `synthetic-claims-v1` dan mapping `synthetic-canonical-v1` berstatus `ready` atau `ready_with_warnings`. Adapter `synthetic-claims-v1` ke fitur canonical memvalidasi versi dan field, menyalin hanya kolom fitur yang diizinkan, dan membentuk metadata kapasitas fasilitas dari pasangan sintetis `facility_id`/`facility_daily_capacity`. Nilai kapasitas yang bertentangan untuk satu facility ID menolak eksekusi. Tidak ada BPJS mapping, ground-truth field, atau label eksperimen dalam fitur. Run dibuat melalui provider batch sintetis yang dipilih eksplisit berdasarkan `source_type`; tidak ada provider fallback.

Run manifest dan hasil berada dalam database batch yang sama (`CIR_BATCH_DB_PATH`; default `backend/outputs/data_batches.sqlite3`). Tidak ada konfigurasi run database terpisah. Ini membuat validasi status/checksum batch, referensi manifest, hasil, dan security event satu SQLite transaction domain. Tabel baru ditambahkan secara idempotent; tabel auth/review tidak di-reset atau dimigrasikan. `GET /health` tidak membuka database tersebut.

### `POST /api/v1/runs`

Memerlukan sesi, CSRF cookie/header, dan `runs:write` (`data_operator` pada baseline prototipe). Payload menerima `batch_id` untuk run baru, atau `retry_of_run_id` untuk retry run gagal; retry dapat juga menyertakan `batch_id`, yang harus sama persis dengan batch versi/checksum asli. Field tambahan ditolak. Pelaku selalu berasal dari sesi tervalidasi.

```json
{
  "batch_id": "bat_illustrative_only",
  "source_type": "synthetic_csv",
  "action_policy_version": "action-policy-demo-v1-provisional"
}
```

`source_type` opsional dan default-nya `synthetic_csv` agar klien lama tetap berfungsi. Nilai selain sumber tersebut menghasilkan `422 RUN_SOURCE_UNSUPPORTED`; jika nilainya tidak sama dengan sumber batch, server mengembalikan `409 RUN_SOURCE_BATCH_MISMATCH`. Sumber yang belum didukung tidak dialihkan ke synthetic.

`action_policy_version` opsional; jika tidak diberikan, server memakai versi default yang terdaftar. Request hanya memilih versi server-side dan tidak menerima threshold. Membuat versi/config baru dilakukan melalui perubahan konfigurasi server yang ditinjau, dengan identifier versi baru.

Respons `201` berisi manifest tanpa result payload. Contoh berikut ilustrasi kontrak, bukan hasil analisis:

```json
{
  "run": {
    "run_id": "run_illustrative_only",
    "batch_id": "bat_illustrative_only",
    "batch_version": 1,
    "content_checksum": "illustrative-checksum-not-real",
    "source_type": "synthetic_csv",
    "source_classification": "synthetic_only_declared",
    "source_schema_version": "synthetic-claims-v1",
    "source_mapping_version": "synthetic-canonical-v1",
    "creator_user_id": "usr_illustrative_only",
    "retry_of_run_id": null,
    "created_at": "2026-01-01T00:00:00Z",
    "started_at": "2026-01-01T00:00:00Z",
    "completed_at": "2026-01-01T00:00:01Z",
    "execution_status": "partial",
    "failure_category": null,
    "detector_suite_version": "detector-suite-v1-manual",
    "scoring_version": "rule-risk-index-v1-provisional",
    "priority_version": "audit-priority-v1-synthetic-assumption",
    "action_policy_version": "action-policy-demo-v1-provisional",
    "configuration": {
      "detector_suite_version": "detector-suite-v1-manual",
      "action_policy": {
        "version": "action-policy-demo-v1-provisional",
        "green_upper": 0.3333333333333333,
        "yellow_upper": 0.6666666666666666
      }
    },
    "coverage": [],
    "result_available": true,
    "result_storage_reference": "analysis_run_results:run_illustrative_only"
  },
  "notice": "Hasil run sintetis tersimpan; sinyal bukan bukti fraud dan bukan hasil data BPJS."
}
```

`execution_status` menggunakan `running`, `completed`, `partial`, atau `failed`. Run dicatat `running` sebelum pipeline sinkron dimulai. `not_applicable` sendiri bukan kegagalan; status terminal memakai status pipeline terkoordinasi. Bila seluruh detektor tidak tersedia, run gagal dengan `ALL_DETECTORS_UNAVAILABLE` dan hasil diagnostik coverage yang aman dapat tersimpan. Exception pipeline memakai kategori aman `PIPELINE_EXECUTION_FAILED` tanpa stack trace, record, atau pesan exception.

### `GET /api/v1/runs` dan `GET /api/v1/runs/{run_id}`

Keduanya memerlukan `runs:read` untuk metadata. Daftar menggunakan `limit` 1–100 (default 50), `offset` non-negatif, dan filter opsional `batch_id`; daftar tidak menyertakan result payload. Detail memerlukan permission terpisah `runs:results:read` dan mengembalikan manifest plus snapshot tersimpan. GET tidak menjalankan ulang detector, scoring, atau priority. `404 RUN_NOT_FOUND` digunakan untuk run yang tidak ada.

Error create: `404 BATCH_NOT_FOUND`, `409 BATCH_NOT_RUNNABLE`/`BATCH_VERSION_MISMATCH`/`RUN_SOURCE_BATCH_MISMATCH`/`RUN_NOT_RETRYABLE`/`RETRY_BATCH_MISMATCH`/`ACTION_POLICY_VERSION_CONFLICT`, `422 INVALID_PAYLOAD`/`ACTION_POLICY_VERSION_UNKNOWN`/`RUN_SOURCE_UNSUPPORTED`, `500 ANALYSIS_RUN_FAILED`, atau `503 RUN_STORAGE_UNAVAILABLE`. Kegagalan tidak mengembalikan input batch atau exception detail; jika run sempat dibuat, `500` menyertakan `run_id` untuk penelusuran status.

### Retry dan persistensi

Untuk run lama yang dibuat sebelum metadata `source` ditambahkan ke konfigurasi, manifest mempertahankan kompatibilitas dengan menurunkan klasifikasi `synthetic_only_declared` dari `source_type=synthetic_csv`; ini tidak memverifikasi independen provenance konten.

Retry adalah `POST /api/v1/runs` dengan `retry_of_run_id`; hanya run `failed` dapat di-retry. Batch harus kembali berstatus ready dan memiliki ID, versi, checksum, schema, serta mapping yang tepat sama. Retry membuat ID baru dan tidak mengubah run lama. `completed`, `partial`, dan `failed` terminal; SQLite trigger menolak update/delete hasil terminal. Hasil dan perubahan manifest terminal disimpan dalam satu transaksi; security event pembuatan/hasil run juga ditulis pada transaksi terkait. Bila proses terputus setelah status `running` di-commit, run tetap `running` dan tidak diklaim selesai; tidak ada pemulihan otomatis atau retry untuk run tersebut pada prototipe ini.

Manifest merekam klasifikasi sumber `synthetic_only_declared`, schema profile, mapping version, checksum dan versi batch; konfigurasi sumber dan metadata yang sama disimpan pada snapshot. Klasifikasi tersebut berasal dari deklarasi saat impor dan bukan verifikasi independen isi CSV. Ringkasan coverage per indikator dan snapshot hasil/reason dipersistenkan. Coverage mempertahankan status parsial, tidak berlaku, tidak tersedia, jumlah record belum dinilai dan flag pencarian terpotong; kondisi tersebut tidak dipaksa menjadi negatif atau `complete`. Manifest juga merekam scoring/priority version aktual, konfigurasi detector yang tersedia, action-policy version, dan konfigurasi persis yang dipakai. `detector_suite_version` saat ini `detector-suite-v1-manual`, identifier kontrak yang dipelihara manual; ia bukan hash kode atau provenance build. Policy default `action-policy-demo-v1-provisional` membagi indeks normalisasi sama besar pada batas 1/3 dan 2/3 menjadi `green`, `yellow`, dan `red`. Nilai threshold ini hanya untuk demo sintetis, belum divalidasi atau disahkan; API hanya menerima pemilihan versi yang terdaftar dan tidak menerima threshold dari klien. Versi policy/config disimpan immutable; perubahan config harus memakai identifier versi baru. Hasil GET menyertakan snapshot `action_policy` tersimpan dan tidak menghitung ulang provider, orchestrator, scoring, priority, policy, atau detektor. Ground truth, participant token, nilai signature mentah, dan row sumber tidak disimpan dalam result. `risk_score: null`, coverage parsial/tidak tersedia, serta facility priority yang tidak dapat dinilai dipertahankan dari pipeline.

Snapshot `action_policy` hanya memberi lane pada finding kasus yang muncul di snapshot; klaim yang tidak muncul tidak otomatis dianggap green. Setiap item memuat lane, versi policy, assessment status, alasan interval/ketidaklayakan, dan limitations. Score null/parsial, indikator relevan belum dinilai/unavailable, atau pencarian relevan truncated menghasilkan `cannot_recommend`. `not_applicable` saja tidak menghalangi lane jika masih ada pemeriksaan yang relevan dan dinilai lengkap. Action lane bukan `risk_level`, fraud confirmation, review status, atau review outcome. Facility priority ditahan sebagai `null` per unit jika nilai klaim tidak lengkap, score/cakupan/keanggotaan kelompok tidak memadai, atau effort tidak positif; alasan aman tersedia pada `eligibility_reasons`. Jika antrean berisi unit layak dan tak layak, status ringkasnya `partial`.

Permission baseline prototipe untuk demo: `runs:write` dimiliki `platform_admin` dan `data_operator`; `runs:read` dan `runs:results:read` dimiliki `platform_admin`, verifikator, serta audit lead. Data operator tetap tidak dapat membaca hasil. Scope run masih `shared_synthetic`, belum ada assignment/object scope, dan bukan kontrol untuk data terbatas/operasional. Tidak ada event API baca audit event. Akses Admin operasional penuh hanya asumsi demo sintetis; permission dan pembagian tanggung jawab tetap memerlukan persetujuan pemilik proses/security.
