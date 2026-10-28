# Kompatibilitas Panduan Data Sample BPJS

**Status:** tinjauan dokumentasi dari panduan-data-sample-bpjs.pdf. Tidak ada file dataset BPJS yang dibuka/diproses. Ini bukan validasi file aktual, persetujuan BPJS, atau bukti semua kolom hadir/terisi pada semua observasi.

## 1. Metode dan batas sumber

Panduan asli 31 halaman diekstrak secara lokal dengan tata letak. Tabel FKRTL halaman 19–25 dan tabel diagnosis sekunder halaman 31 dapat diekstrak dengan mode table. Halaman 7 menjelaskan hubungan dataset, tetapi tata letak relasinya padat; join operasional perlu konfirmasi terhadap spesifikasi file resmi. proposal-page14.png tidak ditemukan di lokasi referensi atau repository; angka proposal halaman 14 berasal dari transkripsi visual pengguna.

**Format sumber dan pertukaran (dipisahkan menurut bukti):** AGENTS.md menyatakan file BPJS `.dta` berada di luar repository; panduan yang ditinjau mendefinisikan kamus dan relasi, tetapi ekstraksi yang diperiksa tidak menetapkan format seluruh file sampel. Karena itu `.dta` adalah format file sumber yang disebut instruksi proyek, bukan hasil inspeksi dataset. CSV dapat dipilih sebagai format pertukaran fixture sintetis yang portabel, tetapi generator saat ini mengembalikan objek Python dan tidak menyediakan importer/exporter CSV. CSV adalah rekomendasi format pertukaran sintetis, bukan kemampuan implementasi atau format yang dinyatakan panduan BPJS.

Dalam tabel berikut, **Fakta panduan** berarti teks kamus; **Implementasi** berarti source canonical saat ini; **Gap/rekomendasi** berarti pemetaan belum disahkan.

## 2. Field yang diminta

