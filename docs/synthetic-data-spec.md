# Spesifikasi Generator Data Sintetis Eksperimen

Dokumen ini menetapkan generator eksperimen terpisah dari adapter `synthetic_demo` runtime. Semua fasilitas, peserta, klaim, kode, tanggal, kapasitas, dan label dibuat artifisial oleh kode. Tidak ada nilai atau distribusi yang diambil dari dataset BPJS. Label hanya menyatakan pola yang sengaja disuntikkan ke simulasi; label tersebut bukan ground truth fraud BPJS.

## Modul dan kontrak pemanggilan

- Generator: `backend/app/data_sources/synthetic_generator.py`.
- Hasil fungsi `generate_synthetic_dataset(config)` memiliki tiga bagian: `facilities`, `records` dan `ground_truth`, ditambah `metadata` konfigurasi.
- Kirim hanya `result.records` ke pemeriksa/detektor. Jangan mengirim `ground_truth` atau menggabungkannya ke record fitur.
- Adapter API runtime `backend/app/data_sources/synthetic.py` tetap merupakan sumber 12 klaim `synthetic_demo`; modul eksperimen ini tidak dipanggil endpoint dan tidak memuat data 120.000 baris secara otomatis.
- Fungsi mengembalikan data baru setiap panggilan. Pemanggil bertanggung jawab menyimpan atau membuangnya; generator tidak menulis file.

## Konfigurasi

`SyntheticGeneratorConfig` mendukung `seed`, `claim_count`, `facility_count`, `target_anomaly_rate`, `start_date`, dan `end_date`. Nilai kecil bawaan ditujukan untuk pemakaian eksplisit saat pengembangan. Konfigurasi proposal tersedia lewat `SyntheticGeneratorConfig.proposal_target(seed=2026)`: 200 fasilitas, 120.000 klaim, periode 2024-01-01 sampai 2024-12-31, dan tingkat anomali sintetis target 4%. Tingkat 4% adalah parameter eksperimen di dalam rentang proposal 3–5%, bukan estimasi prevalensi nyata.

Generator versi 3 menggunakan `random.Random(seed)` dan aturan pembulatan eksplisit `floor(n * rate + 0.5)` (half-up). Konfigurasi harus menyediakan sedikitnya delapan klaim anomali agar semua modus memiliki contoh minimal serta dua klaim kontrol negatif. Alokasi jumlah klaim ekstra dibagi bergiliran menurut urutan skenario; setelah itu, indeks klaim diacak dengan RNG ber-seed sebelum dibagi ke modus. Dengan demikian rentang `claim_id` tidak menunjukkan label. Hasil deterministik untuk versi kode, seed, dan konfigurasi yang sama; output versi 3 sengaja tidak identik dengan versi 2.

## Skema fitur

Semua ID memiliki prefix `syn-` dan dibuat untuk eksperimen ini. `case_id` sama dengan `claim_id` artifisial agar kompatibel dengan bentuk masukan dua detektor yang telah ada.

| Kelompok | Field |
|---|---|
| Identitas sintetis | `claim_id`, `case_id`, `facility_id`, `participant_token` |
| Signature kanonis detektor | `service_date`, `province_code`, `municipality_code`, `facility_ownership`, `facility_type`, `facility_class`, `admission_diagnosis`, `primary_diagnosis`, `claim_group`, `procedure_code`, `billed_amount` |
| Calon pemeriksa kapasitas/waktu | `service_type`, `service_units`, `facility_daily_capacity`, `facility_daily_claim_count` |
| Calon pemeriksa bukti | `supporting_evidence_required`, `supporting_evidence_types`, `supporting_evidence_present` |

