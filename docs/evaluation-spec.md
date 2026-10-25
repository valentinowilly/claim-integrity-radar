# Spesifikasi Evaluasi Sintetis

## Batas evaluasi dan reproducibility

Evaluator ada di `backend/app/analytics/evaluation.py`; CLI sintetis ada di `backend/app/analytics/evaluate_synthetic.py`. Eksperimen ML terpisah berada di `backend/scripts/benchmark_ml.py` dan dijalankan dengan `python -m scripts.benchmark_ml` dari direktori `backend`; ia bukan modul aplikasi/API. Sweep PowerShell memakai root repository relatif terhadap lokasi script. Evaluasi hanya menerima generator sintetis. Versi generator, seed, ukuran dataset, dan tingkat injeksi masuk metadata laporan. Evaluator memisahkan label dari fitur.

Urutan pemrosesan adalah:

1. Jalankan keenam detektor hanya dengan `records` fitur; kapasitas juga menerima metadata fasilitas sintetis.
2. Berikan hasil detektor dan fitur kepada risk scoring, kemudian ke audit priority.
3. Baru setelah pipeline tersebut selesai, evaluator membaca `ground_truth.claim_labels` untuk metrik klaim dan fasilitas.

Tidak ada ID klaim, fasilitas, peserta, record individual, atau label baris dalam laporan. Laporan JSON agregat ditulis di `outputs/synthetic_evaluations/`, yang diabaikan Git. Pengukuran memori menggunakan `tracemalloc` dan tidak mewakili seluruh RSS proses atau alokasi native.

## Pemetaan skenario ke pemeriksa

| Skenario label generator v3 | Pemeriksa yang dirancang untuk sinyal terkait | Catatan interpretasi |
|---|---|---|
| `phantom_physiotherapy` | Kelengkapan bukti | Pemeriksa menguji inventaris bukti sintetis; hasil tidak membuktikan layanan tidak diberikan. |
| `cloning` | Near-duplicate; pola temporal | Cloning menyertakan variasi atribut terkontrol sehingga exact-match tidak diharapkan menemukan semua kelompok. Pola menit yang sama dapat memicu temporal. |
| `repeat_billing` | Repeat billing; pola temporal | Signature berulang adalah sinyal, bukan kesimpulan tagihan ganda. |
| `action_without_support` | Kelengkapan bukti | Aturan bukti hanya stipulasi simulasi. |
| `mixed_light_severe` | Kapasitas; near-duplicate; pola temporal; kelengkapan bukti; exact-pattern untuk anggota yang cocok | Campuran sengaja menggabungkan beberapa sinyal; tidak semua klaim harus terpicu semua pemeriksa. |
| `legitimate_repeat_control` (label kelompok negatif) | Repeat billing dapat memicu kandidat | Kontrol ini tetap negatif pada label klaim. Sinyal repeat dapat menjadi false positive terhadap stipulasi kontrol. |

Pemetaan ini menyatakan tujuan desain skenario, bukan jaminan deteksi. Setiap pemeriksa juga dievaluasi terhadap seluruh label anomali sebagai konteks, tetapi sensitivitas terhadap skenario yang bukan target tidak menjadi sasaran keberhasilan.

## Definisi metrik klaim

Unit deteksi adalah `case_id` sintetis. Untuk setiap pemeriksa dan gabungan:

- `TP`, `FP`, `TN`, dan `FN` dihitung hanya pada klaim yang status prediksi/penilaiannya dapat diketahui.
- Precision = TP / (TP + FP); recall = TP / (TP + FN); F1 adalah harmonic mean; false-positive rate = FP / (FP + TN).
- Rasio yang pembaginya nol bernilai `null`. Jika precision dan recall keduanya terdefinisi dan bernilai 0, F1 bernilai 0.
- `unassessed_positive_label_count` dan `unassessed_negative_label_count` melaporkan label yang dikeluarkan dari confusion matrix. Klaim tanpa sinyal tidak otomatis menjadi TN jika pemeriksaan terpotong/tidak tersedia.
- Metrik per skenario memakai label skenario itu sebagai kelas positif dan semua klaim lain sebagai kelas negatif, dengan aturan cakupan yang sama.
- Untuk gabungan, klaim diprediksi positif bila setidaknya satu indikator berkontribusi pada skor. Klaim tanpa pemicu hanya dapat dihitung negatif jika scoring menyatakan pemeriksaan lengkap untuk klaim tersebut.

Detektor dengan `search_truncated`, kelompok kandidat dengan anggota terpotong, atau status tidak tersedia dilaporkan dengan cakupan. Pada pencarian terpotong, kandidat yang benar-benar dikembalikan tetap dapat dihitung sebagai positif teramati; klaim lain yang tidak dapat dipastikan dikeluarkan dari metrik dan tidak disebut negatif.

## Definisi ranking fasilitas

Label positif fasilitas berarti fasilitas sintetis tersebut memiliki sekurangnya satu klaim berlabel anomali sintetis. Ketiga metode memilih jumlah fasilitas yang sama, `K = ceil(facility_count × audit_budget_fraction)`, minimal satu dan dibatasi jumlah fasilitas:

1. **Baseline acak:** urutan fasilitas diacak untuk setiap seed yang tercantum; laporan berisi rerata dan simpangan baku precision@K serta rerata recall@K/lift.
2. **Aturan sederhana:** hitung klaim unik pada fasilitas yang memiliki setidaknya satu pemicu detektor, urut menurun, lalu ID sintetis sebagai tie-break.
3. **Claim Integrity Radar:** ikuti urutan antrean audit priority yang tersedia. Fasilitas tanpa item antrean ditempatkan sesudah item antrean dengan urutan ID sintetis.

Precision@K = fasilitas positif dalam K / K. Recall@K = fasilitas positif dalam K / seluruh fasilitas positif. Lift terhadap baseline acak = precision@K metode / rerata precision@K acak. Jika denominator tidak tersedia, hasil `null`. Lift terhadap prevalensi fasilitas juga disediakan sebagai pembanding deskriptif. Ini eksperimen pada label buatan dan bukan bukti manfaat operasional.

## Menjalankan

Dari `backend/`:

```powershell
.venv\Scripts\python -m app.analytics.evaluate_synthetic --claims 250 --facilities 12 --seed 2026 --random-seeds 30
```

Perintah skala proposal:

```powershell
.venv\Scripts\python -m app.analytics.evaluate_synthetic --claims 120000 --facilities 200 --seed 2026 --random-seeds 30
```

Kedua perintah hanya memakai generator sintetis, menjalankan detektor aplikasi, dan menyimpan agregat. Tidak menjalankan lima skrip analisis lama. File JSON default ditulis ke `../outputs/synthetic_evaluations/`; opsi `--output` dapat menentukan lokasi lain.

## Protokol Stage 16: populasi metrik per detektor

Metrik individual tidak lagi membandingkan setiap pemeriksa dengan semua label anomali. `SUPPORTED_SCENARIOS` pada evaluator menjadi pemetaan eksplisit dan diuji:

| Detektor | Skenario positif yang berlaku | Perlakuan skenario anomali lain |
|---|---|---|
| Repeat billing exact | `repeat_billing` | Tidak berlaku untuk metrik detektor ini |
| Similar claim pattern exact | `mixed_light_severe` | Tidak berlaku; variasi cloning bukan target exact match |
| Near-duplicate | `cloning`, `mixed_light_severe` | Tidak berlaku |
| Capacity | `mixed_light_severe` | Tidak berlaku |
| Temporal patterns | `repeat_billing`, `cloning`, `mixed_light_severe` | Tidak berlaku |
| Evidence completeness | `phantom_physiotherapy`, `action_without_support`, `mixed_light_severe` | Tidak berlaku |

Untuk setiap pemeriksa, populasi berlaku adalah klaim positif dari skenario target ditambah klaim tanpa injeksi skenario (termasuk kontrol repeat sah). Klaim anomali di skenario lain dilaporkan `not_applicable_anomaly_count`, dan bukan negatif. Label kontrol `legitimate_repeat_control` dianggap klaim normal dalam populasi detektor yang sesuai. Kelompok kontrol boleh memicu repeat detector dan karenanya dapat menjadi FP menurut label simulasi.