| Field | Fakta dari panduan | Implikasi dan status |
|---|---|---|
| PSTV01 | Nomor peserta; nomor identifikasi unik yang dideidentifikasi untuk melindungi identitas sebenarnya (hlm. 19). Dataset FKRTL juga memuatnya (hlm. 7). | Identifier peserta pseudonim, bukan facility ID. Jangan tampilkan atau log. Untuk repeat billing, hanya boleh dipakai sebagai kunci pembatas internal “peserta sama” bila diizinkan; jangan jadikan bagian signature layanan generik untuk membandingkan pola lintas peserta. Re-tokenisasi per batch hanya bila diizinkan dan kunci/retensinya disetujui. |
| FKL02 | ID Kunjungan FKRTL; nomor identifikasi unik setiap kunjungan FKRTL oleh peserta (hlm. 19). Pada dataset diagnosis sekunder FKL02 juga ID kunjungan FKRTL (hlm. 31). | Kandidat kunci kunjungan/join sekunder, bukan participant ID atau facility ID. Uniqueness/null/duplikasi/cardinality harus diprofilkan pada batch yang berizin. |
| FKL03 | Tanggal datang kunjungan FKRTL; tanggal melakukan kunjungan (hlm. 19). | Tanggal, bukan jam/menit. Dapat mendukung aturan date-level dengan validasi. |
| FKL04 | Tanggal pulang kunjungan FKRTL; tanggal menyelesaikan kunjungan (hlm. 19). | Tanggal pulang, bukan timestamp atau durasi presisi. |
| FKL05 | Provinsi FKRTL; provinsi fasilitas tempat layanan diakses (hlm. 19). | Lokasi administratif, bukan fasilitas unik. |
| FKL05_NEW | Tidak tercantum dalam kamus FKRTL halaman 19–25 yang ditinjau. | Spesifikasi lama dan script historis mengasumsikan nama ini. Jangan otomatis memetakan ke FKL05 tanpa konfirmasi versi sumber/mapping resmi. |
| FKL06 | Kabupaten/Kota FKRTL (hlm. 19). | Lokasi administratif, bukan fasilitas unik. |
| FKL07 | Kepemilikan FKRTL (hlm. 20). | Kategori kepemilikan; bukan ID tunggal. |
| FKL08 | Jenis FKRTL (hlm. 20). | Kategori jenis; bukan facility key. |
| FKL09 | Tipe FKRTL (hlm. 20). | Kategori tipe; bukan facility key. |
| FKL16 | Kode ICD-10 diagnosis masuk FKRTL (hlm. 21). Nama field menyebut 3–6 digit, sedangkan keterangan menjelaskan variasi 3–5 digit. | Ketidaksesuaian internal rentang digit; jangan validasi berdasarkan panjang asumsi sebelum diklarifikasi. |
| FKL18 | Kode ICD-10 diagnosis primer FKRTL; diagnosis primer diterangkan sebagai pilihan dokter pada hari terakhir perawatan berdasarkan penggunaan sumber daya/hari rawat paling lama (hlm. 21). Nama field menyebut 3–6 digit. | Semantik diagnosis dicatat; format/rentang dan kelayakan waktu untuk prediksi pra-verifikasi harus dikonfirmasi. |
| FKL19 | Kode INA-CBGs; uraian menyebut digit CMG, tipe kelompok, spesifikasi, dan tingkat keparahan (hlm. 21). | Kelompok klaim, bukan ID kasus/fasilitas. |
| FKL13 | Kelas rawat peserta: "Kelas rawat saat peserta mengakses pelayanan kesehatan di FKRTL" (hlm. 20). | Dibaca sebagai kode numerik (berlabel nilai) ke field kanonis `care_class`; hanya dipakai sebagai kunci kelompok pembanding penyaringan durasi. Minggu 2024-03-04..10: tidak ada nilai kosong, 3 kelas. |
| FKL31 / FKL32 | Tarif regional INA-CBGs (5 regional) / Group tarif INA-CBGs (hlm. 23). | Dipetakan ke `tariff_region` / `tariff_group` (mapping v2) sebagai konteks; belum dipakai detektor. |
| FKL18A | Nama diagnosis primer (teks). | Tidak dibaca: kode FKL18 sudah cukup; teks bebas tidak diperlukan. |
| FKL30 | Jenis prosedur dalam pelayanan FKRTL (hlm. 23): "Jenis prosedur yang dilakukan pada pelayanan FKRTL". Panduan tidak mendefinisikan arti nilai kosong. | Profil agregat sampel 202403: 41,7% baris berisi string kosong (bukan null); kosong hampir tidak pernah muncul pada kelompok kasus INA-CBG digit 1–3 dan sering pada digit 4 (24%) dan 5 (71%). Konsisten dengan "tidak ada prosedur tercatat", tetapi **tidak terverifikasi**: arti digit kelompok kasus tidak dijabarkan panduan dan digit 5 masih 29% berisi prosedur. Implementasi: kosong = tidak tersedia; record tidak dinilai oleh pemeriksaan repeat. Perlu konfirmasi pemilik data. |
| FKL47 | Biaya tagih oleh fasilitas kesehatan (provider) untuk setiap ID kunjungan (hlm. 25). Teks penjelasan yang sama menuliskan formula komponen yang memasukkan FKL47 itu sendiri. | Makna label menunjukkan nilai tagih provider, tetapi formula yang tercetak tampak sirkular. Jangan menganggap formula komponen sebagai terverifikasi; konfirmasi rumus, satuan, tipe nilai, dan ketersediaan pra-verifikasi sebelum mapping produksi. FKL47 bukan label fraud. |
| FKL48 | Biaya verifikasi BPJS Kesehatan setelah dilakukan verifikasi; biaya yang diverifikasi BPJS untuk setiap ID kunjungan (hlm. 25). | Nilai pascaverifikasi: jangan gunakan sebagai prediktor pra-verifikasi, label fraud, atau proksi evaluasi. Jangan petakan ke canonical `billed_amount`. |
| FKL24 | File FKRTL Diagnosis Sekunder: kode diagnosis ICD-10 3–5 digit; FKL24A dan FKL24B disebut sebagai kode/nama diagnosis 3 digit (hlm. 31). | Add-on; join melalui FKL02 hanya setelah relasi/cardinality dikonfirmasi. Tidak wajib untuk FKRTL utama. |

## 3. Kesimpulan identitas dan prasyarat

