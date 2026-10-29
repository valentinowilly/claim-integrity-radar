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
- **Kolom operasional tambahan (sintetis, bukan bagian data sampel BPJS):** `ID_FASKES`, `KAPASITAS_HARIAN`,
  `JENIS_LAYANAN`, `JUMLAH_LAYANAN`, `JAM_LAYANAN`, `BUKTI_WAJIB`, `BUKTI_TERCATAT`, `STATUS_BUKTI`. Kolom ini diisi
  hanya untuk layanan yang digambarkannya: fisioterapi rawat jalan (ICD-9 93.1x/93.3x) serta obat (DD) dan alkes (YY)
  khusus. Di produksi nilainya diambil dari data faskes dan rekam medis elektronik. Kapasitas ditetapkan per kelas RS,
  tidak diambil dari data. Kolom ini mengaktifkan tiga pemeriksaan: kapasitas layanan, pola waktu (banyak layanan
  pada menit yang sama), dan kelengkapan bukti; tanpa kolom ini ketiganya berstatus "tidak berlaku".
- Modus yang memakai kolom itu meniru kasus fisioterapi yang diungkap KPK (4.341 klaim, hanya 1.072 berkas rekam
  medisnya lengkap): sesi fisioterapi jauh di atas kapasitas RS, sebagian besar tanpa catatan sesi, banyak dimasukkan
  pada menit yang sama; dan obat/alkes khusus tanpa bukti pemberian. Pembanding jujurnya: unit fisioterapi sibuk yang
  masih dalam kapasitas, sesi latihan kelompok pada menit yang sama, dan RS yang belum mencatat inventaris buktinya.
- Baris diurutkan menurut tanggal masuk lalu referensi kasus, sehingga posisi baris tidak menunjukkan klaim curang.

Dibuat oleh `backend/scripts/make_bpjs_demo_datasets.py` dengan seed tetap.

| File | Klaim | Cerita yang dibuktikan |
|---|---|---|
| `demo-1-faskes-jujur.csv` | 11.854 (24 RS, 14 provinsi) | Tanpa kecurangan, termasuk klaim jujur yang mirip pola curang (layanan rutin bervolume tinggi, terapi mingguan, fisioterapi sibuk, sesi kelompok). Tidak ada RS berisiko tinggi. |
| `demo-2-kasus-kpk.csv` | 12.088 (24 RS, 14 provinsi) | Satu RS menagih kunjungan dua kali, menaikkan keparahan INA-CBG klaim yang sama, memperpanjang lama rawat, dan menagih sesi fisioterapi di atas kapasitasnya (262 klaim curang). RS itu langsung di peringkat 1. |
| `demo-3-operasional.csv` | 29.628 (40 RS, 17 provinsi) | Sebulan operasional, sekitar 2,9% klaim curang (846 klaim di 12 RS) dalam delapan modus (tagihan ganda, *upcoding*, lama rawat diperpanjang, pemecahan rawat inap, klaim salinan, tambahan khusus fiktif, fisioterapi fiktif di atas kapasitas, obat/alkes tanpa bukti pemberian), ditambah klaim jujur yang mirip. |
| `harian/klaim-YYYY-MM-DD.csv` | 37 file | demo-3 dipecah per tanggal masuk, untuk peragaan pengambilan otomatis dari folder kiriman. |

Cara pakai: Data & Analisis → Unggah file CSV → pilih file → sistem memeriksa lalu menganalisis.

File `*.answers.json` adalah kunci jawaban untuk pengujian. **Jangan diunggah.**

Membuat ulang (butuh model AI dan `category_labels.json` di `backend/models/`):
`cd backend && python -m scripts.make_bpjs_demo_datasets --out ../demo-data --check`
