# Spesifikasi Analitik Awal

Dokumen ini membedakan ide indikator dari implementasi yang sudah terbukti. Skrip eksplorasi yang ada menjadi bahan rancangan; keberadaan skrip **tidak** berarti analitik produksi telah tervalidasi. Semua indikator menghasilkan kandidat untuk tinjauan manusia, bukan kesimpulan fraud.

## Prinsip umum

- Analisis dilakukan lokal sesuai ketentuan penggunaan data. Pengembangan dan demo memakai data sintetis secara default.
- Minimalkan field yang disimpan atau dikembalikan. Identifier peserta dapat dipakai sementara untuk menghitung peserta berbeda hanya bila diperlukan dan diizinkan; jangan kembalikan atau mencatat identifier maupun hash-nya.
- Simpan versi definisi indikator, rentang observasi, jumlah record layak, dan keterbatasan bersama hasil.
- Jangan gunakan `FKL48` (biaya pascaverifikasi) sebagai prediktor risiko sebelum verifikasi.
- Skema yang diaudit belum membuktikan adanya ID fasilitas unik. Tidak ada peringkat fasilitas atau klaim “fasilitas yang sama” tanpa bukti skema dan validasi terpisah.

## Indikator rancangan: kandidat repeat billing

**Tujuan.** Menemukan kelompok klaim/kunjungan yang memiliki signature atribut teramati berulang, untuk membantu auditor memeriksa kemungkinan pengulangan pola penagihan. Istilah “repeat billing” adalah nama indikator; pengulangan signature saja tidak membuktikan penagihan ganda.

**Mekanisme awal.** Normalisasi tanggal, spasi, nilai kosong, dan representasi tipe secara konsisten; bentuk signature dari atribut yang ditetapkan; hitung frekuensi signature; kelompok berulang menjadi kandidat. Jangan menandai dua baris sebagai duplikat hanya dari hash: periksa aturan bisnis, perbedaan kunjungan, dan kelengkapan field. Signature dan identifier sumber tidak ditampilkan.

**Kolom rancangan.** `FKL03` (tanggal), `FKL05_NEW`, `FKL06`, `FKL07`, `FKL08`, `FKL09`, `FKL16`, `FKL18`, `FKL19`, `FKL30`, `FKL47`, serta `FKL02` untuk membedakan kunjungan pada pendekatan skrip yang ada. `PSTV01` mungkin diperlukan untuk validasi peserta berbeda pada varian tertentu. Daftar final, definisi “billing berulang”, kunci kunjungan, dan peran `FKL02` harus disetujui sebelum implementasi produksi. `FKL48` dikecualikan dari prediktor.

**Alasan yang ditampilkan kepada auditor.** “Signature atribut klaim yang dipakai indikator teramati sebanyak N kali dalam periode terpilih”; sertakan atribut kategoris yang aman dan relevan, frekuensi, periode, serta field yang tidak tersedia. N hanya ditampilkan setelah benar-benar dihitung. Hindari menampilkan identifier, fingerprint, atau nilai sensitif.

**Batasan/false positive.** Prosedur atau episode yang sah dapat berulang; kode atau tanggal yang dibulatkan dapat menggabungkan layanan berbeda; signature yang terlalu ketat melewatkan variasi, sedangkan normalisasi terlalu longgar menyatukan klaim berbeda. Data hilang dan nilai kode yang berubah memengaruhi frekuensi. Kandidat memerlukan pemeriksaan dokumen serta konteks layanan.

## Indikator rancangan: pola klaim serupa (cloning candidate)

**Tujuan.** Mencari pola atribut layanan yang sangat mirip pada klaim terkait peserta berbeda sebagai sinyal untuk pemeriksaan lebih lanjut. Nama teknis “cloning” tidak boleh ditampilkan seolah diagnosis pelanggaran.

