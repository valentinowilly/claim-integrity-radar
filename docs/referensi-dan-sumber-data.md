# Referensi dan sumber data

Daftar sumber yang dipakai Claim Integrity Radar, beserta cara pemakaiannya. Semua angka kinerja di dokumen lain berasal
dari data sintetis berlabel, kecuali bila disebut "data sampel BPJS".

## 1. Data

| Sumber | Dipakai untuk | Batas pemakaian |
|---|---|---|
| **Data sampel BPJS Kesehatan** (berkas `.dta` FKRTL 2024 dari panitia Healthkathon 2026; panduan: `panduan-data-sample-bpjs.pdf`) | Melatih AI tahap 1 (Isolation Forest, 126.871 klaim, 5 Februari–3 Maret 2024); tabel agregat kombinasi kode (diagnosis × INA-CBG, INA-CBG × prosedur, lama rawat, diagnosis sekunder); kamus label wilayah dan kelas faskes; uji agregat pada jendela 4–10 Maret 2024 | Data asli disimpan di luar repositori dan diproses lokal. Yang dilaporkan hanya angka agregat. Kombinasi kode yang muncul kurang dari 5 kali tidak disimpan. Model terlatih (`backend/models/`) tidak di-commit. Data tidak dikirim ke model bahasa atau layanan luar. |
| **Data contoh berformat kolom BPJS** (`demo-data/`, dibuat `backend/scripts/make_bpjs_demo_datasets.py`, seed tetap) | Demo, tangkapan layar, video, dan pengujian berlabel | Sepenuhnya sintetis. Nomor peserta berawalan `SYN`. Cara pembuatan dijelaskan di `demo-data/README.md`. |
| **Kolom operasional tambahan** (`ID_FASKES`, `KAPASITAS_HARIAN`, `JENIS_LAYANAN`, `JUMLAH_LAYANAN`, `JAM_LAYANAN`, `BUKTI_WAJIB`, `BUKTI_TERCATAT`, `STATUS_BUKTI`) | Pemeriksaan kapasitas, pola waktu, dan kelengkapan bukti | Tidak ada di data sampel BPJS. Nilainya sintetis; kapasitas ditetapkan per kelas RS (asumsi tim), bukan angka resmi. Di produksi berasal dari data faskes dan rekam medis elektronik. |
| **Kasus fisioterapi fiktif yang diaudit KPK bersama Tim PK-JKN** (dikutip di proposal; sumber InfoPublik dan Itjen Kemenkes; data Juli 2017–Juni 2018) | Pola modus "fisioterapi fiktif": 4.341 klaim, hanya 1.072 dengan rekam medis lengkap (±25%) | Dipakai sebagai pola acuan, bukan gambaran kondisi terkini. Nilai dugaan adalah dugaan, bukan putusan. |

## 2. Materi Healthkathon 2026 (folder `reference-materials/`)

| Materi | Dipakai untuk |
|---|---|
| *Materi HealthKathon 2026* dan *Alur Kegiatan Healthkathon* | Ruang lingkup, jadwal, aturan data |
| *BPJS Healthkathon 2026 – Basic* | Pendekatan *unsupervised anomaly detection*; *upcoding* sebagai anomali dibanding rata-rata regional |
| *Building Practical AI Inference Pipeline: From Data to API* (Said Achmad) | Arsitektur tahap 1 ML + tahap 2 LLM; deteksi *cloning* lewat kemiripan teks catatan medis; sistem tetap jalan saat LLM mati (*fallback*); API-first |
| *Panduan data sampel BPJS* | Arti kolom FKL; keparahan INA-CBG ditentukan diagnosis sekunder; FKL48 adalah biaya pasca-verifikasi |
| *Template Project Final Healthkathon 2026* | Struktur submission |
| Kit penilaian Workshop #3, `healthkathon-eval-kit` (github.com/Luche/healthkathon-eval-kit) | Kartu bukti: ketepatan pada kapasitas audit, lift, rupiah tertangkap, ablasi, plasebo, permutasi, uji kebocoran. Dijalankan tanpa mengubah kodenya. |

## 3. Sumber berita yang dikutip di proposal

Dipakai hanya sebagai latar masalah, tidak sebagai masukan sistem.

- **CNN Indonesia, 12 Juni 2026.** Pernyataan Direktur Utama BPJS Kesehatan di DPR.
- **Liputan6, Mei 2026.** Tren modus kecurangan 2026 menurut BPJS.
- **Kompas.** Klarifikasi isu dugaan kerugian Rp20 triliun dalam Program JKN.

## 4. Regulasi dan tata kelola

- **UU No. 27 Tahun 2022 tentang Pelindungan Data Pribadi.** Dasar pseudonimisasi, akses per peran, log audit, dan keputusan akhir oleh manusia.
- **Prinsip tata kelola AI BPJS dari materi Healthkathon.** Data peserta diproses dengan AI internal; tidak memakai akun AI gratis; hasil AI diverifikasi manusia.

## 5. Peta

**geoBoundaries gbOpen IDN ADM1** (34 provinsi, batas 2017 dari OpenStreetMap), github.com/wmgeolab/geoBoundaries.

- Lisensi: Open Data Commons Open Database License 1.0, © kontributor OpenStreetMap.
- Berkas `frontend/src/assets/indonesia-provinces.json` adalah turunan yang disederhanakan (`frontend/scripts/build_province_map.py`) dan tetap berlisensi ODbL 1.0 dengan atribusi yang sama.

## 6. Perangkat lunak dan model

| Komponen | Pemakaian |
|---|---|
| React 18, TypeScript, Vite, Tailwind CSS 4, Recharts, React Router, lucide-react | Antarmuka |
| Python, FastAPI, Uvicorn | API |
| pandas, NumPy, scikit-learn (Isolation Forest) | Analitik dan AI tahap 1 |
| SQLite (pengembangan) dan PostgreSQL (psycopg) | Basis data operasional |
| Ollama + Qwen3 4B (model lokal) | AI tahap 2: membaca catatan klinis sintetis |
| Anthropic SDK (opsional, akun enterprise) | Penghubung alternatif untuk tahap 2; mati secara bawaan |
| Playwright | Uji ujung ke ujung antarmuka |

## 7. Kode klinis

ICD-10 (diagnosis), ICD-9-CM (prosedur), dan kode INA-CBG yang dipakai sistem diambil dari kolom data sampel BPJS. Sistem tidak memuat tabel tarif INA-CBG resmi. Tarif pada data contoh adalah angka sintetis tetap per kode INA-CBG (rawat inap Rp3–9 juta dikali faktor keparahan 1; 1,5; 2,2; rawat jalan Rp150–450 ribu), bukan tarif resmi.
