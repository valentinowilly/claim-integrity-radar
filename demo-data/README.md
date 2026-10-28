# Data contoh berformat data klaim BPJS

File CSV untuk demo dan video, dengan **kolom yang sama dengan data klaim BPJS FKRTL** (PSTV01, FKL02, FKL03 … FKL32,
FKL47), kode tambahan khusus (FKL33/35/38/41/44), diagnosis sekunder (`FKL24`, kode dipisah `;`), dan kolom
opsional `CATATAN_KLINIS` (resume medis singkat). Isinya data contoh, bukan data peserta asli:

- Semua nomor peserta diawali `SYN`. Aplikasi menolak file berisi nomor peserta asli.
- Kode diagnosis, INA-CBG, prosedur, dan lama rawat diambil dari tabel agregat model AI. Tabel itu hanya memuat
  kombinasi kode yang muncul minimal 5 kali di data latih, tanpa satu baris pun data BPJS.
- Nama wilayah dan kelas faskes diambil dari kamus label data sampel.
- Catatan klinis dibuat acak (tanda vital dan lab berbeda tiap pasien). Klaim curang meninggalkan jejak di catatannya:
  klaim salinan menyalin catatan pasien lain kata demi kata, *upcoding* tetap bercatatan "tanpa komplikasi", lama
  rawat yang diperpanjang tetap menyebut lama rawat semula. Buka klaim mana pun lalu tekan **Baca catatan dengan AI**.
- Diagnosis sekunder mengikuti pola data sampel 2024. Pelaku *upcoding* mempertahankan diagnosis sekunder keparahan
  aslinya; 40% di antaranya ikut memalsukan satu diagnosis sekunder (sengaja tidak semua tertangkap).
- Kode tambahan khusus klaim jujur diambil dari pasangan INA-CBG x kode khusus di data acuan; satu RS menempelkan
  obat/alat/tindakan khusus ke INA-CBG yang tidak pernah mendapatkannya (modus "tambahan khusus fiktif").

Dibuat oleh `backend/scripts/make_bpjs_demo_datasets.py` dengan seed tetap.

| File | Klaim | Cerita yang dibuktikan |
|---|---|---|
| `demo-1-faskes-jujur.csv` | 11.698 (24 RS) | Tanpa kecurangan, termasuk klaim jujur yang mirip pola curang (layanan rutin bervolume tinggi, terapi mingguan). Tidak ada RS berisiko tinggi. |
| `demo-2-kasus-kpk.csv` | 11.752 (24 RS) | Satu RS menagih kunjungan dua kali, menaikkan keparahan INA-CBG klaim yang sama, dan memperpanjang lama rawat. RS itu langsung di peringkat 1. |
| `demo-3-operasional.csv` | 28.918 (40 RS) | Sebulan operasional, sekitar 1,6% klaim curang (470 klaim di 10 RS) dalam enam modus (tagihan ganda, *upcoding*, lama rawat diperpanjang, pemecahan rawat inap, klaim salinan, tambahan khusus fiktif), ditambah klaim jujur yang mirip. Dipakai juga untuk halaman Kinerja Sistem. |
| `harian/klaim-YYYY-MM-DD.csv` | 37 file | demo-3 dipecah per tanggal masuk, untuk peragaan pengambilan otomatis dari folder kiriman. |

Cara pakai: Data & Analisis → Unggah file CSV → pilih file → sistem memeriksa lalu menganalisis.

File `*.answers.json` adalah kunci jawaban untuk pengujian. **Jangan diunggah.**

Membuat ulang (butuh model AI dan `category_labels.json` di `backend/models/`):
`cd backend && python -m scripts.make_bpjs_demo_datasets --out ../demo-data --check`