**Mekanisme awal.** Normalisasi field, lalu kelompokkan signature exact-match yang memenuhi kelengkapan minimum. Hitung kemunculan dan, bila aturan akses mengizinkan, banyaknya peserta sumber berbeda secara internal. Varian lengkap dapat memasukkan kode prosedur; varian parsial tanpa kode prosedur harus dipisahkan dan diberi label keyakinan/keterbatasan berbeda. Exact-match adalah heuristik; matching fuzzy belum ditetapkan.

**Kolom rancangan.** Atribut pola: `FKL03`, `FKL05_NEW`, `FKL06`, `FKL07`, `FKL08`, `FKL09`, `FKL16`, `FKL18`, `FKL19`, `FKL47`, dan `FKL30` untuk signature lengkap. `PSTV01` dibutuhkan hanya untuk menghitung peserta berbeda secara internal, bukan menjadi bagian signature layanan atau keluaran. Tidak ada kolom yang saat ini memastikan ID fasilitas unik; `FKL05_NEW`/`FKL06` tidak boleh dianggap identitas fasilitas. `FKL48` dikecualikan sebagai prediktor.

**Alasan yang ditampilkan kepada auditor.** “Pola atribut layanan yang sama terdeteksi pada N klaim dan M peserta berbeda menurut field pembanding yang tersedia”; cantumkan apakah prosedur tersedia, field yang dibandingkan, cakupan, dan pesan bahwa fasilitas yang sama tidak dapat dipastikan dari skema yang diketahui. Tampilkan hanya agregat atau detail yang diperlukan dan berwenang.

**Batasan/false positive.** Layanan standar, protokol klinis serupa, variasi pencatatan rendah, atau kode lokasi administratif yang sama dapat menghasilkan pola identik. Pola dapat terjadi di fasilitas berbeda; skema saat ini tidak membuktikan fasilitas yang sama. Data tidak lengkap mengubah kelayakan; exact-match terlalu ketat dapat melewatkan pola variasi. Indikator tidak membuktikan layanan fiktif atau kolusi.

## Indikator lain: rencana, belum menjadi fitur terverifikasi

| Indikator rencana | Tujuan yang mungkin | Data minimum yang perlu divalidasi | Status |
|---|---|---|---|
| Anomali nilai biaya tagih | Menandai nilai atau distribusi `FKL47` yang menyimpang untuk ditinjau | `FKL47`, konteks klaim/layanan dan periode; metode pembanding harus ditentukan | Rencana; tidak ada ambang atau hasil produksi yang ditetapkan |
| Kelengkapan/kualitas data | Menyoroti kolom wajib yang hilang atau tidak konsisten | Skema dan field wajib yang disepakati | Rencana; bukan skor fraud |
| Ketidakwajaran kombinasi kode | Mengidentifikasi kombinasi diagnosis, prosedur, dan kelompok klaim yang perlu validasi aturan | `FKL16`, `FKL18`, `FKL19`, `FKL30` serta referensi aturan klinis resmi dan versi | Rencana; perlu validasi ahli dan aturan otoritatif |
| Perubahan pola waktu | Menandai perubahan agregat lintas periode | Tanggal klaim dan agregat indikator/biaya yang sah | Rencana; perlu periode dasar dan penanganan perubahan volume |

Tidak satu pun indikator rencana tersebut boleh muncul sebagai fitur aktif atau dipakai untuk mengarang metrik dashboard/evaluasi sebelum diimplementasikan dan diuji.

## Definisi operasional awal untuk mesin aturan (Tahap 4)

Implementasi awal berada di `backend/app/analytics/` dan menerima record terkontrol dalam bentuk mapping Python. Nama field di bawah adalah **skema kanonis internal**, bukan klaim bahwa pemetaan kolom sumber BPJS sudah disahkan. Pemetaan ke kode lama diturunkan dari komentar dan daftar field pada skrip yang diaudit, lalu perlu divalidasi terhadap metadata resmi dan pemilik proses sebelum penggunaan data nyata.

