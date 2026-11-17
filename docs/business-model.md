# Model bisnis dan penerapan — Claim Integrity Radar

Claim Integrity Radar ditawarkan sebagai **solusi B2G yang dipasang di server internal BPJS Kesehatan**: kode dan lisensinya diserahkan tanpa biaya, dan tim menjadi mitra implementasi, penyetelan aturan, dan pemeliharaan. Pilot berjalan di server yang sudah ada; perangkat GPU baru dibutuhkan pada skala nasional.

Setiap angka diberi asal-usul. Perhitungan lengkap (uji beban, kebutuhan server, biaya, titik impas, tahapan, risiko) ada di [`analisis-kelayakan.md`](analisis-kelayakan.md). Semua uji memakai data sintetis; ketepatan pada data klaim nyata diukur saat pilot.

## 1. Posisi dalam proses klaim

| Hal | Isi |
|---|---|
| Proses sasaran | C03.04 Pengelolaan Klaim Faskes pada arsitektur proses bisnis BPJS Kesehatan |
| Letak | Di samping aplikasi verifikasi yang ada (VClaim, VIDI), sebelum tindak lanjut audit (SIGAP, AUDIA) |
| Peran | Lapisan prioritas: mengurutkan klaim dan faskes yang paling layak diperiksa, dengan alasan, bukti berkas, dan nilai tagihan |
| Yang tidak dilakukan | Tidak menggantikan verifikasi, tidak memutuskan klaim; keputusan selalu di tangan verifikator |

Usulan penempatan ini belum dikonfirmasi BPJS Kesehatan dan belum terintegrasi dengan aplikasinya.

## 2. Pengguna dan nilai

| Pengguna | Kebutuhan | Yang diberikan Radar |
|---|---|---|
| Verifikator | Memilih berkas yang diperiksa lebih dulu dari volume besar, dari data yang datang dalam banyak bentuk (CSV E-Klaim, RME SATUSEHAT, PDF faskes) | Satu antrean dari tiga sumber, diurutkan menurut risiko, dengan alasan, bukti berkas, dan nilai tagihan; ringkasan risiko setiap kali masuk |
| Tim Anti Kecurangan | Menindaklanjuti faskes dan modus secara proporsional | Kelompok faskes per modus, peta risiko per provinsi, keputusan tercatat |
| Admin | Mengelola akses | Dua peran (verifikator dan admin), log keamanan |
| Faskes jujur (tidak langsung) | Tidak ikut diperiksa tanpa alasan | Pada data sintetis, hanya 1,0% klaim jujur yang ikut ditandai, dibanding 26,9% dengan aturan sederhana |

Pada data sintetis berlabel (29.628 klaim, 40 rumah sakit), dari 100 berkas yang dibuka, 94 bermasalah; dengan pemilihan acak 2,9. Beban kerja verifikator tidak bertambah, yang berubah urutannya. Sumber: [`analytics-spec.md`](analytics-spec.md).

## 3. Model penerapan dan kerja sama

- **B2G, server internal BPJS.** Data klaim dan catatan klinis adalah data pribadi yang spesifik (UU 27/2022 PDP), jadi seluruh komponen, termasuk model bahasa, berjalan di jaringan BPJS.
- **Lisensi Rp0.** Semua komponen berlisensi terbuka: FastAPI, PostgreSQL, scikit-learn, RapidOCR (PP-OCRv6), vLLM, dan Gemma 4 (Apache 2.0).
- **Mitra implementasi.** Tim mendampingi pemasangan (Docker Compose, satu berkas pengaturan), penyetelan aturan bersama koder klinis, dan pemeliharaan.
- **Tidak terikat satu model.** Model bahasa dipanggil lewat endpoint kompatibel OpenAI; model lain dapat dipasang tanpa mengubah aplikasi bila kebijakan BPJS mengizinkan.

## 4. Biaya bertahap

| Tahap | Kebutuhan | Biaya perangkat |
|---|---|---|
| Pilot | Server aplikasi dan basis data yang ada; aturan, AI Pola Klaim, dan OCR berjalan di CPU. Tanpa model bahasa, pembacaan memakai pola formulir dan aturan teks. | Tidak ada pembelian baru |
| Skala nasional dengan AI pembaca | Satu server dengan 2 GPU 80 GB (H100 atau setara): satu melayani, satu cadangan | ±US$70.000–90.000, sekitar Rp1,2–1,5 miliar sekali beli (harga publik GPU; kurs Rp16.500) |

Biaya perangkat AI itu setara ±0,0009% biaya pelayanan FKRTL setahun (±Rp166 triliun, dari Rp191,33 triliun biaya pelayanan JKN 2025). Biaya operasional (listrik, pemeliharaan, tim penyetel aturan) diukur saat pilot karena bergantung pada tarif dan struktur tim BPJS.

## 5. Titik impas

Belum ada angka resmi tingkat kecurangan klaim JKN yang terbuka, jadi tim tidak menebak rupiah yang akan diselamatkan. Yang dapat dihitung:

- Sistem balik modal bila membantu mencegah atau memulihkan tagihan bermasalah senilai biaya GPU, sekali saja.
- Satu kasus klaim fiktif fisioterapi dan katarak di 3 rumah sakit yang diungkap KPK bernilai ±Rp35 miliar, sekitar 25 kali biaya tersebut.

## 6. Tahapan dan ukuran keberhasilan

| Tahap | Lama | Isi | Ukuran berhasil |
|---|---|---|---|
| 0. Persiapan | 1 bulan | Izin data; penyesuaian pemetaan ke profil resmi SATUSEHAT dan E-Klaim; pemasangan di lingkungan uji | Paket klaim satu hari dari satu cabang berhasil dianalisis |
| 1. Pilot berdampingan | 3 bulan, 1 kedeputian wilayah | Berjalan di samping verifikasi yang ada tanpa mengubah keputusan | Temuan per 100 berkas, porsi klaim jujur yang ikut ditandai, waktu per berkas, kepuasan petugas |
| 2. Penyetelan | 1 bulan | Ambang dan aturan disetel bersama koder klinis; ketepatan baca berkas nyata diukur | Ambang disahkan pemilik proses |
| 3. Perluasan | Bertahap | Wilayah lain; GPU internal untuk AI pembaca; integrasi otomatis dari sistem klaim | Kapasitas dan ketepatan bertahan di volume nasional |

Rencana pengembangan berikutnya: cek mandiri untuk faskes sebelum mengajukan klaim, agar klaim pending dan sengketa berkurang (belum dibangun).

## 7. Risiko utama

| Risiko | Mitigasi |
|---|---|
| Ketepatan pada data nyata lebih rendah dari data sintetis | Pilot berdampingan tanpa mengubah keputusan; ketepatan diukur dari keputusan verifikator yang tercatat |
| Faskes jujur ikut ditandai | Setiap tanda disertai alasan dan bukti; keputusan di tangan manusia; porsi klaim jujur yang ditandai diukur |
| Berkas nyata lebih sulit dibaca (tulisan tangan, stempel, pindaian buram) | Pembaca tingkat kedua (model bahasa-visual), tanda "OCR kurang yakin", nilai yang tidak terbaca tidak dipakai |
| Bias antarwilayah atau jenis faskes | Proporsi klaim berisiko dipantau per provinsi, kelas, dan kepemilikan faskes dibanding rata-rata |
| Data kesehatan bocor | Semua komponen di jaringan sendiri, identitas disamarkan, jejak audit setiap tindakan |
