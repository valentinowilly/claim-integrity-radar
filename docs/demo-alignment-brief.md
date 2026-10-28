# Brief presentasi dan demo — Claim Integrity Radar (RC)

Untuk tim, sebagai pegangan presentasi/demo berikutnya. Proposal yang diajukan tetap arsip historis dan tidak diubah; bila isi proposal berbeda dengan brief ini, yang berlaku untuk demo adalah brief ini dan `docs/RELEASE-CANDIDATE.md` (§2.1 crosswalk).

## 1. Masalah dan kategori

Kategori Healthkathon: **Efisiensi Risiko pada Fasilitas Kesehatan** (tema *Detect Smarter, Protect JKN*). Modus resmi yang disentuh: #11 Repeat billing, #5 Cloning, #6 Phantom billing, #12 Prolonged length of stay; #17 Klaim fiktif obat/alkes/tindakan disebut proposal tetapi belum ada detektornya. Volume klaim besar, kapasitas auditor terbatas: pertanyaannya bukan hanya "apakah ada fraud", tetapi "berkas mana yang ditinjau lebih dulu, dan mengapa".

## 2. Peran CIR

Lapisan **pendukung keputusan audit** yang dapat dijelaskan: membentuk kandidat peninjauan, menunjukkan alasan dan cakupan setiap pemeriksaan, mengurutkan antrean, dan mencatat keputusan manusia. CIR **tidak** menetapkan fraud dan bukan pengganti sistem verifikasi BPJS.

## 3. Yang benar-benar ditunjukkan RC