`case_id` adalah ID kasus internal/opaque yang harus unik pada satu input; modul mengharuskan prefix `case_` untuk ID aplikasi atau `syn-` untuk ID fixture. ID tidak boleh sama dengan token peserta. Fixture memakai ID `syn-` artifisial, bukan identifier dataset. Token peserta hanya digunakan untuk pencocokan internal dan tidak pernah dikembalikan. Hasil mengembalikan nama atribut, ID kasus aplikasi, jumlah, alasan, dan keterbatasan—tanpa nilai signature, token, atau fingerprint.

### Normalisasi bersama

- Teks di-trim pada kedua ujung dan **case-sensitive**. Normalisasi tidak mengubah huruf besar/kecil karena aturan kesetaraan kode sumber belum dikonfirmasi.
- `None`, teks kosong/whitespace, serta sentinel teks `NA`, `N/A`, `NaN`, `NaT`, `null`, `none`, dan `<NA>` dianggap kosong. String sentinel tersebut diakui tanpa membedakan kapitalisasi.
- Tanggal harus berupa tanggal ISO (`YYYY-MM-DD`) atau datetime ISO yang dapat diparse; datetime dinormalisasi ke tanggal kalender ISO. Nilai tanggal yang tidak valid dianggap tidak tersedia.
- Biaya dikonversi melalui `Decimal` agar pencocokan tidak bergantung pada pembulatan float. Hanya angka finite dan non-negatif yang diterima; nilai kosong, negatif, boolean, atau gagal parse dianggap tidak valid.
- Nilai kosong tidak diisi dengan token bersama seperti `"<MISSING>"`; record yang tidak memenuhi field wajib dikeluarkan dari signature. Pengecualian: kode prosedur kosong hanya boleh masuk mode pola parsial pada indikator pola serupa.
- Tidak ada validasi kamus kode klinis atau kode fasilitas dalam modul ini. String non-kosong dianggap nilai kode untuk keperluan exact-match, bukan berarti kode tersebut sah secara klinis.

### A. Kandidat repeat billing

**Tujuan operasional.** Mengelompokkan sedikitnya dua record yang mempunyai signature lengkap sama, termasuk token peserta yang sama, sebagai pola kunjungan/tagihan berulang yang dapat ditinjau. Kecocokan tidak menyimpulkan tagihan ganda, layanan fiktif, atau fraud.

**Signature exact-match dan pemetaan kerja:**

| Field kanonis | Pemetaan kerja dari skrip lama | Peran |
|---|---|---|
| `participant_token` | `PSTV01` | Memastikan peserta sama; dibandingkan internal, tidak dikeluarkan |
| `service_date` | `FKL03` | Tanggal kunjungan |
| `province_code` | `FKL05_NEW` | Atribut administratif |
| `municipality_code` | `FKL06` | Atribut administratif |
| `facility_ownership` | `FKL07` | Kategori kepemilikan, bukan ID unik fasilitas |
| `facility_type` | `FKL08` | Kategori fasilitas |
| `facility_class` | `FKL09` | Kategori fasilitas |
| `admission_diagnosis` | `FKL16` | Diagnosis masuk |
| `primary_diagnosis` | `FKL18` | Diagnosis primer |
| `claim_group` | `FKL19` | Kelompok klaim |
| `procedure_code` | `FKL30` | Kode prosedur |
| `billed_amount` | `FKL47` | Biaya tagih pra-verifikasi yang dipertimbangkan |

Pemetaan di tabel adalah asumsi kerja dari kode dan komentar skrip, bukan validasi label atau makna kolom sumber. `FKL02` tidak dimasukkan ke signature karena skrip repeat lama memakai field itu terpisah sebagai pembeda kunjungan; definisi final perlu memastikan semantik dan aturan identifikasi kunjungan. `FKL48` tidak dibaca atau digunakan.

**Syarat kandidat.** Semua 12 field signature harus valid setelah normalisasi dan sekurangnya dua record harus sama persis pada seluruh nilai signature. Satu record tak lengkap tidak dipasangkan melalui nilai pengganti. Hasil mengandung `candidate_record_count`, ID kasus yang terlibat, `matched_attributes`, dan alasan bahwa signature cocok tanpa mengungkap nilai signature.