Field kapasitas, volume, layanan, dan bukti adalah observasi simulasi untuk rancangan pemeriksa berikutnya, bukan fakta operasional atau aturan klinis tervalidasi. Fasilitas sintetis memiliki atribut lokasi/kategori buatan dan `daily_capacity_units`; itu bukan representasi kolom fasilitas BPJS. `facility_id` hanya ID buatan generator ini dan tidak menyatakan bahwa skema dataset BPJS memiliki ID fasilitas unik. `FKL48` tidak dibuat atau dipakai.

## Ground truth terpisah

`ground_truth.claim_labels` memiliki satu label per klaim: `claim_id`, `case_id`, `is_synthetic_anomaly`, `primary_scenario`, `scenario_group_id`, `intensity_level`. Skenario bukti satu klaim (`phantom_physiotherapy` dan `action_without_support`) tidak diberi `scenario_group_id`, karena tidak ada hubungan antarklaim yang dimaksud. `ground_truth.group_labels` hanya mencatat kejadian dengan relasi kelompok yang disengaja: repeat, cloning, campuran, dan kontrol negatif. Kelompok sah `legitimate_repeat_control` memiliki `is_synthetic_anomaly: false` meskipun dua signature berulang, untuk menyediakan contoh negatif yang dapat memicu kandidat repeat.

Label klaim menyatakan klaim yang termasuk injeksi skenario. Label kelompok menyatakan kejadian berelasi, bukan label fasilitas. Untuk repeat, cloning, dan campuran, setiap kelompok punya ID unik dan 2–3 anggota. Ground truth dikembalikan terpisah, tidak disalin ke record fitur, dan tidak berisi token peserta. Tautan dilakukan hanya menggunakan ID klaim/kasus sintetis. Detektor, skor, dan generator fitur tidak membaca label. Label ini adalah kebenaran yang ditetapkan skenario buatan, bukan putusan auditor, label fraud terverifikasi, atau label acuan BPJS.

## Lima skenario anomali

Anomali target dihitung pada klaim unik, bukan jumlah kelompok. Ukuran dasar lima skenario adalah `[1, 2, 2, 1, 2]` dalam urutan tabel. Bila target lebih besar dari delapan, sisa klaim dialokasikan satu per satu secara bergilir menurut urutan berikut. Indeks dipilih dengan permutasi deterministik atas seluruh klaim, bukan rentang berurutan berdasarkan ID. Skenario per klaim tidak memerlukan kelompok besar; repeat, cloning, dan campuran dipecah menjadi banyak kejadian kecil berukuran 2–3. Algoritme pembagian menghindari kelompok tunggal.

| Skenario | Pola fitur yang dibuat | Cakupan label |
|---|---|---|
| `phantom_physiotherapy` | Klaim sintetis fisioterapi individual dengan inventaris bukti tercatat tetapi tanpa `therapy_session_log`. | Label per klaim saja; tidak ada relasi kelompok yang diklaim. Ini adalah pola kekurangan bukti dalam simulasi, bukan pernyataan layanan nyata fiktif. |
| `cloning` | Banyak templat kecil berisi 2–3 peserta sintetis berbeda. Setiap kejadian berbagi atribut inti, tetapi anggota selain templat memiliki variasi terkontrol pada prosedur atau biaya (selisih biaya 0,50). | Label per klaim dan per kejadian. Setiap kejadian memakai satu fasilitas sintetis yang dipilih dari basis fasilitas; kejadian berbeda tersebar acak ke fasilitas. Fasilitas bukan label anomali. |
| `repeat_billing` | Banyak kelompok kecil berisi 2–3 klaim dengan signature repeat lengkap yang sama, termasuk token peserta sintetis, tanggal, dan atribut signature. ID klaim tetap unik. | Semua anggota mendapat label anomali klaim dan satu label kelompok kejadian. Peserta, tanggal, dan layanan konsisten dalam kelompok; kelompok dipilih dan ditempatkan secara acak. |
| `action_without_support` | Klaim sintetis individual dengan aturan skenario order dan catatan klinis, tetapi inventaris tercatat kosong. | Label per klaim saja; persyaratan bukti bukan pedoman klinis BPJS. |
| `mixed_light_severe` | Kelompok kecil 2–3 klaim berbagi fasilitas, tanggal, menit, dan pola layanan. Setiap klaim melampaui kapasitas simulasi fasilitas per hari; anggota `severe` juga tidak mencatat bukti yang disyaratkan, sedangkan `light` mencatatnya. | Label per klaim dan per kelompok kejadian. Intensitas hanya metadata skenario, tidak diberikan ke pemeriksa dan bukan skor. Pengelompokan fasilitas/waktu disengaja agar sinyal kapasitas dan, untuk kelompok 3 klaim, pola waktu dapat diuji. |

