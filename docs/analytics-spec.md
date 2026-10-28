# Spesifikasi Analitik Awal

## Addendum rekonsiliasi signature FKRTL lokal (2026-10)

Modul `backend/app/analytics/fkrtl_signatures.py` memberi nama dan versi eksplisit pada empat definisi eksploratif yang sebelumnya tersebar di skrip. `SIGNATURE_SPECS` mencatat field wajib, normalisasi, aturan peserta, dan eligibility status setiap versi. Fungsi ini hanya menghitung agregat dari record yang diberikan dan tidak membaca file. Setiap definisi melaporkan `repeated_group_count`, `rows_in_repeated_groups`, `excess_rows`, dan `ineligible_rows`; record dengan salah satu atribut signature atau kunci peserta yang diwajibkan kosong/tidak valid tidak dihitung sebagai negatif.

| Versi | Definisi signature | Makna |
|---|---|---|
| `repeat_service_v1` | PSTV01, FKL03, FKL18, FKL19, FKL30 | Pola layanan berulang pada peserta sama; mereplikasi basis `run_fkrtl_real_detection.py`, tanpa nominal. |
| `repeat_service_same_amount_v1` | Signature di atas + FKL47 | Subset pola layanan dengan nominal tagihan sama; bergantung pada klarifikasi FKL47 dan belum layak untuk prioritas/operasional. |
| `legacy_audit_signature_v1` | PSTV01, FKL03, FKL04, FKL18, FKL19, FKL30, FKL47 | Signature audit eksploratif awal yang mencakup tanggal pulang dan nominal; berbeda dari definisi detector aplikasi. |
| `cross_participant_exact_v1` | FKL03, FKL05, FKL06, FKL07–09, FKL16, FKL18, FKL19, FKL30, FKL47; syarat internal ≥2 PSTV01 | Pola exact antar peserta; FKL05 mengikuti kamus, bukan alias otomatis `FKL05_NEW`. FKL47 tetap prasyarat belum terverifikasi. |

Repeat detector aplikasi yang sudah ada (`repeat_billing.py`) adalah definisi lain: signature canonical 12 atribut termasuk token peserta, tanggal, lokasi/kategori, diagnosis, kelompok, prosedur, dan `billed_amount`. Itu tidak identik dengan empat profil skrip di atas. Pola exact lintas peserta pada skrip lama juga bukan fuzzy cloning. Kosong tidak pernah diganti dengan satu sentinel signature bersama dalam definisi berversi ini.

`summarize_signature` menolak profil yang menyertakan FKL47 secara default. Fixture sintetis dapat mengujinya dengan opt-in eksplisit `allow_unverified_amount=True`; opt-in tes tersebut tidak mengesahkan FKL47 pada sampel BPJS atau untuk prioritas. Profil berstatus blocked tidak boleh dipakai pada sumber BPJS sampai konfirmasi resmi dan perubahan kontrak dilakukan.

Perbedaan angka historis seperti “20 versus 81” **belum direkonsiliasi**. Source yang ditinjau memakai kombinasi field, aturan missing, populasi eligibility, serta unit hitung yang berbeda. Perbandingan sah memerlukan populasi sumber yang sama dan keluaran agregat per definisi; tahap ini tidak membuka data sumber dan tidak membuktikan angka mana yang benar.

## Adapter FKRTL sample-compatible

`backend/app/data_sources/bpjs_fkrtl_adapter.py` menetapkan mapping kode ke nama canonical dengan versi `bpjs-fkrtl-sample-map-v2` (kontrak field: `FIELD_CONTRACT` di modul adapter). Ini adalah adapter eksplisit untuk caller lokal yang telah mendapat otorisasi, bukan koneksi runtime/API dan bukan validasi pada file aktual. Adapter menerima baris yang telah dibaca caller; tidak dipanggil otomatis. ID kasus harus disediakan oleh factory aplikasi lokal, bukan diturunkan dari `FKL02`. `FKL02` tidak diperlakukan sebagai facility ID. `PSTV01` hanya dipertahankan sebagai kunci internal `participant_token` untuk pemeriksaan peserta sama/berbeda.

`FKL03`/`FKL04` diparse sebagai tanggal saja. `FKL05` dipetakan ke `province_code`; `FKL05_NEW` tidak diasumsikan. `FKL02` dan `PSTV01` menjadi input HMAC ber-key lokal minimal 32 byte untuk `case_id` stabil (FKL02 didefinisikan per peserta); nilai sumber tidak dimasukkan ke record keluaran. Secret dibaca dari konfigurasi lokal oleh caller (`CIR_FKRTL_PSEUDONYM_KEY` bila memakai helper env), tidak ditanam pada source atau dicetak. `PSTV01` dipseudonimkan dengan key yang sama menjadi `participant_token` internal untuk membandingkan peserta sama/berbeda; token ini bukan atribut signature lintas peserta dan tidak boleh masuk respons atau log. FKL47 sengaja tidak dipetakan ke `billed_amount` sampai formula, satuan, tipe, dan ketersediaan pra-verifikasi diklarifikasi. FKL48 tidak dipilih atau dipetakan. ID fasilitas, timestamp, kapasitas, jenis/unit layanan, dan inventory bukti ditandai tidak tersedia. Karena itu adapter belum membuat profil yang layak untuk ranking fasilitas atau menjalankan seluruh enam pemeriksa. Metadata coverage menjelaskan batas tersebut; implementasi ini belum menggantikan `synthetic_demo` atau import batch sintetis.

Reader `.dta` menolak case reference duplikat lintas chunk dengan menyimpan set HMAC case ID selama iterasi; ini memakai memori sebanding jumlah kunjungan. Uniqueness FKL02/PSTV01 pada file aktual belum diperiksa. Perubahan pseudonym key mengubah case ID sehingga key rotation memerlukan kebijakan agar riwayat review tidak terlepas.