- **Unique facility ID:** tidak terbukti di halaman panduan yang ditinjau. FKL05/06 adalah provinsi/kabupaten-kota; FKL07–09 adalah kategori. Kombinasi kategori/lokasi tidak boleh dijadikan identitas unik.
- **Tanggal vs waktu:** FKL03 dan FKL04 adalah tanggal datang/pulang. Tidak ada waktu jam/menit di kamus FKRTL yang ditinjau.
- **Kapasitas:** tenaga, alat, jam operasional, atau kapasitas per jenis layanan tidak tercantum pada kamus FKRTL yang ditinjau.
- **Evidence:** inventaris rekam medis/penunjang atau status bukti tercatat/tidak tercatat tidak ditetapkan oleh field yang ditinjau.
- **Nilai tagih:** label FKL47 adalah biaya tagih provider dan FKL48 adalah biaya verifikasi setelah verifikasi (hlm. 25). Rumus komponen yang dicetak pada penjelasan FKL47 tampak sirkular karena menyebut FKL47 sebagai salah satu komponennya; rumus, satuan, tipe, dan ketersediaan nilai pra-verifikasi harus dikonfirmasi sebelum mapping. FKL48 tetap dikecualikan dari prediksi pra-verifikasi.
- **Diagnosis sekunder:** ada tabel terpisah, tetapi bukan bukti semua batch memiliki dataset itu atau relasi satu-ke-satu dengan kunjungan.
- **FKTP Non Kapitasi:** memiliki ID kunjungan sendiri `PNK02` dan tanggal kunjungan `PNK03` (hlm. 27). Belum ada kunci lintas dataset tervalidasi antara `PNK02` dan `FKL02`; relasi terdokumentasi hanya lewat peserta. Dataset ini tidak diproses RC dan tidak di-join.
- **Izin:** akses portal data sampel tidak dengan sendirinya mengizinkan setiap tujuan pemrosesan per kasus atau demonstrasi publik keluaran turunan data nyata; keduanya tetap memerlukan izin resmi.

## 4. Profil import yang direkomendasikan (belum diimplementasikan)

Backend canonical record menggunakan case_id, participant_token, service_date, location/facility categories, diagnosis, claim_group, procedure_code, billed_amount, serta field timestamp/capacity/evidence tambahan untuk checker tertentu. Adapter runtime synthetic.py berisi 12 record artifisial tanpa facility metadata/capacity/evidence/timestamp. Generator benchmark v3/v4 menambah metadata sintetis dan tidak dipanggil otomatis API runtime.

| Tingkat profil | Field/metadata | Aturan rekomendasi |
|---|---|---|
| Batch envelope wajib | batch ID, profil sumber, dataset role (FKRTL/secondary), periode, versi mapping, otorisasi dicatat, actor terautentikasi, digest akses terbatas, waktu. | Path lokal/row tidak masuk log. Digest berakses terbatas. |
| Gate schema FKRTL minimum | FKL02 visit key, FKL03 arrival date, nama map, parsing tanggal, agregat null/key/duplikasi. | Rekomendasi pengenalan dan profiling, bukan klaim seluruh row valid. |
| Konteks opsional | PSTV01, FKL04–FKL19, FKL30 dan field lain yang disahkan. | Jalankan checker hanya bila semua prasyaratnya lulus. Token peserta tidak dikembalikan. |
| Nilai klaim | FKL47 adalah biaya tagih provider; rumus tertulisnya perlu klarifikasi. FKL48 adalah biaya verifikasi pascaverifikasi (hlm. 25). | Jangan map amount untuk priority sebelum rumus/satuan/tipe FKL47 dikonfirmasi. FKL48 tidak digunakan sebagai predictor atau nilai klaim pra-verifikasi. |
| Dataset sekunder opsional | FKL02, FKL24, FKL24A, FKL24B. | Validasi join, one-to-many, duplicates, panjang dan semantik dengan pemilik data. |
| Demo sintetis lengkap saja | facility_id, tenaga/kapasitas, timestamp layanan, service units/type, evidence inventory/status. | Jangan wajibkan untuk profil sample BPJS tanpa bukti resmi field tersedia. |

Importer membedakan field hadir, dipetakan, lolos validasi, dipakai checker, dan tidak dapat digunakan. Kehadiran kolom saja bukan coverage.

## 5. Dukungan pemeriksa menurut profil

Ini adalah rancangan capability dari source guide; **belum ada detector yang dijalankan pada data BPJS**.

