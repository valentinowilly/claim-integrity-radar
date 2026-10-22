# Frontend Claim Integrity Radar

Frontend Claim Integrity Radar memakai React + TypeScript + Vite, Tailwind CSS, dan React Router. Lima halaman mengambil respons dari FastAPI lokal. Seluruh hasil yang tersedia saat ini berasal dari `synthetic_demo`, bukan dataset BPJS. Grafik tidak ditampilkan karena respons kontrak saat ini lebih tepat disajikan sebagai ringkasan angka dan daftar kandidat.

## Prasyarat

- Node.js 18 atau lebih baru (sesuai engine Vite 5 yang dipakai proyek ini).
- npm 9 atau lebih baru.
- Backend lokal Claim Integrity Radar berjalan. Default proxy Vite adalah `http://127.0.0.1:8000`.

## Pasang dependensi

```powershell
cd frontend
npm.cmd install
```

## Jalankan mode pengembangan

```powershell
npm.cmd run dev
```

Buka URL lokal yang dicetak Vite, umumnya `http://127.0.0.1:5173`. Proxy development meneruskan `/health` dan `/api` ke target `VITE_BACKEND_URL`, sehingga frontend tidak memerlukan konfigurasi CORS terbuka. Untuk workspace ini, gunakan backend lengkap pada port `8001` melalui `frontend/.env.local`.

Untuk setup lokal baru, salin `.env.example` menjadi `.env.local` jika file lokal tersebut belum ada. Jangan menimpa `.env.local` yang sudah berisi konfigurasi pribadi. File `.env.local` diabaikan Git. Nilai contoh menunjuk ke port `8001`; ubah bila backend workspace berjalan di port lain.

## Build production

```powershell
npm.cmd run build
```

Build TypeScript dan aset produksi berada di `dist/`.

## Jalankan bersama backend

Di terminal pertama:

```powershell
cd backend
python -m uvicorn app.main:app --reload
```

Di terminal kedua:

```powershell
cd frontend
npm.cmd run dev
```

Target proxy default adalah `http://127.0.0.1:8000` bila `VITE_BACKEND_URL` tidak diset. Konfigurasi lokal di `.env.local` memilih `http://127.0.0.1:8001`, karena port 8000 pada mesin ini hanya menyediakan health check. Untuk override sementara pada proses Vite di PowerShell:

```powershell
$env:VITE_BACKEND_URL = "http://127.0.0.1:8001"
npm.cmd run dev
```

Indikator pada header memeriksa `GET /health` melalui proxy Vite secara berkala. Halaman terhubung ke endpoint berikut:

- Overview: `GET /api/v1/dashboard/summary`
- Analisis Risiko: `GET /api/v1/analysis` dan alasan dari `GET /api/v1/cases`
- Antrean Audit: `GET /api/v1/cases` dengan filter, sort key, dan pagination
- Detail Kasus: `GET /api/v1/cases/{case_id}`
- Evaluasi: `GET /api/v1/evaluation`
- Antrean dan detail review: `GET /api/v1/cases` memakai filter `review_status`, `GET /api/v1/cases/{case_id}/review`, dan `POST /api/v1/cases/{case_id}/review`.

Status review adalah metadata workflow (`pending_review`, `needs_more_evidence`, `not_substantiated`, atau `escalated`), bukan kesimpulan fraud. Catatan disimpan di SQLite lokal backend. Demo belum memiliki autentikasi/kontrol akses; jangan masukkan data peserta, klaim nyata, identitas, atau informasi sensitif pada catatan.

Jika request gagal atau respons tidak sesuai kontrak, halaman menampilkan error dan aksi coba lagi; daftar kosong dari API ditampilkan sebagai empty state tersendiri. Skor/level risiko dan waktu deteksi yang bernilai `null` tidak ditampilkan sebagai metrik. Sorting antrean meneruskan parameter kontrak, tetapi backend saat ini menggunakan urutan `case_id` karena nilai risiko/waktu belum tersedia.