> Protokol evaluasi detektor dan ranking sintetis ditetapkan terpisah dalam `docs/evaluation-spec.md`. Angka benchmark di sana berasal dari generator v3 dan bukan pengukuran data BPJS.

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

## Pipeline API terkoordinasi (Tahap 17)

`backend/app/services/analytics.py` menjalankan satu pass berurutan pada sumber demo aktif: enam detektor melalui `run_detector_suite`, `score_claims`, lalu `build_audit_priority_queue`. Detektor menerima record fitur dan metadata fasilitas eksplisit saja; ground truth generator benchmark tidak diimpor atau dibaca oleh service/API. Skor mengagregasi bobot provisional yang sudah ditetapkan per indikator yang dapat dinilai; sinyal yang sama dari banyak grup dalam indikator yang sama tetap dihitung satu kali oleh scoring yang ada. Formula prioritas, deduplikasi nilai klaim, batas berkas audit, dan tie-break tetap mengikuti `audit_priority.py`.

Respons analisis mengekspos versi/bobot, cakupan per detektor, jumlah kandidat/grup, status pemotongan, serta unit prioritas dan alasannya. Status per kasus membedakan sinyal, tidak ada sinyal pada pemeriksaan tercakup, tidak berlaku, dan belum dinilai. Skor null tetap null ketika tidak ada pemeriksaan yang dapat dinilai; level risiko tetap null karena threshold level tidak didefinisikan. `/api/v1/cases` mengurutkan indeks aturan provisional jika diminta `sort_by=risk_score`, bukan probabilitas fraud.

Adapter runtime `synthetic_demo` saat ini berisi 12 klaim artifisial tetapi tidak memberikan metadata kapasitas fasilitas atau identifier fasilitas. Oleh sebab itu pemeriksa kapasitas tidak berlaku pada klaim demo tersebut, sebagian aturan temporal/bukti belum dinilai, dan audit priority fasilitas tidak membentuk unit dari identitas rekaan. Kandidat terpicu yang tidak memiliki facility ID dilaporkan sebagai `unassigned_triggered_case_count`. Hal ini berbeda dari generator benchmark, yang memberi fasilitas sintetis untuk evaluasi batch tetapi tidak dipanggil oleh API.

Semua API response masih bertanda `synthetic_demo`; indeks skor dan alasan adalah hasil aturan pada fixture tersebut. Skor bukan probabilitas fraud, sementara ketiadaan sinyal, ketidakberlakuan, atau pemeriksaan terpotong tidak membuktikan klaim normal.

## Status proses tinjauan auditor (Tahap 8)

Status tindak lanjut adalah `pending_review`, `needs_more_evidence`, `not_substantiated`, atau `escalated`. Kasus tanpa event tinjauan berstatus awal `pending_review`. Status dapat berubah ke status diizinkan mana pun; setiap POST yang diterima menambahkan event berisi waktu, status sebelumnya, status baru, catatan opsional, dan label reviewer demo. Status yang sama dapat dikirim lagi untuk mencatat pembaruan catatan. Status ini hanya alur kerja, bukan label fraud atau keputusan yang diverifikasi independen. Metadata disimpan terpisah dalam SQLite lokal dan tidak memuat baris analitik, token peserta, atau signature. Autentikasi, retensi, kontrol akses, serta penggunaan catatan untuk data nyata belum ditetapkan.

## Pemeriksa tambahan eksperimen (Tahap 12)

Pemeriksa berikut berada di `backend/app/analytics/`, menerima record fitur sintetis terkontrol, dan tidak membaca ground truth. Service API saat ini memanggil keenam pemeriksa melalui `run_detector_suite`; hasilnya adalah kandidat untuk ditinjau manusia. Unit test memakai fixture/generator sintetis; tidak ada validasi pada klaim nyata. Snapshot API menghitung ulang sumber demo kecil dan bukan AnalysisRun persisten.

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

1. `short_window_repeat`: sedikitnya 2 klaim dengan peserta, fasilitas sintetis, dan jenis layanan sama; jendela default 3 hari. Klaim dirantai: klaim masuk grup bila jaraknya ke klaim sebelumnya dengan kunci yang sama paling lama 3 hari, sehingga setiap klaim yang punya tetangga dalam jendela ikut ditandai (versi sebelumnya meng-anchor jendela pada klaim pertama dan melewatkan klaim berikutnya dalam rangkaian kunjungan).
2. `uniform_service_minute`: sedikitnya 3 klaim dan 3 peserta berbeda pada fasilitas/jenis layanan/tanggal/menit yang sama.

Tanggal sibuk saja bukan sinyal. Output menunjukkan tipe pola, jumlah, tanggal, menit (bila relevan), dan ID kasus terbatas. Pengulangan layanan terjadwal, episode perawatan, slot klinik seragam, atau pencatatan sistem dapat menjadi false positive. Timestamp simulasi tidak membuktikan waktu layanan aktual. Perubahan pola waktu lintas baseline/periode masih rencana terpisah.

### Kelengkapan bukti pendukung

`evidence_completeness.py` memakai `service_type`, `supporting_evidence_required`, `supporting_evidence_types`, `supporting_evidence_present`, dan `supporting_evidence_recording_status`. Aturan sintetis default: fisioterapi memerlukan `therapy_session_log` dan `clinical_note`; `synthetic_supported_action` serta `synthetic_mixed_action` memerlukan `procedure_order` dan `clinical_note`. Kandidat hanya dibuat saat status inventaris `recorded`, daftar bukti tersedia dan konsisten, serta ada bukti yang diwajibkan tetapi tidak tercantum. `not_recorded` menjadi unassessed; daftar/status tidak valid menjadi ineligible. Output menampilkan jenis bukti yang kurang, aturan layanan, alasan, dan batasan. Ketiadaan entri bukan bukti layanan tidak diberikan.

