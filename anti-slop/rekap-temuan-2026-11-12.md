# Rekap semua temuan (12 November 2026)

Satu daftar untuk semua temuan dari empat pemeriksaan:
1. audit antislop 001: tampilan dan aksesibilitas;
2. pemeriksaan BA/PM/SA: alur, kasus negatif, kelayakan produk;
3. audit antislop 002: UI/UX menyeluruh;
4. pekerjaan yang masih terbuka dari tahap sebelumnya.

Setiap butir punya kode unik. Kolom **Terkait** menunjukkan butir lain yang membahas hal yang sama, supaya nanti dikerjakan sekaligus.

**Status:**
- **Terbuka:** belum dikerjakan, menunggu persetujuan.
- **Selesai:** sudah dikerjakan.
- **Keputusan:** perlu keputusan Anda atau BPJS, bukan pekerjaan kode.

**Prioritas:**
- **P0:** angka atau data salah.
- **P1:** menjawab catatan mentor atau aturan wajib.
- **P2:** kenyamanan dan kejelasan.
- **P3:** pelengkap.

Rincian bukti setiap temuan ada di `audit-001-2026-11-12.md` dan `audit-002-2026-11-12.md`. Rincian kasus BA/PM/SA ada di bagian 2.

## Ringkasan jumlah

| Sumber | Jumlah | P0 | P1 | P2 | P3 | Selesai |
|---|---|---|---|---|---|---|
| Audit 001 (A-1 s.d. A-16) | 16 | 0 | 13 | 2 | 1 | 1 (A-16) |
| BA/PM/SA (B-1 s.d. B-26) | 26 | 3 | 11 | 10 | 2 | 0 |
| Audit 002 (A-17 s.d. A-34, U-1 s.d. U-5) | 23 | 1 | 9 | 13 | 0 | 0 |
| Pekerjaan terbuka (T-1 s.d. T-9) | 9 | 0 | 1 | 2 | 6 | 0 |
| **Total** | **74** | **4** | **34** | **27** | **9** | **1** |

## 1. Audit antislop 001: tampilan dan aksesibilitas

| Kode | Prio | Halaman | Temuan | Terkait | Status |
|---|---|---|---|---|---|
| A-1 | P1 | Peta | Halaman melebar 21 px di ponsel (bisa digeser ke samping) | | **Selesai** |
| A-2 | P1 | Semua | Sasaran sentuh di bawah 44 px (47 di Peta, 2–5 di halaman lain) | | **Selesai** |
| A-3 | P1 | Berkas klaim, peringatan | Teks kuning #d97706 ukuran kecil, kontras 3,1:1 | DESIGN.md | **Selesai** |
| A-4 | P1 | Semua (gelap) | Teks samar mode gelap 4,18:1 | A-17 | **Selesai** |
| A-5 | P1 | Semua | Em dash "—" sebagai tanda nilai kosong (sekitar 30 tempat) | | **Selesai** |
| A-6 | P1 | Berkas klaim | Kursor tombol contoh pertanyaan yang nonaktif | | **Selesai** |
| A-7 | P2 | Beberapa | Ikon "kilau" sebagai tanda AI (5 tempat) | DESIGN.md | **Selesai** |
| A-8 | P2 | Beberapa | Label kapital berjarak lebar (9 tempat) | DESIGN.md | **Selesai** |
| A-9 | P1 | Antrean | Tidak ada nilai tagihan per klaim maupun total | B-9, A-24, U-3 | **Selesai** |
| A-10 | P1 | Detail klaim | Tidak ada nilai tagihan klaim; halaman paling banyak teks | A-26, B-9 | **Selesai** |
| A-11 | P1 | Beranda | Angka 485 diulang 3–4 kali; tidak ada satu titik fokus | A-20, U-2 | **Selesai** |
| A-12 | P1 | Beranda | "Ringkasan hari ini" berupa kalimat panjang berisi angka | A-11 | **Selesai** |
| A-13 | P1 | Faskes | Kartu ringkasan tanpa rupiah | U-5 | **Selesai** |
| A-14 | P1 | Tren | Grafik didominasi klaim risiko rendah; rupiah hanya di tabel | | **Selesai** |
| A-15 | P1 | Detail klaim | Penjelasan panjang selalu terbuka | A-26 | **Selesai** |
| A-16 | P3 | Proyek | Belum ada `DESIGN.md` | | **Selesai** |

