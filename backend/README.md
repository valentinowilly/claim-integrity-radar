# Backend lokal

Backend minimal memakai FastAPI dan Uvicorn. Endpoint `/health` hanya menguji bahwa proses API merespons; endpoint ini tidak memeriksa konfigurasi atau isi dataset.

## Persyaratan

Python **3.10 atau lebih baru**. Rentang dependensi aplikasi dan pengujian tercantum di `requirements.txt`.

## Menyiapkan dan menjalankan

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

Server berjalan di `http://127.0.0.1:8000`; health check tersedia di `http://127.0.0.1:8000/health`.

## Tes

```powershell
cd backend
python -m pytest
```

Tes menggunakan `TestClient` dan memeriksa kontrak respons serta bahwa modul aplikasi tidak mengimpor pembaca data atau skrip analisis lama. Tes tidak membutuhkan dataset BPJS.

## Alur tinjauan auditor (demo lokal)

Status tinjauan disimpan terpisah dari sumber analitik dalam SQLite standard library. Default file adalah `backend/outputs/review_workflow.sqlite3` (direktori `outputs/` diabaikan Git). Override dengan environment variable `CIR_REVIEW_DB_PATH`; path relatif dihitung dari working directory proses backend. Database dibuat saat endpoint review atau daftar kasus yang membaca status dipanggil. `GET /health` tidak membuat atau memeriksa database.

Status alur: `pending_review`, `needs_more_evidence`, `not_substantiated`, dan `escalated`. Tiap update ditambahkan ke riwayat; status hanya mengatur tindak lanjut dan bukan penetapan fraud. Aktor review berasal dari sesi backend yang tervalidasi. Jangan memasukkan identitas nyata, token peserta, signature klaim, atau informasi kesehatan pada catatan. Role dan kebijakan tetap baseline prototipe, bukan kontrol operasional BPJS.

Untuk tes, aplikasi dibuat dengan path SQLite terisolasi di direktori temporer; tes tidak menggunakan file runtime default.

## Autentikasi dan bootstrap admin (demo lokal)

Password di-hash dengan scrypt + salt acak. Token sesi acak hanya disimpan sebagai hash SQLite, dikirim lewat cookie `HttpOnly`, `SameSite=Lax`, dan secara default `Secure`; permintaan mutasi memakai cookie/header CSRF. Jangan menonaktifkan `Secure` selain untuk pengembangan lokal HTTP yang terisolasi. Default masa berlaku sesi 8 jam; konfigurasi: `CIR_SESSION_TTL_SECONDS`, `CIR_COOKIE_SECURE`, dan `CIR_AUTH_DB_PATH`. Database auth secara default berbagi file metadata lokal dengan review, bukan dengan sumber analitik. `GET /health` tidak membuat database.

Tidak ada akun/password bawaan atau registrasi publik. Untuk membuat administrator pertama kali, set secret kuat sementara di environment, lalu jalankan dari folder `backend`:

```powershell
$env:CIR_ADMIN_BOOTSTRAP_SECRET = "<secret-sementara-dari-operator>"
python -m app.security.bootstrap_admin
Remove-Item Env:CIR_ADMIN_BOOTSTRAP_SECRET
```

CLI meminta username, secret bootstrap, dan password baru melalui prompt (password tidak diecho). Prosedur hanya berhasil sekali per database. Simpan SQLite lokal di lokasi yang diabaikan Git dan lindungi akses filesystem. Jangan gunakan untuk akun atau data operasional nyata sebelum kebijakan sesi, distribusi secret, backup, audit, dan kontrol akses disetujui security/pemilik proses.

Role sementara: `platform_admin`, `data_operator`, `verifikator`, `audit_lead`. Backend menegakkan permission pada setiap endpoint; frontend hanya menyembunyikan navigasi sebagai bantuan UX. Scope assignment untuk cases/runs belum tersedia; metadata batch sintetis bersifat shared sesuai permission. Event yang ada mencakup bootstrap, autentikasi, pencabutan/expiry sesi, perubahan akun/review, impor batch, dan AnalysisRun; belum ada endpoint pembacaan security audit.

