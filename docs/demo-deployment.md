# Deployment demo terbatas — Claim Integrity Radar (data sintetis)

Panduan menyiapkan demo yang dapat direproduksi dan aksesnya dibatasi. **Hanya data sintetis.** Jangan mengonfigurasi `BPJS_FKRTL_SAMPLE_PATH` dan jangan memuat kasus BPJS nyata pada host demo. Pengumpulan karya ke kompetisi tidak sama dengan izin penggunaan operasional.

## 1. Topologi

```
browser ──HTTPS──> reverse proxy (TLS, akses terbatas, rate limit edge)
                     ├── /            → file statis frontend/dist
                     ├── /api, /health → uvicorn 127.0.0.1:8000 (satu proses)
                     └── semua lain   → 404
```

Frontend memanggil API secara same-origin (`/api/v1/...`), jadi proxy harus menyajikan keduanya pada origin yang sama. API hanya mendengarkan `127.0.0.1`.

## 2. Build dan instalasi

```powershell
cd backend; python -m venv .venv; .venv\Scripts\python -m pip install -r requirements.txt
cd ..\frontend; npm ci; npm run build        # hasil: frontend/dist
```

Catat versi yang dipasang (tanggal, hash commit atau checksum arsip) untuk rollback.

## 3. Konfigurasi dan rahasia

Semua konfigurasi lewat environment layanan (bukan file di repository). Jangan menyimpan nilai rahasia di shell history, log, atau tangkapan layar.

| Variabel | Nilai demo | Catatan |
|---|---|---|
| `CIR_DATABASE_URL` | `postgresql://cir_app:<rahasia>@<host>/cir` | database operasional untuk semua store; skema lewat `python -m scripts.db_migrate`; lihat `docs/database-postgresql.md` |
| `CIR_AUTH_DB_PATH`, `CIR_BATCH_DB_PATH`, `CIR_REVIEW_DB_PATH` | hanya tanpa `CIR_DATABASE_URL`: path di direktori data khusus (§4) | di luar direktori web dan repository |
| `CIR_COOKIE_SECURE` | `true` | wajib di balik HTTPS |
| `CIR_SESSION_TTL_SECONDS` | `28800` atau lebih pendek | |
| `CIR_RATE_LIMIT_ENABLED` | `true` | batas default: `docs/api-contracts.md` |
| `CIR_RATE_LIMIT_*` | default | dengan PostgreSQL berlaku bersama untuk semua worker; dengan SQLite per proses |
| `CIR_ADMIN_BOOTSTRAP_SECRET` | rahasia acak sementara | hanya saat bootstrap, lalu dihapus |
| `BPJS_FKRTL_SAMPLE_PATH`, `CIR_FKRTL_PSEUDONYM_KEY` | **tidak diset** | sumber FKRTL dinonaktifkan di demo |
| `CIR_ENV` | tidak diset | jalur `--local-demo` (admin123) tidak dipakai di host demo |

Bootstrap admin sekali (`backend/README.md`), lalu buat akun per peran lewat API admin dengan password ≥ 12 karakter. Bagikan kredensial lewat saluran terpisah; satu akun per orang.

## 4. Basis data: izin file, persistensi, backup

* Buat direktori data khusus yang **hanya** dapat dibaca/ditulis akun layanan API. Linux: `chown cir:cir /srv/cir-data && chmod 700 /srv/cir-data` dan file `600`. Windows: `icacls <dir> /inheritance:r /grant:r "<akun-layanan>:(OI)(CI)M" "Administrators:(OI)(CI)F"`.
* Trigger append-only SQLite **tidak** melindungi dari pihak yang dapat menulis file database: mereka dapat menghapus trigger atau mengganti file. Karena itu izin file adalah kontrol utama; jangan beri akses tulis direktori data kepada pengguna interaktif.
* Backup online konsisten (dari `backend`, akun layanan):

  ```powershell
  .venv\Scripts\python -c "import sqlite3,sys; s=sqlite3.connect(sys.argv[1]); d=sqlite3.connect(sys.argv[2]); s.backup(d); d.close(); s.close()" <db> <backup-dengan-tanggal>.sqlite3
  ```

  Jalankan untuk ketiga file DB, simpan di lokasi dengan izin yang sama ketatnya, dan uji pemulihan sekali sebelum demo.