**Alasan untuk auditor.** Bentuk alasan: “2 record memiliki nilai exact-match pada seluruh atribut signature repeat billing; nilai signature tidak ditampilkan. Pola ini memerlukan peninjauan auditor dan bukan bukti fraud.” Jumlah pada aplikasi berasal dari hasil fungsi, bukan angka tetap.

**Contoh ilustratif—seluruhnya data sintetis buatan fixture.** `syn-repeat-001` dan `syn-repeat-002` memakai token sintetis yang sama dan signature lengkap yang sama. Detektor mengelompokkannya dengan hitungan 2. Contoh terpisah `syn-routine-001` dan `syn-routine-002` juga identik tetapi sengaja mewakili pengulangan layanan terencana yang mungkin sah; keduanya tetap hanya kandidat yang memerlukan konteks auditor.

### B. Kandidat pola klaim serupa

**Tujuan operasional.** Menandai exact-match atribut pola layanan yang ditemukan pada sedikitnya dua peserta berbeda. `participant_token` dipakai hanya untuk menghitung banyak peserta unik dan tidak menjadi bagian signature. Hasil adalah pola serupa, bukan “cloning” yang terbukti.

**Signature dasar (complete dan partial):** `service_date` (`FKL03`), `province_code` (`FKL05_NEW`), `municipality_code` (`FKL06`), `facility_ownership` (`FKL07`), `facility_type` (`FKL08`), `facility_class` (`FKL09`), `admission_diagnosis` (`FKL16`), `primary_diagnosis` (`FKL18`), `claim_group` (`FKL19`), dan `billed_amount` (`FKL47`). Signature **complete** menambahkan `procedure_code` (`FKL30`).

Pemetaan ini mengikuti kolom signature base/full pada skrip cloning lama. Semua field dasar dan token peserta harus tersedia. Jika prosedur valid tersedia, record hanya dibandingkan dengan signature complete. Jika prosedur kosong/tidak tersedia, record dibandingkan terpisah sebagai signature `procedure_missing`; record complete tidak digabung dengan grup partial. Field administratif dan tipe fasilitas bukan ID unik, sehingga kecocokan tidak menyatakan fasilitas yang sama.

**Syarat kandidat.** Satu grup harus memuat setidaknya dua record dan setidaknya dua token peserta berbeda. Grup complete menuntut signature complete sama; grup partial hanya menuntut signature dasar sama dan menandai mode parsial. Keluaran mencantumkan jumlah record, jumlah peserta berbeda, mode, atribut pembanding, ID kasus, alasan, dan keterbatasan. Token peserta dan nilai signature tidak dikembalikan.

**Alasan untuk auditor.** Bentuk alasan: “3 record dari 3 peserta berbeda memiliki signature lengkap yang cocok exact-match; nilai signature dan token peserta tidak ditampilkan. Kecocokan ini hanya sinyal untuk ditinjau, bukan bukti cloning atau fraud.” Untuk mode partial, alasan menyebut prosedur tidak tersedia dan keterbatasan false positive yang lebih besar.

**Contoh ilustratif—seluruhnya data sintetis buatan fixture.** `syn-pattern-001`, `syn-pattern-002`, dan `syn-pattern-003` dibangun dengan atribut pola sama dan token peserta sintetis berbeda. Ketiganya menghasilkan satu kandidat complete, hitungan 3 record dan 3 peserta. Dua record sintetis yang hanya berbeda pada `procedure_code` tidak disatukan ke signature complete yang sama.

### Batas interpretasi implementasi

Modul tidak menghitung probabilitas, tidak memberi skor fraud, tidak menyebut bukti fraud, tidak mengakses database/API, dan tidak memakai `FKL48`. Protokol klinis lazim, layanan berulang yang sah, field administratif serupa, atau variasi pencatatan dapat menimbulkan false positive. Exact-match ketat juga dapat melewatkan pola yang berbeda hanya karena format kode/tanggal. Signature partial lebih rentan false positive karena kode prosedur tidak tersedia. Tanpa identifier fasilitas unik yang tervalidasi, tidak ada kesimpulan lintas record bahwa fasilitasnya sama.

