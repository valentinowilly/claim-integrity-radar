# Skenario uji penerimaan

Skenario ini menguji apakah verifikator bisa menyelesaikan pekerjaan nyata dengan sistem, bukan hanya apakah fiturnya ada. Setiap skenario punya batas waktu dan syarat lulus yang bisa diamati.

Semua uji memakai **data sintetis** (paket contoh "Klaim September multisumber": 29.628 klaim, 240 berkas PDF). Hasil di bawah adalah simulasi otomatis di peramban (Playwright) yang menjalankan langkah yang sama dengan pengguna. Simulasi membuktikan alurnya berjalan dan cukup cepat. Simulasi tidak membuktikan bahwa pengguna paham tanpa dibantu; itu perlu diuji dengan orang sungguhan (lihat bagian terakhir).

## Hasil simulasi, 12 November 2026

| Kode | Skenario | Syarat lulus | Batas | Waktu | Hasil |
|---|---|---|---|---|---|
| UAT-1 | Temukan klaim risiko tinggi dengan tagihan terbesar, lalu catat tindakannya | Dari Beranda sampai status "Minta klarifikasi" tersimpan | 3 menit | 3 detik | Lulus |
| UAT-2 | Jelaskan dari mana angka rupiah risiko tinggi berasal | Rincian menampilkan asal angka (FKL47), porsi dari seluruh tagihan, keterangan "bukan kerugian", per modus, dan klaim terbesar | 1 menit | 1 detik | Lulus |
| UAT-3 | Unggah paket berisi berkas keliru (JSON bukan Bundle FHIR, gambar bernama .pdf) | Paket tetap selesai; setiap berkas keliru disebut namanya beserta alasannya | 3 menit | 3 detik | Lulus |
| UAT-4 | Batalkan paket yang salah kirim | Analisisnya pindah ke Arsip dan berkas PDF-nya lepas dari klaim | 1 menit | di bawah 1 detik | Lulus |
| UAT-5 | Buat paket bukti untuk kelompok faskes paling mendesak | Paket bukti memuat daftar klaim sampel dan total tagihannya | 2 menit | 4 detik | Lulus |
| UAT-6 | Lihat lagi notifikasi yang sudah hilang dari layar | Ikon lonceng berisi riwayat notifikasi | 30 detik | di bawah 1 detik | Lulus |
| UAT-7 | Di ponsel (lebar 390 px), baca angka utama | Halaman tidak bisa digeser ke samping; semua tombol minimal 44 px | 1 menit | 1 detik | Lulus |

Waktu simulasi adalah waktu mesin, bukan waktu orang membaca. Batas waktu disusun untuk orang.

## Pemeriksaan pendukung

- Uji otomatis server: termasuk 17 uji paket klaim (berkas keliru, batal unggah, pembersihan otomatis, RME diutamakan dari CSV, paket ganda, nama berkas yang ditolak, model bahasa hanya untuk halaman yang tampak seperti berkas klaim).
- Pemeriksaan ponsel di enam halaman utama: tidak ada geser samping dan tidak ada tombol di bawah 44 px. Kotak provinsi pada Peta tetap 22 px, tetapi setiap provinsi juga bisa dipilih dari daftar di bawah peta.
- Kontras warna diperiksa untuk teks merah, kuning, dan teks samar di mode terang dan gelap (semua minimal 4,5:1).

## Uji dengan pengguna sungguhan

Langkah berikutnya, sebelum dipakai:

1. Minta 3 sampai 5 verifikator mencoba UAT-1 sampai UAT-5 tanpa diberi tahu letak tombolnya.
2. Catat waktu, tempat mereka ragu, dan pertanyaan yang muncul.
3. Skenario lulus bila sedikitnya 4 dari 5 orang selesai dalam batas waktu tanpa dibantu.
4. Perbaiki bagian yang membuat ragu, lalu ulangi.

## Hal yang menunggu lingkungan atau keputusan

| Kode | Hal | Keadaan |
|---|---|---|
| T-1 | Alamat yang bisa dibuka mentor dan juri | Keputusan tim (kapan dipasang) |
| T-4 | Uji beban 440 ribu klaim | Butuh server dengan RAM lebih besar; angka di analisis kelayakan adalah perkiraan dari 30 ribu, 120 ribu, dan 240 ribu klaim yang diukur |
| T-5 | Profil GPU (vLLM) dan HTTPS | Butuh server dengan GPU dan sertifikat |
| T-6 | Pembanding model selain Gemma | Tidak tersedia di layanan gratis |
| T-7 | Ketepatan baca berkas nyata | Baru diuji pada berkas sintetis cetak dan pindai; perlu tahap pilot |
| T-8 | Kecepatan AI di layanan gratis (30 sampai 80 detik) | Bukan ukuran kecepatan di server sendiri; layar menampilkan tahap dan perkiraan waktunya |
| B-22 | Masa simpan berkas PDF rekam medis | Keputusan BPJS sesuai aturan rekam medis; saat ini berkas disimpan sampai dihapus |
