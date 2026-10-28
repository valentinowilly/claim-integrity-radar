# Database operasional PostgreSQL

## 1. Arsitektur

* **Satu konfigurasi:** `CIR_DATABASE_URL=postgresql://…`. Bila diset, **semua** store memakai satu database PostgreSQL itu: autentikasi, review legacy, batch, AnalysisRun beserta hasil, baris per kasus dan ringkasan, review run, riwayat review, konfirmasi audit, validasi sumber, dan job validasi. Path SQLite (`CIR_*_DB_PATH`) diabaikan, sehingga tidak ada dua database operasional yang sama-sama menerima tulisan. Bila kosong, store memakai berkas SQLite seperti sebelumnya (pengembangan lokal, tes, dan sisi sumber migrasi).
* **Lapisan koneksi** (`backend/app/db.py`): pool `psycopg_pool` per proses (`CIR_DATABASE_POOL_MAX`, default 10; `CIR_DATABASE_POOL_TIMEOUT_SECONDS`, default 10). Store tetap memakai SQL yang sama; lapisan ini menerjemahkan placeholder `?`, `INSERT OR IGNORE`, `instr`, dan `BEGIN IMMEDIATE`. Yang terakhir menjadi `pg_advisory_xact_lock` pada satu kunci aplikasi, setara kunci tulis berkas SQLite, untuk seluruh worker. Kegagalan koneksi menjadi 503 terkendali tanpa URL atau kredensial.
* **Skema:** migrasi berversi di `backend/app/db_migrations/NNNN_*.sql`, tercatat dengan SHA-256 di `schema_migrations`. Migrasi yang sudah diterapkan lalu diubah akan ditolak. Saat ini ada `0001_initial`, `0002_event_insertion_order`, dan `0003_data_migration_log`; semuanya aditif. Aplikasi **tidak** membuat, menghapus, atau mereset tabel. Saat startup aplikasi hanya memeriksa versi skema dan menolak start dengan pesan aman bila skema belum sesuai atau server tidak dapat dihubungi.
* **Imutabilitas:** semua trigger SQLite memiliki padanan PL/pgSQL dengan aturan yang sama:
  * batch ready imutabel;
  * transisi run hanya `running` → terminal;
  * hasil run, baris kasus, dan ringkasan tidak dapat di-update/delete, dan baris kasus ditulis sekali;
  * riwayat review, konfirmasi audit, event keamanan, konfigurasi action policy, dan log migrasi bersifat append-only.

  JSON dan timestamp tetap `TEXT`, sehingga hasil tersimpan dan respons API identik byte-per-byte dengan SQLite.
* **Kueri:** ringkasan, antrean (pagination, urutan, filter indikator, pencarian, dan filter review lewat JOIN), detail, dan pemeriksaan review dibaca dari `analysis_run_cases` dan `analysis_run_result_views` berindeks; tidak ada parse snapshot penuh per permintaan.
* **Job validasi lintas worker** (`app/services/validation_jobs.py`):
  * Klaim job berjalan dalam satu transaksi dengan advisory lock: pulihkan job basi, periksa job aktif, sisipkan job baru. Indeks unik parsial `one_active_validation_job` menjamin di level database bahwa paling banyak satu job `pending`/`running` ada.
  * Worker pemilik (`owner`) memperbarui `heartbeat_at` setiap 15 detik dan pada setiap progres. Job dengan heartbeat lebih lama dari `CIR_VALIDATION_JOB_STALE_SECONDS` (default 120) ditandai `FKRTL_VALIDATION_INTERRUPTED` saat startup, saat job diminta, atau saat state dibaca. Job worker lain yang masih hidup tidak ikut ditandai.
  * Laporan dan status `completed` ditulis dalam satu transaksi, hanya selama worker masih memiliki job tersebut.
  * Thread validasi **tidak** durable: job yang terputus tidak dilanjutkan dan harus diminta ulang.

## 2. Setup lokal

```powershell
cd backend
.venv\Scripts\python -m pip install -r requirements.txt     # psycopg[binary], psycopg-pool
# Buat database dan pengguna aplikasi (contoh; jalankan sebagai admin PostgreSQL):
#   CREATE ROLE cir_app LOGIN PASSWORD '<rahasia>';  CREATE DATABASE cir OWNER cir_app;
$env:CIR_DATABASE_URL = "postgresql://cir_app:<rahasia>@127.0.0.1:5432/cir"   # set di environment layanan, bukan di repo
python -m scripts.db_migrate --check     # status; exit 1 bila belum mutakhir
python -m scripts.db_migrate             # terapkan migrasi yang tertunda
python -m uvicorn app.main:app           # satu atau beberapa worker memakai database yang sama
```