Fixture `backend/tests/fixtures/synthetic_claims.py` sepenuhnya artifisial dan hanya untuk tes. Record, ID, kode, tanggal, token, dan jumlah di contoh fixture bukan sampel, statistik, ataupun temuan dataset BPJS. Definisi serta pemetaan di atas masih perlu persetujuan pemilik data/ahli domain sebelum pemrosesan sumber nyata.

## Keluaran analitik dan tata kelola

Setiap hasil kandidat sebaiknya menyimpan kode dan versi indikator, waktu proses, cakupan/periode, jumlah record yang diperiksa dan memenuhi syarat, alasan ringkas, serta batasan. Keluaran kasus menggunakan ID internal acak aplikasi. Catatan auditor/keputusan disimpan terpisah dari hasil deteksi. Akses, retensi, dan audit log untuk data nyata harus ditetapkan sebelum integrasi dataset.

## Status proses tinjauan auditor (Tahap 8)

Status tindak lanjut adalah `pending_review`, `needs_more_evidence`, `not_substantiated`, atau `escalated`. Kasus tanpa event tinjauan berstatus awal `pending_review`. Status dapat berubah ke status diizinkan mana pun; setiap POST yang diterima menambahkan event berisi waktu, status sebelumnya, status baru, catatan opsional, dan label reviewer demo. Status yang sama dapat dikirim lagi untuk mencatat pembaruan catatan. Status ini hanya alur kerja, bukan label fraud atau keputusan yang diverifikasi independen. Metadata disimpan terpisah dalam SQLite lokal dan tidak memuat baris analitik, token peserta, atau signature. Autentikasi, retensi, kontrol akses, serta penggunaan catatan untuk data nyata belum ditetapkan.

## Pemeriksa tambahan eksperimen (Tahap 12)

Pemeriksa berikut berada di `backend/app/analytics/`, menerima record fitur sintetis terkontrol, tidak membaca ground truth, dan belum dihubungkan ke API. Hasilnya adalah kandidat untuk ditinjau manusia. Semuanya diuji dengan fixture/generator sintetis; tidak ada validasi pada klaim nyata.

### Kewajaran kapasitas sintetis

- **Input:** `records[].case_id`, `facility_id`, `service_type`, `service_date`, `service_units`; `facilities[].facility_id` dan `daily_capacity_units`.
- **Unit dan aturan:** jumlahkan `service_units` per fasilitas sintetis, jenis layanan, dan hari. Kandidat jika jumlahnya `> daily_capacity_units × max_utilization`; default `max_utilization=1.0`, jendela harian (`window_days=1`). ID fasilitas harus unik dan kapasitas harus angka finite positif. Metadata hilang/duplikat/tidak valid membuat record terkait tidak layak dan tidak menghasilkan kandidat kapasitas.
- **Keluaran:** ID kandidat deterministik dalam hasil dataset, ID fasilitas sintetis, ID kasus terbatas, hitungan kasus, tanggal, jenis layanan, unit teramati, kapasitas pembanding, rasio utilisasi, alasan, dan batasan. ID kasus dibatasi 20 per kandidat secara default.
- **Cakupan uji:** kelompok campuran generator dengan unit layanan sintetis di atas kapasitas fasilitas. Bukan pemeriksa phantom billing.
- **False positive/gap:** kapasitas fasilitas adalah asumsi simulasi. Metadata tidak memberi kapasitas spesifik per layanan ataupun jumlah tenaga/terapis. Nilai kapasitas fasilitas dipakai sebagai batas atas pembanding untuk setiap jenis layanan secara terpisah; pendekatan ini dapat melewatkan akumulasi lintas jenis layanan. Kapasitas universal dan implikasi klinis perlu validasi ahli.

### Pola klaim serupa: exact dan near duplicate

