# DESIGN.md: Claim Integrity Radar

Arahan desain untuk semua perubahan tampilan. Isinya diturunkan dari tampilan yang sudah ada dan sudah lolos 20 besar, bukan gaya baru. Aturan antislop (`antislop`) dipakai sebagai penyaring di atas arahan ini.

## Siapa dan untuk apa

- **Pengguna:** verifikator klaim BPJS Kesehatan dan administrator. Mereka memakai aplikasi ini berjam-jam setiap hari, di layar kantor dan kadang di ponsel.
- **Pekerjaan utama di setiap layar:** memutuskan klaim mana yang diperiksa lebih dulu, lalu memutuskan klaim itu. Setiap layar dibangun di sekitar keputusan itu, bukan di sekitar template dasbor.
- **Rasa yang dituju:** institusional, tenang, dan bisa dipercaya. Ini alat kerja lembaga publik, bukan halaman pemasaran.

## Dial

`Dial: ENERGY 2 / RHYTHM 2 / MOTION 1`

| Dial | Nilai | Artinya di produk ini |
|---|---|---|
| ENERGY | 2 | Ramah dan jelas, dengan satu titik fokus kuat per layar (misalnya blok risiko tinggi), tanpa dekorasi ramai |
| RHYTHM | 2 | Pola kartu dan tabel yang konsisten, dengan variasi pada bagian yang paling penting (blok fokus, kepala klaim) |
| MOTION | 1 | Gerak hanya untuk umpan balik: arah kursor, buka-tutup, penghitung angka saat pertama tampil, dan tanda memuat. Tidak ada gerak dekoratif berulang. |

## Prinsip isi (jawaban atas catatan mentor)

1. **Angka dulu, kalimat kemudian.** Bila sebuah informasi berupa jumlah, tampilkan angkanya besar dengan label pendek, bukan dalam kalimat.
2. **Jumlah selalu berpasangan dengan rupiah.** Di mana pun ada jumlah klaim berisiko (jalur, modus, faskes, antrean, klaim), tampilkan nilai tagihannya.
3. **Setiap angka bisa dijelaskan.** Asal angka ditulis terlihat di bawahnya, misalnya "jumlah tagihan RS (FKL47) sebelum verifikasi, bukan kerugian". Kalau diklik, angkanya membuka rincian, bukan halaman yang tidak memuat angka itu.
4. **Satu angka, satu tempat.** Angka yang sama tidak diulang di beberapa kartu pada layar yang sama.
5. **Bahasa kerja verifikator.** Bahasa Indonesia yang lugas, tanpa istilah teknis sistem (persentil, model bahasa, nama kolom) di layar utama. Istilah teknis tinggal di "Detail teknis".
6. **Jujur.** Tidak ada angka tanpa sumber. Hasil uji sintetis disebut sintetis. Tanda risiko adalah prioritas pemeriksaan, bukan bukti kecurangan.

## Warna

Palet inti dua warna ditambah warna status. Warna netral tidak dihitung.

| Peran | Terang | Gelap | Alasan |
|---|---|---|---|
| Merek / aksi utama | `#047857` (hover `#065f46`) | `#087f5b` (aksen teks `#34d399`) | Hijau BPJS: menandai milik siapa produk ini; dipakai untuk aksi utama dan navigasi |
| Latar halaman | `#edf1ee` dengan gradasi hijau muda di atas | `#0b1311` | Latar hangat kehijauan, bukan putih steril |
| Kartu | `#ffffff`, garis `#e1e7e3`, bayangan halus | `#121c19`, garis `#22302b` | Kartu terpisah jelas dari latar |
| Risiko tinggi | `#dc2626` (latar `#fef2f2`) | `#ef4444` (latar `#2c1414`) | Warna jalur; satu-satunya merah di layar |
| Risiko sedang | `#d97706` (latar `#fffbeb`) | `#f59e0b` (latar `#2a2010`) | Warna jalur. **Hanya untuk ikon, titik, dan teks besar**; untuk teks kecil kontrasnya kurang dari 4,5:1 (audit 001 no. 3) |
| Risiko rendah | `#059669` (latar `#ecfdf5`) | `#10b981` (latar `#0f2a1f`) | Warna jalur |