TP/FP/TN/FN dihitung hanya pada item applicable dan eligible. Klaim yang tidak memenuhi syarat, yang hasil pemeriksanya tidak tersedia, atau yang tertutup oleh batas pencarian tidak masuk confusion matrix dan dihitung sebagai `unassessed`; tidak adanya kandidat dari pencarian terpotong bukan TN. Cakupan `eligible_count / applicable_count` dan unassessed positif/negatif dilaporkan. Tanpa denominator metrik yang sah, nilai metrik berupa JSON `null`. Precision tanpa prediksi adalah null; recall tanpa positif ground truth eligible adalah null; F1 null bila precision atau recall null; FPR null bila tidak ada negatif eligible. Bila precision dan recall terdefinisi tetapi keduanya nol, F1 adalah 0.

Evaluasi gabungan memakai semua label anomali sintetis versus klaim tanpa injeksi skenario pada ruang yang memenuhi syarat dari pipeline scoring. Ini bukan metrik tiap detektor. Label ground truth tidak diteruskan ke detektor, scoring, ataupun ranking; evaluator menolak label pada record fitur dan membaca ground truth setelah hasil pipeline tersedia.

## Ranking fasilitas dengan benchmark v4

Generator benchmark terpisah versi 4 memakai profil `facility-stratified-sparse-positive-v1`: secara default 20% fasilitas positif dipilih reproducibly berdasarkan seed dan strata tipe fasilitas; kelompok anomali ditempatkan sebagai kejadian pada fasilitas positif; fasilitas lainnya adalah kontrol negatif. Klaim per fasilitas diseimbangkan agar selisih jumlah total maksimal satu. Kontrol `legitimate_repeat_control` ditempatkan pada fasilitas negatif. Label fasilitas dihitung dari label klaim dan divalidasi konsistensinya.

Ranking mengukur fasilitas dengan setidaknya satu klaim berlabel anomali. Pada setiap K sama, evaluator membandingkan random baseline beberapa seed, aturan jumlah klaim unik yang mendapat sinyal, serta urutan antrean prioritas yang ada. Random baseline melaporkan mean/std precision dan mean recall; lift terhadap rata-rata random hanya diberikan bila mean random precision bukan nol. Lift terhadap prevalensi fasilitas juga dilaporkan bila denominator valid. Pilihan K adalah `ceil(N * fraction)` dengan batas minimal satu dan maksimal N. Fasilitas tanpa unit prioritas ditambahkan di bagian akhir secara deterministik, dan keterbatasan cakupan/truncation dicantumkan.

`priority_ranking.status` hanya mengukur label sintetis. `unassessed` pada level ranking merujuk fasilitas/unit prioritas parsial atau tidak dapat dinilai; karena label outcome fasilitas tersedia untuk seluruh fasilitas v4, ini tidak berarti outcome fasilitas tidak diketahui. Ranking tetap tidak memakai ground truth sebagai fitur.

## Hasil smoke test awal

Seed `2026`, generator v3, 250 klaim, 12 fasilitas, target injeksi 4%, budget 10%, dan 30 seed random menghasilkan 10 label klaim anomali sintetis. Satu eksekusi smoke test mencatat sekitar 0,07 detik dan puncak `tracemalloc` 1,80 MiB pada lingkungan ini; angka tersebut bersifat spesifik lingkungan dan belum mewakili skala besar.

Pada eksekusi tersebut, pemeriksa bukti hanya menilai 54 dari 250 klaim karena aturan layanannya terbatas; 196 klaim tidak dinilai oleh pemeriksa itu. Metrik gabungan mencakup 61 klaim dan mengeluarkan 189 klaim sebagai belum dinilai. Near-duplicate membandingkan 6 pasangan tanpa mencapai batas pencarian pada smoke test. Ranking memakai K=2: random baseline precision@K rerata 0,35 (simpangan baku 0,293), aturan jumlah klaim terpicu 1,00, dan antrean prioritas 1,00; kedua aturan memprioritaskan 2 dari 5 fasilitas yang berlabel positif pada K tersebut. Sampel kecil dan seed tunggal untuk metode deterministik membuat angka ini sangat tidak stabil; bukan klaim performa nyata.

Metrik individual lengkap tersimpan pada artefak runtime yang diabaikan Git.

## Benchmark skala proposal v3 (historis; bukan protokol Stage 16)

Bagian berikut mencatat hasil Stage 15 untuk keterlacakan saja. Protokol Stage 16 di atas memperbaiki populasi positif per detektor dan Stage 16 memakai benchmark fasilitas v4. Angka tabel historis ini tidak boleh dipakai sebagai hasil evaluasi terbaru.

## Hasil benchmark Stage 16 v4, 22 Oktober 2026

Perintah memakai seed 2026, generator v4 / base v3, 120.000 klaim, 200 fasilitas, injeksi klaim 4%, fasilitas positif 20%, budget 5%, 10%, 20%, dan 30 seed random (`12026`–`12055`). Output JSON agregat berada pada `outputs/synthetic_evaluations/stage16-v4-120000-seed2026.json` (diabaikan Git). Hasil memiliki 4.800 label klaim sintetis: fisioterapi 960, cloning 961, repeat 960, tindakan tanpa penunjang 959, campuran 960. Label fasilitas: 40 positif dan 160 negatif. Setiap fasilitas memiliki tepat 600 klaim; tanggal mengikuti rentang 2024-01-01 hingga 2024-12-31.

| Detektor | Populasi berlaku | TP | FP | TN | FN | Precision | Recall | F1 | FPR | Tidak berlaku (anomali lain) | Unassessed positif / negatif | Cakupan |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Repeat billing | 116.160 | 960 | 2 | 115.198 | 0 | 0,997921 | 1,000000 | 0,998959 | 0,000017 | 3.840 | 0 / 0 | 100% |
| Similar pattern exact | 116.160 | 960 | 0 | 115.200 | 0 | 1,000000 | 1,000000 | 1,000000 | 0,000000 | 3.840 | 0 / 0 | 100% |
| Near-duplicate | 117.121 | 758 | 0 | 0 | 0 | 1,000000 | 1,000000* | 1,000000* | null | 2.879 | 1.163 / 115.200 | 0,6472% |
| Kapasitas | 116.160 | 960 | 0 | 115.200 | 0 | 1,000000 | 1,000000 | 1,000000 | 0,000000 | 3.840 | 0 / 0 | 100% |
| Temporal | 118.081 | 1.308 | 2 | 0 | 0 | 0,998473 | 1,000000* | 0,999236* | 1,000000* | 1.919 | 1.573 / 115.198 | 1,1094% |
| Kelengkapan bukti | 118.079 | 2.305 | 0 | 23.158 | 574 | 1,000000 | 0,800625 | 0,889275 | 0,000000 | 1.921 | 0 / 92.042 | 22,0505% |
| Gabungan rule score | 120.000 | 4.204 | 2 | 0 | 0 | 0,999524 | 1,000000* | 0,999762* | 1,000000* | 0 | 596 / 115.198 | 3,5050% |

`*` Hanya untuk klaim eligible. Near-duplicate berhenti pada batas 5.000 perbandingan dan 500 kandidat; 1.163 label positif serta semua 115.200 label negatif target-scope tidak dinilai. Temporal menyentuh batas 500 kandidat; 1.573 positif dan 115.198 negatif tak dinilai. Maka precision/recall eligible yang sempurna pada hasil near-duplicate tidak menggambarkan seluruh populasi. Evidence completeness menilai subset layanan: 92.042 klaim negatif tak berlaku terhadap aturan bukti yang tersedia dan tidak dinilai; 574 klaim campuran yang applicable menjadi FN. Untuk gabungan, 596 positif serta 115.198 negatif tidak dinilai, dan TN=0; FPR 1,0 dari hanya dua negatif eligible tidak informatif. Baris gabungan tidak boleh dibaca sebagai recall dataset penuh.