Detektor exact-match `similar_claim_pattern.py` dipertahankan tanpa perubahan: signature complete/partial, normalisasi, dan syarat peserta berbeda tetap seperti definisi di atas. Pelengkap baru `near_duplicate_claims.py` memakai field pola kanonis—tanggal, atribut administratif/fasilitas kategori, diagnosis masuk/primer, kelompok klaim, prosedur, dan biaya—tanpa token peserta dalam signature. Token hanya dipakai internal untuk mensyaratkan peserta berbeda. Ground truth dan label skenario tidak dibaca.

MinHash/LSH **tidak diimplementasikan** pada tahap ini. Metode yang benar-benar digunakan adalah blocking deterministik pada tiga kombinasi: `(service_date, municipality_code, primary_diagnosis)`, `(service_date, municipality_code, claim_group)`, dan `(service_date, province_code, admission_diagnosis)`. Pasangan blok kecil dibandingkan lengkap; blok di atas 100 record dibandingkan melalui tetangga berurutan untuk menghindari kombinasi kuadratik. Batas default: 5.000 perbandingan pasangan dan 500 kandidat. Output mengurutkan ID kasus, menyebut atribut cocok/berbeda, dan tidak memuat nilai signature. `search_truncated` mengungkap bahwa batas pencarian tercapai.

Default pasangan harus memiliki sedikitnya 9 atribut yang dapat dibandingkan, rasio cocok sekurangnya 0,8, dan toleransi absolut biaya `1.00` (unit biaya sintetis yang belum dikalibrasi). Satu pasangan dihasilkan hanya bila token peserta berbeda. Blok menuntut beberapa atribut tetap cocok; variasi pada semua atribut pemblokir dapat luput. Protokol umum dapat menghasilkan banyak pasangan sah. Similarity ratio menjelaskan atribut yang cocok dan bukan probabilitas fraud atau skor risiko.

### Pola waktu dan pengulangan

`temporal_patterns.py` menerima `case_id`, token peserta (internal), `facility_id` sintetis, `service_type`, `service_date`, dan `service_timestamp`. Generator eksperimen kini menyediakan timestamp sintetis lokal tanpa zona waktu. Dua sinyal terpisah diuji:

1. `short_window_repeat`: sedikitnya 2 klaim dengan peserta, fasilitas sintetis, dan jenis layanan sama; jendela default 3 hari. Jendela di-anchor pada tanggal paling awal dan diproses tanpa tumpang tindih.
2. `uniform_service_minute`: sedikitnya 3 klaim dan 3 peserta berbeda pada fasilitas/jenis layanan/tanggal/menit yang sama.

Tanggal sibuk saja bukan sinyal. Output menunjukkan tipe pola, jumlah, tanggal, menit (bila relevan), dan ID kasus terbatas. Pengulangan layanan terjadwal, episode perawatan, slot klinik seragam, atau pencatatan sistem dapat menjadi false positive. Timestamp simulasi tidak membuktikan waktu layanan aktual. Perubahan pola waktu lintas baseline/periode masih rencana terpisah.

### Kelengkapan bukti pendukung

`evidence_completeness.py` memakai `service_type`, `supporting_evidence_required`, `supporting_evidence_types`, `supporting_evidence_present`, dan `supporting_evidence_recording_status`. Aturan sintetis default: fisioterapi memerlukan `therapy_session_log` dan `clinical_note`; `synthetic_supported_action` serta `synthetic_mixed_action` memerlukan `procedure_order` dan `clinical_note`. Kandidat hanya dibuat saat status inventaris `recorded`, daftar bukti tersedia dan konsisten, serta ada bukti yang diwajibkan tetapi tidak tercantum. `not_recorded` menjadi unassessed; daftar/status tidak valid menjadi ineligible. Output menampilkan jenis bukti yang kurang, aturan layanan, alasan, dan batasan. Ketiadaan entri bukan bukti layanan tidak diberikan.

Aturan tersebut menguji kelengkapan daftar dalam skenario perangkat lunak, bukan kecukupan klinis/administratif. Field/aturan harus disahkan ahli sebelum diterapkan pada data nyata.