Aturan tersebut menguji kelengkapan daftar dalam skenario perangkat lunak, bukan kecukupan klinis/administratif. Field/aturan harus disahkan ahli sebelum diterapkan pada data nyata.

### Status pengujian dan batas penggunaan

**Status historis Tahap 12:** enam pemeriksa memiliki unit test sintetis dan benchmark terpisah; benchmark bukan bukti performa pada data produksi. MinHash/LSH tidak digunakan; near-duplicate memakai blocking berbatas. Integrasi API dilaksanakan pada Tahap 17 dan dirangkum pada bagian Pipeline API terkoordinasi di atas. Validasi ahli domain pada data BPJS belum dilakukan.

**Near-duplicate search coverage (pembaruan pipeline sintetis):** primary blocks memakai field kanonis yang sudah ditetapkan modul. Blok diproses dari ukuran terkecil ke terbesar; tie-break menggunakan digest deterministik atas kunci blok agar batas global tidak selalu memeriksa prefix leksikografis yang sama. Pemilihan stratified dipakai bila estimasi kerja blok melebihi anggaran. `search_truncated` menunjukkan batas keras pencarian/penerbitan yang tercapai; flag ini bukan satu-satunya bukti kelengkapan. Detektor juga mengembalikan `assessment_incomplete` serta hitungan agregat `unassessed_case_count` dan penyebab non-eksklusifnya. Sampling blok dapat meninggalkan record belum dinilai walaupun `search_truncated=false`; risk scoring karena itu melaporkan coverage `partial` bila ada record eksplisit belum dinilai. Sampling saja tidak membuat hasil parsial bila tidak ada record/pasangan yang tertinggal dan seluruh assessment relevan selesai. Pasangan yang tidak tercakup tetap belum dinilai.

Blok yang melampaui `max_block_size` dipecah lagi menggunakan kesamaan eksak pada fitur kanonis lain, dengan nilai kosong tidak menjadi bukti kecocokan. Bucket refinement yang tetap padat hanya mendapat sampel silang-peserta yang dibatasi, dan tetap menandai pencarian parsial. Peserta yang sama atau token pembanding yang tidak tersedia dikecualikan sebelum anggaran perbandingan; token hanya dipakai internal dan tidak menjadi signature atau keluaran. Diagnostik agregat mencatat jumlah blok, ukuran maksimum, bucket padat, batas keras, sampling stratified, jumlah record belum dinilai menurut sebab, dan assessment-incomplete. Hitungan sebab dapat tumpang tindih; diagnostik tidak memuat ID atau signature. Batas saat ini tetap 5.000 perbandingan dan 5.000 kandidat; status tidak dinilai tidak menghasilkan kesimpulan negatif.

**Profil benchmark sintetis pipeline penuh (riwayat sebelum compact score; hasil terbaru di bawah):** 25.000 baris selesai dalam 27,212 detik; peak `tracemalloc` 213.177.583 byte; working set puncak 478.314.496 byte (delta dari baseline 408.313.856 byte). 120.000 baris selesai dalam 123,522 detik; peak `tracemalloc` 822.141.125 byte; working set puncak 1.651.404.800 byte (delta 1.582.407.680 byte). Near-duplicate mencapai batas 5.000 pasangan kandidat, yang melibatkan 10.000 klaim unik pada kedua ukuran; cakupan: 11.995 klaim dinilai dan 13.005 belum dinilai pada 25.000; 10.000 dinilai dan 110.000 belum dinilai pada 120.000. Batas jumlah kandidat/perbandingan tercapai pada keduanya, jadi hasil ini bukan cakupan penuh. Pada ukuran 120.000, 5.000 pasangan dinilai dan sekitar 2.719.800 slot pasangan dari kombinasi blok primer tidak tercakup; angka terakhir adalah hitungan slot lintas blok (pasangan yang sama dapat terwakili pada lebih dari satu blok), bukan jumlah pasangan unik. Sampling menyebar secara deterministik ke blok; pencarian tetap ditandai terpotong. Angka berasal dari fixture `.dta` sintetis dengan chunk 2.000, bukan benchmark data BPJS atau jaminan kapasitas produksi. `tracemalloc` tidak menangkap semua alokasi native; working set diambil sampling proses tiap 20 ms dan dapat melewatkan puncak singkat. Dibanding hasil sebelum perubahan (120.000: 102,865 detik, `tracemalloc` 863.524.873 byte, working set puncak 1.737.408.512 byte), peak Python turun sekitar 4,8% dan puncak working set sekitar 5,0%, sementara waktu bertambah sekitar 20,1%. Hasil 25.000 awal memiliki working-set puncak sekitar 439 MB; pengukuran final lebih tinggi karena alur baru menghasilkan lebih banyak pasangan kandidat dan cakupan per kasus eksplisit. Memori tetap tinggi dan runtime bertambah; ini pengurangan terbatas, bukan penyelesaian skalabilitas.

**Benchmark pipeline penuh setelah pengurangan detail skor non-terpicu (fixture `.dta` sintetis, chunk 2.000):** 25.000 record: 25,262 detik, peak `tracemalloc` 170.986.827 byte, sampled peak working set 403.886.080 byte (delta 336.015.360 byte). Near-duplicate mengeluarkan sinyal untuk 10.000 kasus unik dari maksimum 5.000 pasangan; 10.000 assessed dan 15.000 unassessed; pencarian terpotong. Pada 120.000 record: 67,733 detik, peak `tracemalloc` 520.067.001 byte, sampled peak working set 1.101.111.296 byte (delta 1.033.236.480 byte). Near-duplicate tetap dibatasi 5.000 pasangan, dengan 10.000 kasus terpicu, 10.000 assessed, 110.000 unassessed, dan `search_truncated=true`. Perbandingan langsung terhadap eksekusi sebelumnya pada 120.000 menunjukkan waktu turun dari 153,963 detik ke 67,733 detik, peak `tracemalloc` dari 825.393.712 ke 520.067.001 byte, dan sampled working-set peak dari 1.652.858.880 ke 1.101.111.296 byte. Pengurangan ini berasal terutama dari tidak menyimpan detail per indikator untuk klaim non-terpicu pada snapshot; coverage agregat tetap dihitung pada seluruh populasi. Pengukuran sampled working set dapat melewatkan puncak singkat dan `tracemalloc` tidak mencakup semua alokasi native.