## DataBatch CSV sintetis (P0 Stage 3)

Importer menerima hanya CSV fitur skema `synthetic-claims-v1` dengan mapping `synthetic-canonical-v1`; ini bukan import BPJS atau `.dta`. Exporter programatis tersedia melalui `app.data_sources.synthetic_csv.export_synthetic_csv(records)`. Ground-truth labels dikeluarkan dari ekspor dan tidak diterima oleh skema. Import membutuhkan login `data_operator`, header deklarasi `X-Data-Classification: synthetic_only`, versi schema/mapping, `X-Batch-Key` berawalan `synthetic-` (jangan isi informasi sensitif), serta CSRF token. Deklarasi klasifikasi adalah pernyataan pemanggil dan bukan validasi independen atas asal nilai.

Database terpisah: default `backend/outputs/data_batches.sqlite3`, override dengan `CIR_BATCH_DB_PATH`. Ukuran default maksimum 50 MiB dan 120.000 baris; override tervalidasi: `CIR_BATCH_MAX_BYTES` (1 KiB–512 MiB) dan `CIR_BATCH_MAX_ROWS` (1–1.000.000). Tidak ada byte CSV yang disimpan. Hanya record sintetis tervalidasi disimpan sebagai record anak; API mengembalikan metadata dan ringkasan error agregat tanpa record, participant token, checksum, atau nilai baris. `ready`/`ready_with_warnings` immutable. Import identik pada batch key/schema/mapping yang sama memakai versi yang sama; perubahan konten membuat versi baru. Validasi gagal menghasilkan `rejected` tanpa baris normalized parsial.

`GET /health` tetap tidak membuka database apa pun. Akses metadata batch bersifat shared untuk role yang diberi `batches:read`; assignment/scope belum ada. Ini hanya baseline prototipe synthetic-only dan bukan kontrol akses operasional. Eksekusi AnalysisRun batch sintetis dijelaskan pada bagian berikut.

## AnalysisRun persisten (P0 Stage 4)

`POST /api/v1/runs` menjalankan pipeline analitik yang sama atas DataBatch `synthetic-claims-v1` siap. Adapter memeriksa schema/mapping/version/checksum dan meneruskan salinan kolom fitur saja; facility capacity diadaptasi dari `facility_id` dan `facility_daily_capacity` yang berulang dan harus konsisten. Ground truth dan raw CSV tidak dipakai. Hasil run menghapus token peserta dan atribut token dari daftar atribut yang cocok.

Run manifest, result JSON, dan event keamanan memakai file database batch yang sama (`CIR_BATCH_DB_PATH`, default `backend/outputs/data_batches.sqlite3`); tidak ada `CIR_RUN_DB_PATH`. Tabel run dibuat saat route run pertama dipakai dan tidak diinisialisasi oleh health check. Database auth/review tidak di-reset. Satu batch immutable dapat digunakan banyak run. GET run hanya membaca snapshot tersimpan. Status `running` dicatat sebelum eksekusi, lalu terminal `completed`, `partial`, atau `failed`. Retry hanya untuk failed; membuat run baru dan mempertahankan hasil lama. Run terputus dapat tetap `running`; pemulihan otomatis belum ada.

Permission sementara: `runs:write` hanya `data_operator`; `runs:read` data operator/verifikator/audit lead untuk metadata/status; `runs:results:read` verifikator/audit lead untuk hasil. Administrator tidak mendapat akses hasil klaim otomatis. Scope tetap shared synthetic tanpa assignment, bukan kontrol operasional. Versi detector suite belum didefinisikan source sehingga dicatat null; versi scoring/priority berasal dari konstanta aktual. Run event disimpan lokal, belum ada endpoint pembacaan audit log. UI belum mengintegrasikan pemilihan batch dan alur run.