Kontrol negatif `legitimate_repeat_control` memilih dua klaim non-anomali secara acak dan memberi keduanya signature repeat yang sama. Label klaim tetap `is_synthetic_anomaly: false`, sementara satu label kelompok menyatakan pola ini sah menurut stipulasi simulasi. Kontrol ini sengaja dapat ditemukan indikator repeat dan memperlihatkan potensi false positive. Semua klaim lain tanpa injeksi juga berlabel negatif di tingkat klaim.

Fasilitas untuk klaim dasar dipilih acak dari 200 fasilitas sintetis; tanggal dipilih seragam secara artifisial pada rentang konfigurasi. Dengan demikian ID klaim tidak menentukan fasilitas atau tanggal. Kelompok repeat/cloning/campuran mempertahankan konsistensi fasilitas dan waktu yang dibutuhkan oleh modusnya. Kelompok cloning dan repeat memakai fasilitas dari templat awal tiap kejadian; kelompok campuran sengaja berkonsentrasi dalam fasilitas/tanggal/minute per kejadian. Pengelompokan ini adalah konstruksi pengujian terarah, bukan distribusi layanan yang diamati.

## Batasan dan penggunaan

Seed membuat hasil dapat diulang pada versi generator yang sama, tetapi komposisi kode, frekuensi, kapasitas, jenis layanan, pola tanggal, dan tingkat injeksi tidak berasal dari populasi nyata. Lima skenario adalah pola perangkat lunak yang dipaksakan, bukan definisi pelanggaran, bukti pembayaran, standar klinis, atau data audit. Sistem yang bekerja pada benchmark ini belum terbukti akurat pada data operasional dan tidak boleh menggeneralisasi temuan ke BPJS atau fasilitas nyata.

Generator tidak menghitung precision, recall, F1, akurasi, skor prioritas, ataupun metrik evaluasi lain. Perbandingan hasil detektor dengan label adalah pekerjaan tahap evaluasi mendatang setelah protokol dan unit evaluasi disepakati. Detektor yang ada tetap menggunakan signature saat ini; field baru tidak mengubah kedua detektor.

## Tes dan benchmark

Dari folder `backend`, tes rutin dapat dijalankan dengan `.venv\\Scripts\\python -m pytest`. Tes generator memakai 250 klaim sintetis agar cepat. Pemeriksaan konfigurasi skala proposal dijalankan terpisah dengan:

```powershell
cd backend
.venv\Scripts\python -m app.data_sources.synthetic_benchmark
```

Perintah benchmark membuat data target di memori, mencetak ringkasan hitungan dan waktu, serta mengukur alokasi Python melalui `tracemalloc`; ia tidak menulis dataset, tidak mencetak record individual, dan tidak memanggil endpoint runtime. Penggunaan RSS proses dapat berbeda dari pengukuran `tracemalloc`.

## Tambahan skema untuk pemeriksa Tahap 12

Generator menambahkan dua field fitur secara aditif:

- `service_timestamp`: waktu layanan sintetis ISO lokal tanpa zona waktu, pada jam/menit deterministik; `service_date` tetap tersedia dan tidak berubah makna.
- `supporting_evidence_recording_status`: `recorded` bila inventaris sintetis dianggap diperiksa. Nilai `not_recorded` dapat dipakai fixture untuk menunjukkan bahwa bukti belum diinventarisasi. Daftar kosong dengan status `recorded` berarti tidak ada jenis bukti yang tercatat pada inventaris buatan; daftar kosong dengan `not_recorded` tidak boleh ditafsirkan sebagai bukti tidak ada.