## 2. Pemeriksaan BA/PM/SA

Semua butir ini diuji langsung pada salinan basis data, dengan data sintetis.

### 2a. Berkas sembarangan dan kasus negatif

| Kode | Prio | Kasus | Respons sistem sekarang | Yang seharusnya | Terkait | Status |
|---|---|---|---|---|---|---|
| B-1 | **P0** | PDF berisi nomor kunjungan yang sama tetapi **nomor peserta lain** | **Ditautkan ke klaim itu tanpa peringatan**; catatannya ikut dianalisis | Tautkan hanya bila nomor kunjungan **dan** nomor peserta cocok; bila tidak, berkas ditandai dan tidak dipakai | | **Selesai** |
| B-2 | **P0** | Paket keliru untuk klaim yang sama dengan paket sebelumnya | **Berkas paket keliru ikut tampil di hasil analisis lain** | Berkas dibatasi pada paket milik analisis yang dibuka | B-12 | **Selesai** |
| B-3 | **P0** | Klaim dibentuk dari satu PDF saja, sementara OCR salah membaca nomor peserta | Terbentuk klaim "hantu" dengan identitas keliru | Klaim dari PDF saja hanya dibentuk bila minimal 2 berkas sepakat soal identitas | | **Selesai** |
| B-4 | P2 | PDF undang-undang, artikel, atau bacaan lain | Paket jalan; alasannya "nomor kunjungan tidak terbaca" (menyesatkan) | Alasan "bukan berkas klaim" | B-25 | **Selesai** |
| B-5 | P2 | JSON acak, gambar atau video bernama .pdf | Diabaikan diam-diam; nama berkas tidak disebut | Daftar berkas yang tidak dikenali, beserta alasannya | B-10 | **Selesai** |
| B-6 | P2 | JSON FHIR tanpa data kunjungan | Terhitung "1 FHIR", 0 klaim, tanpa peringatan | Peringatan "berkas FHIR tanpa kunjungan" | | **Selesai** |
| B-7 | P1 | Satu JSON FHIR yang bukan Bundle | **Seluruh paket gagal**, termasuk CSV yang benar | Berkas itu saja yang ditolak; paket tetap jalan | | **Selesai** |
| B-8 | P2 | PDF klaim pasien nyata (nomor peserta asli) | Seluruh paket ditolak tanpa menyebut berkasnya | Tetap ditolak (pengaman), tetapi menyebut nama berkas | B-25 | **Selesai** |
| B-9 | P1 | PDF acak saat model bahasa aktif | Setiap PDF tak dikenal dikirim ke model (boros: 100 PDF ≈ 7 menit lebih) | Model hanya dipanggil bila halamannya tampak seperti berkas klaim | | **Selesai** |

### 2b. Asal nilai rupiah (catatan coaching)

| Kode | Prio | Temuan | Yang seharusnya | Terkait | Status |
|---|---|---|---|---|---|
| B-10 | P1 | Rp1,8 miliar adalah jumlah tagihan RS (FKL47) untuk 485 klaim risiko tinggi, sebelum verifikasi. Penjelasannya hanya lewat ikon (i) yang muncul saat kursor diarahkan: tidak terbaca di ponsel dan tidak bisa dibuka dengan keyboard. | Kalimat penjelasan terlihat langsung di bawah angka | U-3 | **Selesai** |
| B-11 | P1 | Kartu dan baris modus berisi rupiah mengarah ke antrean yang tidak memuat rupiah | Klik angka rupiah membuka rincian (per modus, per faskes, 10 klaim terbesar) | A-9, U-3 | **Selesai** |

### 2c. Membatalkan unggahan