Ranking fasilitas memakai prevalence positif 40/200 = 20%; setiap metode memakai K sama. Random baseline memakai 30 seed, mean dan population standard deviation precision. Aturan sederhana menghitung klaim unik berindikator per fasilitas; antrean CIR menggunakan urutan priority index yang sudah ada. Semua nilai berasal dari label sintetis.

| K (budget) | Metode | Precision@K | Recall@K | Positif diprioritaskan | Lift vs mean random precision |
|---:|---|---:|---:|---:|---:|
| 10 (5%) | Random mean (SD 0,098263) | 0,203333 | 0,050833 | 2,03 rata-rata | — |
| 10 (5%) | Aturan sinyal klaim | 1,000000 | 0,250000 | 10 | 4,918033 |
| 10 (5%) | Priority CIR | 1,000000 | 0,250000 | 10 | 4,918033 |
| 20 (10%) | Random mean (SD 0,072954) | 0,213333 | 0,106667 | 4,27 rata-rata | — |
| 20 (10%) | Aturan sinyal klaim | 1,000000 | 0,500000 | 20 | 4,687500 |
| 20 (10%) | Priority CIR | 1,000000 | 0,500000 | 20 | 4,687500 |
| 40 (20%) | Random mean (SD 0,050697) | 0,205833 | 0,205833 | 8,23 rata-rata | — |
| 40 (20%) | Aturan sinyal klaim | 1,000000 | 1,000000 | 40 | 4,858300 |
| 40 (20%) | Priority CIR | 1,000000 | 1,000000 | 40 | 4,858300 |

Lift vs prevalence fasilitas untuk dua metode deterministik adalah 5,0 pada semua K. Ini hasil sangat optimistis dari benchmark konstruksi: kejadian positif ditempatkan pada 40 fasilitas positif, semua fasilitas lain menerima klaim normal, dan semua fasilitas positif berada pada urutan teratas kedua aturan. Karena itu ranking belum menguji generalisasi, perpindahan fasilitas/kejadian, atau kegunaan audit nyata. Antrean hanya berisi 41 unit dari 200 fasilitas (159 tanpa unit ber-trigger); 41 unit berstatus parsial/tidak dapat dinilai, dan 2 pemeriksa terpotong. Fasilitas tanpa unit diurutkan setelah unit yang ada secara ID sintetis, bukan dianggap bebas anomali. Label outcome fasilitas tersedia penuh dari ground truth v4, sementara cakupan analitik priority tidak penuh.

Benchmark end-to-end memerlukan 46,721 detik. Puncak `tracemalloc` 717,14 MiB dan current 267,77 MiB sebelum objek dilepas; ini alokasi Python yang terlacak, bukan RSS proses. Angka berlaku untuk mesin dan konfigurasi tersebut.

## Reproduksi ulang tabel proposal pada working tree lokal, 25 Oktober 2026

Eksperimen ulang memakai implementasi yang saat ini ada di working tree, tanpa mengubah detektor, threshold, bobot, atau budget: generator benchmark v4 (base v3), profil `facility-stratified-sparse-positive-v1`, seed `2026`, 120.000 klaim, 200 fasilitas, injeksi klaim 4%, 40 fasilitas positif/160 kontrol negatif, tepat 600 klaim per fasilitas, periode 2024-01-01–2024-12-31. Lima skenario menghasilkan 4.800 label positif: `phantom_physiotherapy` 960, `cloning` 961, `repeat_billing` 960, `action_without_support` 959, dan `mixed_light_severe` 960. Versi yang diperiksa: evaluator `synthetic-evaluation-v1`, scoring `rule-risk-index-v1-provisional` (enam bobot sama), priority `audit-priority-v1-synthetic-assumption`; konfigurasi near-duplicate default similarity 0,8, minimal 9 atribut, toleransi amount sintetis 1,00, block maksimum 100, budget 5.000 perbandingan dan 5.000 kandidat.

Benchmark dijalankan melalui `run_benchmark` yang sama dengan CLI, lalu hanya proyeksi agregat ditulis ke `outputs/synthetic_evaluations/stage23-proposal-reproduction-v4-120000-seed2026.json`. Output tidak memuat ID kasus/fasilitas, participant token, kandidat baris, atau signature. Perintah memakai `.venv\Scripts\python.exe` dari `backend`; parameter ialah `claims=120000`, `facilities=200`, `seed=2026`, `target_anomaly_rate=0.04`, `audit_budget_fractions=(0.05, 0.10, 0.20)`, `random_seed_count=30`, `generator_version="4"`, dan `positive_facility_fraction=0.20`. Seed baseline acak adalah 12026–12055. Waktu end-to-end terukur 50,633 detik; peak `tracemalloc` 648,16 MiB dan current sebelum release 267,78 MiB. Ini bukan pengukuran RSS.

### Metrik ranking yang benar-benar dihitung

Unit outcome ialah fasilitas sintetis positif bila memiliki setidaknya satu klaim berlabel anomali. Precision@K = fasilitas positif yang terpilih / K; recall@K = fasilitas positif terpilih / 40 fasilitas positif. K adalah `ceil(200 × fraksi budget)`, sehingga 10/20/40 fasilitas. Random memilih K fasilitas dengan urutan teracak untuk masing-masing dari 30 seed. Semua metode menerima K yang sama. V4 menyeimbangkan tiap fasilitas menjadi 600 klaim, sehingga jumlah klaim dalam populasi fasilitas terpilih sama untuk K yang sama; ini tetap bukan rencana sampling berkas dan bukan berarti seluruh 600 berkas tiap fasilitas diperiksa.

| K fasilitas | Metode yang dijalankan | Precision@K | Recall@K | Fasilitas positif terpilih |
|---:|---|---:|---:|---:|
| 10 (5%) | Random, mean (SD precision 0,098263) | 0,203333 | 0,050833 | 2,03 mean |
| 10 (5%) | Aturan sederhana aktual* | 1,000000 | 0,250000 | 10 |
| 10 (5%) | Prioritas CIR | 0,900000 | 0,225000 | 9 |
| 20 (10%) | Random, mean (SD precision 0,072954) | 0,213333 | 0,106667 | 4,27 mean |
| 20 (10%) | Aturan sederhana aktual* | 1,000000 | 0,500000 | 20 |
| 20 (10%) | Prioritas CIR | 0,950000 | 0,475000 | 19 |
| 40 (20%) | Random, mean (SD precision 0,050697) | 0,205833 | 0,205833 | 8,23 mean |
| 40 (20%) | Aturan sederhana aktual* | 1,000000 | 1,000000 | 40 |
| 40 (20%) | Prioritas CIR | 0,975000 | 0,975000 | 39 |

*Definisi kode saat ini untuk “aturan sederhana” adalah menghitung jumlah klaim unik dengan **setidaknya satu pemicu dari seluruh detektor** per fasilitas, lalu mengurutkan menurun dengan ID sintetis sebagai tie-break. Ini bukan implementasi satu aturan anomali seperti deskripsi proposal; tabel ini mereproduksi evaluator yang ada, bukan metode proposal yang telah ditentukan. Hasil baseline ini membuat gap desain terlihat dan tidak boleh dilabeli sebagai replikasi tepat metode aturan sederhana proposal.

### Hasil pemeriksa dan cakupan pada run ini

Populasi confusion matrix per detektor hanya mencakup skenario target detektor tersebut dan klaim normal; skenario anomali lain tidak berlaku. Persentase cakupan di bawah memakai populasi applicable itu. Tidak ada missing positif/negatif yang dinilai sebagai negatif saat tidak tercakup.