**Atribusi memori per tahap (satu eksekusi setelah optimasi, 120.000 record):** retained Python allocation bertambah sekitar 247,5 MB pada provider load, 175,3 MB pada detector suite, 30,6 MB pada scoring compact, 0,1 MB pada priority, dan 65,7 MB pada snapshot; transient Python allocation peak interval masing-masing sekitar 393,8 MB, 185,8 MB, 84,1 MB, 15,5 MB, dan 65,7 MB. Sampled working set pada milestone yang sama sekitar 545 MB, 901 MB, 963 MB, 964 MB, dan 1.104 MB. Ini menunjukkan provider materialization dan hasil detector tetap besar, walaupun detail skor untuk record non-terpicu tidak lagi ditahan. Angka per tahap adalah delta alokasi Python antar-marker dan bukan ukuran RSS eksklusif komponen; working set merupakan pembacaan sesaat pada marker.

**Uji kualitas candidate generation pada fixture pasangan sintetis berlabel (seed 731, evaluator dengan observer pasangan lokal):** ground truth dipisahkan dari record fitur dan tidak diteruskan ke detektor. ID kasus tidak memuat label. Setiap pasangan positif ditanam dengan variasi prosedur; kontrol negatif sah berbeda pada prosedur, kelompok klaim, dan kelas fasilitas sehingga masih masuk blocking tetapi berada di bawah threshold. Blocking key unik per pasangan, dengan atribut blok dibangkitkan dari seed. Ini menguji pola langka dan batas budget, bukan distribusi dunia nyata.

Metrik dibedakan sebagai berikut: `discovered` berarti pasangan target positif masuk set pasangan yang dihasilkan blocking; `actually similarity-checked` berarti comparator benar-benar menghitung similarity; `checked and passed` berarti lolos threshold. `not generated by bounded block search` adalah pasangan target yang tidak masuk set pembanding; hal itu dapat disebabkan budget/pemilihan blok atau keterbatasan blocking, dan bukan label negatif. Pasangan yang dihasilkan tetapi tidak dibandingkan (misalnya bila batas output kandidat lebih kecil dari set pasangan) dihitung terpisah. Negative control hanya disebut assessed jika comparator benar-benar dijalankan. Discovery rate = positive target pairs discovered / all planted positive target pairs. Seluruh angka di bawah adalah fixture sintetis saja.

| Record | Budget pasangan | Target positif | Positif ditemukan blocking | Positif dibandingkan | Positif lolos threshold | Positif tidak dihasilkan oleh blocking berbatas | Negative control dibandingkan / dipicu | Discovery rate | Truncated |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|:---|
| 100 | 25 | 25 | 14 | 14 | 14 | 11 | 11 / 0 | 56% | Ya |
| 100 | 100 | 25 | 25 | 25 | 25 | 0 | 25 / 0 | 100% | Tidak |
| 1.000 | 25 | 250 | 19 | 19 | 19 | 231 | 6 / 0 | 7,6% | Ya |
| 1.000 | 100 | 250 | 64 | 64 | 64 | 186 | 36 / 0 | 25,6% | Ya |
| 1.000 | 5.000 | 250 | 250 | 250 | 250 | 0 | 250 / 0 | 100% | Tidak |
| 10.000 | 25 | 2.500 | 14 | 14 | 14 | 2.486 | 11 / 0 | 0,56% | Ya |
| 10.000 | 100 | 2.500 | 55 | 55 | 55 | 2.445 | 45 / 0 | 2,2% | Ya |
| 10.000 | 5.000 | 2.500 | 2.500 | 2.500 | 2.500 | 0 | 2.500 / 0 | 100% | Tidak |

Di konfigurasi ini pasangan positif yang dibandingkan semuanya lolos threshold; tidak terlihat pasangan target positif yang dibandingkan tetapi gagal threshold. Jadi pada fixture tersebut penurunan discovery di budget kecil berasal dari pasangan yang tidak dihasilkan/dicapai oleh pencarian berbatas, bukan threshold. Ini tidak mengisolasi kekurangan blocking secara umum: pasangan positif fixture memang sengaja memenuhi blocking keys, sedangkan truncation mengecualikan banyak blok. Budget 5.000 mencukupi fixture 10.000 karena hanya terdapat 5.000 pasangan desain; hasil “tidak truncated” hanya berlaku pada ruang pasangan fixture ini. Untuk kasus 120.000 sintetis sebelumnya, detector mencapai budget 5.000 dan menyisakan 110.000 klaim belum dinilai; detector harus diperlakukan partial. Tidak ada perubahan algoritme, budget, atau threshold berdasarkan hasil ini. Kontrol negatif yang tidak dibandingkan juga bukan true negative. Dense-block refinement, variasi atribut prosedur, urutan input terbalik, dan determinisme tetap dicakup tes terpisah. Semua hasil hanya mengukur kemampuan menemukan pola yang ditanam, bukan precision/recall fraud atau validitas pada BPJS.

## Skor risiko gabungan dan prioritas audit (Tahap 13)

Modul `risk_scoring.py` menerima enam keluaran detektor beserta record fitur, dan `audit_priority.py` membentuk antrean terpisah. `run_detector_suite(records, facilities)` menjalankan keenam detektor pada record fitur saja; ia tidak menerima ground truth. Route analytics lama tetap menghitung snapshot `synthetic_demo`; route AnalysisRun menjalankan pipeline pada batch CSV sintetis siap dan menyimpan snapshot. GET AnalysisRun membaca hasil tersimpan. Evaluasi ground truth tetap terpisah dari jalur operasional.

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

