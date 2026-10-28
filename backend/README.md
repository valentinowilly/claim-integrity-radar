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

## Database operasional

Tanpa konfigurasi, store memakai berkas SQLite lokal. Untuk produksi set `CIR_DATABASE_URL=postgresql://…` (semua store memakai database itu), lalu jalankan `python -m scripts.db_migrate`. Migrasi data lama: `python -m scripts.migrate_sqlite_to_postgres --batch-db … --auth-db … --review-db … --dry-run`, lalu tanpa `--dry-run`. Konfigurasi, cutover, backup, dan rollback: `docs/database-postgresql.md`; contoh variabel di `.env.example`.

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

Password di-hash dengan scrypt + salt acak. Token sesi acak hanya disimpan sebagai hash SQLite, dikirim lewat cookie `HttpOnly`, `SameSite=Lax`, dan secara default `Secure`; permintaan mutasi memakai cookie/header CSRF. Jangan menonaktifkan `Secure` selain untuk pengembangan lokal HTTP yang terisolasi. Default masa berlaku sesi 8 jam; konfigurasi: `CIR_SESSION_TTL_SECONDS`, `CIR_COOKIE_SECURE`, dan `CIR_AUTH_DB_PATH`. Rate limit login dan penulisan review: lihat `docs/api-contracts.md` (endpoint hasil audit) dan variabel `CIR_RATE_LIMIT_*`; hitungan berlaku per proses. Database auth secara default berbagi file metadata lokal dengan review, bukan dengan sumber analitik. `GET /health` tidak membuat database.

Tidak ada akun/password bawaan atau registrasi publik. Untuk membuat administrator pertama kali, set secret kuat sementara di environment, lalu jalankan dari folder `backend`:

```powershell
$env:CIR_ADMIN_BOOTSTRAP_SECRET = "<secret-sementara-dari-operator>"
python -m app.security.bootstrap_admin
Remove-Item Env:CIR_ADMIN_BOOTSTRAP_SECRET
```

Untuk demonstrasi lokal saja, tersedia jalur eksplisit dengan akun tetap `admin` / `admin123`. Jalur ini tidak aktif otomatis, tetap membutuhkan bootstrap secret, dan hanya berjalan jika `CIR_ENV=development`:

```powershell
$env:CIR_ENV = "development"
$env:CIR_ADMIN_BOOTSTRAP_SECRET = Read-Host "Buat secret bootstrap sementara yang kuat"
python -m app.security.bootstrap_admin --local-demo
Remove-Item Env:CIR_ADMIN_BOOTSTRAP_SECRET
Remove-Item Env:CIR_ENV
```

Password pendek tersebut hanya diizinkan oleh flag `--local-demo` pada environment development dan tetap di-hash dengan scrypt. Jalur bootstrap normal dan endpoint provisioning akun tetap menerapkan password minimal 12 karakter. Jika akun administrator sudah ada, command gagal dan tidak mereset atau menimpanya.

CLI meminta username, secret bootstrap, dan password baru melalui prompt (password tidak diecho). Prosedur hanya berhasil sekali per database. Simpan SQLite lokal di lokasi yang diabaikan Git dan lindungi akses filesystem. Jangan gunakan untuk akun atau data operasional nyata sebelum kebijakan sesi, distribusi secret, backup, audit, dan kontrol akses disetujui security/pemilik proses.

Role sementara: `platform_admin`, `data_operator`, `verifikator`, `audit_lead`. Backend menegakkan permission pada setiap endpoint; frontend hanya menyembunyikan navigasi sebagai bantuan UX. Scope assignment untuk cases/runs belum tersedia; metadata batch sintetis bersifat shared sesuai permission. Event yang ada mencakup bootstrap, autentikasi, pencabutan/expiry sesi, perubahan akun/review, impor batch, dan AnalysisRun; belum ada endpoint pembacaan security audit.

## DataBatch CSV sintetis (P0 Stage 3)

Importer menerima hanya CSV fitur skema `synthetic-claims-v1` dengan mapping `synthetic-canonical-v1`; ini bukan import BPJS atau `.dta`. Exporter programatis tersedia melalui `app.data_sources.synthetic_csv.export_synthetic_csv(records)`. Ground-truth labels dikeluarkan dari ekspor dan tidak diterima oleh skema. Import membutuhkan login `data_operator`, header deklarasi `X-Data-Classification: synthetic_only`, versi schema/mapping, `X-Batch-Key` berawalan `synthetic-` (jangan isi informasi sensitif), serta CSRF token. Deklarasi klasifikasi adalah pernyataan pemanggil dan bukan validasi independen atas asal nilai.