| Kode | Prio | Saat | Kondisi sekarang | Yang seharusnya | Terkait | Status |
|---|---|---|---|---|---|---|
| B-12 | P1 | Paket sudah selesai, ternyata salah | Analisis bisa diarsipkan, tetapi berkas tetap menempel ke klaim | "Batalkan paket": arsipkan analisis dan lepas berkasnya | B-2 | **Selesai** |
| B-13 | P1 | Sedang mengunggah | Tidak ada tombol batal; bila tab ditutup, paket tertinggal berstatus "mengunggah" dan berkas sementara tertinggal di server | Tombol "Batalkan unggahan" | B-14 | **Selesai** |
| B-14 | P1 | Paket terbengkalai | Tidak pernah dibersihkan | Dibersihkan otomatis (misalnya setelah 24 jam) | B-13, B-26 | **Selesai** |
| B-15 | P2 | Berkas sudah dipilih, belum diunggah | Tidak ada daftar nama berkas, tidak ada hapus per berkas | Daftar berkas terpilih (nama, jenis, ukuran, hapus); peringatan berkas tak dikenal sebelum diunggah | B-5 | **Selesai** |
| B-16 | P3 | Sedang diproses | Tidak bisa dibatalkan | Boleh tetap begitu (singkat); tampilkan bahwa hasilnya bisa diarsipkan | | **Selesai** |

### 2d. Notifikasi

| Kode | Prio | Temuan | Yang seharusnya | Terkait | Status |
|---|---|---|---|---|---|
| B-17 | P1 | Dialog peringatan faskes muncul setiap login walaupun isinya sama (berisiko kelelahan peringatan) | Muncul hanya bila ada analisis yang belum pernah dilihat pengguna itu | | **Selesai** |
| B-18 | P1 | Belum ada notifikasi saat analisis baru menemukan faskes terindikasi | Pop-up kanan atas dengan tombol "Lihat faskes" | | **Selesai** |
| B-19 | P2 | Pop-up hilang tanpa riwayat | Ikon lonceng berisi riwayat notifikasi (dibaca dan belum) | | **Selesai** |

### 2e. Kasus lain

| Kode | Prio | Kasus | Kondisi sekarang | Yang seharusnya | Status |
|---|---|---|---|---|---|
| B-20 | P2 | Klaim yang sama ada di CSV dan FHIR | Yang diunggah lebih dulu menang; aturannya tidak jelas | RME (FHIR) diutamakan; perbedaannya dicatat | **Selesai** |
| B-21 | P2 | Paket yang sama diunggah dua kali | Dua hasil analisis tanpa peringatan | Peringatkan bahwa paket ini sudah pernah dianalisis | **Selesai** |
| B-22 | P3 | Masa simpan berkas medis (PDF) | Tersimpan selamanya | Kebijakan retensi sesuai aturan rekam medis | **Selesai** (10 tahun berdasar UU 8/1997; paket batal 30 hari; dapat diubah) |
| B-23 | P2 | Banyak paket besar diproses bersamaan | Semua berjalan bersamaan dan berebut CPU | Antrean pemrosesan dengan posisi antrean | **Selesai** |
| B-24 | P2 | Sesi habis di tengah unggahan ribuan berkas | Gagal di tengah; paket tertinggal | Lanjutkan unggahan, atau pesan jelas lalu dibersihkan (B-14) | **Selesai** |

### 2f. Kelayakan produk dan penerimaan pengguna (SA/PO)

| Kode | Prio | Temuan | Yang seharusnya | Terkait | Status |
|---|---|---|---|---|---|
| B-25 | P1 | Pesan galat sebagian masih umum dan tidak menyebut langkah berikutnya | Setiap pesan menyebut apa yang salah, berkas mana, dan apa yang harus dilakukan | B-4, B-8 | **Selesai** |
| B-26 | P1 | Belum ada skenario uji penerimaan per peran | Skenario dengan kriteria lulus (misalnya "temukan klaim risiko tinggi terbesar dan putuskan dalam 3 menit"), dijalankan sebagai simulasi, lalu dicoba pengguna | | **Selesai** |

Panduan di aplikasi, penjelasan istilah, dan tunggu AI yang terasa macet dicatat sekali saja di A-32 dan A-33.

## 3. Audit antislop 002: UI/UX menyeluruh