Metadata fasilitas memakai `daily_capacity_units` sebagai jumlah unit layanan simulasi per fasilitas per hari. Record memiliki `service_units`; `facility_daily_capacity` merupakan salinan fitur untuk inspeksi lokal. Belum ada jumlah terapis/tenaga atau kapasitas per jenis layanan, sehingga kapasitas tidak dapat ditafsirkan sebagai sesi per terapis.

Field timestamp dan bukti tersebut tetap bagian dari record fitur dan tidak mengandung ground truth. Kedua detektor signature lama tidak berubah. Pemeriksa Tahap 12 memerlukan hanya `result.records` dan, untuk kapasitas, `result.facilities`; `result.ground_truth` tidak diberikan ke fungsi detektor.

Penambahan Tahap 12 menaikkan `metadata.generator_version` menjadi `2`. Audit Tahap 14 mengubah generator menjadi versi `3`: alokasi indeks yang semula berurutan dan satu kelompok besar per skenario berkelompok kini memakai indeks acak ber-seed dan kejadian 2–3 klaim. Pemilihan fasilitas dasar juga acak, dan kontrol negatif dipilih dari klaim non-anomali secara acak. Hasil versi 3 deterministik untuk seed dan konfigurasi sama, tetapi tidak dijamin identik dengan versi 2. Karena fitur dan label berubah, benchmark versi 2 tidak dapat dianggap setara dengan benchmark versi 3.

Pemeriksaan generator target tanpa detektor dijalankan dengan `.venv\\Scripts\\python -m app.data_sources.synthetic_benchmark`. Perintah ini hanya membuat data dan menghitung agregat label, ukuran kelompok, distribusi jumlah klaim per fasilitas, periode, waktu, dan alokasi memori; tidak menjalankan detektor, skor, atau metrik evaluasi dan tidak menyimpan data. Benchmark enam pemeriksa, skor, dan prioritas terpisah pada tahap sebelumnya bukan bagian dari validasi generator ini. Keberhasilan pembuatan 120.000 klaim tidak membuktikan kinerja analitik atau kesesuaian simulasi dengan populasi nyata.

### Hasil audit distribusi generator v3

Benchmark seed `2026` berhasil membuat 120.000 klaim dan 200 fasilitas; 4.800 klaim diberi label anomali sintetis sesuai aturan half-up. Jumlah klaim per skenario: fisioterapi tanpa bukti 960, cloning 961, repeat 960, tindakan tanpa penunjang 959, dan campuran 960. Ini alokasi konfigurasi eksperimen, bukan prevalensi nyata.

Ada 384 kejadian cloning (191 berisi 2 klaim, 193 berisi 3), 383 kejadian repeat (189 berisi 2, 194 berisi 3), dan 386 kejadian campuran (198 berisi 2, 188 berisi 3). Skenario fisioterapi dan tindakan tanpa penunjang adalah label individual sehingga masing-masing memiliki 0 kelompok. Kontrol repeat sah memiliki satu grup beranggotakan 2 klaim.

Distribusi jumlah klaim per fasilitas: minimum 517, median 599, persentil ke-95 645, maksimum 665 dari 200 fasilitas. Rentang tanggal aktual adalah 2024-01-01 sampai 2024-12-31. Generator memerlukan 15,561 detik; `tracemalloc` mengukur puncak alokasi Python 281,58 MiB dan alokasi tersisa 267,67 MiB saat ringkasan dibuat. Nilai ini bukan RSS total proses. Hasil hanya mencerminkan biaya pembuatan generator pada lingkungan pengujian, bukan biaya menjalankan detektor.