| Pemeriksa | TP / FP / TN / FN | Precision | Recall | Eligible / applicable | Cakupan |
|---|---:|---:|---:|---:|---:|
| Repeat billing | 960 / 2 / 115.198 / 0 | 0,997921 | 1,000000 | 116.160 / 116.160 | 100% |
| Similar claim pattern exact | 960 / 0 / 115.200 / 0 | 1,000000 | 1,000000 | 116.160 / 116.160 | 100% |
| Near-duplicate (artefak lama; belum dapat dievaluasi secara sah) | — | null | null | belum dapat dipastikan | tidak valid |
| Kapasitas | 960 / 0 / 115.200 / 0 | 1,000000 | 1,000000 | 116.160 / 116.160 | 100% |
| Temporal | 2.103 / 2 / 115.198 / 778 | 0,999050 | 0,729955 | 118.081 / 118.081 | 100% |
| Kelengkapan bukti | 2.305 / 0 / 115.200 / 574 | 1,000000 | 0,800625 | 118.079 / 118.079 | 100% |

Near-duplicate pada artefak agregat melaporkan 1.055 perbandingan, 770 pasangan kandidat, dan `search_truncated=false`. Audit kode menemukan evaluator lama tidak membaca `unassessed_case_ids`, sehingga angka `eligible=117.121`, cakupan 100%, dan confusion matrix baris tersebut **tidak boleh dipakai sebagai hasil yang sah**. Nilai `381` yang tampil sebagai FN bukan klasifikasi yang dapat dipercaya sampai setiap klaim/pasangan itu dipetakan ke hasil pemeriksaan. Repeat billing menghasilkan dua false positive klaim dari kontrol negatif `legitimate_repeat_control`, memperlihatkan pola berulang sah yang mirip sinyal.

**Audit false negative near-duplicate v4 (seed 2026).** Target label detektor adalah 1.921 klaim dari skenario cloning (961) dan mixed (960). Artefak agregat mencatat 1.540 klaim terpicu dari 770 keluaran ber-scope `claim_pair`, serta 381 klaim label yang sebelumnya dihitung FN. Spesifikasi generator v3 yang menjadi base v4 membentuk 384 grup cloning (193 beranggotakan 3 klaim) dan 386 grup mixed (188 beranggotakan 3); jumlah grup tiga anggota tepat 381. Karena satu keluaran pasangan hanya memuat dua `case_id`, aritmetika ini **konsisten** dengan satu anggota tiap grup tiga orang yang tak tercakup oleh proyeksi pair-to-claim. Namun artefak benchmark hanya menyimpan agregat, bukan relasi pasangan ke `scenario_group_id` atau observer kandidat, sehingga ini belum membuktikan bahwa semua 381 kasus berasal dari pola tersebut.

Penyebab yang dapat dibuktikan terpisah adalah bug coverage evaluator: near-duplicate dapat memakai `stratified_block_sampling`, mengisi `unassessed_case_ids`, tetapi membiarkan `search_truncated=false` jika batas global belum tercapai. Reproduksi fixture tiga record menghasilkan satu perbandingan, satu pasangan, tiga ID eksplisit belum dinilai, dan flag truncation false. Evaluator lama hanya membaca `ineligible_cases`, `unassessed_cases`, dan `unassessed_time_cases`; ia lalu memasukkan klaim yang belum dinilai ke eligible dan dapat menghitungnya sebagai FN/TN. Evaluator sekarang memasukkan `unassessed_case_ids` ke perhitungan coverage, sehingga status menjadi partial dan label positif yang tidak diperiksa dilaporkan sebagai unassessed, bukan FN. `search_truncated=false` tetap berarti batas pencarian keras tidak terlampaui; itu **bukan** bukti candidate generation lengkap.

| Kategori audit | Kesimpulan dari bukti yang tersedia |
|---|---|
| Target tidak dibentuk oleh blocking | Belum dapat dipisahkan untuk 381 pada run v4; artefak agregat tidak menyimpan observer pasangan atau relasi kasus-ke-grup. |
| Batas internal / sampling per blok | Kode mengimplementasikan sampling deterministik yang dapat meninggalkan `unassessed_case_ids` tanpa `search_truncated=true`; jalur ini direproduksi pada fixture kecil. Belum ada diagnostik yang tersimpan untuk memastikan berapa dari 381 berasal dari jalur itu pada benchmark penuh. |
| Pasangan dibentuk tetapi tidak lolos similarity | Tidak dapat ditentukan dari artefak agregat v4; evaluator kandidat terpisah mempunyai observer untuk mengukur tahap ini pada fixture, tetapi tidak dijalankan terhadap hasil run v4 yang telah selesai. |
| Ketidakcocokan unit label dan prediksi | Terbukti: label dievaluasi per klaim, sementara detektor mengeluarkan pasangan klaim; evaluator mengambil gabungan anggota pasangan dan tidak mengukur hit grup. Satu grup terdeteksi dapat tetap menyisakan anggota grup yang tidak tampil di pasangan. |
| Coverage evaluator | Terbukti salah untuk hasil dengan `unassessed_case_ids` ketika flag truncation false; telah diperbaiki agar eksplisit unassessed tidak menjadi negatif. Hasil v4 lama tidak dihitung ulang dalam tugas ini. |

Angka agregat lama dipertahankan dalam uraian untuk keterlacakan artefak, bukan sebagai metrik valid yang dapat ditafsirkan. Sampai run evaluasi baru dilakukan dengan evaluator yang telah diperbaiki dan protokol unit pair/group/claim dipilih, hasil near-duplicate v4 harus dibaca sebagai **tidak terselesaikan**, bukan recall 80,17% atau 381 false negative terkonfirmasi.

Gabungan: TP 4.800, FP 2, TN 115.189, FN 0 pada 119.991 klaim eligible; 9 klaim normal tidak dinilai. Precision 0,999584, recall 1,000000, F1 0,999792 dan FPR 0,000017 hanya berlaku pada simulasi dan definisi gabungan ini. Angka tinggi terutama menunjukkan bahwa generator memberi konstruksi fitur yang sangat berkaitan dengan label skenario; angka tersebut bukan validasi eksternal.

Antrean prioritas membentuk 41 unit fasilitas dari 200; 159 fasilitas tanpa unit terpicu ditempatkan terakhir menurut ID sintetis dan tidak ditafsirkan normal. Dari 41 unit antrean, 40 berstatus parsial/tidak dapat dinilai. Ringkasan detector global pada run ini tidak melaporkan search truncation. Kelengkapan label fasilitas (40 positif/160 negatif) tidak berarti seluruh unit eligible untuk perhitungan priority.

### Perbandingan dengan angka ilustratif proposal

Transkripsi visual proposal halaman 14 memuat Precision@K 20%/45%/78%, Recall Fraud 20%/45%/75%, fraud per 100 berkas 4/9/16, klaim sah tetap hijau 95%/88%/92%, dan klaim sah masuk kuning/merah 5%/12%/8% untuk Audit Acak/Aturan Sederhana/Radar. Slide menandai tabel itu “Dummy simulasi” dan menyatakan kuantitatif belum tersedia serta belum tervalidasi pada data riil. Angka itu bukan hasil yang direproduksi, baseline faktual, atau acceptance threshold.

Precision@K dan recall aktual di atas dihitung pada **fasilitas**, sementara proposal tidak menjelaskan apakah K ialah fasilitas, klaim, atau berkas. Karena itu angka fasilitas tidak dapat dibandingkan langsung dengan angka proposal, meski satuannya sama-sama ditulis persen. Evaluator tidak menghitung fraud per 100 berkas karena metode belum menentukan jumlah/pemilihan berkas per fasilitas untuk setiap pendekatan. Ia juga tidak menghitung proporsi klaim sah hijau/kuning-merah per pendekatan: lane provisional hanya diterapkan pada finding yang ada di snapshot, bukan pada seluruh klaim atau baseline audit acak/aturan sederhana; ketiadaan finding bukan green. Ketiga metrik tersebut harus tetap `belum didefinisikan/tidak dihitung`, bukan diberi angka pengganti.

### Interpretasi dan tindak lanjut desain

Pada benchmark buatan ini, kedua ranking deterministik mengungguli rerata acak untuk precision/recall fasilitas, tetapi aturan sederhana aktual lebih tinggi daripada prioritas CIR pada semua K yang diuji. Tidak ada bukti dari run ini bahwa CIR meningkatkan precision, dan pada K=10/20/40 fasilitas ia memprioritaskan masing-masing 1/1/1 lebih sedikit fasilitas positif dibanding aturan sederhana aktual. Jangan mengubah bobot atau threshold untuk mengejar nilai slide.