| Kode | Prio | Halaman | Temuan | Terkait | Status |
|---|---|---|---|---|---|
| A-34 | **P0** | Beranda | **Angka salah:** "Menguatkan klaim risiko tinggi" selalu 0; seharusnya 165 | A-23 | **Selesai** |
| A-17 | P2 | Semua (gelap) | Kartu hampir sewarna latar; mode gelap datar tanpa gradasi | A-4 | **Selesai** |
| A-18 | P1 | Detail klaim | Dua skor 0–100 berbeda arti berdampingan | A-26 | **Selesai** |
| A-19 | P1 | Beberapa | Istilah teknis tampil ke verifikator ("Tambahan AI 95+", rumus indeks prioritas, "model bahasa belum dikonfigurasi", pengaturan server) | DESIGN.md | **Selesai** |
| A-20 | P2 | Beranda | Label "Analisis pertama" di 4 kartu tanpa pembanding | U-2, A-11 | **Selesai** |
| A-21 | P2 | Beranda | Grafik kelompok faskes berlabel #1–#6; satu batang mendominasi | | **Selesai** |
| A-22 | P1 | Beranda, Antrean | Kemajuan "0 / 8.540" ikut menghitung 7.450 klaim risiko rendah | U-1 | **Selesai** |
| A-23 | P2 | Beranda | Kartu AI berisi angka tanpa makna; "95+" tampak seperti jumlah | A-34 | **Selesai** |
| A-24 | P1 | Antrean | Baris penuh chip; di ponsel 5–6 baris per klaim; tanpa rupiah | A-9 | **Selesai** |
| A-25 | P2 | Antrean | Panel kanan kosong besar saat belum memilih klaim | U-3 | **Selesai** |
| A-26 | P1 | Detail klaim | Kepala mengulang "Risiko tinggi" dua kali, tanpa rupiah; bukti baru muncul setelah ±2 layar | A-10, A-15, A-18 | **Selesai** |
| A-27 | P2 | Detail klaim | Bilah "Tindakan cepat" menutupi isi saat membaca | | **Selesai** |
| A-28 | P1 | Rincian faskes, Paket bukti | Kesimpulan faskes berupa paragraf "(1)…(2)…(3)…" | U-5 | **Selesai** |
| A-29 | P2 | Paket bukti | Kolom "Risiko" sama di 30 baris dan terpotong; tanpa rupiah | | **Selesai** |
| A-30 | P2 | Data & Analisis | Dua tempat unggah (paket dan CSV cepat) membingungkan | B-15 | **Selesai** |
| A-31 | P2 | Data & Analisis | Tombol "Hapus" merah penuh di setiap baris | | **Selesai** |
| A-32 | P2 | Detail klaim | Menunggu AI (27–80 detik) tanpa keterangan tahap | | **Selesai** |
| A-33 | P2 | Semua | Tidak ada panduan di aplikasi dan penjelasan istilah (halaman bantuan sempat dibuat, lalu ikut dibatalkan dari `master`) | | **Selesai** |
| U-1 | P1 | Beranda | **Usulan:** alur tinjauan (Belum → Sedang → Klarifikasi → Audit → Selesai) dengan jumlah dan rupiah per tahap, bisa diklik | A-22 | **Selesai** |
| U-2 | P1 | Beranda | **Usulan:** kartu angka dengan rupiah dan tren harian | A-11, A-20 | **Selesai** |
| U-3 | P1 | Beranda, Antrean | **Usulan:** rincian nilai tagihan saat angka rupiah diklik | B-10, B-11, A-9, A-25 | **Selesai** |
| U-4 | P2 | Beranda | **Usulan:** batang bertumpuk porsi rupiah per modus | | **Selesai** |
| U-5 | P2 | Faskes | **Usulan:** kartu profil kelompok faskes yang ringkas | A-13, A-28 | **Selesai** |

## 4. Pekerjaan terbuka dari tahap sebelumnya

