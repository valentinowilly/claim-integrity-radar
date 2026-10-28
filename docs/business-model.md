# Model bisnis dan penerapan — Claim Integrity Radar

Status: **usulan model operasional dan adopsi**, bukan *business case* finansial yang tervalidasi. Tidak ada angka penghematan, harga, atau ROI yang diklaim; nilai ekonomi baru dapat diukur melalui pilot berizin (`docs/audit-pilot-protocol.md`). Fakta tentang sistem BPJS Kesehatan di bawah bersumber dari materi panitia "Sistem Layanan JKN & Pemanfaatan AI" (20 Oktober 2026).

Dokumen ini membedakan tiga hal:

| Hal | Status |
|---|---|
| Penempatan dalam proses klaim BEA (§1) | **usulan tim** |
| Model penerapan internal/B2G (§3) | **rekomendasi tim** untuk data operasional sensitif |
| Persetujuan, integrasi, atau adopsi resmi oleh BPJS Kesehatan | **belum ada**; tidak ada integrasi dengan aplikasi BPJS yang dibangun atau diuji |

Tetap belum terbukti: hasil pilot, label fraud terverifikasi, dan penerapan produksi. RC tidak memakai LLM, model eksperimen Isolation Forest v2 tidak dipindahkan ke sistem utama, dan metrik sintetis bukan kinerja pada data BPJS nyata.

## 1. Usulan penempatan dalam proses bisnis BPJS Kesehatan

Proses sasaran yang diusulkan: **C03.04 Pengelolaan Klaim Faskes** pada arsitektur proses bisnis (BEA) BPJS Kesehatan — pengajuan klaim faskes, verifikasi (sudah berbantuan AI), register dan persetujuan. Aplikasi yang tercantum pada proses ini antara lain VClaim, VIDI, SIGAP, LUPIS, BOA, dan AUDIA.

CIR **tidak menggantikan** aplikasi tersebut maupun verifikasi klaim. Usulannya, CIR menjadi lapisan pendukung keputusan di antara verifikasi dan audit: membaca data klaim yang sudah ada, membentuk kandidat peninjauan dengan alasan dan cakupan pemeriksaan, mengurutkan antrean, dan mencatat keputusan manusia serta hasil audit berwenang secara terpisah.

## 2. Pengguna dan nilai yang ditawarkan

| Pengguna | Kebutuhan | Yang diberikan CIR |
|---|---|---|
| Verifikator | memilih berkas yang perlu dicek lebih dalam dari volume besar | antrean kandidat dengan alasan per pemeriksaan dan status cakupan |
| Audit lead / Tim Anti Kecurangan | menetapkan tindak lanjut yang proporsional dan dapat dipertanggungjawabkan | outcome reviewer, hasil audit berwenang dengan rujukan, riwayat append-only |
| Operator data | menjalankan analisis berulang secara terkendali | run berversi, hasil immutable, konfigurasi sumber terkunci di server |
| Faskes (tidak langsung) | tidak dibebani pemeriksaan yang tidak perlu | sinyal ditandai sebagai kandidat, bukan temuan; "tidak dinilai" tidak dianggap negatif |

## 3. Rekomendasi model penerapan

* **Rekomendasi: internal (B2G).** Materi Healthkathon yang tersedia tidak melarang SaaS secara umum, dan tim tidak mengutip kebijakan resmi yang melarangnya. Rekomendasi penerapan internal adalah pilihan konservatif yang mengikuti prinsip dalam materi tersebut: data peserta JKN nyata tidak boleh dipakai tanpa izin tertulis penyelenggara (Participant Guide §12); "data sintetis/sandbox & tokenisasi; tanpa data peserta ke AI publik"; dan bila ada data peserta atau riwayat kesehatan, gunakan AI internal (materi SI JKN, prinsip solusi AI & ML). Karena CIR memproses data klaim yang sensitif, menjalankannya di infrastruktur BPJS Kesehatan meminimalkan perpindahan data.
* **Dirancang agar dapat selaras dengan arah TI 2026–2027** (belum dikonfirmasi BPJS): API-first dan modular (FastAPI dengan kontrak API terdokumentasi), mengikuti inisiatif *Microservices & Single Source of Truth* dan *Enterprise AI & JKN Data Hub*. Sumber data dihubungkan lewat adaptor; detektor tidak bergantung pada format sumber.
* **Data aman:** pseudonimisasi identifier dengan kunci lokal (dapat diganti tokenisasi yang sudah dipakai BPJS), tanpa pengiriman data ke AI publik, RBAC dan CSRF, log audit.

## 4. Struktur biaya (kualitatif)

Infrastruktur internal (komputasi batch, penyimpanan hasil run); pemeliharaan aturan dan ambang oleh tim data bersama pakar klinis/koder; waktu auditor untuk pilot dan label hasil audit; tinjauan keamanan independen dan operasional (backup, monitoring, manajemen kunci). Besaran biaya belum diestimasi.

## 5. Ukuran keberhasilan (diukur saat pilot, belum diklaim)

* Proporsi kandidat yang berakhir `confirmed_issue` dibanding sampel kontrol acak dari jendela yang sama.
* Waktu tinjauan per kasus dan jumlah eskalasi.
* Beban pada faskes jujur: proporsi kandidat dengan outcome `signal_not_supported`.
* Cakupan: proporsi klaim yang dapat dinilai per pemeriksaan, dan perubahannya bila data tambahan tersedia.
* Kesepakatan antar-reviewer pada subset ganda.

## 6. Tahapan dan keberlanjutan

1. **Pilot terbatas** pada satu wilayah dan satu jendela waktu, dengan izin penggunaan data dan auditor berwenang.
2. **Evaluasi** terhadap ukuran di §5; aturan, ambang, dan taksonomi outcome disahkan pemilik proses.
3. **Perluasan** bertahap per wilayah setelah prasyarat produksi terpenuhi (infrastruktur, keamanan independen, kebijakan).

Keberlanjutan dijaga dengan aturan dan konfigurasi berversi, ambang yang dikelola petugas berwenang (bukan klien), pemantauan cakupan per run, dan penambahan modus sebagai detektor baru tanpa mengubah alur review.

## 7. Risiko utama

| Risiko | Mitigasi |
|---|---|
| Faskes jujur ikut tertandai | kandidat ≠ temuan; outcome reviewer dan hasil audit terpisah; ukur `signal_not_supported` |
| Ketergantungan pada field yang belum terkonfirmasi (FKL30, FKL47) | record dengan bukti hilang tidak dinilai; FKL47/FKL48 tidak dipakai untuk prioritas |
| Bias antar wilayah/jenis faskes | uji tingkat penandaan per segmen pada pilot (belum diimplementasikan) |
| Klaim kemampuan berlebihan | metrik sintetis selalu dilabeli sintetis; tidak ada klaim akurasi pada data BPJS |
