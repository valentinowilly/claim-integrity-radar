# Perubahan dari proposal dan alasannya

Proposal Claim Integrity Radar ditulis sebelum tim melihat data sampel BPJS dan materi Healthkathon 2026. Setelah
keduanya tersedia (workshop 20–23 Oktober 2026), acuan desain berpindah ke **materi BPJS**: panduan data sampel,
tata kelola AI BPJS, dan arsitektur tahap 1 ML + tahap 2 LLM. Tabel ini mencatat setiap perubahan beserta dasarnya.

## Yang tetap seperti proposal

- Posisi: alat bantu prioritas untuk verifikator dan Tim Anti Kecurangan, bukan pengganti sistem yang ada.
- Tiga jalur tindakan hijau / kuning / merah, alasan dalam bahasa manusia, keputusan akhir di tangan petugas.
- Prioritas faskes mempertimbangkan usaha audit (jumlah rekam medis yang perlu diminta) dan paket bukti yang
  bisa dicetak.
- Uji keadilan antarwilayah dan jenis faskes; uji klaim jujur yang mirip pola curang.
- Privasi: pseudonimisasi, akses per peran, log audit, data contoh untuk demo.

## Yang berubah

| Proposal | Sekarang | Alasan |
|---|---|---|
| Empat pemeriksa: kapasitas, klaim kembar, pola waktu, kelengkapan bukti | Keempatnya berjalan, ditambah pemeriksa dari kolom yang benar-benar ada di data BPJS: layanan berulang, klaim mirip, lama rawat ekstrem, rawat inap ulang cepat, keparahan tidak lazim, keparahan tanpa diagnosis sekunder, tambahan khusus tidak lazim, catatan klinis kembar. Kapasitas, pola waktu, dan kelengkapan bukti membaca **kolom operasional tambahan** (`ID_FASKES`, `KAPASITAS_HARIAN`, `JENIS_LAYANAN`, `JUMLAH_LAYANAN`, `JAM_LAYANAN`, `BUKTI_WAJIB`, `BUKTI_TERCATAT`, `STATUS_BUKTI`) | Data sampel tidak memuat kapasitas faskes, jam layanan, ID faskes, maupun dokumen pendukung (panduan data sampel). Panitia membolehkan data sintetis asal cara pembuatannya dijelaskan, jadi kolom itu diisi sintetis pada berkas contoh dan diberi label jelas; di produksi kolom itu berasal dari data faskes dan rekam medis elektronik. Berkas tanpa kolom itu (termasuk data sampel BPJS) tetap dianalisis; ketiga pemeriksa dilaporkan "tidak berlaku", bukan dipaksakan. |
| Kasus fisioterapi fiktif (contoh proposal: volume 3,4× kapasitas, hanya ±25% berbukti) | Modus "fisioterapi fiktif melebihi kapasitas" di data contoh: sesi jauh di atas kapasitas harian RS, ±25% bercatatan sesi, sebagian dimasukkan pada menit yang sama | Meniru kasus yang diungkap KPK (4.341 klaim, hanya 1.072 berkas lengkap). Pembanding jujur ikut dibuat: unit fisioterapi sibuk yang masih dalam kapasitas, dan sesi latihan kelompok pada menit yang sama. |
| Klaim fiktif obat/alkes (bukti penyerahan) | Dua lapis: "tambahan khusus tidak lazim" (obat, prostesis, prosedur, pemeriksaan khusus FKL33–FKL46 yang jarang dipasangkan dengan INA-CBG-nya; dari kolom BPJS) dan "kelengkapan bukti" untuk obat (resep + catatan penyerahan) dan alkes (permintaan + catatan penyerahan) bila kolom bukti tersedia | Data sampel tidak memuat bukti penyerahan, sehingga lapis kedua hanya berjalan pada berkas berkolom operasional. Obat khusus berulang sengaja tidak dijadikan aturan karena terapi hemofilia dan kelasi besi memang rutin tiap bulan. RS yang belum mencatat inventaris buktinya tidak dianggap tanpa bukti. |
| Data sintetis buatan tim (200 faskes, 120.000 klaim, skema sendiri) | Data contoh **berformat kolom BPJS**, dengan kombinasi kode dari tabel agregat data sampel; AI dilatih pada data sampel BPJS | Sistem harus bekerja pada format data BPJS yang sebenarnya. Kombinasi yang muncul kurang dari 5 kali tidak disimpan. |
| Skor gabungan: aturan berbobot vs *gradient boosting* + SHAP | Tahap 1: Isolation Forest (tanpa label) yang dilatih pada data sampel BPJS, ditambah faktor penjelas per klaim; aturan tetap memberi alasan | Data BPJS tidak memiliki label kecurangan, sehingga model terawasi (*gradient boosting*) tidak dapat dilatih secara jujur. Model tanpa label sesuai materi Basic (*unsupervised learning* untuk *anomaly detection*). |
| Tidak ada LLM | Tahap 2: model bahasa membaca catatan klinis dan menilai kesesuaiannya dengan kode | Materi Said Achmad (use case "Deteksi fraud dan audit klaim JKN": tahap 1 ML, tahap 2 LLM membaca catatan medis). |
| – | Model bahasa **lokal** (Ollama, Qwen3 4B), bukan layanan AI gratis | Tata kelola AI BPJS: "ada data peserta → gunakan AI internal", "akun enterprise resmi, bukan akun gratis", "opt-out pelatihan model". Model lokal tidak mengirim data ke luar server. Penghubung Claude (akun enterprise) tetap tersedia. |
| – | Model mengekstrak fakta dari catatan, aturan yang memutuskan; ada pembacaan cadangan saat model gagal | Uji kami: model 4B yang langsung menilai melewatkan semua kasus curang (0/15); dengan ekstraksi fakta 23/24, tanpa salah tandai pada 8 klaim jujur. Materi Said Achmad: sistem harus tetap jalan saat LLM mati (*fallback*). |
| Klaim kembar dengan MinHash/LSH pada diagnosis, tindakan, dan obat | Klaim mirip (kode) + **catatan klinis kembar** (teks catatan medis) | Materi Said Achmad pilar 01: deteksi *cloning* rekam medis lewat kemiripan teks catatan medis. Kemiripan kode saja tidak membedakan salinan dari layanan rutin. |
| *Upcoding* lewat skor | Tiga lapis: keparahan tidak lazim untuk diagnosisnya, keparahan tanpa diagnosis sekunder, dan pembanding wilayah | Panduan data sampel: keparahan INA-CBG ditentukan komorbid/komplikasi (diagnosis sekunder). Materi Basic: jejak *upcoding* adalah anomali dibanding rata-rata regional. |
| Prioritas = risiko × nilai klaim ÷ usaha | Urutan faskes: tingkat risiko, klaim risiko tinggi, temuan per berkas yang diminta; nilai tagihan ditampilkan, tidak menentukan urutan | Nilai tagihan FKL47 belum terverifikasi dan FKL48 adalah biaya pasca-verifikasi (tidak boleh dipakai sebagai prediktor), sehingga nominal tidak dijadikan dasar urutan. |
| Hasil eksperimen (slide 14, angka *dummy*) | Perbandingan nyata pada data demo-3 berlabel: audit acak 2,9 kecurangan per 100 berkas, aturan sederhana 9,2, Radar 93; klaim sah yang ikut diperiksa 3,6% / 26,9% / 1,0%. Ditambah kartu bukti dari kit penilaian resmi Workshop #3 | Angka diukur, bukan diasumsikan. Tetap data sintetis; kinerja pada data JKN memerlukan label kasus terkonfirmasi dari BPJS. |
| Skenario disimpan khusus untuk pengujian | Jenis kecurangan "penggelembungan prosedur" hanya ada di data uji dan tidak punya aturan khusus. Hasilnya: 0 dari 60 tertangkap | Dicatat apa adanya: sistem kuat pada pola yang dikenal dan lemah pada modus baru. |
| Uji ketahanan terhadap penyamaran (status "Rencana") | Dijalankan: pelaku *upcoding* menyalin diagnosis sekunder dari klaim jujur sejenis; *upcoding* di antrean turun dari 24 menjadi 9 dari 55 | Pemeriksa "keparahan tanpa diagnosis sekunder" mudah dihindari; ini dicatat sebagai kelemahan. Pembacaan catatan klinis (tahap 2) adalah lapis yang dirancang untuk kasus ini. |
| Aturan jalur v3 | Aturan jalur v4: klaim yang hanya "mirip klaim lain" tidak lagi naik ke merah/kuning hanya karena AI menilainya tidak biasa | Ablasi kit penilaian: klaim seperti itu hanya ±2,5% curang, setara pilihan acak. Setelah diubah, ketepatan pada kapasitas 880 klaim naik dari 0,57 ke 0,78, dan RS jujur yang ikut diaudit turun dari 27 menjadi 9 dari 27. Perubahan ini dicek di demo-1 dan demo-2; karena lahir dari data uji tim sendiri, angkanya bukan ukuran yang sepenuhnya independen. |
| Streamlit | React + FastAPI, API-first | Materi BPJS: siap produksi, API-first, modular. |

