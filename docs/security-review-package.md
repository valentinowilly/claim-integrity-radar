# Paket tinjauan keamanan independen — Claim Integrity Radar (RC)

Untuk peninjau keamanan independen. Paket ini membatasi lingkup tinjauan agar dapat dilakukan tanpa mengulang seluruh proyek. Paket tidak memuat data nyata, identifier, salt, rahasia, atau path lokal sensitif.

**Status tinjauan independen: BELUM DILAKUKAN.** Bagian §8 kosong sampai diisi peninjau. Tinjauan internal di §6 dilakukan oleh agen yang mengimplementasikan kontrol, sehingga **tidak** memenuhi syarat independensi. Peninjau independen tidak boleh orang atau agen yang mengimplementasikan kontrol yang ditinjau, dan harus memiliki kompetensi tinjauan keamanan aplikasi web.

## 1. Sistem dan batas kepercayaan

| Komponen | Keterangan |
|---|---|
| Frontend | React/Vite SPA; tidak menyimpan token sesi di `localStorage`; semua otorisasi ditegakkan backend |
| Backend | FastAPI (`backend/app/main.py`); route di `backend/app/api/routes/` |
| Penyimpanan | SQLite lokal: auth (`CIR_AUTH_DB_PATH`), batch/run/review run-scoped (`CIR_BATCH_DB_PATH`), review lama (`CIR_REVIEW_DB_PATH`); default di `backend/outputs/` (di-ignore Git) |
| Sumber data nyata | file `.dta` FKRTL di luar repository, dibaca server-side dari `BPJS_FKRTL_SAMPLE_PATH`; identifier di-HMAC dengan `CIR_FKRTL_PSEUDONYM_KEY` |

Batas kepercayaan: (1) browser ↔ API (cookie sesi, CSRF); (2) API ↔ file SQLite (proses API dipercaya penuh; siapa pun dengan akses tulis file melewati semua kontrol aplikasi); (3) API ↔ file sumber BPJS (hanya baca, konfigurasi server, tidak dapat dipilih klien).

## 2. Endpoint hasil audit dan model izin

`POST /api/v1/runs/{run_id}/cases/{case_id}/review/audit-confirmation` — `backend/app/api/routes/run_reviews.py`.

| Kontrol | Implementasi | Bukti tes |
|---|---|---|
| Autentikasi | `current_principal` (`backend/app/security/dependencies.py`); sesi tidak ada/kedaluwarsa/akun nonaktif → 401 | `test_audit_confirmation_rejects_missing_session_crossed_csrf_and_deactivated_account` |
| Otorisasi | `require_permission("review:manage")`: `audit_lead`, `platform_admin` | `test_audit_result_requires_manage_permission_csrf_and_an_existing_review`, `test_recorder_cannot_be_impersonated_and_verifier_cannot_record` |
| CSRF | `require_csrf`: header `X-CSRF-Token` = cookie `cir_csrf`, dan hash-nya sama dengan hash CSRF milik sesi | tes di atas (tanpa token, token sesi lain) |
| Identitas pencatat | `recorded_by_user_id` dari sesi; payload `extra="forbid"` menolak field aktor | `test_recorder_cannot_be_impersonated_and_verifier_cannot_record` |
| Prasyarat | kandidat harus ada di hasil run tersimpan; harus ada rekaman tinjauan (409 `RUN_AUDIT_CONFIRMATION_REQUIRES_REVIEW`) | `test_audit_result_requires_manage_permission_csrf_and_an_existing_review` |
| Pemisahan | outcome reviewer (`run_case_reviews`) dan hasil audit (`run_case_audit_confirmations`) tabel terpisah; hasil audit tidak pernah diturunkan dari outcome | `test_reviewer_outcome_never_becomes_an_audit_result_and_confirmation_is_recorded_separately` |
| Rate limit | `user_rate_limit("audit_confirmation")` (10/60 s per pengguna) dijalankan setelah izin dan CSRF; 429 + `Retry-After`; permintaan yang ditolak tidak menyimpan apa pun | `test_audit_confirmation_is_limited_per_user_and_rejected_requests_store_nothing` |

Matriks peran lengkap: `docs/role-permission-matrix.md`.

## 3. Sesi dan CSRF

* Cookie sesi `cir_session`: `HttpOnly`, `SameSite=Lax`, `Secure` (default `true`; `CIR_COOKIE_SECURE=false` hanya untuk HTTP lokal), path `/api/v1`, TTL absolut 8 jam (`CIR_SESSION_TTL_SECONDS`, 60 s–7 hari).
* Token sesi dan CSRF disimpan sebagai SHA-256; password scrypt (n=2^14, r=8, p=1), minimal 12 karakter.
* Login gagal dicatat (`login_failed`) tanpa username; pembandingan konstan-waktu; pengguna tidak dikenal tetap menjalankan scrypt.
* Menonaktifkan akun mencabut semua sesinya; logout mencabut sesi di server.
* Admin pertama hanya lewat CLI dengan `CIR_ADMIN_BOOTSTRAP_SECRET`, satu kali.
* Login dibatasi per alamat klien dan per jumlah gagal per username sebelum scrypt dijalankan (`backend/app/security/rate_limit.py`, `backend/app/api/routes/auth.py`; tes `test_failed_logins_for_one_username_are_limited_before_the_password_check`, `test_successful_login_resets_failures_and_client_address_limit_applies`). Kebijakan lengkap dan asumsi penerapan: `docs/api-contracts.md`.