| Detector | Field prasyarat aktual | Bila field tidak tersedia | Demo Sintetis Lengkap | BPJS FKRTL Sample-Compatible | Keluaran aman dan batas klaim |
|---|---|---|---|---|---|
| Capacity | `case_id`, `facility_id`, `service_type`, `service_date`, `service_units`; metadata facility dengan `facility_id`, `daily_capacity_units`. | Jika facility key/kapasitas hilang, invalid, atau ambigu: tidak dapat dinilai/tidak berlaku untuk profil; jangan menghasilkan volume berisiko atau nol palsu. | Didukung pada benchmark dengan metadata artifisial. Adapter runtime 12 record tanpa metadata fasilitas: tidak dapat membentuk prioritas fasilitas. | **Tidak dapat dinilai** dari kamus: facility ID unik, unit layanan, kapasitas/staf/peralatan tidak terbukti. | Candidate group dengan unit teramati, kapasitas pembanding, periode dan alasan. Parameter bukan standar klinis dan bukan bukti phantom billing. |
| Repeat billing exact | Semua `SIGNATURE_FIELDS`: token peserta, tanggal, provinsi/kabupaten, kategori kepemilikan/jenis/kelas fasilitas, diagnosis masuk/primer, claim group, prosedur, dan billed amount; plus case ID aplikasi. | Field signature kosong/tidak valid membuat klaim ineligible pada checker; laporkan tidak dapat dinilai, bukan negatif. | Didukung sintetis. | **Conditional** setelah mapping dan kelayakan penggunaan disahkan. Kamus mendokumentasikan PSTV01, FKL02, FKL03, FKL05–09, FKL16/18/19, FKL30, FKL47; formula FKL47 perlu klarifikasi. FKL05_NEW tidak ditemukan, tetapi bukan prasyarat jika mapping resmi memakai FKL05. | Grup exact-match, jumlah record, atribut nama yang cocok; token/signature tidak ditampilkan. Kunjungan berulang sah dapat cocok; bukan bukti billing ganda/fraud. |
| Similar claim pattern exact | Tanggal, lokasi/kategori fasilitas, diagnosis masuk/primer, claim group, billed amount, prosedur opsional; token peserta hanya untuk memastikan peserta berbeda, bukan signature. | Atribut dasar atau token peserta invalid membuat record ineligible; tidak ada kecocokan bukan negatif untuk record ineligible. | Didukung sintetis. | **Conditional** setelah mapping approved; basis diagnosis/procedure/kategori ada dalam kamus, tetapi billed amount FKL47 dan mapping canonical perlu disahkan. FKL05_NEW bukan field wajib bila FKL05 yang authoritative dipetakan. | Grup pola exact lintas token berbeda; jelaskan atribut/mode; bukan bukti fasilitas sama atau cloning. |
| Near-duplicate | Field pola tanggal, kode wilayah/kategori, diagnosis, claim group, procedure, amount; token peserta untuk syarat beda peserta saja. Blocking butuh tuple blok lengkap; default min 9 atribut, similarity ≥0,8, batas 5.000 pasangan/500 kandidat. | Input tanpa tuple blocking tidak memberi jaminan pencarian; token hilang tidak eligible; cap tercapai = partial/truncated dan klaim yang tidak ditemukan tidak boleh disebut negatif. | Didukung sintetis dengan blocking deterministik dan cap. | **Conditional/parsial hanya setelah mapping fitur**; waktu/tanggal dan beberapa diagnosis/procedure/kategori dokumenter, namun amount FKL47 perlu diklarifikasi. Tanpa itu jangan mengklaim coverage detector ini. | Pasangan kandidat berisi nama atribut cocok/berbeda dan rasio kemiripan, tanpa signature. Bukan bukti cloning/fraud; pencarian terbatas dan pola umum bisa cocok sah. |
| Temporal | Tanggal, token peserta, `facility_id`, `service_type`; `service_timestamp` tambahan untuk pola menit seragam. | Tanggal invalid tidak eligible. Tanpa timestamp, pola menit berstatus unassessed; tanpa facility key/service type, pola yang bergantung pada keduanya tidak dapat dinilai. Tanggal saja tidak cukup untuk uniform-time. | Repeat window dan uniform-minute didukung pada benchmark timestamp/facility sintetis; adapter API lebih terbatas. | **Belum dapat dinilai oleh implementasi saat ini** karena kamus tidak membuktikan facility ID unik/service type canonical; tanggal FKL03/04 ada, jam/menit tidak. Jangan klaim pola menit atau menganggap FKL02 sebagai facility key. | Pola rentang hari atau menit dengan hitungan dan periode; layanan terjadwal/episode berulang dapat sah. Tidak semua tanggal sibuk menjadi sinyal. |
| Evidence completeness | `service_type`, expected evidence, present evidence, boolean presence, recording status dan aturan layanan. | Inventory `not_recorded` → unassessed; field/list tidak valid → ineligible; hanya inventory tercatat dan konsisten dapat dinilai. | Didukung untuk aturan fixture sintetis. | **Tidak dapat dinilai**: inventory bukti dan recording status tidak terbukti dalam kamus FKRTL. Kolom tidak ada bukan bukti evidence tidak ada. | Sebut item yang tidak tercantum terhadap aturan sintetis serta status pencatatan; bukan bukti layanan tidak dilakukan atau fraud. |