### Status keputusan protokol record-level

Unit, anggaran K, baseline aturan tunggal, dan kebijakan seleksi CIR dijabarkan pada bagian protokol di bawah dan diimplementasikan sebagai utilitas evaluasi terpisah di `backend/app/analytics/record_selection.py`. Kebijakan ini untuk benchmark sintetis; bukan kebijakan audit operasional BPJS. Metrik lane hijau/kuning/merah lintas metode tetap belum dapat dihitung karena pemetaan setara untuk seluruh populasi belum ditetapkan.

## Protokol pembanding record-level dan selektor sintetis

Bagian ini menetapkan unit, rumus, dan selektor record-level sintetis. Selektor mula-mula diuji dengan fixture; eksekusi skala penuh berikutnya dicatat terpisah pada bagian **Benchmark record-level v4** di bawah. Hasil benchmark v4 fasilitas di atas tetap historis dan bukan hasil untuk protokol ini.

### Populasi, unit, dan K

- Populasi adalah seluruh **unique synthetic claim record** pada satu snapshot benchmark v4 yang sama, diidentifikasi oleh `case_id` unik. Generator memang menghasilkan satu record fitur klaim dengan ID klaim/kasus; generator tidak membuktikan bahwa record sama dengan satu berkas rekam medis yang diperiksa. Karena itu laporan memakai “record klaim”, bukan “berkas”.
- Untuk 120.000 record, anggaran metode adalah tepat **K=6.000 (5%)**, **K=12.000 (10%)**, dan **K=24.000 (20%)** record unik. Seleksi tanpa penggantian; satu record yang terkena banyak pasangan/indikator hanya dihitung sekali.
- Semua metode harus mengembalikan tepat K `case_id` dari populasi dan snapshot yang sama. Bila selection policy yang disepakati tidak dapat mengisi K, hasil K itu berstatus tidak dapat dibandingkan; laporkan jumlah terpilih aktual dan sebabnya. Jangan mengganti denominator K atau memperlakukan record tidak terpilih/tidak dinilai sebagai negatif.
- Ground truth baru dibaca setelah daftar terpilih dibentuk dan dibekukan. Label, `scenario_group_id`, dan `facility_labels` tidak boleh dipakai untuk ordering, tie-break, strata seleksi, atau fallback.

### Aturan tiga metode

| Metode | Definisi rancangan | Status |
|---|---|---|
| Random baseline | Ambil tepat K record secara uniform tanpa penggantian dari seluruh populasi. Gunakan 30 seed yang dipraregistrasi dari seed benchmark 2026: 12026–12055. Laporkan setiap seed dan setiap K, mean, serta simpangan baku hasil. | Dapat ditentukan tanpa asumsi domain tambahan; belum dijalankan untuk K record. |
| Simple-rule baseline | Hanya `repeat_billing_candidate` menjadi pemicu primer. Anggota kandidat dideduplikasi dan diurutkan dengan tie pseudoacak seed `12026`; jika kandidat kurang dari K, sisa dipilih tanpa penggantian dari non-kandidat dengan ordering seed yang sama. | Diimplementasikan di `record_selection.py`; tidak memakai skor baru atau gabungan detektor. Fallback adalah pemilihan eksploratori, bukan prediksi negatif. |
| CIR priority | Fasilitas hanya valid bila memiliki `priority_status=available` dan `priority_index` finite; fasilitas diurutkan menurun, tie dengan hash pseudoacak seed. Dalam fasilitas, finite `risk_score` yang tersedia diurutkan menurun, lalu nilai yang tidak tersedia memakai tie pseudoacak tanpa imputasi nol. Setelah record pada fasilitas prioritas habis, sisa K diambil tanpa penggantian dari pool fasilitas tanpa prioritas valid. | Diimplementasikan di `record_selection.py`. Priority parsial/tidak assessable tidak diranking; fasilitas itu hanya dapat masuk fallback dan tidak dianggap normal. |

Seleksi fallback pada metode rule/CIR hanya memakai record yang belum dipilih. Ia memenuhi anggaran dengan memilih record untuk ditinjau; ia tidak memberi label prediksi dan tidak mengubah `risk_score`, `risk_level`, coverage detector, atau action lane. Seed tie/fallback selektor deterministik adalah `12026`; random baseline tetap memakai 30 seed `12026–12055`. `RecordSelection.summary()` hanya memuat agregat, sedangkan `selected_assessment_summary()` melaporkan status coverage dari scoring tanpa mengubah unassessed menjadi negatif.

### Implementasi selektor dan runner komparatif

`backend/app/analytics/record_selection.py` menyediakan random baseline, baseline satu aturan, selektor CIR, serta ringkasan assessment yang aman. `backend/app/analytics/record_level_evaluation.py` menjalankan `run_detector_suite`, `score_claims`, dan `build_audit_priority_queue` yang sama dengan pipeline aplikasi, lalu membekukan pilihan record sebelum membaca label. Hasil fungsi adalah objek agregat JSON-compatible; daftar `selected_case_ids` hanya hidup sementara di objek seleksi dan tidak disertakan dalam summary.

Audit implementasi mengonfirmasi `priority_index = risk_score × nilai klaim terindikasi ÷ estimasi usaha`; antrean fasilitas mengurutkan `priority_index` menurun, sehingga angka lebih besar berarti urutan lebih tinggi. `priority_status=available` diberikan bila prasyarat indeks terpenuhi dan effort tidak terkena cap; status cap menjadi `partial`, sehingga selektor tidak memakai indeks parsial sebagai ranking valid. `risk_score` adalah indeks aturan normalisasi 0–1, dengan nilai lebih besar berarti proporsi bobot indikator terpicu lebih besar; ia bukan probabilitas. Identifier antrean `synthetic-audit-unit:<facility_id>` dipetakan ke `facility_id` kanonis pada record fitur; ID hanya dipakai internal.

Repeat detector menghasilkan `candidate_groups` berisi semua anggota signature exact-match lengkap yang berulang, bukan edge pasangan. Baseline satu aturan mengambil union `case_ids` dari grup tersebut dan mendeduplikasi berdasarkan `case_id`; untuk detektor grup exact-match, setiap anggota yang dikembalikan detector memang bagian dari grup yang cocok. Kontrak ini tidak boleh digunakan untuk menyimpulkan seluruh anggota grup near-duplicate terdeteksi dari satu pasangan.

Selektor menolak field ground truth pada record fitur dan tidak menerima argumen label. Urutan tie memakai SHA-256 dengan namespace/seed agar stabil lintas proses dan tidak bergantung pada hash acak Python. `selected_assessment_summary` mempertahankan hitungan `score_status` dan status per indikator untuk record terpilih; seleksi fallback tidak mengubah status assessment dan tidak dianggap prediksi negatif. Summary tidak mengeluarkan ID record atau fasilitas.

Runner smoke dijalankan melalui tes `tests/test_record_level_evaluation.py` pada generator benchmark sintetis v4, seed 2026, 1.200 record, 20 fasilitas, target injeksi 4%, K=60/120/240. Laporan agregat mencatat versi generator/detector/scoring/priority/seleksi, versi Python, seed, jumlah record/fasilitas, K, metrik, coverage terpilih, dan jumlah positif per jalur sinyal/fallback; tidak menyimpan ID pilihan. Ini menguji integrasi dan bentuk kontrak saja; hasil populasi kecil bukan bukti kualitas atau keunggulan metode. Benchmark 120.000 record belum dijalankan.

Runner juga menghasilkan `facility_priority_diagnostics` agregat: ukuran populasi fasilitas dan metadata, jumlah unit antrean, histogram status, kategori validitas indeks (missing, tipe tak layak, non-finite, negatif, finite nonnegative), jumlah unit yang cocok/tidak cocok dengan `facility_id` fitur, dan jumlah record populasi yang punya/tidak punya priority tersedia. Ini diagnostik untuk run selanjutnya; artefak historis yang tidak menyimpan rincian unit tidak dapat direkonstruksi secara retrospektif. Hasil terpilih membawa agregat status scoring dan coverage per indikator, dipisahkan menurut jalur seleksi utama dan fallback.