| Kode | Prio | Hal | Keterangan | Status |
|---|---|---|---|---|
| T-1 | P1 | Deploy ke alamat yang bisa diakses mentor dan juri | Syarat agar catatan mentor 2 ("upload belum dapat dicoba") benar-benar terjawab | **Keputusan** Anda (waktunya) |
| T-2 | P2 | Uji `test_demo_files_match_the_generator` gagal di Windows | Akhir baris CSV diubah Git menjadi CRLF; sudah ada sebelum sesi ini | **Selesai** |
| T-3 | P2 | Server Anda di port 8001 masih kode lama | Perlu dinyalakan ulang dengan kode baru (dan API key bila ingin memakai model) | Langkah untuk Anda (lihat laporan) |
| T-4 | P3 | Uji beban 440 ribu klaim | Tidak dijalankan karena RAM laptop; angka di analisis kelayakan berupa perkiraan dari tren terukur | Dicatat; menunggu server |
| T-5 | P3 | Profil GPU (vLLM) dan HTTPS | Tidak bisa diuji di laptop ini | Dicatat; menunggu server |
| T-6 | P3 | Perbandingan dengan model selain Gemma (Qwen, SEA-LION) | Tidak tersedia di layanan gratis | Dicatat; menunggu layanan |
| T-7 | P3 | Ketepatan baca berkas nyata | Hanya diuji pada berkas sintetis cetak | Dicatat; tahap pilot |
| T-8 | P3 | Kecepatan model bahasa di layanan gratis lambat (27–80 detik) | Bukan ukuran kecepatan di server sendiri; mempengaruhi kesan saat demo | Dicatat; layar menampilkan tahap dan perkiraan waktu |
| T-9 | P3 | Branch `feat/masukan-coaching` belum digabung ke `master` | Perintah sudah diberikan; digabung setelah perbaikan selesai | **Keputusan** Anda |

## 5. Pengelompokan untuk pengerjaan

Butir yang saling terkait dikerjakan sekaligus:

| Paket kerja | Isi | Prio tertinggi |
|---|---|---|
| **K1. Kebenaran data** | B-1, B-2, B-3, A-34 | P0 |
| **K2. Rupiah dan teks** (catatan mentor 4 dan coaching) | A-9–A-15, A-18, A-20–A-24, A-26, A-28, B-10, B-11, U-2, U-3, U-4, U-5 | P1 |
| **K3. Paket klaim yang tahan salah** | B-4–B-9, B-12–B-16, B-20, B-21, B-23–B-25, A-30 | P1 |
| **K4. Notifikasi** | B-17, B-18, B-19 | P1 |
| **K5. Aturan wajib tampilan** | A-1–A-6, A-17 | P1 |
| **K6. Kejelasan dan kenyamanan** | A-7, A-8, A-19, A-25, A-27, A-29, A-31, A-32, A-33, U-1 | P1–P2 |
| **K7. Uji penerimaan** | B-26 (setelah K1–K6) | P1 |
| **K8. Lingkungan dan keputusan** | T-1–T-9, B-22 | Keputusan |


## 6. Hasil pengerjaan (12 November 2026)

Semua butir yang bisa dikerjakan di kode sudah selesai. Yang tersisa adalah keputusan (T-1, T-9), langkah di komputer Anda (T-3), dan hal yang butuh lingkungan lain (T-4 sampai T-8).

Bukti:

- Uji server: 593 lulus, 14 dilewati (uji khusus PostgreSQL lokal), 0 gagal. Uji yang dulu gagal di Windows (T-2) sekarang lulus.
- Uji tampilan e2e: 8/8 lulus (mode pengembangan) dan 7/7 lulus (build produksi).
- Stack Docker dengan PostgreSQL: migrasi `0012_intake_cancel` terpasang; batal unggah, berkas keliru, batal paket, dan alur tinjauan diuji langsung.
- Simulasi uji penerimaan: 7/7 skenario lulus (docs/skenario-uji-penerimaan.md).
- Ponsel 390 px: tidak ada geser samping di 6 halaman utama; tidak ada tombol di bawah 44 px (kecuali kotak provinsi di Peta yang punya padanan daftar).

Tambahan setelah rekap: layar **Kelola akun** untuk administrator (tambah akun, ubah peran, nonaktifkan, atur ulang kata sandi, log keamanan).