### Status pengujian dan batas penggunaan

Empat pemeriksa dan detektor lama diuji dengan unit test sintetis, termasuk kondisi normal, pola skenario, input tidak lengkap, input tidak berubah, pembatasan near-match, determinisme, dan kasus yang dapat menjadi false positive. Benchmark terpisah mengukur waktu dan alokasi Python pada ukuran sintetis yang ditentukan; keberhasilan benchmark tidak membuktikan performa pada data produksi. Belum ada MinHash/LSH, metrik evaluasi, integrasi API, maupun validasi ahli domain.

## Skor risiko gabungan dan prioritas audit (Tahap 13)

Modul `risk_scoring.py` menerima enam keluaran detektor beserta record fitur, dan `audit_priority.py` membentuk antrean terpisah. `run_detector_suite(records, facilities)` menjalankan keenam detektor pada record fitur saja; ia tidak menerima ground truth. API runtime belum memanggil modul ini.

### Bobot dan rumus skor

Versi default adalah `rule-risk-index-v1-provisional`. Bobot awal yang dapat dikonfigurasi adalah sama besar untuk setiap indikator:

| Indikator | Bobot awal |
|---|---:|
| `repeat_billing_candidate` | 1 |
| `similar_claim_pattern_candidate` | 1 |
| `near_duplicate_claim_candidate` | 1 |
| `synthetic_capacity_candidate` | 1 |
| `temporal_pattern_candidate` | 1 |
| `supporting_evidence_completeness_candidate` | 1 |

Untuk klaim `c`, tetapkan `T(c)` sebagai himpunan indikator berbeda yang terpicu dan `A(c)` sebagai himpunan indikator yang benar-benar dapat dinilai. Skor:

`risk_score(c) = (Σ_{i ∈ T(c)} bobot(i)) / (Σ_{i ∈ A(c)} bobot(i))`

Skor berada pada rentang 0–1 dan dibulatkan enam angka desimal pada keluaran. Tiap indikator memberi kontribusi paling banyak satu kali per klaim, walaupun klaim muncul pada banyak pasangan near-duplicate atau kelompok. Indikator yang tidak berjalan, tidak memenuhi syarat data, atau tidak dapat dipastikan karena pencarian terpotong tidak dimasukkan sebagai negatif ke penyebut. Jika `A(c)` kosong, skor `null` dan status `not_assessable`; bukan nol. Skor 0 hanya berarti pemeriksaan yang dapat dinilai tidak menemukan sinyal, bukan bukti risiko nihil. Skor dengan indikator yang tidak tersedia diberi status cakupan parsial.

Jika `near_duplicate_claim_candidate` mengembalikan `search_truncated`, kandidat yang benar-benar ditemukan tetap menjadi sinyal yang dapat ditelusuri. Untuk klaim yang tidak ditemukan, indikator itu berstatus tidak dinilai, bukan tidak terpicu. Metadata cakupan dan keterbatasan pencarian diteruskan ke unit audit.

Bobot sama adalah pilihan baseline transparan agar tidak menyatakan satu indikator lebih penting tanpa bukti. Bobot ini belum dilatih, dikalibrasi, atau disahkan ahli domain; skornya bukan probabilitas fraud atau kinerja tervalidasi. Alasan menyimpan kode indikator, ID kandidat, alasan detektor, field atribut yang cocok/berbeda atau nilai agregat yang aman. Token peserta dan nilai signature tidak dimasukkan.

### Unit audit, nilai klaim, dan usaha

Untuk eksperimen generator, unit audit adalah `synthetic_facility` dengan ID `facility_id` buatan. Pilihan ini mengikuti atribut pengelompokan kapasitas yang tersedia dan memudahkan penggabungan klaim lintas pemeriksa. ID ini hanya valid dalam generator sintetis; skema BPJS belum membuktikan ID fasilitas unik.