## Janji proposal yang tidak dipenuhi, dan alasannya

| Janji proposal | Status | Alasan |
|---|---|---|
| *Gradient boosting* + SHAP | Tidak dibuat | Tanpa label kecurangan pada data BPJS, model terawasi hanya akan mempelajari label buatan tim sendiri. Penjelasan diberikan lewat jejak aturan dan faktor penjelas AI per klaim. |
| Prioritas dengan nilai klaim | Diganti | Nilai tagihan (FKL47) ditampilkan, tetapi tidak menentukan urutan. FKL48 (biaya pasca-verifikasi) tidak dipakai sama sekali. |
| 200 faskes, 120.000 klaim, Januari–Desember 2024 | Diganti | Data contoh berisi 40 RS dan 29.628 klaim dalam satu bulan, dengan format kolom BPJS. Skala tidak mengubah cara kerja pemeriksa. Model AI sendiri dilatih pada 126.871 klaim data sampel BPJS. |
| Generator dan pemeriksa dikerjakan terpisah | Tidak terpenuhi | Tim terlalu kecil untuk memisahkan pembuat data uji dan pembuat pemeriksa. Hal ini tertulis di kartu bukti; sebagai gantinya ada satu jenis kecurangan yang disisihkan dan uji plasebo. |
| Validasi pakar klinis | Belum | Pembimbing tim berlatar ilmu komputer; pakar klinis atau verifikator belum dapat dilibatkan dalam waktu lomba. Semua ambang tetap dapat diatur dan diberi label sementara (*provisional*). |
| Validasi pada data riil | Sebagian | AI dilatih dan diperiksa pada data sampel BPJS (hanya angka agregat yang dilaporkan). Tidak ada label kecurangan terkonfirmasi, jadi ketepatan pada data riil belum dapat diukur. |

## Pemetaan ke proses bisnis BPJS (BEA)

- Proses: **C03.04 Pengelolaan Klaim Faskes**, tahap verifikasi (AI-assisted) dan audit.
- Aplikasi yang disentuh: VClaim / VIDI (data klaim FKRTL), SIGAP / AUDIA (tindak lanjut audit), Dashboard EMR (catatan klinis).
- Tata kelola: data contoh untuk demo, pseudonimisasi, AI internal, hasil AI diverifikasi manusia (UU PDP No. 27/2022).