Untuk semua detector: jika satu field prasyarat tidak tersedia pada tingkat profil, importer masa depan harus menandai checker `not_applicable`/unsupported untuk profil tersebut; kegagalan teknis adalah `unavailable`; record yang seharusnya tercakup tetapi datanya invalid/tidak lengkap adalah `unassessed`; pencarian yang mencapai batas adalah `partial`/truncated. `not_triggered` hanya sah untuk klaim yang benar-benar eligible dan diperiksa. Risk score memakai indikator yang dapat dinilai saja; `null` bila tidak ada denominator penilaian. Prioritas fasilitas hanya boleh dihitung bila ID fasilitas valid, amount pra-verifikasi valid dan unik per klaim, serta usaha audit positif tersedia. Jika facility ID tidak tersedia, tampilkan kandidat kunjungan dalam daftar tanpa ranking fasilitas.

Risk score mungkin dihitung hanya jika indikator dapat dinilai; null bukan zero-risk. Facility priority memerlukan facility ID sah, mapping nilai, asumsi effort, dan coverage. Jangan mengurutkan faskes berdasarkan kode wilayah/jenis/kelas.

## 6. Ketidakpastian dan konfirmasi resmi

1. **BPJS:** rumus komponen, satuan, tipe data, nullability, dan waktu ketersediaan FKL47. Labelnya adalah biaya tagih provider, tetapi formula teks hlm. 25 tampak sirkular. Jangan memakai nama yang diasumsikan script.
2. **BPJS:** apakah FKL05_NEW ada pada versi data mendatang; guide menulis FKL05 sebagai provinsi.
3. **BPJS:** hubungan dan cardinality FKL02 antara FKRTL dan diagnosis sekunder.
4. **BPJS:** stabilitas PSTV01 lintas file/periode, tokenisasi, tujuan akses, dan retensi.
5. **Ahli domain:** definisi repeat, similarity/cloning, kapasitas/tenaga, temporal, dan bukti yang lazim per layanan.
6. **Pemilik data/security/privacy:** otorisasi, tujuan, lokasi simpan, akses, audit, retensi, penghapusan.

## 7. Sumber

## 8. Status implementasi adapter lokal

Adapter mapping `bpjs-fkrtl-sample-map-v2` (v2: kolom wajib PSTV01/FKL02/FKL03, kolom lain opsional dan dilaporkan bila hilang; FKL31/FKL32 sebagai konteks; FKL47 hanya sebagai `provider_billed_amount_unverified` untuk subset rekonsiliasi; tanggal di luar 2000–2099 dan nominal negatif/tidak valid menjadi tidak diketahui) tersedia di `backend/app/data_sources/bpjs_fkrtl_adapter.py`; reader chunk `.dta` terpisah di `backend/scripts/fkrtl_dta_reader.py` agar package aplikasi dan health path tidak mengimpor pandas. Tes memakai fixture buatan. Reader tidak aktif pada API/runtime, tidak mengasumsikan `FKL05_NEW`, tidak memilih FKL47/48, dan tidak membentuk facility ID. `PSTV01` dan `FKL02` di-HMAC bersama menjadi case reference stabil (karena ID kunjungan didefinisikan per peserta) menggunakan key lokal yang dipasok caller; ID mentah tidak menjadi record keluaran. Token peserta internal juga di-HMAC dengan konteks terpisah. `PSTV01` hanya digunakan untuk pembatas peserta sama/berbeda dan pseudonimisasi tersebut, bukan sebagai atribut kemiripan lintas peserta. Kehadiran adapter bukan persetujuan penggunaan data.

