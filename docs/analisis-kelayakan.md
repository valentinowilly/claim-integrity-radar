# Analisis Kelayakan Penerapan Claim Integrity Radar

Dokumen ini menjawab satu pertanyaan: **apakah sistem ini dapat diterapkan di BPJS Kesehatan, dengan kebutuhan dan biaya berapa, dan apa manfaatnya?**

Setiap angka diberi asal-usulnya:
- **Terukur**: diukur sendiri di sistem ini.
- **Sumber publik**: dengan tautan.
- **Asumsi**: perkiraan tim, disebut terang dan bisa diganti dengan angka BPJS.

Semua uji memakai **data sintetis**. Hasil uji ketepatan bukan kinerja pada data nyata.

## 1. Ringkasan

| Pertanyaan | Jawaban | Dasar |
|---|---|---|
| Sanggup memproses volume harian BPJS? | **Ya, dengan satu server.** 240 ribu klaim dianalisis dalam ±5 menit memakai 4,1 GB memori. Volume satu hari (±440 ribu klaim FKRTL) diperkirakan ±8 menit dan ±7,6 GB. | Terukur sampai 240 ribu; 440 ribu adalah perkiraan dari tren terukur |
| Butuh perangkat apa? | Satu server aplikasi (16 inti, 32 GB RAM), PostgreSQL, dan untuk model bahasa satu server dengan 2 GPU 80 GB | Terukur dan sumber publik |
| Berapa biayanya? | Perangkat AI sekitar Rp1,2–1,5 miliar sekali beli; server aplikasi dan basis data memakai infrastruktur yang ada | Sumber publik dan asumsi kurs |
| Sebanding dengan manfaatnya? | Satu kasus fisioterapi fiktif yang diungkap KPK di 3 rumah sakit bernilai sekitar Rp34–35 miliar, sekitar 25 kali biaya perangkat AI | Sumber publik |
| Apa yang belum terbukti? | Ketepatan pada data nyata, ketepatan baca berkas nyata, dan kecepatan model bahasa di GPU sendiri. Ketiganya diukur pada tahap pilot. | Lihat bagian 7 |

## 2. Kapasitas terukur

**Cara uji:** `python -m scripts.load_test` (folder `backend`).
- 29.628 klaim sintetis demo-3 diperbanyak menjadi beberapa salinan. Setiap salinan mendapat peserta, nomor kunjungan, dan periode baru, dan catatan klinisnya dibedakan supaya tidak terbaca sebagai salinan catatan.
- Setiap volume diimpor lewat jalur impor tervalidasi yang sama dengan unggahan, lalu dianalisis lengkap: 12 pemeriksaan, AI Pola Klaim, jalur risiko, dan kelompok faskes.
- Mesin uji: laptop AMD Ryzen 7 5825U (8 inti, 16 utas), 15,4 GB RAM, SQLite, satu proses.

| Klaim | Impor tervalidasi | Analisis | Total | Klaim per detik | Memori puncak | Klaim risiko tinggi |
|---|---|---|---|---|---|---|
| 29.628 | 6,9 detik | 39,8 detik | 46,7 detik | 635 | 0,68 GB | 488 |
| 120.000 | 33,4 detik | 137,6 detik | 171 detik | 702 | 2,06 GB | 1.973 |
| 240.000 | 69,2 detik | 219,9 detik | 289 detik | 830 | 4,13 GB | 3.948 |
| ±440.000 (satu hari FKRTL) | | | **±8 menit (perkiraan)** | | **±7,6 GB (perkiraan)** | |