Near-duplicate diagnostics mencatat kandidat blok yang dibentuk/diperiksa/diloloskan melalui observer lokal serta hitungan sampling stratified, blok/bucket berbatas, batas keras, dan record belum dinilai menurut penyebab. Kategori sebab dapat tumpang tindih dan tidak disertai identifier. `search_truncated=false` hanya berarti batas keras comparison/candidate tidak menghentikan pencarian; ia tidak membuktikan bahwa blocking mencakup semua pola target. Explicit-unassessed tetap membuat coverage detektor `partial`, kecuali populasi seluruhnya di luar applicability scope (`not_applicable`).

Diagnostik fasilitas menjelaskan mengapa record CIR dapat banyak masuk fallback, tetapi tidak mengubah eligibility atau menetapkan skor pengganti bagi fasilitas tanpa unit prioritas valid. Pemilihan/pemeringkatan fasilitas tanpa queue item belum mempunyai bukti bahwa fasilitas itu normal; keputusan desain untuk cakupan fasilitas, sinyal yang layak menjadi unit audit, serta perlakuan pada coverage parsial masih perlu ditetapkan sebelum mengubah kebijakan prioritas.

### Metrik seleksi audit record-level

Misalkan `S_K` adalah himpunan tepat K record unik terpilih dan `P` adalah seluruh record dengan label positif sintetis dalam benchmark:

- **Precision@K** = `|S_K ∩ P| / K`.
- **Recall@K** = `|S_K ∩ P| / |P|`.
- **Positive records per 100 selected records** = `100 × |S_K ∩ P| / K`. Nilai ini setara dengan 100 × Precision@K bila setiap label positif berlaku pada record klaim, sehingga harus diberi label metrik deskriptif, bukan unit berkas/fraud.
- Sajikan jumlah positif sintetis terpilih dan jumlah dari sinyal utama versus fallback. Ini adalah hasil seleksi audit terhadap label simulasi; berbeda dari jumlah klaim yang dideteksi oleh model.
- Untuk baseline random, hitung metrik per seed dan K sebelum mean/population SD. Untuk metode deterministik, tetap laporkan seed tie-break yang dipakai.

Metrik seleksi menguji apakah record positif sintetis masuk sampel audit dengan budget yang sama. Ini bukan detector precision/recall dan tidak menyatakan bahwa record terpilih terdeteksi oleh suatu indikator. Untuk detector confusion matrix, gunakan hanya populasi applicable dan record yang benar-benar assessable; laporkan unassessed-positive dan unassessed-negative di luar TP/FP/TN/FN. `unassessed`, partial, unavailable, dan blocking miss tidak boleh dimasukkan sebagai TN. Untuk metrik detector kondisional, denominator hanya item eligible yang didefinisikan protokol; discovery pada universe pasangan planted dilaporkan terpisah agar miss oleh blocking tidak disamarkan sebagai “normal”.

### Near-duplicate: unit pasangan, grup, dan klaim

Ketiga level harus disajikan terpisah; satu pasangan terdeteksi tidak berarti seluruh grup atau semua anggota klaim terdeteksi.

1. **Pasangan:** positive pair adalah pasangan unik tak berurutan yang anggotanya sama-sama berada di grup target `cloning` atau `mixed_light_severe`. Laporkan jumlah pasangan positif planted, yang dibentuk blocking, yang mencapai similarity comparator, yang lolos threshold, serta pasangan yang tidak tercakup/di-unassessed. Pair discovery rate = pasangan positif yang dibentuk blocking / semua pasangan positif planted. Precision pasangan memakai pasangan kandidat yang lolos threshold sebagai prediksi; pasangan negatif yang tidak mencapai comparator tidak menjadi TN.
2. **Grup skenario:** hit grup berarti sedikitnya satu edge kandidat lolos threshold menghubungkan dua anggota grup target. Laporkan hit-group rate dan **full-member coverage** terpisah. Full-member coverage hanya tercapai jika semua anggota target muncul dalam hasil kandidat; bila hendak menyebut grup “terhubung penuh”, kandidat pasangan harus membentuk graf terhubung atas seluruh anggota. Denominator adalah grup target yang dibekukan dari ground truth; grup parsial/tidak tercakup dilaporkan terpisah.
3. **Klaim:** prediction ialah unique `case_id` yang menjadi anggota setidaknya satu edge kandidat lolos threshold. Precision/recall klaim memakai label per klaim pada ruang applicable dan eligible saja; anggota yang secara eksplisit `unassessed` tidak menjadi FN/TN. Laporkan jumlah anggota yang dipicu dan jumlah anggota target yang tidak tercakup.

Artefak evaluasi berikutnya harus menyimpan agregat aman per tahap (positive pairs planted/generated/compared/passed, negative controls compared/passed, target groups hit/full-member-covered, unique claims triggered/unassessed, dan flag/diagnostik sampling). Jangan menyimpan pasangan, `case_id`, token, signature, atau record baris ke laporan. `search_truncated=false` hanya menyatakan hard cap tertentu tidak tercapai; status coverage juga harus membaca daftar explicit-unassessed dan diagnostik blocking.

### Lane dan perlindungan klaim sah

Tidak ada lane lintas metode yang ditetapkan untuk seluruh populasi. Lane provisional saat ini muncul pada findings tertentu, bukan seluruh record; random dan simple-rule juga tidak mempunyai pemetaan lane setara. Maka metrik proposal “klaim sah tetap hijau” dan “klaim sah ke kuning/merah” tetap **belum dapat dihitung**. Tidak ditemukannya sinyal bukan hijau. Sebelum menghitungnya, pemilik kebijakan harus menyetujui pemetaan yang sama untuk ketiga metode, penanganan `cannot_recommend`/unassessed sebagai kategori terpisah, serta denominator semua klaim sah sintetis dalam scope.

Angka proposal halaman 14 tetap dummy simulasi tak terverifikasi. Benchmark v4 terdahulu menggunakan **fasilitas** sebagai unit K dan angka pemilihan fasilitas 10/20/40; bukan eksperimen record-level K=6.000/12.000/24.000. Pernyataan bahwa benchmark record-level belum dijalankan berlaku pada saat protokol ini pertama ditetapkan; hasil eksekusi berikutnya dicatat tanpa mengganti angka proposal.

### Rincian historis benchmark v3

Eksekusi final memakai generator v3, seed `2026`, 120.000 klaim, 200 fasilitas, target 4%, budget fasilitas 10%, dan 30 seed random (`12026`–`12055`). Dataset menghasilkan 4.800 label klaim anomali sintetis. End-to-end memerlukan 43,407 detik dengan puncak `tracemalloc` 712,05 MiB dan alokasi tersisa 267,68 MiB sebelum pelepasan objek.

| Pemeriksa | TP | FP | TN | FN | Precision | Recall | F1 | FPR | Cakupan klaim | Label positif tak dinilai | Status pencarian |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| Repeat billing | 960 | 2 | 115.198 | 3.840 | 0,997921 | 0,200000 | 0,333218 | 0,000017 | 120.000 / 120.000 | 0 | Lengkap |
| Similar claim pattern exact | 960 | 0 | 115.200 | 3.840 | 1,000000 | 0,200000 | 0,333333 | 0,000000 | 120.000 / 120.000 | 0 | Lengkap |
| Near-duplicate | 758 | 0 | 0 | 0 | 1,000000 | 1,000000* | 1,000000* | null | 758 / 120.000 | 4.042 | Terpotong: 5.000 perbandingan dan 500 kandidat |
| Kapasitas | 960 | 0 | 115.200 | 3.840 | 1,000000 | 0,200000 | 0,333333 | 0,000000 | 120.000 / 120.000 | 0 | Lengkap |
| Pola temporal | 1.308 | 2 | 0 | 0 | 0,998473 | 1,000000* | 0,999236* | 1,000000* | 1.310 / 120.000 | 3.492 | Terpotong pada batas 500 kandidat |
| Kelengkapan bukti | 2.305 | 0 | 23.158 | 943 | 1,000000 | 0,709667 | 0,830182 | 0,000000 | 26.406 / 120.000 | 1.552 | Parsial: aturan bukti hanya berlaku untuk subset jenis layanan |
| Gabungan rule score | 4.204 | 2 | 0 | 0 | 0,999524 | 1,000000* | 0,999762* | 1,000000* | 4.206 / 120.000 | 596 | Parsial; cakupan 3,505% |