Database terpisah: default `backend/outputs/data_batches.sqlite3`, override dengan `CIR_BATCH_DB_PATH`. Ukuran default maksimum 50 MiB dan 120.000 baris; override tervalidasi: `CIR_BATCH_MAX_BYTES` (1 KiB–512 MiB) dan `CIR_BATCH_MAX_ROWS` (1–1.000.000). Tidak ada byte CSV yang disimpan. Hanya record sintetis tervalidasi disimpan sebagai record anak; API mengembalikan metadata dan ringkasan error agregat tanpa record, participant token, checksum, atau nilai baris. `ready`/`ready_with_warnings` immutable. Import identik pada batch key/schema/mapping yang sama memakai versi yang sama; perubahan konten membuat versi baru. Validasi gagal menghasilkan `rejected` tanpa baris normalized parsial.

`GET /health` tetap tidak membuka database apa pun. Akses metadata batch bersifat shared untuk role yang diberi `batches:read`; assignment/scope belum ada. Ini hanya baseline prototipe synthetic-only dan bukan kontrol akses operasional. Eksekusi AnalysisRun batch sintetis dijelaskan pada bagian berikut.

### Provider analitik dan adapter FKRTL lokal

`app.data_sources.providers.FeatureSourceProvider` menyediakan batas eksplisit untuk canonical feature records. `SyntheticDemoProvider` tetap menjadi default untuk jalur demo; `SyntheticBatchProvider` digunakan oleh AnalysisRun dari batch `synthetic_csv`. `build_analytics_snapshot_from_provider()` menjalankan pipeline terkoordinasi pada provider yang dipilih caller tepercaya. Tidak ada route API yang menerima nama/path provider.

Adapter `.dta` berada di `scripts/fkrtl_dta_provider.py`, bukan sebagai sumber API/runtime aktif. Ia hanya dapat dibuat melalui pemanggilan lokal eksplisit dengan path dan key pseudonim lokal, dan harus diberi klasifikasi sumber eksplisit. Tes memberi label `synthetic_fixture`; tidak ada dataset BPJS aktual yang dibuka. Reader menggunakan SQLite sementara berisi digest HMAC case reference untuk pemeriksaan duplikasi lintas chunk dan menghapus scratch pada akhir/error. Reader masih memuat chunk sekarang, sedangkan provider `.dta` menahan seluruh fitur untuk menjalankan pemeriksa; pengukuran ini belum membuktikan kelayakan pipeline penuh skala target. Sampel FKRTL hanya dapat dijalankan sebagai AnalysisRun melalui sumber lokal terkonfigurasi di bawah; `.dta` tetap tidak dapat diunggah melalui API.

### Sampel FKRTL BPJS lokal sebagai AnalysisRun

Sumber `bpjs_fkrtl_local` membaca **satu** file `202403_fkrtl.dta` dari path yang dikonfigurasi di environment proses backend (tidak di kode, tidak dari request). File dibuka read-only, hanya kolom allow-list (`PSTV01`, `FKL02`–`FKL09`, `FKL13`, `FKL16`, `FKL18`, `FKL19`, `FKL30`–`FKL32`, kode tambahan khusus `FKL33`/`35`/`38`/`41`/`44`, `FKL47`) yang dibaca; `FKL47` hanya disimpan sebagai nominal tagih provider belum terverifikasi untuk subset rekonsiliasi (bukan fitur detektor/ML), dan `FKL48` tidak pernah dibaca. `PSTV01`+`FKL02` di-HMAC menjadi `case_…` dengan kunci lokal; ID mentah tidak disimpan atau dikirim. Run mendaftarkan DataBatch metadata-only (tanpa baris) lalu memakai pipeline, penyimpanan run, dan review run-scoped yang sama dengan CSV sintetis.