Jangan menulis URL berisi password ke shell history, log, atau berkas di repository. `backend/.env.example` hanya berisi placeholder.

## 3. Migrasi data SQLite → PostgreSQL

Skrip: `python -m scripts.migrate_sqlite_to_postgres --batch-db <CIR_BATCH_DB_PATH> --auth-db <CIR_AUTH_DB_PATH> --review-db <CIR_REVIEW_DB_PATH> [--dry-run | --verify-only]`. Pakai path yang benar-benar dipakai layanan; defaultnya `backend/outputs/data_batches.sqlite3`, dan untuk auth serta review `backend/outputs/review_workflow.sqlite3` (berkas yang sama). Bila satu berkas berisi auth dan review, berkas itu dibaca sekali.

* **Sumber** dibuka read-only (`mode=ro`) dan tidak pernah diubah.
* **Yang disalin:**
  * pengguna, metadata auth, event keamanan/audit, dan review legacy;
  * batch CSV sintetis beserta record-nya, dan action policy;
  * run dengan `result_json` identik byte-per-byte, baris kasus, dan ringkasan;
  * review run, riwayat review, dan konfirmasi audit;
  * validasi dan job validasi.

  ID, timestamp, relasi, status, nilai numerik, dan urutan sisip (rowid → kolom `rowid`) dipertahankan.
* **Sengaja tidak disalin atau diubah:**
  * Record batch FKRTL (data mentah) membuat migrasi **ditolak**; berkas `.dta` tidak pernah dibaca.
  * Sesi tidak disalin, jadi pengguna login ulang.
  * Fingerprint validasi dikosongkan, sehingga setelah cutover setiap run FKRTL wajib divalidasi ulang.
  * Job `pending`/`running` menjadi `failed` dengan `FKRTL_VALIDATION_INTERRUPTED` pada heartbeat terakhirnya.
  * `security_audit_events` dari berkas auth dan review digabung, dengan urutan per sumber dipertahankan.
* **Transaksi tunggal:** semua data disalin lalu diverifikasi (jumlah baris, digest kanonis per tabel, SHA-256 setiap `result_json`) sebelum commit dan dicatat di `data_migration_runs`. Bila gagal, tidak ada yang ditulis dan pesan galatnya aman. Trigger imutabilitas tetap aktif: run terminal ditulis melalui siklus normalnya (running → hasil → baris kasus → terminal).
* **Idempoten:** baris yang sudah ada dilewati bila identik, dan migrasi dibatalkan bila ada baris yang berbeda. `--dry-run` menyalin dan memverifikasi lalu rollback; `--verify-only` hanya membandingkan.
* **Run lama tanpa baris per kasus** tetap dapat dibaca. Setelah migrasi, jalankan `python -m scripts.backfill_run_case_rows` dengan `CIR_DATABASE_URL` diset.

## 4. Prosedur cutover

1. Hentikan API (tidak ada tulisan baru ke SQLite). Salin semua berkas SQLite ke lokasi pemulihan dan catat SHA-256-nya.
2. Siapkan database kosong, lalu `python -m scripts.db_migrate` dan `--check`.
3. `python -m scripts.migrate_sqlite_to_postgres … --dry-run`; periksa `verification.ok` dan jumlah per tabel.
4. Jalankan tanpa `--dry-run`, lalu ulangi dengan `--verify-only`.
5. `python -m scripts.backfill_run_case_rows` (opsional, untuk run lama).
6. Start API dengan `CIR_DATABASE_URL`. Smoke test: login, daftar run, ringkasan, antrean, detail kasus, review; lalu validasi sumber FKRTL sebelum run baru (validasi lama tidak berlaku).
7. Simpan berkas SQLite asli sampai verifikasi selesai dan backup PostgreSQL pertama berhasil dipulihkan di lingkungan uji.

## 5. Backup, verifikasi, rollback