File: `backend/app/security/auth.py`, `backend/app/security/dependencies.py`, `backend/app/api/routes/auth.py`.

## 4. Validasi dan visibilitas rujukan audit

* Validator: `AuditConfirmationMutation.validate_reference` di `backend/app/schemas/run_reviews.py` — 3–64 karakter `[A-Za-z0-9._/:-]`; menolak ≥ 9 digit (juga bila dipisah `.`/`/`/`:`/`-`), kata kunci rahasia/identifier, dan segmen > 20 karakter. Catatan audit memakai validasi pola sensitif yang sama dengan catatan tinjauan.
* Rujukan **tidak diverifikasi** ke sistem audit mana pun; disimpan sebagaimana diketik pengguna `review:manage` (dinyatakan di UI dan `docs/api-contracts.md`).
* **Visibilitas (least privilege):** rujukan, catatan audit, dan pencatat hanya dikembalikan kepada pemanggil dengan `review:manage` (`audit_lead`, `platform_admin`). Peran `review:read` lain (`verifikator`) menerima status `audit_result` saja, `audit_confirmations: []`, dan `audit_details_visible: false` pada GET maupun PATCH; UI menampilkan status dan keterangan bahwa rinciannya terbatas. Pemangkasan dilakukan di server (`_response` di `backend/app/api/routes/run_reviews.py`), bukan hanya di UI. `data_operator` tanpa `review:read` mendapat 403. Tes: `test_only_audit_management_roles_receive_the_audit_reference`, `test_audit_reference_is_not_readable_without_review_read`, dan E2E tes 2 (payload API dan halaman Case Review verifikator tidak memuat rujukan).
* Output: respons JSON; frontend React meng-escape teks; charset rujukan tidak memuat `<` atau `>`.

## 5. Integritas basis data, logging, dan konfigurasi

* Tulis hasil audit dalam satu transaksi `BEGIN IMMEDIATE`: cek kandidat, cek rekaman tinjauan, insert konfirmasi, insert event keamanan (`run_audit_confirmation_recorded`).
* Trigger SQLite menolak `UPDATE`/`DELETE` pada `run_case_audit_confirmations`, `run_case_review_events`, `run_review_security_audit_events` (tes: `UPDATE`/`DELETE` langsung gagal).
* **Batas basis data:** trigger hanya mencegah perubahan lewat koneksi SQL biasa. Siapa pun yang dapat menulis file SQLite dapat menghapus trigger, mengubah baris, atau mengganti file; trigger **bukan** penyimpanan audit yang tahan manipulasi. Kontrol yang diandalkan adalah izin OS: file dan direktori data hanya dapat dibaca/ditulis akun layanan API (lihat `docs/demo-deployment.md` §4), backup terpisah, dan untuk produksi log audit tamper-evident di luar host aplikasi.
* Tabel dibuat aditif (`CREATE TABLE/TRIGGER IF NOT EXISTS`); tidak ada migrasi destruktif.
* Error: validasi 422 tidak menggemakan nilai input; error tak terduga → 500 generik; error penyimpanan → pesan tetap (`backend/app/api/errors.py`).
* Aplikasi tidak menulis log aplikasi berisi payload; log akses server (uvicorn) memuat path URL dengan `run_id` dan `case_id` pseudonim (HMAC), bukan identifier mentah.
* Rahasia hanya dari environment (`CIR_FKRTL_PSEUDONYM_KEY`, `CIR_ADMIN_BOOTSTRAP_SECRET`); file `*.sqlite3`, `*.db`, `outputs/`, `data/` di-ignore Git.

## 6. Temuan tinjauan internal (bukan tinjauan independen)

Tinjauan internal 2026-10-26 atas kode saat ini. Keparahan memperhitungkan kemungkinan eksploitasi pada penerapan lokal prototipe dan pada produksi.