Nilai klaim unit adalah jumlah `billed_amount` valid dari ID klaim unik yang terindikasi oleh setidaknya satu detektor. Klaim yang dipicu beberapa indikator atau beberapa pasangan hanya dijumlahkan sekali. Nilai hilang/invalid tidak diisi. Indeks prioritas hanya dihitung jika seluruh klaim terindikasi pada unit memiliki nilai valid; jika ada nilai yang hilang/invalid, nilai agregat yang diketahui tetap dapat ditampilkan sebagai parsial, tetapi `priority_index` adalah `null` dan unit tidak mendapat urutan numerik.

Usaha audit diukur sebagai **jumlah berkas rekam medis yang direkomendasikan**, bukan waktu kerja: `ceil(jumlah klaim terindikasi unik × files_per_claim)`. Default simulasi adalah satu berkas per klaim dan batas maksimal 20 berkas per unit. Parameter dapat dikonfigurasi. Jika batas berlaku, antrean mencatat nilai sebelum dan setelah pembatasan serta status `capped`; pemilihan berkas sampel belum ditentukan. Ini bukan standar operasional BPJS.

### Indeks dan urutan antrean

Indeks mengikuti formula proposal tanpa perubahan:

`Prioritas Audit(unit) = Skor Risiko(unit) × Nilai Klaim(unit) ÷ Usaha Audit(unit)`

Pada implementasi, skor yang dipakai adalah skor unit (maksimum skor klaim terindikasi), nilai adalah total nilai klaim valid unik, dan usaha adalah jumlah berkas yang direkomendasikan. Komponen ditampilkan secara terpisah. Bila skor tidak tersedia, nilai tidak lengkap, usaha tidak positif, cakupan unit parsial/tidak tersedia, atau keanggotaan kandidat terpotong, indeks `null`; tidak ada pembagi nol atau pengganti numerik. `not_applicable` tidak menghalangi ranking jika pemeriksaan relevan lainnya cukup. Jika beberapa unit eligible dan beberapa tidak, status ringkasan antrean adalah `partial`, dan alasan ketidaklayakan disajikan per unit. Batas jumlah berkas tetap merupakan asumsi; unit berstatus `capped` dapat memiliki indeks yang mengikuti konfigurasi cap tetapi diberi keterbatasan eksplisit.

Urutan adalah `priority_index` menurun, lalu `tie_break_case_id` menaik hanya saat indeks sama. Unit tanpa indeks ditempatkan sesudah indeks yang dapat dihitung; ID kasus tidak menggantikan nilai prioritas. Urutan ini alat bantu pengurutan prototipe, bukan peringkat risiko tervalidasi, prediksi kerugian, atau probabilitas fraud.

### Contoh sintetis terhitung

Tes sintetis membuat tiga klaim unik di satu unit fasilitas: nilai 100, 200, dan 300. Klaim 100 terpicu repeat sekali dan muncul dalam dua pasangan near-duplicate; kontribusi near tetap satu bobot, bukan dua. Dua klaim lain masing-masing terpicu near. Dengan keenam indikator dinilai dan bobot 1, skor tertinggi unit adalah `2/6 = 0.333333`. Nilai unik unit adalah `100 + 200 + 300 = 600`; rekomendasi usaha adalah 3 berkas. Maka indeks dari nilai keluaran skor adalah `0.333333 × 600 ÷ 3 = 66.6666`. Ini contoh fixture test yang seluruhnya artifisial, bukan hasil BPJS atau metrik evaluasi.

### Status dan validasi

Tes mencakup kontribusi berbobot, banyak pasangan dari indikator sama, deduplikasi nilai, nilai invalid, tidak tersedia vs tidak terpicu, truncation near-duplicate, usaha tidak valid, formula indeks, perubahan urutan, tie-break case ID, determinisme, minimisasi keluaran, dan input tak berubah. Benchmark dilakukan terpisah pada ukuran sintetis; tidak ada klaim kinerja 120.000 klaim hanya dari benchmark yang lebih kecil. Bobot, unit, nilai usaha, aturan cakupan, dan kegunaan skor tetap perlu ditinjau pengguna serta ahli domain sebelum pemakaian selain eksperimen sintetis.

### Policy action demo (P0 Stage 5)

`backend/app/analytics/action_policy.py` memisahkan lane tindakan demo dari scoring dan facility priority. Policy berlaku hanya pada finding kasus yang memang ada di snapshot run; klaim yang tidak masuk `cases` tidak otomatis memperoleh lane hijau. Nilai `risk_level` tetap `null`, dan status review/outcome manusia tidak berubah.

Versi default `action-policy-demo-v1-provisional` membagi rentang indeks aturan `[0,1]` menjadi tiga interval sama besar: `green` bila skor `<= 1/3`, `yellow` bila `1/3 < skor <= 2/3`, dan `red` bila `skor > 2/3`. Nilai tersebut hanya batas teknis untuk demonstrasi, bukan threshold domain, hasil kalibrasi, kebijakan resmi, atau validasi BPJS. Versi konfigurasi didefinisikan server-side; route hanya menerima pemilihan versi yang tersedia, bukan threshold bebas dari operator. Setiap versi terdaftar immutable di database batch/run; memakai konfigurasi berbeda memerlukan identifier versi baru. Manifest menyimpan versi dan konfigurasi persis yang digunakan.

Lane `cannot_recommend` dikembalikan untuk skor null/invalid, status score parsial/tidak dapat dinilai, tidak adanya indikator relevan yang dinilai, indikator lokal `not_assessed`, indikator relevan unavailable, atau pencarian relevan truncated. `not_applicable` diabaikan dan tidak meniadakan lane bila masih ada pemeriksaan yang dinilai lengkap. Cakupan global parsial pada record lain ditampilkan sebagai limitation; kasus dengan penilaian lokal lengkap dapat tetap memperoleh lane. Semua hasil menyertakan input assessment status, alasan, versi, dan limitation. Ini saran alur demo, bukan probabilitas fraud, `risk_level`, prioritas fasilitas, atau keputusan auditor.