Cara membaca tabel:
- **Hasil konsisten saat volume naik.** Jumlah klaim risiko tinggi naik sebanding dengan jumlah salinan (488 → 1.973 → 3.948, yaitu 4,0 dan 8,1 kali). Pemeriksaan tidak "kehilangan" temuan pada volume besar.
- **Perkiraan 440 ribu** diambil dari kenaikan terukur antara 120 ribu dan 240 ribu: sekitar 1 milidetik dan 17 KB memori per klaim tambahan. Uji 440 ribu tidak dijalankan karena memori laptop tidak cukup. Perlu diukur ulang di server sasaran.
- **Volume harian** diambil dari 143,1 juta kunjungan rawat jalan tingkat lanjut dan 18,4 juta kasus rawat inap setahun ([laporan DJSN Desember 2025](https://sismonev.djsn.go.id/kesehatan/doc/laporan-bulanan/Monthly_Report_JKN_12_2025.pdf)), dibagi 365.

**Temuan dari uji beban ini.** Uji pertama pada 120 ribu klaim berjalan lebih dari 20 menit lalu dihentikan, padahal 30 ribu klaim hanya butuh 68 detik. Penyebabnya: pemeriksaan "klaim serupa antarpeserta" memindai seluruh klaim untuk setiap tanggal. Penghitungannya dibatasi pada klaim bertanggal sama. Keluaran pada data demo-3 terbukti **identik** (4.466 kandidat, isi sama persis), dan waktunya kini naik hampir linear. Tanpa uji beban, masalah ini baru akan muncul saat dipasang di BPJS.

**Membaca berkas PDF** (terukur):
- PDF digital dibaca dalam hitungan milidetik.
- PDF hasil pindai butuh ±2 detik per halaman pada satu inti CPU, atau ±40 ribu halaman per hari per proses.
- Paket 242 berkas (CSV, JSON, dan 240 PDF, 81 di antaranya hasil pindai) selesai digabung dan dianalisis dalam ±5,5 menit.

Sejak SEB RME–SATUSEHAT (Juli 2026), berkas PDF makin berkurang. Yang tetap ada: masa transisi, klaim pending, dispute, dan koreksi audit.

## 3. Kebutuhan perangkat

| Komponen | Kebutuhan | Dasar |
|---|---|---|
| Server aplikasi (API, analisis, OCR) | 16 inti, 32 GB RAM. Analisis satu hari butuh ±7,6 GB; sisanya untuk OCR, basis data cache, dan cadangan. | Terukur, ditambah cadangan 4 kali lipat |
| Basis data | PostgreSQL 16, sekitar 3,8 MB per seribu klaim (±1,7 GB per hari volume FKRTL, sebelum kebijakan retensi) | Terukur dari ukuran basis data uji |
| Model bahasa (opsional) | Satu server dengan 2 GPU 80 GB (H100 atau setara): satu melayani, satu cadangan | Gemma 4 31B muat di satu GPU 80 GB ([uji vLLM](https://markaicode.com/benchmarks/cuda-gemma-4-h100-latency-benchmark/)) |
| Penyimpanan berkas | Sesuai volume PDF; berkas disimpan sekali per isi (nama berkas berupa *hash*) | Desain sistem |

**Model bahasa hanya dipakai untuk klaim yang ditandai**, sekitar 3,7% klaim di data uji. Untuk ±16 ribu klaim per hari dengan ±300 token jawaban, totalnya ±5 juta token. Satu GPU H100 melayani 855–1.260 token per detik pada beban puncak ([InferenceBench](https://inferencebench.io/blog/gemma-4-31b-h100-complete-inference-benchmark/)), jadi selesai dalam 1–2 jam. Tanpa model bahasa, sistem tetap berjalan penuh dengan pembaca aturan teks.

## 4. Biaya

| Pos | Perkiraan | Asal |
|---|---|---|
| 2 GPU H100 80 GB | US$50.000–62.000 | US$25.000–31.000 per kartu ([panduan harga, Agustus 2026](https://intuitionlabs.ai/articles/nvidia-ai-gpu-pricing-guide)) |
| Server untuk GPU | US$20.000–28.000 | Asumsi tim (sasis, CPU, memori, catu daya) |
| **Total perangkat AI** | **US$70.000–90.000, atau Rp1,2–1,5 miliar** | Asumsi kurs Rp16.500 per US$ |
| Server aplikasi dan basis data | Memakai infrastruktur yang ada | Asumsi: kebutuhannya setara satu server menengah |
| Lisensi perangkat lunak | Rp0 | Semua komponen berlisensi terbuka: FastAPI, PostgreSQL, scikit-learn, RapidOCR, vLLM, Gemma 4 (Apache 2.0) |

Biaya operasional (listrik, pemeliharaan, tim pemelihara aturan bersama koder klinis) belum dihitung, karena bergantung pada tarif dan struktur tim BPJS.

## 5. Manfaat

### 5.1 Skala uang yang dilindungi

| Angka | Nilai | Sumber |
|---|---|---|
| Biaya pelayanan kesehatan JKN 2025 | Rp191,33 triliun | [Okezone/RCTI+](https://www.rctiplus.com/news/detail/okezone/5419478/bpjs-kesehatan-salurkan-rp191-33-triliun-untuk-layanan--jantung-jadi-pengeluaran-terbesar) |
| Porsi rawat inap tingkat lanjut | ±56,5% dari beban jaminan | [Laporan DJSN Desember 2025](https://sismonev.djsn.go.id/kesehatan/doc/laporan-bulanan/Monthly_Report_JKN_12_2025.pdf) |
| Porsi rawat jalan tingkat lanjut | ±30,3% | [Laporan DJSN Juli 2025](https://sismonev.djsn.go.id/kesehatan/doc/laporan-bulanan/Monthly_Report_JKN_07_2025.pdf) |
| Rasio klaim 2025 | 108,27% (pengeluaran melebihi iuran) | [Fortune IDN](https://www.fortuneidn.com/news/bpjs-kesehatan-defisit-rp14-61-triliun-di-2025-rasio-klaim-108-27-00-ccw2k-k3zd10) |
| Satu kasus fisioterapi dan katarak fiktif, 3 RS | ±Rp34–35 miliar; dari 4.341 klaim fisioterapi hanya sekitar 1.072 yang punya rekam medis | [Kontan](https://nasional.kontan.co.id/news/kpk-ada-rs-ajukan-klaim-palsu-ke-bpjs-diduga-rugikan-negara-puluhan-miliar), [Detik](https://finance.detik.com/moneter/d-7463145/dirugikan-rp-35-m-bpjs-kesehatan-minta-rs-kembalikan-uang-klaim-fiktif/amp) |

### 5.2 Titik impas

Belum ada angka resmi tingkat kecurangan klaim JKN yang terbuka, jadi tim **tidak menebak berapa rupiah yang akan diselamatkan**. Yang bisa dihitung adalah titik impasnya:

- **Biaya perangkat AI** (Rp1,2–1,5 miliar) **setara dengan sekitar 0,0007–0,0009% dari biaya pelayanan FKRTL setahun** (±87% dari Rp191 triliun, atau ±Rp166 triliun).
- **Sistem balik modal bila mencegah atau memulihkan tagihan bermasalah senilai Rp1,5 miliar**, sekali saja, dari seluruh FKRTL.
- **Satu kasus KPK di 3 rumah sakit** (Rp34–35 miliar) bernilai sekitar **25 kali** titik impas itu.

Modus kasus tersebut (sesi fisioterapi melebihi kapasitas, tanpa catatan sesi, dicatat serentak) adalah modus yang ditangkap pemeriksaan kapasitas, pola waktu, dan kelengkapan bukti di sistem ini. Pada data sintetis, 301 dari 301 klaim modus ini masuk jalur merah.

### 5.3 Efisiensi kerja verifikator

| Angka | Nilai | Asal |
|---|---|---|
| Klaim masuk per hari, FKTP sampai FKRTL | ±2 juta | [GovInsider](https://govinsider.asia/indo-en/article/integrasi-data-kesehatan-bantu-bpjs-kesehatan-deteksi-potensi-fraud) |
| Jumlah verifikator | ±1.000 (tanpa tanggal; mungkin sudah berubah) | [GovInsider](https://govinsider.asia/indo-en/article/integrasi-data-kesehatan-bantu-bpjs-kesehatan-deteksi-potensi-fraud) |
| Klaim bermasalah per 100 berkas yang dibuka (data sintetis) | Audit acak 2,9; aturan sederhana 9,4; **Radar 94** | Terukur, `docs/analytics-spec.md` |

Artinya: dengan jumlah berkas yang dibuka sama, verifikator menemukan sekitar **30 kali lebih banyak klaim bermasalah** dibanding memilih acak (pada data sintetis). Radar tidak menambah beban kerja; ia mengubah urutan pemeriksaan.

## 6. Tahapan penerapan

| Tahap | Lama | Isi | Ukuran berhasil |
|---|---|---|---|
| **0. Persiapan** | 1 bulan | Izin data; penyesuaian pemetaan FHIR dengan profil resmi SATUSEHAT dan E-Klaim; pemasangan di lingkungan uji BPJS (Docker Compose) | Paket klaim satu hari dari satu cabang berhasil masuk dan dianalisis |
| **1. Pilot berdampingan** | 3 bulan, 1 kedeputian wilayah | Radar berjalan berdampingan dengan verifikasi yang ada, tanpa mengubah keputusan. Verifikator mencatat hasil pemeriksaan klaim yang ditandai | Ketepatan pada data nyata (berapa yang ditandai memang bermasalah); porsi klaim jujur yang ikut ditandai; waktu per berkas |
| **2. Penyetelan** | 1 bulan | Ambang dan aturan disetel dari hasil pilot bersama koder klinis; ketepatan baca berkas nyata diukur | Ambang disahkan pemilik proses |
| **3. Perluasan** | bertahap | Wilayah lain; server model bahasa di GPU internal; integrasi otomatis dari sistem klaim | Kapasitas dan ketepatan bertahan di volume nasional |

Orang yang terlibat: tim TI (pemasangan dan operasi), verifikator wilayah pilot (pengguna), koder klinis atau dokter verifikator (penyetelan aturan), tim anti-kecurangan (tindak lanjut), dan keamanan informasi (tinjauan).

## 7. Risiko dan yang belum terbukti

| Risiko | Mitigasi |
|---|---|
| Ketepatan pada data nyata lebih rendah dari data sintetis | Pilot berdampingan tanpa mengubah keputusan; ketepatan diukur dari keputusan verifikator yang tercatat di sistem |
| Klaim jujur ikut ditandai | Jalur hijau untuk kemiripan saja; setiap tanda disertai alasan dan bukti; keputusan tetap pada manusia |
| Berkas nyata (tulisan tangan, stempel, pindaian buram) lebih sulit dibaca | Pembaca tingkat kedua (model bahasa-visual); tanda "OCR kurang yakin"; nilai yang tidak terbaca tidak dipakai mengisi data |
| Data pendukung belum tersedia (kapasitas faskes, jam layanan, bukti penyerahan) | Pemeriksaan yang datanya tidak ada berstatus "tidak berlaku", tidak dianggap aman; data ini makin tersedia lewat RME |
| Volume nasional melebihi satu server | Analisis berjalan per paket harian; paket bisa dibagi per wilayah dan dijalankan paralel |
| Data kesehatan bocor | Semua komponen berjalan di jaringan sendiri; identitas disamarkan; jejak audit setiap tindakan |

**Yang belum terbukti dan akan diukur saat pilot:**
- ketepatan pada data klaim nyata;
- ketepatan baca berkas nyata;
- kecepatan model bahasa di GPU sendiri;
- waktu analisis 440 ribu klaim pada server sasaran;
- dampak pada waktu kerja verifikator.

## Cara mengulang pengukuran

```bash
cd backend
python -m scripts.load_test --claims 29628 --claims 120000 --claims 240000 --out hasil-uji-beban.json
python -m scripts.evaluate_document_reader          # ketepatan baca PDF sintetis
python -m scripts.evaluate_clinical_reader --set independent   # pembaca catatan (butuh model bahasa)
```