Skor unit adalah **maksimum skor per klaim yang terindikasi** dalam fasilitas itu. Aturan max dipilih agar jumlah klaim fasilitas tidak dengan sendirinya menaikkan skor. Daftar alasan unit menautkan klaim dan indikator pemicu; indikator unit merupakan gabungan indikator unik.

Nilai klaim unit adalah jumlah `billed_amount` valid dari ID klaim unik yang terindikasi oleh setidaknya satu detektor. Klaim yang dipicu beberapa indikator atau beberapa pasangan hanya dijumlahkan sekali. Nilai hilang/invalid tidak diisi. Jika sebagian valid, jumlah yang diketahui berstatus parsial dan antrean memberi peringatan bahwa nilai/prioritas dapat berubah; jika tidak ada yang valid, indeks unit `null` dan unit tidak dapat diurutkan secara numerik.

Usaha audit diukur sebagai **jumlah berkas rekam medis yang direkomendasikan**, bukan waktu kerja: `ceil(jumlah klaim terindikasi unik × files_per_claim)`. Default simulasi adalah satu berkas per klaim dan batas maksimal 20 berkas per unit. Parameter dapat dikonfigurasi. Jika batas berlaku, antrean mencatat nilai sebelum dan setelah pembatasan serta status `capped`; pemilihan berkas sampel belum ditentukan. Ini bukan standar operasional BPJS.

### Indeks dan urutan antrean

Indeks mengikuti formula proposal tanpa perubahan:

`Prioritas Audit(unit) = Skor Risiko(unit) × Nilai Klaim(unit) ÷ Usaha Audit(unit)`

Pada implementasi, skor yang dipakai adalah skor unit (maksimum skor klaim terindikasi), nilai adalah total nilai klaim valid unik yang diketahui, dan usaha adalah jumlah berkas yang direkomendasikan. Komponen ditampilkan secara terpisah. Bila skor, nilai, atau usaha tidak valid/tidak tersedia, indeks `null`; tidak ada pembagi nol atau pengganti numerik. Bila nilai atau cakupan parsial, indeks berdasarkan nilai/cakupan diketahui ditandai `partial`; antrean menyebut posisinya dapat berubah.

Urutan adalah `priority_index` menurun, lalu `tie_break_case_id` menaik hanya saat indeks sama. Unit tanpa indeks ditempatkan sesudah indeks yang dapat dihitung; ID kasus tidak menggantikan nilai prioritas. Urutan ini alat bantu pengurutan prototipe, bukan peringkat risiko tervalidasi, prediksi kerugian, atau probabilitas fraud.

### Contoh sintetis terhitung

Tes sintetis membuat tiga klaim unik di satu unit fasilitas: nilai 100, 200, dan 300. Klaim 100 terpicu repeat sekali dan muncul dalam dua pasangan near-duplicate; kontribusi near tetap satu bobot, bukan dua. Dua klaim lain masing-masing terpicu near. Dengan keenam indikator dinilai dan bobot 1, skor tertinggi unit adalah `2/6 = 0.333333`. Nilai unik unit adalah `100 + 200 + 300 = 600`; rekomendasi usaha adalah 3 berkas. Maka indeks dari nilai keluaran skor adalah `0.333333 × 600 ÷ 3 = 66.6666`. Ini contoh fixture test yang seluruhnya artifisial, bukan hasil BPJS atau metrik evaluasi.

### Status dan validasi

Tes mencakup kontribusi berbobot, banyak pasangan dari indikator sama, deduplikasi nilai, nilai invalid, tidak tersedia vs tidak terpicu, truncation near-duplicate, usaha tidak valid, formula indeks, perubahan urutan, tie-break case ID, determinisme, minimisasi keluaran, dan input tak berubah. Benchmark dilakukan terpisah pada ukuran sintetis; tidak ada klaim kinerja 120.000 klaim hanya dari benchmark yang lebih kecil. Bobot, unit, nilai usaha, aturan cakupan, dan kegunaan skor tetap perlu ditinjau pengguna serta ahli domain sebelum pemakaian selain eksperimen sintetis.