Sinyal utama: `repeat_billing_candidate` dengan profil `repeat-service-v1` — kunjungan berbeda dari peserta yang sama dengan tanggal datang, diagnosis primer, INA-CBG, dan prosedur identik; prosedur kosong berarti tidak dinilai. Wilayah, kategori fasilitas, dan diagnosis masuk hanya ditampilkan sebagai konteks (sama/berbeda/tidak tercatat), bukan syarat kandidat; nilai tagih tidak dibandingkan. Ini kandidat tinjauan, bukan bukti fraud. Tidak ada ranking fasilitas (tidak ada ID fasilitas terverifikasi), dan sampel tidak berlabel sehingga tidak ada klaim akurasi.

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt          # menambah pandas
$env:BPJS_FKRTL_SAMPLE_PATH = "<path lokal ke 202403_fkrtl.dta>"
$env:CIR_FKRTL_PSEUDONYM_KEY = python -c "import secrets; print(secrets.token_hex(32))"  # simpan lokal; mengganti kunci mengubah case_id
$env:BPJS_FKRTL_DATE_FROM = "2024-03-04"           # wajib; jendela tanggal datang FKL03, inklusif
$env:BPJS_FKRTL_DATE_TO = "2024-03-10"             # wajib; 7 hari ≈ 35.565 baris pada sampel 202403
$env:BPJS_FKRTL_MAX_ROWS = "50000"                 # opsional; batas baris terpilih. Jendela lebih besar GAGAL, tidak dipotong
$env:BPJS_FKRTL_SECONDARY_PATH = "<path lokal ke 202405_diagnosissekunder.dta>"  # opsional; diagnosis sekunder per kunjungan
python -m scripts.fkrtl_local_smoke                # opsional: hanya mencetak agregat, tidak menyimpan
python -m scripts.fkrtl_repeat_reconciliation      # opsional: validasi adapter + rekonsiliasi definisi repeat (agregat, ke outputs/ yang di-ignore)
python -m uvicorn app.main:app --reload
```

Sebelum run, validasi sumber dari kartu FKRTL di halaman Claim Data (tombol *Validate Source*, atau `POST /api/v1/sources/fkrtl-local/validation`): laporan agregat kolom, nilai kosong, tanggal, duplikasi kunjungan, dan prasyarat pemeriksaan; run FKRTL hanya dapat dibuat setelah validasi yang berlaku dan tidak gagal untuk berkas dan konfigurasi saat ini (sekitar 2,5 menit pada sampel penuh; hasil validasi tersimpan dan tetap berlaku setelah restart selama berkas dan konfigurasi tidak berubah).

Run CSV sintetis menjalankan peringkat anomali unsupervised per run (Isolation Forest, `app/analytics/ml_anomaly.py`). **Run FKRTL memakai model yang dilatih offline** (`app/analytics/ml_model.py`, versi `cir-iforest-fkrtl-v2`): artefak di `backend/models/cir-iforest-fkrtl-v2/` (`model.joblib`, `reference.json` berisi tabel frekuensi kode dengan hitungan < 5 disupresi dan statistik agregat, `manifest.json` berisi checksum SHA-256 yang diperiksa sebelum model dimuat). Run hanya memuat artefak dan menilai record; tidak ada pelatihan per permintaan. Lokasi lain dapat diatur dengan `CIR_ML_MODEL_DIR`. Bila artefak hilang atau tidak valid, `ml_anomaly.status` = `unavailable` dengan `error_code`, dan sinyal aturan tetap berjalan. Skor = anomali relatif terhadap data latih (lebih tinggi = lebih tidak biasa), bukan probabilitas fraud dan tanpa klaim akurasi (tidak ada label).

Berkas pendamping di folder model (lokal, tidak di-commit; dibuat dari sumber FKRTL terkonfigurasi, hanya kamus kode atau hitungan agregat dengan ambang ≥ 5):

```powershell
python -m scripts.export_category_labels       # nama wilayah dan kategori faskes (category_labels.json)
python -m scripts.export_code_names            # nama diagnosis ICD-10 dan INA-CBG (code_names.json)
python -m scripts.export_special_reference     # pasangan INA-CBG x kode tambahan khusus, di luar jendela analisis (special_reference.json)
python -m scripts.check_claim_detail_rules_real  # hitungan agregat pemeriksaan diagnosis sekunder/tambahan khusus pada jendela
```

```powershell
# Latih ulang dari sumber FKRTL terkonfigurasi (path dan kunci dari environment seperti di atas).
# Jendela latih harus berakhir sebelum jendela evaluasi/demo.
python -m scripts.train_ml_model --date-from 2024-02-05 --date-to 2024-03-03
# Evaluasi pada jendela tertahan BPJS_FKRTL_DATE_FROM/TO (agregat ke outputs/benchmarks/, di-ignore Git)
python -m scripts.evaluate_ml_model --seeds 1-3 --save
```

Validasi sumber FKRTL berjalan sebagai job latar belakang (`POST` → `202`, UI memantau progres); run hanya dapat dibuat setelah validasi terakhir selesai dan tidak gagal. Run lama yang tersimpan sebelum baris per kasus tersedia tetap dapat dibuka; untuk membaca halamannya tanpa mem-parse snapshot penuh, jalankan sekali `python -m scripts.backfill_run_case_rows` (opsional `--database PATH`, `--dry-run`; hanya menambah baris turunan).

Lalu di UI: login sebagai `data_operator` → **Data Klaim** → kartu "Sampel FKRTL BPJS (lokal)" → **Analisis sampel FKRTL**; buka hasil sebagai verifikator/audit lead dan tinjau kandidat seperti biasa. Bila konfigurasi kurang, kartu dan `POST /api/v1/runs` menampilkan kode masalah (`FKRTL_SOURCE_NOT_CONFIGURED`, `FKRTL_SOURCE_FILE_UNAVAILABLE`, `FKRTL_READER_UNAVAILABLE`, `FKRTL_PSEUDONYM_KEY_INVALID`, `FKRTL_CONFIGURATION_INVALID`, `FKRTL_DATE_WINDOW_NOT_CONFIGURED`, `FKRTL_WINDOW_EXCEEDS_CAP`, `FKRTL_SOURCE_READ_FAILED`). Hasil run (case reference pseudonim dan nama atribut, tanpa nilai) tersimpan di SQLite lokal `outputs/` yang diabaikan Git. Seleksi baris memakai **jendela tanggal datang (FKL03) inklusif**: seluruh file dipindai per chunk dan hanya baris di dalam jendela yang dipetakan; hasilnya sama untuk ukuran chunk dan urutan file apa pun. Batas, jumlah baris terpilih, dan baris yang dikecualikan tercatat di `configuration.source.selection`. Hasil hanya mewakili jendela itu, bukan seluruh sampel. Karena kunci repeat dan near-duplicate memuat tanggal datang, pasangan di dalam jendela lengkap tercakup; fitur frekuensi ML dan jumlah kunjungan per peserta hanya menggambarkan jendela. Pengukuran lokal (agregat): volume 2024 ≈ 5–7 ribu baris/hari, 7 hari maks. 38.410 baris; jendela 2024-03-04..10 = 35.565 baris, baca ≈ 23 s, pipeline ≈ 32 s. **FKL30 kosong**: kamus tidak mendefinisikan arti nilai kosong (41,7% baris berisi string kosong), sehingga record tanpa prosedur tetap *belum dinilai* oleh pemeriksaan repeat. Urutan analitik near-duplicate memakai digest fitur non-identitas (seed `ordering_seed`), bukan case ID pseudonim, sehingga kunci pseudonim tidak memengaruhi pasangan yang diperiksa.

### Pembacaan catatan klinis (tahap 2)

Bawaan: model bahasa lokal lewat [Ollama](https://ollama.com) di komputer/server yang sama (sesuai tata kelola AI BPJS: data tidak dikirim ke layanan AI publik). Tanpa model, tombol pembacaan tetap bekerja dengan pembacaan cadangan (aturan teks).

```powershell
$env:OLLAMA_MODELS = "D:\ollama-models"          # lokasi model (disk dengan ruang cukup)
ollama pull qwen3:4b                              # ±2,5 GB; jawaban ±40 dtk per klaim di CPU laptop
$env:CIR_CLINICAL_AI_PROVIDER = "ollama"          # atau "anthropic" (akun enterprise, ANTHROPIC_API_KEY)
$env:CIR_CLINICAL_AI_MODEL = "qwen3:4b"           # opsional
$env:CIR_OLLAMA_URL = "http://127.0.0.1:11434"    # opsional
$env:CIR_CLINICAL_AI = "off"                      # opsional: matikan model bahasa (cadangan tetap jalan)
python -m scripts.evaluate_clinical_reader --per-label 8   # ukur pembacaan pada klaim demo berlabel
python -m scripts.evaluate_clinical_reader --set independent  # 16 catatan tulisan tangan (scripts/clinical_reader_cases.py)
```

## AnalysisRun persisten (P0 Stage 4)

`POST /api/v1/runs` menjalankan pipeline analitik yang sama atas DataBatch `synthetic-claims-v1` siap. Adapter memeriksa schema/mapping/version/checksum dan meneruskan salinan kolom fitur saja; facility capacity diadaptasi dari `facility_id` dan `facility_daily_capacity` yang berulang dan harus konsisten. Ground truth dan raw CSV tidak dipakai. Hasil run menghapus token peserta dan atribut token dari daftar atribut yang cocok.

Run manifest, result JSON, dan event keamanan memakai file database batch yang sama (`CIR_BATCH_DB_PATH`, default `backend/outputs/data_batches.sqlite3`); tidak ada `CIR_RUN_DB_PATH`. Tabel run dibuat saat route run pertama dipakai dan tidak diinisialisasi oleh health check. Database auth/review tidak di-reset. Satu batch immutable dapat digunakan banyak run. GET run hanya membaca snapshot tersimpan. Status `running` dicatat sebelum eksekusi, lalu terminal `completed`, `partial`, atau `failed`. Retry hanya untuk failed; membuat run baru dan mempertahankan hasil lama. Run terputus dapat tetap `running`; pemulihan otomatis belum ada.

Permission sementara: `runs:write` hanya `data_operator`; `runs:read` data operator/verifikator/audit lead untuk metadata/status; `runs:results:read` verifikator/audit lead untuk hasil. Administrator tidak mendapat akses hasil klaim otomatis. Scope tetap shared synthetic tanpa assignment, bukan kontrol operasional. Versi detector suite belum didefinisikan source sehingga dicatat null; versi scoring/priority berasal dari konstanta aktual. Run event disimpan lokal, belum ada endpoint pembacaan audit log. UI belum mengintegrasikan pemilihan batch dan alur run.