AnalysisRun menambahkan action policy pada snapshot persisten; GET mengembalikan nilai tersimpan tanpa menghitung ulang. `DETECTOR_SUITE_VERSION = detector-suite-v1-manual` adalah identifier kontrak yang dipelihara manual, bukan source hash, provenance build, atau jaminan seluruh perubahan kode terdeteksi. Run menyimpan scoring/priority versions serta action-policy version/configuration yang benar-benar dipakai. Proses yang terputus masih dapat meninggalkan run `running`; pemulihan otomatis belum diterapkan.

## Kesesuaian dengan proposal (revisi alur)

- **Lampu lalu lintas (Langkah D):** policy `action-policy-two-signal-v2-provisional` — pada data dengan indeks aturan memakai interval indeks; pada sampel FKRTL (hanya dua pemeriksaan berlaku) memakai kesepakatan pemeriksaan aturan + AI (merah: ditandai aturan dan AI ≥ persentil 95; kuning: AI 90–95; hijau: lainnya). Uji agregat pada jendela 4–10 Maret 2024 (35.565 klaim): merah 275, kuning 434, hijau 9.915, tanpa saran 0.
- **Rangkuman per faskes (Langkah B, C, E, F):** `app/analytics/facility_groups.py` — kelompok faskes FKL05–FKL09 dengan nama dari value label .dta, minimal 30 klaim, vonis satu kalimat, urutan "untung diperiksa" tanpa nominal, klaim sampel untuk paket bukti. Pada jendela uji: 340 kelompok (22 risiko tinggi, 88 sedang); 1.438 kelompok kecil (14.063 klaim) disembunyikan.
- **Di-drop dari produk:** layar lama rawat (modul tetap sebagai masukan AI), halaman Evaluasi kosong, halaman detail kasus lama. Pemeriksaan kapasitas, pola waktu, dan kelengkapan bukti tetap hanya berlaku pada data contoh.

## Evaluasi pipeline saat ini (data sintetis berlabel)

`scripts/evaluate_current_pipeline.py` menjalankan pipeline produksi (pemeriksaan aturan + AI + policy v3) pada generator sintetis v4 dan menggabungkan label setelah analisis. Hasil seed 2026, 30.000 klaim, 60 faskes, 4% kecurangan: 100% klaim kecurangan terdeteksi pemeriksaan aturan; 96,7% masuk risiko sedang/tinggi (cloning 83%, modus lain 100%); 2 dari 28.800 klaim jujur tertandai (keduanya kontrol pengulangan sah, berisiko tinggi); ketepatan risiko tinggi 99,7% (≈25× pemilihan acak); 12/12 faskes di 20% teratas adalah faskes yang disuntik kecurangan. Data sintetis sengaja berpola jelas, sehingga angka ini tidak mewakili kinerja pada data nyata. Evaluasi lama `record-level-v4-120000` (prioritas fasilitas versi lama) menunjukkan presisi setara pemilihan acak (3,9% vs 4%) dan digantikan oleh pengukuran ini.

**Stress test "jujur tapi mirip" (ditambahkan ke evaluasi):** 200 klaim terapi rutin bervolume tinggi dan 120 sesi terapi terjadwal, berlabel jujur, memakai kombinasi kode fisioterapi jujur yang paling umum. Menurut aturan saja seluruhnya berisiko sedang (satu temuan "pola identik"); setelah digabung AI pada data sintetis menjadi tinggi, karena kode sintetis acak membuat paket rutin tampak langka. Akibatnya ketepatan risiko tinggi pada uji sintetis turun dari 99,7% menjadi ±62%. Cek di data asli (4–10 Maret 2024): klaim dengan 10 kode INA-CBG paling umum (76,5% klaim) hanya 2,0% berpersentil AI ≥ 95%, kode langka 70,4%; jadi pada data asli AI tidak menilai klaim rutin sebagai anomali.

## Pembaruan pemeriksaan dan evaluasi (data demo realistis)

- **Pola identik antar-pasien** kini memperhitungkan peluang kebetulan pada input ≥ 200 klaim: jumlah klaim identik di faskes-hari tersebut dibandingkan perkiraan (klaim faskes-hari × porsi kombinasi kode di seluruh input), dan grup hanya dipertahankan bila peluang Poisson terjadinya ≥ jumlah itu secara kebetulan < 0,1%. Templat langka yang disalin tetap tertangkap; paket layanan umum tidak. Jumlah grup yang dilewati dilaporkan (`common_pattern_groups_skipped`).
- **Policy v3**: skor AI yang relatif terhadap analisis itu sendiri (model dilatih per analisis, tanpa `reference_percentile`) tidak dapat mengonfirmasi pemeriksaan kemiripan yang eksploratif; hanya skor terhadap pembanding tetap (model terlatih FKRTL) yang dapat.
- **Evaluasi Kinerja Sistem** memakai dunia `demo-3-operasional` (kode realistis). Hasil: 4 dari 4 modus 100% terdeteksi (phantom 88,7%), ketepatan risiko tinggi 88,8% (≈32× pemilihan acak), klaim jujur yang masuk risiko sedang/tinggi 3,8% (termasuk 544 kasus jujur-mirip yang sengaja dibuat; risiko tinggi hanya 30 dari 24.160). Generator v4 lama (kode acak) tetap tersedia dengan `--source v4`.

## Pemeriksaan klinis pada kolom BPJS (`clinical-rules-v1`)

