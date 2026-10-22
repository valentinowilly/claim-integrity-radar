# Spesifikasi Evaluasi Sintetis

## Batas evaluasi dan reproducibility

Evaluator ada di `backend/app/analytics/evaluation.py`; CLI ada di `backend/app/analytics/evaluate_synthetic.py`. Evaluasi hanya menerima hasil `generate_synthetic_dataset`. Versi generator, seed, ukuran dataset, dan tingkat injeksi selalu masuk metadata laporan. Evaluator memastikan ID fitur dan label sama, dan menolak label ground truth bila ditemukan di record fitur.

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