## 5. HTTPS dan pembatasan akses

* TLS di reverse proxy (sertifikat valid; HTTP dialihkan ke HTTPS; HSTS).
* Batasi akses: allowlist IP, VPN, atau autentikasi tambahan di proxy. Jangan membuka demo tanpa batas ke internet.
* Rate limit di proxy untuk `/api/v1/auth/login` dan semua `POST`/`PATCH` `/api/v1/runs/` sebagai lapisan kedua; batas aplikasi hanya per proses.
* Bila proxy meneruskan alamat klien, jalankan `uvicorn app.main:app --host 127.0.0.1 --port 8000 --proxy-headers --forwarded-allow-ips=127.0.0.1`.
* Tambahkan header `Content-Security-Policy`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin` di proxy.

## 6. Kesehatan dan log

* `GET /health` hanya melaporkan proses API hidup (tidak membuka database).
* Respons error tidak menggemakan payload; aplikasi tidak menulis log payload. Log akses uvicorn memuat path URL (berisi `run_id` dan `case_id` sintetis). Simpan log dengan akses terbatas dan retensi pendek; jangan aktifkan log body di proxy.

## 7. Data demo sintetis

Buat CSV sintetis dari generator proyek (dari `backend`):

```powershell
.venv\Scripts\python -c "from pathlib import Path; from app.data_sources.synthetic_generator import generate_synthetic_dataset; from app.data_sources.synthetic_csv import export_synthetic_csv; Path('demo-synthetic.csv').write_bytes(export_synthetic_csv(generate_synthetic_dataset().records))"
```

Unggah lewat halaman Claim Data dengan akun `data_operator` atau admin. Label ground truth tidak diekspor.

## 8. Checklist smoke test (setiap deployment)

| # | Langkah | Hasil yang diharapkan |
|---|---|---|
| 1 | `GET /health` lewat HTTPS | `{"status":"ok",...}` |
| 2 | Login tiap peran; logout | sesi berhasil; cookie `Secure`, `HttpOnly` |
| 3 | 6 login gagal untuk satu username | permintaan ke-6 `429` dengan `Retry-After` |
| 4 | Unggah CSV sintetis | batch `ready`; tidak ada BPJS/FKRTL yang dapat dipilih |
| 5 | Buat run | run selesai; hasil tersimpan; membuka ulang tidak menjalankan ulang |
| 6 | Hasil dan cakupan | tiap pemeriksaan menampilkan ditandai / dinilai / tidak dinilai / tidak berlaku |
| 7 | Case Review | alasan, bukti, batasan, dan cakupan per pemeriksaan tampil |
| 8 | Review (verifikator) | status tersimpan dan riwayat bertambah |
| 9 | Outcome dan hasil audit (audit lead) | tersimpan; rujukan terlihat oleh audit lead |
| 10 | Hasil audit dilihat verifikator | status terlihat; rujukan tidak ada di halaman maupun respons API |
| 11 | Antrean | status review dan hasil audit tampil |

## 9. Rollback dan pemulihan

1. Hentikan layanan API.
2. Kembalikan versi aplikasi sebelumnya (`frontend/dist` dan kode backend dari versi yang dicatat di §2).
3. Bila skema atau data rusak, pulihkan ketiga file DB dari backup terakhir yang teruji (salin ke direktori data dengan izin yang sama).
4. Jalankan kembali layanan dan ulangi checklist §8.

Skema tabel dibuat aditif (`CREATE ... IF NOT EXISTS`); versi lama tetap dapat membaca DB dari versi ini, tetapi kolom/tabel baru tidak dihapus saat rollback.

## 10. Status kesiapan

Paket konfigurasi dan prosedur siap. Belum ada host demo yang benar-benar dideploy atau diuji dari panduan ini; checklist §8 harus dijalankan pada host sasaran.