Berlaku hanya untuk sumber berformat kolom data klaim BPJS FKRTL (sampel lokal dan unggahan `bpjs-fkrtl-csv-v1`); untuk sumber lain ketiganya `not_applicable`. Ketiganya adalah temuan aturan spesifik (bukan eksploratif), jadi ikut menentukan lane v3 dan level faskes. Referensi diambil dari tabel agregat model AI (median dan MAD lama rawat per INA-CBG dan kelas rawat; jumlah pasangan diagnosis–INA-CBG; kombinasi < 5 tidak disimpan). Tanpa model, pemeriksaan lama rawat dan keparahan berstatus `unavailable`.

| Kode | Aturan (ambang dinyatakan sebelum diuji) |
|---|---|
| `length_of_stay_extreme_candidate` | Rawat inap dengan lama rawat > max(median + 7 hari, median + 5 × 1,4826 × max(MAD, 1)) dari INA-CBG dan kelas rawat yang sama. Kunjungan sehari: tidak berlaku. |
| `rapid_readmission_candidate` | Peserta yang sama dirawat inap lagi dengan diagnosis utama sama ≤ 3 hari setelah pulang; kedua klaim ditandai sebagai satu pasangan. |
| `unusual_severity_candidate` | INA-CBG keparahan II/III yang, untuk diagnosis utama dan kelompok INA-CBG dasar yang sama, dipakai < 5% klaim acuan (minimal 30 klaim acuan). |

Uji agregat pada data sampel asli (4–10 Maret 2024, 35.565 klaim; `scripts/check_clinical_rules_real.py`, hanya hitungan): lama rawat ekstrem 19 klaim (0,6% rawat inap yang dinilai), rawat inap ulang cepat 14 (0,4%), keparahan tidak lazim 45 (10% klaim keparahan II/III yang dapat dinilai). Uji "keparahan III tetapi rawat singkat" ditolak: di data latih median lama rawat keparahan III hanya ±1 hari di atas keparahan I.

## Level faskes: hanya temuan spesifik yang membuat "tinggi"

`facility-group-v1` kini memerlukan minimal 3 klaim risiko tinggi **dengan temuan aturan spesifik** (`red_with_specific_finding`) dan porsi risiko tinggi ≥ 2× rata-rata. Klaim risiko tinggi yang hanya berasal dari penyaringan kemiripan (eksploratif) yang dikuatkan AI membuat faskes paling tinggi "sedang".

## Tahap 2: catatan klinis (`note-clone-v1`) dan pembacaan AI

Mengikuti panduan panitia (tahap 1 skor ML, tahap 2 LLM membaca catatan klinis; pilar 01 *cloning* lewat kemiripan teks catatan medis):

- **Catatan klinis kembar** (`cloned_clinical_note_candidate`, `app/analytics/note_similarity.py`). Catatan dinormalisasi (huruf kecil, hanya kata dan angka) lalu di-*hash*; catatan ≥ 12 kata yang sama persis pada klaim dari ≥ 2 peserta berbeda menjadi satu grup. Angka tanda vital dan lab ikut dibandingkan, karena pada pasien berbeda angka itu hampir tidak mungkin sama semua. Peserta yang sama dengan catatan sama adalah urusan pemeriksaan layanan berulang, bukan salinan. Batas: hanya salinan kata demi kata; parafrase tidak tertangkap.
- **Pembacaan AI** (`app/services/clinical_ai.py`): atas permintaan petugas per klaim, model bahasa (bawaan: model lokal lewat Ollama; opsional Claude enterprise) membaca fakta dari catatan, lalu aturan membandingkannya dengan data klaim dan menilai apakah catatan mendukung kode yang ditagih mendukung kode yang ditagih (`sesuai`, `perlu_dicek`, `mencurigakan`) dengan alasan dan hal yang perlu dicek di rekam medis. Bukan putusan dan tidak memengaruhi skor. Bila model tidak tersedia, pembacaan cadangan berbasis aturan teks dipakai dan ditandai demikian.
- **Data demo**: setiap klaim membawa catatan sintetis dengan tanda vital dan lab acak. Modus kecurangan meninggalkan jejak di catatan: klaim salinan menyalin catatan pasien lain kata demi kata; *upcoding* tetap bercatatan "tanpa komplikasi" di bawah INA-CBG keparahan III; lama rawat diperpanjang tetap menyebut lama rawat semula; pemecahan rawat inap menyebut "lanjutan perawatan".
- **Hasil evaluasi demo-3** (28.953 klaim, `scripts/evaluate_current_pipeline.py`): klaim salinan terdeteksi 72 dari 72 (sebelumnya 0); tidak ada catatan jujur yang tergrup (12 klaim di luar label adalah klaim templat asal salinan). Ketepatan risiko tinggi 60,5% (≈38× acak); 8 dari 8 faskes di 20% teratas adalah faskes yang disuntik kecurangan. Angka ini dari data sintetis berpola jelas, tidak mewakili kinerja pada data nyata. Pengukuran pembacaan catatan ada di bagian berikut.

## Diagnosis sekunder dan tambahan khusus (`claim-detail-rules-v1`)

Dasar: panduan data sampel BPJS (keparahan INA-CBG = komorbid/komplikasi, dicatat sebagai diagnosis sekunder FKL24; tambahan khusus FKL33–FKL46) dan materi BPJS (jejak *upcoding*: anomali dibanding rata-rata regional; contoh *phantom billing* operasi katarak).

Profil agregat sampel 2024 (`scripts/profile_special_and_secondary_real.py`, 1,70 juta kunjungan; hanya angka): 100% kunjungan file diagnosis sekunder cocok dengan FKRTL; rawat inap keparahan I/II/III yang punya ≥ 1 diagnosis sekunder: 38,5% / 99,83% / 99,96%. Tambahan khusus jarang: prosedur 0,52% klaim (terbanyak *phacoemulsification*), pemeriksaan 0,11% (MRI), obat 0,09% (faktor anti-hemofilia, deferasirox), prostesis 0,018% (implan pinggul/lutut). Obat khusus berulang ≤ 30 hari 715 dari 1.599: wajar untuk terapi kronis bulanan, sehingga **tidak** dijadikan aturan.

