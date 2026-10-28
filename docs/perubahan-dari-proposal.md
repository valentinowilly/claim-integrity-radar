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
| Empat pemeriksa: kapasitas, klaim kembar, pola waktu, kelengkapan bukti | Pemeriksa dipilih dari kolom yang benar-benar ada di data BPJS: layanan berulang, klaim mirip, lama rawat ekstrem, rawat inap ulang cepat, keparahan tidak lazim, keparahan tanpa diagnosis sekunder, tambahan khusus tidak lazim, catatan klinis kembar | Data sampel tidak memuat kapasitas faskes, jam layanan, ID faskes, maupun dokumen pendukung (panduan data sampel). Pemeriksa yang membutuhkannya tetap ada di kode, tetapi dilaporkan "tidak berlaku", bukan dipaksakan. |
| Klaim fiktif obat/alkes (bukti penyerahan) | "Tambahan khusus tidak lazim": obat, prostesis, prosedur, dan pemeriksaan khusus (FKL33–FKL46) yang jarang dipasangkan dengan INA-CBG-nya | Data tidak memuat bukti penyerahan obat/alat, sehingga "fiktif" tidak bisa dibuktikan. Yang bisa: pasangan kode yang tidak lazim. Obat khusus berulang sengaja tidak dijadikan aturan karena terapi hemofilia dan kelasi besi memang rutin tiap bulan. |
| Data sintetis buatan tim (200 faskes, 120.000 klaim, skema sendiri) | Data contoh **berformat kolom BPJS**, dengan kombinasi kode dari tabel agregat data sampel; AI dilatih pada data sampel BPJS | Sistem harus bekerja pada format data BPJS yang sebenarnya. Kombinasi yang muncul kurang dari 5 kali tidak disimpan. |
| Skor gabungan: aturan berbobot vs *gradient boosting* + SHAP | Tahap 1: Isolation Forest (tanpa label) yang dilatih pada data sampel BPJS, ditambah faktor penjelas per klaim; aturan tetap memberi alasan | Data BPJS tidak memiliki label kecurangan, sehingga model terawasi (*gradient boosting*) tidak dapat dilatih secara jujur. Model tanpa label sesuai materi Basic (*unsupervised learning* untuk *anomaly detection*). |
| Tidak ada LLM | Tahap 2: model bahasa membaca catatan klinis dan menilai kesesuaiannya dengan kode | Materi Said Achmad (use case "Deteksi fraud dan audit klaim JKN": tahap 1 ML, tahap 2 LLM membaca catatan medis). |
| – | Model bahasa **lokal** (Ollama, Qwen3 4B), bukan layanan AI gratis | Tata kelola AI BPJS: "ada data peserta → gunakan AI internal", "akun enterprise resmi, bukan akun gratis", "opt-out pelatihan model". Model lokal tidak mengirim data ke luar server. Penghubung Claude (akun enterprise) tetap tersedia. |
| – | Model mengekstrak fakta dari catatan, aturan yang memutuskan; ada pembacaan cadangan saat model gagal | Uji kami: model 4B yang langsung menilai melewatkan semua kasus curang (0/15); dengan ekstraksi fakta 23/24, tanpa salah tandai pada 8 klaim jujur. Materi Said Achmad: sistem harus tetap jalan saat LLM mati (*fallback*). |
| Klaim kembar dengan MinHash/LSH pada diagnosis, tindakan, dan obat | Klaim mirip (kode) + **catatan klinis kembar** (teks catatan medis) | Materi Said Achmad pilar 01: deteksi *cloning* rekam medis lewat kemiripan teks catatan medis. Kemiripan kode saja tidak membedakan salinan dari layanan rutin. |
| *Upcoding* lewat skor | Tiga lapis: keparahan tidak lazim untuk diagnosisnya, keparahan tanpa diagnosis sekunder, dan pembanding wilayah | Panduan data sampel: keparahan INA-CBG ditentukan komorbid/komplikasi (diagnosis sekunder). Materi Basic: jejak *upcoding* adalah anomali dibanding rata-rata regional. |
| Prioritas = risiko × nilai klaim ÷ usaha | Urutan faskes: tingkat risiko, klaim risiko tinggi, temuan per berkas yang diminta; nilai tagihan ditampilkan, tidak menentukan urutan | Nilai tagihan FKL47 belum terverifikasi dan FKL48 adalah biaya pasca-verifikasi (tidak boleh dipakai sebagai prediktor), sehingga nominal tidak dijadikan dasar urutan. |
| Hasil eksperimen (slide 14, angka *dummy*) | Perbandingan nyata pada data demo berlabel: audit acak 1,6 kecurangan per 100 berkas, aturan sederhana 4,7, Radar 63; klaim sah yang ikut diperiksa 3,3% / 29% / 1,9% | Angka diukur, bukan diasumsikan. Tetap data sintetis; kinerja pada data JKN memerlukan label kasus terkonfirmasi dari BPJS. |
| Streamlit | React + FastAPI, API-first | Materi BPJS: siap produksi, API-first, modular. |

## Pemetaan ke proses bisnis BPJS (BEA)

- Proses: **C03.04 Pengelolaan Klaim Faskes**, tahap verifikasi (AI-assisted) dan audit.
- Aplikasi yang disentuh: VClaim / VIDI (data klaim FKRTL), SIGAP / AUDIA (tindak lanjut audit), Dashboard EMR (catatan klinis).
- Tata kelola: data contoh untuk demo, pseudonimisasi, AI internal, hasil AI diverifikasi manusia (UU PDP No. 27/2022).
