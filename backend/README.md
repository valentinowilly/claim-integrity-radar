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

Status alur: `pending_review`, `needs_more_evidence`, `not_substantiated`, dan `escalated`. Tiap update ditambahkan ke riwayat; status hanya mengatur tindak lanjut dan bukan penetapan fraud. Reviewer ditandai tetap sebagai `demo_reviewer (unauthenticated)` karena autentikasi belum tersedia. Jangan memasukkan identitas nyata, token peserta, signature klaim, atau informasi kesehatan pada catatan. Fitur ini hanya penyimpanan demo lokal, bukan sistem audit operasional.

Untuk tes, aplikasi dibuat dengan path SQLite terisolasi di direktori temporer; tes tidak menggunakan file runtime default.