| Kode | Aturan (dinyatakan sebelum diuji) |
|---|---|
| `severity_without_secondary_candidate` | Rawat inap (tipe kasus 1/4/6) dengan INA-CBG keparahan II/III tanpa satu pun diagnosis sekunder. |
| `unusual_special_topup_candidate` | Kode tambahan khusus yang ditagihkan bersama INA-CBG yang di acuan (FKRTL 2024 di luar jendela analisis, 1,66 juta klaim) muncul < 5 kali bersama kode itu. |

Uji pada jendela analisis asli (4–10 Maret 2024, 35.565 klaim, `scripts/check_claim_detail_rules_real.py`): keparahan tanpa diagnosis sekunder 0 dari 862 klaim yang dinilai; tambahan khusus tidak lazim 1 dari 285. Artinya beban bagi faskes jujur sangat kecil; tanpa label, kemampuan menangkap kecurangan nyata tidak dapat diukur.

**Pembanding wilayah** (`facility_groups.peer_signals`): porsi rawat inap keparahan II/III (minimal 30 klaim, pembanding ≥ 100, rasio ≥ 2, porsi ≥ 10%) dan porsi klaim bertambahan khusus (minimal 100 klaim, pembanding ≥ 300, rasio ≥ 3, porsi ≥ 2%) dibandingkan dengan ≥ 2 kelompok faskes sekelas di provinsi yang sama. Pada jendela asli: 3 dari 340 kelompok (semuanya tambahan khusus). Ditampilkan sebagai alasan, tidak mengubah tingkat risiko.

## Pembacaan catatan klinis oleh model lokal

`scripts/evaluate_clinical_reader.py` mengukur pembacaan catatan pada klaim berlabel, tanpa temuan aturan dan skor AI agar yang diukur hanya pembacaan catatannya. Dua himpunan: `--set demo` (8 klaim per label dari dunia demo-3, catatan dari generator kami) dan `--set independent` (16 catatan tulisan tangan di `scripts/clinical_reader_cases.py` dengan gaya resume medis yang beragam: singkatan, angka dalam kata, "2x24 jam", kasus berat yang jujur dengan komorbid). Qwen3 4B di CPU laptop (Ryzen 7 5825U, tanpa GPU):

| Cara | Himpunan | Klaim curang ditandai | Klaim jujur ditandai | Waktu per klaim |
|---|---|---|---|---|
| Model langsung memberi verdict (ditinggalkan) | demo | 0 / 15 | 1 / 5 | ±45 dtk |
| Model mengekstrak fakta, aturan memutuskan (versi awal) | catatan tulisan tangan | 12 / 12 | 2 / 4 | ±43 dtk |
| **Model + aturan teks (dipakai)** | demo | 23 / 24 | 0 / 8 | ±43 dtk (maks. 53) |
| **Model + aturan teks (dipakai)** | catatan tulisan tangan | 12 / 12 | 0 / 4 | ±40 dtk (maks. 43) |
| Pembacaan cadangan tanpa model | demo | 23 / 24 | 0 / 8 | < 0,01 dtk |
| Pembacaan cadangan tanpa model | catatan tulisan tangan | 11 / 12 | 0 / 4 | < 0,01 dtk |

Perubahan dari versi awal setelah melihat catatan tulisan tangan: (1) selisih lama rawat satu hari tidak lagi dianggap bertentangan (cara menghitung hari masuk/malam; kasus lama rawat diperpanjang berselisih ≥ 5 hari); (2) catatan "ringan" yang tidak menyebut komorbid kini "perlu dicek", bukan "mencurigakan", dan model diberi tahu bahwa penyakit penyerta yang terkontrol tetap komorbid; (3) aturan teks (lama rawat dalam berbagai penulisan, tanda rawat ulang, kata "tanpa penyulit/penyerta") ikut diterapkan pada hasil model, karena model kecil kadang tidak membaca "2x24 jam" atau "hari perawatan kedua". Karena aturan itu disusun setelah melihat himpunan tulisan tangan, angka pada himpunan itu bukan lagi ukuran yang sepenuhnya independen. Sampel kecil dan semuanya catatan buatan; angka ini bukan ukuran kemampuan pada rekam medis asli. Kecepatan ±40 dtk per klaim di CPU laptop; dengan GPU server jauh lebih cepat (belum diukur).

## Perbandingan metode (data demo-3 berlabel)

| Cara memeriksa | Berkas diperiksa | Kecurangan per 100 berkas pertama | Kecurangan tertangkap | Klaim sah ikut diperiksa |
|---|---|---|---|---|
| Audit acak (beban sama dengan Radar) | 951 | 1,6 | 3,3% | 3,3% |
| Aturan sederhana (satu aturan mana pun, tanpa AI/urutan) | 8.748 | 4,7 | 86,6% | 29,3% |
| Claim Integrity Radar (risiko tinggi + sedang) | 951 | 63 | 85,5% | 1,93% |

Populasi 28.918 klaim, 470 curang (1,6%) dalam enam modus di 10 dari 40 RS; tiap provinsi punya beberapa RS sekelas (pembanding wilayah). Per modus (aturan saja): klaim salinan 100%, pemecahan rawat inap 100%, tambahan khusus fiktif 100%, lama rawat diperpanjang 79%, tagihan ganda 76%, *upcoding* 42% (sebagian pelaku sengaja ikut memalsukan diagnosis sekunder). Ketepatan risiko tinggi 47% (29× acak); 8 dari 8 faskes di 20% teratas adalah faskes curang. Pembanding wilayah menandai satu kelompok: RS penambah kode khusus (7,4% vs 1,4% faskes sekelas di provinsinya). Data sintetis berpola jelas; bukan kinerja pada data JKN.