`*` Nilai tersebut hanya berlaku pada klaim teramati/eligible. Recall 1,0 untuk pencarian terpotong tidak berarti recall dataset penuh 1,0: label positif yang belum dinilai dilaporkan terpisah. Untuk near-duplicate, tidak ada TN/FN yang dapat dihitung dari sisa pencarian. Pola temporal mempunyai 0 TN karena pencarian terpotong; FPR 1,0 hanya mencerminkan 2 FP di antara 2 negatif teramati, bukan tingkat false positive pada seluruh dataset.

Pemeriksa yang dirancang untuk skenario tertentu memperlihatkan hasil berikut pada target skenario: repeat billing menemukan 960/960 label repeat yang eligible; kapasitas menemukan 960/960 klaim campuran; exact pattern menemukan 960/960 klaim campuran; near-duplicate mengamati 365 klaim cloning dan 393 klaim campuran sebagai TP, sementara 596 label cloning dan 567 label campuran belum dinilai; pemeriksa bukti menilai 959/959 tindakan tanpa penunjang, 960/960 fisioterapi, dan 386/960 klaim campuran (574 label campuran belum ditemukan/terpicu dalam cakupan yang diperiksa). Metrik skenario lain dan false positive tampak pada artefak agregat. Ini menunjukkan bahwa indikator mengukur konstruksi generator berbeda dan tidak diharapkan mendeteksi semua skenario.

Skor gabungan mengeluarkan 4.206 klaim yang dapat dinilai: 4.204 TP dan 2 FP, sementara 115.794 klaim tidak dinilai, termasuk 596 label positif. Karena itu angka precision/recall gabungan yang tinggi tidak mewakili dataset lengkap dan tidak boleh dibaca sebagai performa umum.

### Ranking fasilitas

Generator menempatkan sekurangnya satu klaim anomali sintetis pada **200 dari 200 fasilitas**. Dengan definisi label fasilitas ini tidak ada fasilitas negatif; baseline acak, aturan jumlah klaim terpicu, dan prioritas Claim Integrity Radar masing-masing menghasilkan precision@20 = 1, recall@20 = 0,1, dan lift acak = 1,0. Simpangan baku precision@20 baseline acak adalah 0. Seluruh 200 unit prioritas tercatat parsial, dan near-duplicate serta temporal ditandai terpotong. Hasil ini **tidak menguji daya pisah ranking fasilitas**. Nilai sama bukan bukti metode bekerja sama baik atau lebih baik.

Perbaikan benchmark berikutnya sebaiknya menetapkan target evaluasi yang sparse pada tingkat fasilitas (dengan fasilitas kontrol negatif yang eksplisit) atau mengevaluasi ranking kejadian/klaim dengan unit audit yang cocok. Perubahan itu harus dilakukan sebagai versi/desain eksperimen baru, tidak dengan mengubah label v3 setelah melihat hasil. Ambang dan bobot detektor tidak diubah pada tahap evaluasi ini.

## Batasan

- Ground truth menyatakan injeksi skenario generator v3, bukan label fraud terverifikasi.
- Generator membuat kontrol negatif dan campuran dengan aturan buatan; hasil sensitif terhadap seed, ukuran sampel, dan tingkat injeksi.
- Kapasitas, persyaratan bukti, dan intensitas bukan standar BPJS atau klinis.
- Kinerja pada data sintetis tidak dapat digeneralisasikan langsung ke klaim/fasilitas nyata.
- Skor berbobot masih provisional, bukan probabilitas fraud. Ranking bukan prediksi kerugian dan belum membuktikan penghematan usaha audit.
- Batas kandidat dan pencarian near-duplicate dipertahankan serta ditampilkan; skor/ranking dengan cakupan parsial dapat berubah jika pencarian lebih lengkap.

## Benchmark record-level v4, 25 Oktober 2026

Benchmark komparatif penuh dijalankan melalui `evaluate_record_level_comparison` pada generator sintetis v4 dan protokol record-level di atas. Konfigurasi aktual diverifikasi dari objek generator: 120.000 record klaim, 200 fasilitas, seed generator 2026, target 4% (4.800 label positif; pembulatan `floor(n × rate + 0.5)`), profil `facility-stratified-sparse-positive-v1`, 20% fasilitas positif (40 positif/160 kontrol), base generator v3, dan periode 2024-01-01 sampai 2024-12-31. Setiap fasilitas memiliki 600 record. Lima jumlah label positif: fisioterapi 960, cloning 961, repeat billing 960, tindakan tanpa penunjang 959, campuran 960. Seed random 12026–12055; seed tie/fallback 12026. Nilai K: 6.000, 12.000, 24.000 record unik. Ketiga metode memenuhi K pada semua anggaran.

Seleksi dibentuk dan dibekukan sebelum label dibaca evaluator. Record fitur dan metadata fasilitas diperiksa tidak memiliki field ground truth; selector menolak `is_anomalous`, label skenario, dan key label lain yang dikenal. Artefak hanya berisi agregat, tanpa daftar record terpilih: `outputs/synthetic_evaluations/record-level-v4-120000-seed2026.json` (diabaikan Git).

### Hasil seleksi

| K | Metode | Positif terpilih | Precision@K | Recall@K | Positif per 100 | Jalur utama | Fallback |
|---:|---|---:|---:|---:|---:|---:|---:|
| 6.000 | Random mean | 241,20 | 0,040200 | 0,050250 | 4,0200 | 6.000 | 0 |
| 6.000 | Aturan repeat billing | 1.139 | 0,189833 | 0,237292 | 18,9833 | 962 | 5.038 |
| 6.000 | CIR facility priority | 235 | 0,039167 | 0,048958 | 3,9167 | 600 | 5.400 |
| 12.000 | Random mean | 480,57 | 0,040047 | 0,100118 | 4,0047 | 12.000 | 0 |
| 12.000 | Aturan repeat billing | 1.351 | 0,112583 | 0,281458 | 11,2583 | 962 | 11.038 |
| 12.000 | CIR facility priority | 445 | 0,037083 | 0,092708 | 3,7083 | 600 | 11.400 |
| 24.000 | Random mean | 957,43 | 0,039893 | 0,199465 | 3,9893 | 24.000 | 0 |
| 24.000 | Aturan repeat billing | 1.714 | 0,071417 | 0,357083 | 7,1417 | 962 | 23.038 |
| 24.000 | CIR facility priority | 920 | 0,038333 | 0,191667 | 3,8333 | 600 | 23.400 |

Jalur utama adalah uniform sampling untuk random, anggota `repeat_billing_candidate` untuk aturan, dan record dari fasilitas ber-priority valid untuk CIR. Fallback adalah pilihan eksploratori tanpa penggantian, bukan sinyal negatif. Baseline repeat memiliki 962 kandidat unik: 960 label repeat sintetis dan 2 anggota kontrol repeat sah (false positive terhadap label simulasi). CIR memilih 600 record pada jalur fasilitas-priority (satu fasilitas karena beban seragam); tidak satu pun positif sintetis. Sisanya dipilih lewat fallback. Artefak tidak merinci alasan eligibility setiap fasilitas, jadi alasan hanya satu unit masuk pool valid tidak disimpulkan.

Pilihan positif per skenario (random adalah mean 30 seed; deterministic methods adalah hitungan tunggal):