Signature eksploratif berversi dijelaskan di `docs/analytics-spec.md`. Angka dari populasi/definisi berbeda tidak dapat dibandingkan sebagai rekonsiliasi sampai keduanya dijalankan pada populasi eligible yang sama dengan unit hitung seragam. Tidak ada pemrosesan dataset aktual yang dilakukan dalam tahap ini.

- panduan-data-sample-bpjs.pdf: hlm. 6–7 dataset/relasi; 18–25 FKRTL; 30–31 diagnosis sekunder. Tabel penting diekstrak dalam mode table. Format `.dta` dirujuk terpisah oleh AGENTS.md, bukan dipastikan dari kamus/isi dataset.
- proposal-healthkathon.pdf: hlm. 11–12 data sintetis, checker, dan batasan; 17–19 izin, modularitas, privasi, validasi.
- Repository: backend/app/analytics/{repeat_billing,similar_claim_pattern,near_duplicate_claims,capacity,temporal_patterns,evidence_completeness,normalization,risk_scoring,audit_priority}.py; backend/app/data_sources/{synthetic,synthetic_generator,synthetic_benchmark_generator}.py; docs/analytics-spec.md.

## 9. Local reader/provider contract (fixture-tested; not enabled in API)

The canonical feature-provider interface is `app.data_sources.providers.FeatureSourceProvider`, returning records, facility metadata, and source metadata. `SyntheticDemoProvider` remains the default for legacy analytics calls; `SyntheticBatchProvider` is the provider used by persistent synthetic-batch runs. `build_analytics_snapshot_from_provider()` coordinates a caller-selected provider with the existing six-detector/scoring/priority service. API parameters do not select providers.

`scripts.fkrtl_dta_provider.LocalFkrtlDtaProvider` is an explicit local-only bridge from the versioned mapping to that service. Its constructor requires an explicit source classification (`synthetic_fixture` or `bpjs_sample`), input path, and caller-provided local pseudonym key. It is not registered in routes, is not connected to DataBatch/AnalysisRun persistence, and does not make BPJS processing authorized. Tests use only generated synthetic `.dta` files and classify them `synthetic_fixture`. If later enabled for an authorized sample, metadata includes `bpjs_sample`, mapping/profile version, aggregate mapping coverage, and limitations; private paths are not included.

The chunk reader in `backend/scripts/fkrtl_dta_reader.py` checks duplicate case references across chunks using a temporary SQLite scratch table containing only SHA-256 digests of the already-HMAC-pseudonymized case references. Raw participant/visit values and the HMAC secret are not written to scratch storage. The scratch directory is removed on complete iteration and exceptions; callers that stop early must close the iterator. Each current chunk is still held in memory. The local provider currently accumulates all mapped rows because the coordinated detectors require a population; target-scale provider memory is not established by the reader benchmark below.

### Synthetic-only verification

- `python -m pytest tests/test_fkrtl_signatures_and_adapter.py -q`: 17 passed in the verified run. Tests cover within/across-chunk duplicates, stable references across chunk sizes, invalid required references, scratch cleanup, output minimization, and provider-to-analytics execution. All `.dta` values are generated fixtures.
- `python -m scripts.benchmark_fkrtl_reader_synthetic --rows 25000 --chunk-size 2000`: read 25,000 synthetic rows in 4.987 seconds; `.dta` fixture 4,527,703 bytes; `tracemalloc` peak 10,782,460 bytes. This is Python-traced allocation peak and excludes some native pandas/NumPy allocations; it is not process RSS and does not establish full-detector/provider memory at 120,000 rows.
- `python -m scripts.fkrtl_signature_sensitivity`: same four-row synthetic population per definition. Baseline group aggregates: `repeat_service_v1` 1 group / 3 rows / 2 excess; same-amount 1 / 3 / 2; legacy signature 1 / 3 / 2; cross-participant exact 1 / 4 / 3. Changing one FKL04 reduces legacy repeated rows to 2 while repeat-service remains 3. Changing FKL47 leaves repeat-service at 3 and reduces same-amount rows to 2. Normalized date/text variants retain the baseline counts; one missing required diagnosis yields one ineligible row. These synthetic observations do not reconcile earlier 20-versus-81 counts, which remain unresolved until identical eligible real-data populations are authorized and compared.