Aturan:
- **Merah, kuning, dan hijau jalur hanya dipakai untuk tingkat risiko.** Bukan untuk dekorasi atau status lain.
- **Satu aksen per layar:** hijau merek untuk aksi utama. Blok risiko tinggi boleh memakai merah sebagai titik fokus.
- **Gradasi hanya untuk dua hal:** kartu utama yang menjadi titik fokus (kartu hijau Beranda, kepala klaim) dan latar halaman. Selain itu permukaan rata.
- **Teks kecil harus mencapai kontras 4,5:1** di kedua mode. Teks samar di mode gelap perlu dinaikkan (audit 001 no. 4).

## Huruf

- **Plus Jakarta Sans** (400, 500, 600, 700, 800). Alasannya: huruf yang dirancang di Indonesia, ramah dan jelas pada ukuran kecil, dan selaras dengan nuansa layanan publik. Ini bukan pilihan default AI.
- **Hierarki:**
  - judul halaman 40 px tebal dengan kata kedua berwarna lebih lembut ("Prioritas *hari ini*");
  - angka utama 40–52 px tebal;
  - judul kartu 15–16 px;
  - isi 14–15 px;
  - keterangan 12–13 px.
- **Angka** memakai `font-variant-numeric: tabular-nums` di tabel supaya rata.
- **Huruf kapital berjarak lebar** hanya untuk satu penanda per layar yang punya alasan (misalnya "FOKUS UTAMA"), bukan untuk label biasa (audit 001 no. 8).

## Bentuk dan jarak

- **Sudut:** 10 px untuk tombol, kolom, dan chip; 12–14 px untuk kartu dalam; 18–22 px untuk kartu utama dan panel. Tidak semua elemen dibuat bulat penuh. Bentuk pil hanya untuk chip status dan filter.
- **Bayangan** hanya untuk tanda ketinggian: kartu, dialog, dan bilah yang mengambang. Elemen di dalam kartu tidak berbayang.
- **Jarak** antarkartu 18 px; di dalam kartu 14–22 px. Bagian yang paling penting boleh lebih lega.

## Ikon

- Pustaka Lucide dipakai karena konsisten dan tipis. Ikon dipilih karena relevan dengan isinya, misalnya gedung untuk faskes, perisai untuk risiko tinggi, dan dokumen untuk berkas.
- **Tidak ada ikon "kilau" (Sparkles) sebagai tanda AI.** Gunakan ikon yang menjelaskan fungsinya: memindai teks untuk pembaca catatan, daftar berurutan untuk urutan AI, dan gelembung pertanyaan untuk tanya berkas (audit 002 no. 7).

## Pola komponen

| Komponen | Pola |
|---|---|
| Kartu angka | Label pendek, angka besar, nilai rupiah, dan tren kecil bila datanya ada. Tidak ada label perbandingan kalau tidak ada pembanding. |
| Daftar klaim | Satu baris: jenis temuan, nilai tagihan, status. Modus dan AI sebagai tanda kecil. |
| Kesimpulan dan alasan | Kartu alasan bernomor dengan satu angka besar, bukan paragraf "(1)…(2)…(3)…". |
| Penjelasan | Satu kalimat terlihat. Rincian panjang disembunyikan di bagian yang bisa dibuka. |
| Status kosong, memuat, galat | Menyebut penyebab dan satu langkah berikutnya. Menunggu yang lama (AI) menampilkan tahap dan perkiraan waktu. |
| Tindakan merusak (hapus, arsip) | Tombol sekunder dengan konfirmasi yang menyebut akibatnya. Tidak berwarna merah penuh di setiap baris. |
| Notifikasi | Pop-up untuk kejadian baru, riwayat lewat ikon lonceng, dan dialog saat login hanya bila ada yang baru. |

## Aksesibilitas dan tata letak

- Semua kontrol bisa dipakai dengan keyboard dan punya penanda fokus yang terlihat.
- Sasaran sentuh di ponsel minimal 44 px. Tidak ada geser horizontal di 390 px.
- Kedua mode (terang dan gelap) diperiksa untuk setiap perubahan.
- `prefers-reduced-motion` menghentikan gerak yang tidak penting.