| # | Temuan | Diverifikasi pada kode | Keparahan | Penanganan |
|---|---|---|---|---|
| I-1 | Validator rujukan audit menerima deret digit terpisah tanda baca, kata kunci rahasia, dan token panjang | ya (sebelum perbaikan) | Sedang (privasi) | **Diperbaiki**; 10 tes regresi |
| I-2 | Tidak ada rate limiting/throttling, termasuk login dan endpoint tulis sensitif | ya (sebelum perbaikan) | Sedang | **Diperbaiki per proses**: limit login (alamat klien, gagal per username) dan penulisan review/hasil audit per pengguna, 429 + `Retry-After`; 9 tes. Sisa risiko: tidak terdistribusi antar worker/host dan tidak menahan serangan terdistribusi → batasi juga di edge; penundaan login akun lewat gagal per username (15 menit) diterima |
| I-3 | Trigger append-only dapat dilewati oleh pihak dengan akses tulis langsung ke file SQLite (mis. `DROP TRIGGER`) | ya, kontrol berada di dalam file yang sama | Sedang di produksi; bergantung kontrol host | Prasyarat produksi: izin file hanya untuk akun layanan, DB terpisah dari host pengguna, backup, log tamper-evident eksternal |
| I-4 | File SQLite dibuat dengan izin default OS; tidak ada penetapan mode eksplisit | ya | Rendah–Sedang | Konfigurasi penerapan (direktori data khusus akun layanan) |
| I-5 | Rujukan audit terbaca oleh peran `review:read` | ya (sebelum perbaikan) | Rendah | **Diperbaiki**: rincian hanya untuk `review:manage`, status tetap terlihat; tes API dan E2E |
| I-6 | Rujukan audit tidak diverifikasi eksternal | ya, by design | Informasional | Dinyatakan di UI/dokumen; integritas bergantung pada audit lead dan rekonsiliasi pilot |
| I-7 | TTL sesi absolut tanpa idle timeout | ya | Rendah | Pertimbangan produksi |
| I-8 | Tidak ada header keamanan (CSP, HSTS) dari API; frontend disajikan terpisah | ya | Rendah (prototipe lokal) | Atur di reverse proxy produksi |
| I-9 | Beberapa hasil audit untuk satu kasus dapat dicatat; yang terbaru menjadi `audit_result` | ya, by design (append-only) | Informasional | Semantik "terbaru berlaku" perlu disahkan pemilik proses |

Tidak ditemukan bypass otorisasi, CSRF, atau pemalsuan identitas pencatat pada endpoint hasil audit. Perubahan kode keamanan: I-1 (validator rujukan), I-2 (rate limit per proses), I-5 (pemangkasan rincian hasil audit di server). Jalur sesi (tanpa sesi, CSRF sesi lain, akun nonaktif) diuji tanpa perubahan kode.

## 7. Perintah verifikasi

| Perintah (dari `backend/` atau `frontend/`) | Hasil 2026-10-26 setelah perubahan terakhir |
|---|---|
| `.venv\Scripts\python -m pytest -q tests/test_rate_limit.py tests/test_audit_confirmation.py tests/test_run_scoped_reviews.py tests/test_workbench_integration.py tests/test_auth_rbac.py` | 64 passed |
| `.venv\Scripts\python -m pytest -q` | 353 passed |
| `npm run build` | exit 0 |
| `npx playwright test -c e2e/playwright.config.ts --retries=0` | 10 run berturut-turut (`attempt-2`), semua 4 passed |

Asumsi konfigurasi yang harus dicek peninjau: satu proses API (batas per proses), `CIR_COOKIE_SECURE=true` di balik HTTPS, uvicorn `--proxy-headers` hanya untuk proxy tepercaya, direktori data hanya untuk akun layanan (`docs/demo-deployment.md`).

## 8. Checklist dan catatan peninjau independen

Checklist minimum:

- [ ] Otorisasi semua route tulis run-scoped (`review:write`, `review:manage`) dan route baca (`review:read`, `runs:results:read`)
- [ ] CSRF pada semua metode non-GET; pengikatan token ke sesi
- [ ] Siklus hidup sesi: login, kedaluwarsa, logout, nonaktivasi akun, atribut cookie
- [ ] Validasi input rujukan dan catatan; tidak ada gema input pada error
- [ ] Pemisahan outcome reviewer dan hasil audit; tidak ada jalur yang menurunkan satu dari yang lain
- [ ] Transaksi dan trigger append-only; dampak akses file langsung (I-3)
- [ ] Penanganan rahasia dan konfigurasi; tidak ada rahasia di repository
- [ ] Kecukupan rate limit per proses (I-2) untuk target penerapan dan kebutuhan limit di edge
- [ ] Pemangkasan rincian hasil audit untuk peran tanpa `review:manage` pada semua respons review (I-5)
- [ ] Izin file/direktori data dan cadangan sesuai `docs/demo-deployment.md` (I-3, I-4)
- [ ] Verifikasi bahwa data BPJS nyata tidak dapat dipilih atau diunggah lewat API

Templat catatan (diisi peninjau; **jangan diisi oleh tim implementasi**):

| Field | Isi |
|---|---|
| Nama/identitas peninjau | |
| Peran dan kompetensi | |
| Independensi (tidak terlibat implementasi) | |
| Lingkup dan versi yang ditinjau (commit/tanggal) | |
| Tanggal tinjauan | |

| # | Temuan | Keparahan | Disposisi (perbaiki / terima risiko / tidak berlaku) | Pemilik | Verifikasi ulang |
|---|---|---|---|---|---|
| | | | | | |

| Sign-off | Isi |
|---|---|
| Temuan pemblokir rilis terselesaikan atau diterima formal oleh pemilik | |
| Verifikasi lanjutan lulus | |
| Tanda tangan peninjau / tanggal | |
| Tanda tangan pemilik risiko / tanggal | |