No actual BPJS data was opened or processed. `FKL47` remains excluded from the canonical feature map and amount-based signatures remain blocked by default. Facility priority, capacity, and evidence checks remain unavailable without their verified prerequisites.

### Orchestrator dan benchmark pipeline penuh (sintetis)

`app.data_sources.providers.CANONICAL_FEATURE_CONTRACT_VERSION` menetapkan `canonical-analytic-features-v1`: `case_id` aplikasi wajib; token peserta pseudonim hanya internal; nama fitur yang diizinkan ialah `participant_token`, `service_date`, `discharge_date`, `service_timestamp`, `facility_id`, `service_type`, `service_units`, `facility_daily_capacity`, `facility_daily_claim_count`, `billed_amount`, `province_code`, `municipality_code`, `facility_ownership`, `facility_type`, `facility_class`, `admission_diagnosis`, `primary_diagnosis`, `claim_group`, `procedure_code`, `supporting_evidence_required`, `supporting_evidence_types`, `supporting_evidence_present`, dan `supporting_evidence_recording_status`. Prasyarat selain `case_id` opsional bagi profil yang tidak menyediakannya. `claim_id` batch diterima sebagai metadata input lalu dihilangkan dari fitur. Field sumber mentah dan label ground truth ditolak. Field yang hilang diproyeksikan sebagai `None`, agar detektor menyatakan tidak berlaku/tidak dinilai sesuai prasyarat, bukan menganggap negatif. Provider `.dta` mengeluarkan canonical shape; `run_provider_analysis()` menjalankan pipeline yang sama dan memberi metadata source, mapping, coverage, signal/reason, score type, priority, action policy, dan limitations. Provider ini tetap tidak terhubung ke route atau penyimpanan AnalysisRun.

Benchmark penuh menghasilkan `.dta` sintetis di temporary directory, memanggil reader, provider, enam detektor, scoring, audit priority, dan action policy. Semua temp file dibersihkan setelah run sukses. Pengukuran final dengan chunk 2.000:

| Klaim sintetis | Waktu pipeline | Peak Python allocation (`tracemalloc`) | Baseline RSS | Peak RSS sampled | Seluruh signal | Skor tidak dapat dinilai | Near-duplicate |
|---:|---:|---:|---:|---:|---:|---:|---|
| 25.000 | 22,874 s | 193.962.832 byte | 67.072.000 byte | 439.345.152 byte | 2.718 | 22.282 | 2.718 kandidat; truncated |
| 120.000 | 102,865 s | 863.524.873 byte | 68.354.048 byte | 1.737.408.512 byte | 0 | 120.000 | 0 kandidat; truncated |

RSS diambil dari working set proses dengan sampler 20 ms, sehingga peak singkat dapat terlewat. `tracemalloc` tidak mencakup sebagian alokasi native pandas/NumPy. Angka ini hanya benchmark fixture, bukan jaminan kinerja untuk input lain. Adapter tidak memiliki amount/facility/capacity/evidence/timestamp yang diperlukan; karena itu 120.000 skor null berarti tidak dapat dinilai, bukan tanpa risiko. Lima indikator berstatus partial dan satu not_applicable pada kedua ukuran.

Perbedaan 2.718 kandidat pada 25.000 dan nol kandidat pada 120.000 terjadi sementara `search_truncated=true` pada kedua ukuran. Pada data lebih besar, block melewati batas dan pencarian beralih ke perbandingan chain deterministik; pasangan yang dibandingkan dapat berbeda sehingga tidak ada kandidat pada fixture 120.000. Ini bukti bahwa cakupan dan hasil near-duplicate bergantung pada batas/blocking, bukan bukti pola tidak ada. Batas pencarian tidak dilonggarkan dalam benchmark. Evaluasi lebih lanjut perlu mengukur strategi blocking pada distribusi yang beragam sebelum hasil tersebut dipakai untuk audit.

Pipeline AnalysisRun persisten sekarang juga melewati provider batch dan validasi canonical yang sama, tetapi DataBatch/AnalysisRun tetap dibatasi `synthetic_csv`. Mengaktifkan sumber lokal `.dta` ke run tersimpan membutuhkan desain eksplisit untuk source type, batch identity/checksum, penyimpanan hasil dan retensi key pseudonim; belum dilakukan.