* **Backup:** `pg_dump --format=custom --file cir-<tanggal>.dump <db>`, dijadwalkan dan dienkripsi di penyimpanan terbatas. Uji pemulihan secara berkala dengan `pg_restore` ke database uji, lalu `python -m scripts.db_migrate --check` dan smoke test.
* **Verifikasi kapan saja:** `--verify-only` terhadap salinan SQLite yang disimpan, ditambah `data_migration_runs` (digest dan jumlah).
* **Rollback:** hentikan API, kosongkan `CIR_DATABASE_URL`, lalu kembalikan path SQLite ke salinan pemulihan. Data yang ditulis ke PostgreSQL setelah cutover **tidak** ikut kembali; catat dan putuskan penanganannya sebelum rollback. Database PostgreSQL tidak dihapus oleh rollback.

## 6. Tes

* `CIR_TEST_DATABASE_URL=postgresql://…/<nama>_test python -m pytest` menjalankan seluruh suite backend di PostgreSQL, dengan skema baru per tes yang dimigrasi lalu dihapus. Nama database wajib berakhiran `_test`, sehingga database pengembangan atau produksi tidak tersentuh. Tes yang memeriksa berkas SQLite ditandai `sqlite_storage` dan dilewati; padanannya ada di `tests/test_postgres_storage.py` dan `tests/test_postgres_migration.py`. Tanpa variabel ini, tes PostgreSQL ditandai `postgres` dan dilewati.
* `CIR_E2E_DATABASE_URL=postgresql://…/<nama>_test npm run test:e2e:prod` menjalankan E2E production build dengan API di PostgreSQL (skema sekali pakai), lalu memeriksa bahwa run dan review tertulis di PostgreSQL.

## 7. Daftar periksa produksi

Jalankan `python -m scripts.postgres_readiness` (membaca `CIR_DATABASE_URL`, hanya membaca, tidak mencetak data atau rahasia). Butir wajib: migrasi terpasang, tabel lengkap, trigger pengaman riwayat aktif, indeks, peran aplikasi bukan superuser, TLS bila database di mesin lain. Butir yang disarankan untuk produksi:

* **Pisahkan peran pemilik dan peran aplikasi.** Migrasi dijalankan oleh peran pemilik; API memakai peran yang hanya boleh membaca dan menulis baris, sehingga tidak dapat mengubah struktur tabel atau mematikan trigger pengaman. Contoh (sebagai admin PostgreSQL):
  ```sql
  CREATE ROLE cir_owner LOGIN PASSWORD '<rahasia-1>';
  CREATE ROLE cir_runtime LOGIN PASSWORD '<rahasia-2>';
  ALTER DATABASE cir OWNER TO cir_owner;
  REASSIGN OWNED BY cir_app TO cir_owner;               -- tabel yang sudah ada
  GRANT CONNECT ON DATABASE cir TO cir_runtime;
  GRANT USAGE ON SCHEMA public TO cir_runtime;
  GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO cir_runtime;
  ALTER DEFAULT PRIVILEGES FOR ROLE cir_owner IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO cir_runtime;
  ALTER ROLE cir_runtime SET statement_timeout = '300s';
  ```
  `scripts.db_migrate` memakai URL `cir_owner`; API memakai URL `cir_runtime`. Trigger pengaman tetap menolak `UPDATE`/`DELETE` pada tabel riwayat meskipun hak tulis diberikan.
* **Batas waktu query** (`statement_timeout`) pada peran aplikasi, setelah mengukur durasi analisis terbesar di lingkungan produksi.
* **TLS** (`sslmode=require` di URL) bila database berada di mesin lain; `pg_hba.conf` hanya mengizinkan alamat server aplikasi.
* **Rahasia** (`CIR_DATABASE_URL`) dari penyimpanan rahasia, bukan berkas di repositori; password kuat.
* **Cadangan terjadwal** (`pg_dump`, bagian 5) dan uji pemulihan berkala.
* **Beberapa proses atau server API** dapat memakai satu database: pengambilan folder kiriman dan pengarsipan otomatis memakai kunci klaster (`pg_try_advisory_lock`; satu pemegang, proses lain melewatkan gilirannya), dan batas permintaan disimpan bersama di tabel `rate_limit_hits` (migrasi `0010`, kunci berupa SHA-256).

## 8. Batasan

* Diuji pada PostgreSQL 12.4 dan 18.6 (seluruh tes backend dan E2E). SQL tidak memakai fitur di atas PostgreSQL 12.
* Lock tulis aplikasi bersifat global (setara satu berkas SQLite). Cukup untuk beban prototipe; partisi kunci per tabel belum diperlukan.
* Dengan SQLite (satu proses) batas permintaan tetap di memori proses; dengan PostgreSQL batas berlaku bersama untuk semua proses. Pembatasan di proxy/gateway tetap dianjurkan sebagai lapis kedua.