| K | Skenario | Random mean (SD) | Repeat rule | CIR priority |
|---:|---|---:|---:|---:|
| 6.000 | `action_without_support` | 47,500 (5,130) | 43 | 52 |
| 6.000 | `cloning` | 49,767 (7,027) | 45 | 46 |
| 6.000 | `mixed_light_severe` | 48,533 (6,796) | 44 | 51 |
| 6.000 | `phantom_physiotherapy` | 48,633 (7,036) | 47 | 45 |
| 6.000 | `repeat_billing` | 46,767 (5,737) | 960 | 41 |
| 12.000 | `action_without_support` | 94,767 (8,409) | 90 | 95 |
| 12.000 | `cloning` | 97,100 (9,809) | 100 | 89 |
| 12.000 | `mixed_light_severe` | 97,900 (8,673) | 101 | 82 |
| 12.000 | `phantom_physiotherapy` | 96,100 (10,619) | 100 | 91 |
| 12.000 | `repeat_billing` | 94,700 (9,052) | 960 | 88 |
| 24.000 | `action_without_support` | 186,333 (11,898) | 179 | 195 |
| 24.000 | `cloning` | 195,300 (14,325) | 192 | 191 |
| 24.000 | `mixed_light_severe` | 193,633 (13,268) | 183 | 168 |
| 24.000 | `phantom_physiotherapy` | 189,300 (10,659) | 200 | 183 |
| 24.000 | `repeat_billing` | 192,867 (10,082) | 960 | 183 |

### Random baseline per seed

Tabel memuat jumlah record positif dalam pilihan tiap seed untuk K=6.000/12.000/24.000. Precision per seed adalah hitungan dibagi K; recall hitungan dibagi 4.800. Statistik ringkasan memakai simpangan baku populasi atas 30 seed.

| Seed | K 6.000 | K 12.000 | K 24.000 |
|---:|---:|---:|---:|
| 12026 | 233 | 493 | 972 |
| 12027 | 229 | 473 | 928 |
| 12028 | 219 | 437 | 903 |
| 12029 | 221 | 469 | 945 |
| 12030 | 229 | 444 | 915 |
| 12031 | 239 | 474 | 962 |
| 12032 | 252 | 491 | 985 |
| 12033 | 239 | 489 | 955 |
| 12034 | 243 | 488 | 981 |
| 12035 | 237 | 477 | 957 |
| 12036 | 243 | 480 | 918 |
| 12037 | 264 | 503 | 965 |
| 12038 | 261 | 521 | 979 |
| 12039 | 250 | 491 | 981 |
| 12040 | 225 | 479 | 970 |
| 12041 | 261 | 516 | 1.026 |
| 12042 | 272 | 511 | 1.009 |
| 12043 | 237 | 473 | 925 |
| 12044 | 236 | 497 | 999 |
| 12045 | 237 | 485 | 989 |
| 12046 | 261 | 502 | 946 |
| 12047 | 238 | 451 | 932 |
| 12048 | 249 | 481 | 965 |
| 12049 | 226 | 466 | 965 |
| 12050 | 245 | 479 | 927 |
| 12051 | 235 | 457 | 919 |
| 12052 | 234 | 475 | 941 |
| 12053 | 263 | 481 | 966 |
| 12054 | 228 | 461 | 931 |
| 12055 | 230 | 473 | 967 |

| K | Mean Precision@K | SD Precision@K | Mean Recall@K | SD Recall@K | Mean positif/100 | SD positif/100 |
|---:|---:|---:|---:|---:|---:|---:|
| 6.000 | 0,040200 | 0,002286 | 0,050250 | 0,002858 | 4,0200 | 0,2286 |
| 12.000 | 0,040047 | 0,001612 | 0,100118 | 0,004030 | 4,0047 | 0,1612 |
| 24.000 | 0,039893 | 0,001219 | 0,199465 | 0,006097 | 3,9893 | 0,1219 |

### Coverage dan near-duplicate

| Pemeriksa | Terpicu | Dinilai | Tidak dinilai | Tidak berlaku | `search_truncated` |
|---|---:|---:|---:|---:|---|
| Repeat billing exact | 962 | 120.000 | 0 | 0 | false |
| Similar claim pattern exact | 960 | 120.000 | 0 | 0 | false |
| Near-duplicate | 1.540 klaim | 119.028 | 972 | 0 | false |
| Kapasitas | 960 | 120.000 | 0 | 0 | false |
| Temporal | 2.105 | 120.000 | 0 | 0 | false |
| Kelengkapan bukti | 2.305 | 26.406 | 0 | 93.594 | false |

Near-duplicate juga melaporkan 1.738 ID pada daftar internal `unassessed_case_ids`; agregasi scoring lama mengeluarkan 972 sebagai belum dinilai setelah klaim yang benar-benar terpicu dipisahkan. Artefak tersebut berasal dari sebelum perbaikan kontrak: status global yang tersimpan sebagai `available` meremehkan adanya kasus explicit-unassessed. Nilai artefak historis tidak ditulis ulang; untuk interpretasi, status itu tidak boleh dianggap sebagai coverage lengkap dan benchmark perlu dijalankan ulang bila metrik coverage pasca-perbaikan diperlukan. `search_truncated=false` hanya berarti batas hard search tidak tercapai, bukan bahwa blocking menangkap semua pasangan target.

Pada unit pasangan, ada 1.532 pasangan positif yang dibentuk dalam grup cloning/campuran. Blocking membentuk 770 (50,26%) dan tidak membentuk 762; semua 770 pasangan target yang dibentuk dibandingkan dan lolos similarity, tanpa pasangan target yang gagal threshold. Total ada 1.055 perbandingan dan 770 pasangan kandidat yang dilaporkan. Jadi miss pasangan positif yang terukur terjadi pada candidate blocking, bukan pada threshold similarity.

Pada unit grup, 770 grup target memiliki setidaknya satu pasangan kandidat, tetapi hanya 389 grup (50,52%) memiliki semua pasangan anggota yang diterima. “Grup tersentuh” bukan berarti semua klaim dalam grup terdeteksi. Pada unit klaim, 1.540 dari 1.921 klaim target masuk ke setidaknya satu pasangan kandidat; 381 tidak. Hubungan ini dihitung memakai ground truth hanya di evaluator setelah pilihan dibekukan. Hasilnya konsisten dengan grup tiga anggota yang hanya memiliki satu edge, tetapi bukan alasan untuk menyebut seluruh grup terdeteksi. Kontrol repeat sah tetap negatif untuk label simulasi dan bukan pasangan positif target near-duplicate.

### Runtime dan interpretasi

Eksekusi final penuh memerlukan 135,574 detik. Peak `tracemalloc` 681.574.900 byte (alokasi Python terlacak, bukan RSS). Peak working set Windows melalui `GetProcessMemoryInfo(PROCESS_MEMORY_COUNTERS_EX)` 1.356.677.120 byte; working set saat pengukuran akhir 383.791.104 byte. Alokasi Python yang masih hidup sebelum pelepasan objek 282.233.342 byte. Pengukuran mencakup pembuatan dataset, detektor, scoring, priority, seleksi, dan agregasi; serialisasi JSON dikecualikan. Eksperimen sebelumnya dalam tugas yang sama berhenti setelah perhitungan karena validasi pembungkus mengasumsikan bentuk field random yang tidak sesuai; angka di sini berasal dari run final yang menyimpan artefak dan sama konfigurasinya.

Baseline repeat-rule memiliki hasil tertinggi dalam eksperimen ini karena satu skenario positif memang menanam signature repeat yang menjadi aturan seleksi; dua kontrol repeat sah memperlihatkan risiko false positive yang dirancang. Hasil CIR dipengaruhi oleh hanya 600 record pada pool prioritas valid dan fallback untuk selebihnya. Near-duplicate masih melewatkan banyak pasangan target di blocking meski hard cap tidak tercapai. Angka proposal halaman 14 tetap dummy simulasi belum terverifikasi; hasil sintetis ini bukan bukti efektivitas pada fraud JKN nyata dan tidak menghitung lane hijau/kuning/merah.