* Alur lengkap: data → run (hasil tersimpan, tidak berubah) → cakupan per pemeriksaan → antrean → Case Review → status/outcome reviewer → hasil audit berwenang terpisah.
* Pada sampel FKRTL lokal: skrining pola layanan berulang (`repeat-service-v1`) untuk **potensi** Repeat Billing; similar-claim screening eksploratif (Cloning); layar durasi rawat eksploratif (terkait #12 Prolonged length of stay); ranking ML eksploratif.
* Cakupan jujur: setiap record dinyatakan ditandai, dinilai tidak ditandai, **tidak dinilai** (mis. FKL30 kosong, pencarian terpotong), atau **tidak berlaku**. Nol kandidat bukan berarti nol risiko.
* Smoke test lokal pada kode final (agregat): 35.565 dan 137.833 klaim per jendela; tanpa ID mentah di UI/API.

## 4. Yang synthetic-only atau eksploratif

| Hal | Status | Cara menyebutnya |
|---|---|---|
| Kapasitas, pola waktu (jendela 3 hari kalender, menit seragam), kelengkapan bukti — modus Phantom | synthetic-only | "perilaku pemeriksa pada skenario sintetis" |
| Similar-claim screening — modus Cloning | eksploratif, terpotong pada data nyata | "skrining kemiripan", bukan "deteksi klon" |
| Repeat | sinyal skrining | "pola layanan berulang, perlu dibandingkan berkasnya" |
| Ranking ML (Isolation Forest) | eksploratif | "alat bantu urutan", bukan probabilitas fraud |
| Jalur hijau/kuning/merah | rekomendasi provisional CIR | bukan kebijakan BPJS |
| Obat/alkes (#17) | tidak ada detektor | "di luar cakupan RC; butuh data item dan penyerahan" |

**Angka sintetis yang boleh dikutip** (benchmark empat modus, 10 seed, ~20.115 record, unit = klaim; label adalah kontrak simulasi, bukan label fraud; tidak berlaku untuk data BPJS):

* Repeat `repeat-service-v1`: presisi 0,70; recall pada record yang dinilai 1,00; prevalensi kohort 0,027. False positive yang diketahui: rujukan sah dengan kunci sama.
* Similar-claim screening: presisi 0,12; recall 0,85; menandai ~33% klaim latar belakang — tidak dapat memisahkan salinan dari klaim rutin.
* Kelengkapan bukti (Phantom, sintetis): presisi 0,49; recall pada record yang dinilai 0,48.

Presisi = TP/(TP+FP); recall pada record dinilai = TP/(TP+FN). Definisi lengkap: `docs/detection-semantics.md`.

**Jangan mengutip** angka proposal hlm. 14 dan 16 (Precision@K 78%, 16 kasus per 100 berkas, "≈4× audit acak", Rp15,6 juta): semuanya dummy simulasi, bukan hasil terukur.

## 5. Yang tidak didukung skema sampel BPJS

Tidak ada ID fasilitas unik, jam/menit layanan, status/riwayat penagihan dan pembayaran, inventaris dokumen pendukung, rincian item obat/alkes, atau catatan penyerahan. FKL48 adalah biaya pasca-verifikasi (tidak dipakai); semantik FKL47 belum dikonfirmasi (tidak dipakai untuk prioritas). Karena itu: tidak ada peringkat fasilitas, tidak ada skor prioritas rupiah pada data nyata, dan Repeat tidak dapat menunjukkan bahwa klaim sebelumnya "sudah ditagih dan dibayar". Dataset FKTP Non Kapitasi punya ID kunjungan sendiri (`PNK02`), tetapi belum ada kunci tervalidasi ke `FKL02`.

## 6. Mengapa eksperimen AI tidak dipromosikan

Eksperimen terpra-registrasi di salinan terpisah (bukan bagian RC):

* Peringkat klaim tidak biasa (Task M salinan eksperimen: 30 seed uji akhir yang sama (101–130), generator sintetis terkalibrasi (Amandemen 3), unit = klaim, P@25 = proporsi target berlabel di antara 25 klaim teratas per seed, dirata-rata antar seed): Isolation Forest yang ada di RC (v1) 0,32; versi eksperimen v2 0,46; heuristik jumlah kunjungan 0,82 dan deviasi lama rawat 0,81 — model kalah dari sinyal transparan. Bukan kinerja pada data BPJS. Versi v2 tidak dipindahkan ke sistem utama.
* Model supervised (termasuk gradient boosting untuk prioritas pasangan Cloning): keunggulan pada Cloning sintetis berasal dari pola injeksi generator dan gugur pada uji ketahanan (subtipe yang ditahan dari training tidak ditemukan); pada Repeat kalah dari aturan transparan. Tidak ada model ini, maupun SHAP, di sistem utama.
* Gate data (Fase 6): field FKRTL tidak memuat informasi pembeda untuk Cloning/Phantom/obat-alkes; **no-go** untuk AI tambahan sampai ada label audit nyata dan data tambahan.

Pesan: "Kami menguji AI dengan jujur; sinyal transparan lebih baik pada data yang tersedia, jadi produk memakai sinyal yang dapat dijelaskan."

## 7. Manusia dan hasil audit

Outcome reviewer (`signal_supported`, `signal_not_supported`, `inconclusive`) **bukan** temuan terkonfirmasi. Hasil audit terkonfirmasi (`confirmed_issue` / `confirmed_no_issue`) dicatat terpisah oleh `review:manage`, dengan rujukan audit wajib, append-only. Aplikasi tidak memverifikasi rujukan ke sistem audit.

## 8. Jalan ke pilot dan produksi

Bergantung pada izin dan keterlibatan mitra: (1) izin resmi untuk pemrosesan per kasus dan untuk menampilkan keluaran turunan data nyata — akses portal data sampel tidak otomatis mencakupnya; (2) auditor berwenang dan pilot sesuai `docs/audit-pilot-protocol.md`; (3) label hasil audit terverifikasi; (4) konfirmasi FKL30/FKL47; (5) data tambahan (ID fasilitas, bukti registrasi, riwayat pengajuan, dispensing); (6) infrastruktur produksi, persetujuan kebijakan ambang, dan tinjauan keamanan independen.

Demo publik memakai **data sintetis**. Keluaran dari sampel BPJS hanya ditunjukkan sebagai agregat dan hanya bila izin mencakupnya.

## 9. Ketentuan data dan kriteria penilaian (materi panitia)

* **Data:** sesuai Participant Guide §12 dan prinsip panitia — jangan memakai data riil peserta JKN tanpa izin tertulis; data sample hanya untuk Healthkathon dan tidak disebarkan ke luar tim. Karena video diunggah ke YouTube, **seluruh layar demo di video memakai data sintetis**; jangan menampilkan run FKRTL, path lokal, atau angka turunan sampel tanpa konfirmasi panitia.
* **AI:** materi panitia meminta data peserta tidak dikirim ke AI publik dan hasil AI diverifikasi manusia; CIR tidak memakai LLM eksternal.

Tabel berikut adalah **penilaian internal tim**. Kriteria penerimaan RC internal terpenuhi menurut bukti tercatat (`docs/RELEASE-CANDIDATE.md` §8–§9, §11); penilaian kompetisi menjadi wewenang juri. Bobot dan rubrik resmi tidak dipublikasikan, sehingga kolom "Celah" adalah pertimbangan kompetitif internal, bukan urutan atau bobot kriteria resmi.

| Kriteria penilaian | Yang dapat ditunjukkan | Celah |
|---|---|---|
| Kreativitas & keunikan (GenAI/ML) | prioritas yang menjelaskan cakupan (dinilai/tidak dinilai/tidak berlaku); ML diuji jujur terhadap baseline transparan | tidak ada GenAI (keputusan RC); ML tidak mengungguli sinyal transparan — dilaporkan sebagai temuan evaluasi (RC §2.4) |
| Model bisnis | posisi sebagai modul pendukung verifikasi/audit klaim (proses BEA C03.04, berdampingan dengan VClaim/VIDI/AUDIA) | uraian: `docs/business-model.md`; belum ada estimasi biaya atau penghematan (menunggu pilot) |
| Dampak terukur | metrik sintetis dengan penyebut jelas; cakupan dan smoke test | tidak ada dampak terukur pada data nyata (perlu pilot) |
| Presentasi & komunikasi | brief ini | — |
| Kesiapan produk | 342 tes backend, build, E2E 4/4, RBAC + CSRF, audit trail append-only | tinjauan keamanan independen, infrastruktur produksi, uji bias per segmen belum ada |

**Uji bias** (dijanjikan proposal hlm. 19 dan prinsip panitia "uji bias antar segmen peserta dan wilayah") belum diimplementasikan; sebutkan sebagai langkah pilot, jangan diklaim.
