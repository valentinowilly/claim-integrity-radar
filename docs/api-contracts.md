# Kontrak API Awal

Dokumen ini menetapkan kontrak awal untuk frontend dan backend Claim Integrity Radar. Semua contoh JSON di bawah adalah **ilustrasi kontrak**, bukan hasil analisis nyata, bukan data BPJS, dan bukan metrik demo. Implementasi harus mengambil angka dari sumber data yang dinyatakan dalam respons; jika belum tersedia, gunakan status ketersediaan yang sesuai.

## Ketentuan umum

- Prefix API versi: `/api/v1`; health check berada di `/health`.
- Tanggal dan waktu menggunakan ISO 8601. Waktu menyertakan zona waktu bila tersedia.
- `data_source.kind` bernilai `synthetic`, `local`, atau `none`. `label` menjelaskan sumber secara aman dan tidak memuat path lokal atau identitas sensitif.
- Implementasi demo tahap integrasi menggunakan `data_source: {"kind":"synthetic","label":"synthetic_demo"}`. Semua angka pada respons bertanda ini dihitung dari record artifisial runtime, bukan dataset BPJS.
- `availability` bernilai `available`, `not_configured`, `insufficient_data`, atau `unavailable`. `available` hanya boleh dipakai bila hasil memang dihitung dari sumber yang terhubung.
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

Setiap hitungan indikator juga memiliki `status`: `complete`, `partial`, `unavailable`, atau `not_applicable`. Bila detektor tidak tersedia, jumlah kandidat/kelompok bernilai null, bukan nol. `not_applicable` berarti tidak ada record yang memenuhi prasyarat/rule indikator; `partial` berarti ada record belum dinilai atau pencarian terbatas; `complete` berarti detektor menyelesaikan pencarian pada input yang dapat dinilai, bukan bukti bahwa metode tervalidasi.

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

`audit_priority` memuat versi, unit, formula, urutan, unit fasilitas yang benar-benar dapat dibentuk, hitungan sinyal tanpa fasilitas untuk diagregasi, alasan, komponen nilai klaim/upaya, cakupan, dan keterbatasan. Unit fasilitas hanya dihasilkan jika `facility_id` sumber memang tersedia. Adapter `synthetic_demo` saat ini tidak menyuplai metadata fasilitas/ID fasilitas; karena itu antrean prioritas fasilitasnya kosong dan sinyal kasus dilaporkan sebagai belum terpetakan, bukan ditempelkan pada fasilitas buatan. Filter `indicator` hanya memfilter daftar indikator yang ditampilkan; scoring dan antrean prioritas tetap dihitung dari keenam indikator pada periode yang sama.

Setiap status cakupan indikator pada respons analisis membedakan `complete`, `partial`, `unavailable`, dan `not_applicable`, beserta jumlah `records_assessed`, `records_not_applicable`, `records_unassessed`, `search_truncated`, dan keterbatasan. Pada detail kasus, `indicator_coverage[].status` bernilai `triggered`, `not_triggered`, `not_applicable`, atau `not_assessed`; alasan/status belum dinilai dicantumkan jika tersedia. Skor hanya memakai indikator yang dapat dinilai. Indikator yang tidak berlaku tidak dimasukkan ke denominator; pemeriksaan belum tuntas juga tidak dianggap negatif.

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
