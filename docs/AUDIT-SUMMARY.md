# Ringkasan Audit Silang Tahap 20B

**Status:** ringkasan audit dokumentasi Tahap 20B. File ini berada di working tree untuk ditinjau; belum staged, committed, atau pushed. Dokumen ini bukan bukti implementasi fitur pada source code.

## Temuan yang diselesaikan dalam paket

1. Prioritas roadmap diselaraskan: P0 mencakup synthetic-only E2E (auth/RBAC, DataBatch, AnalysisRun persisten, action policy demo yang provisional/berversi, review linkage, dan tes perjalanan UI/API). Otorisasi/mapping dan kontrol data untuk sampel BPJS tetap menjadi hard gate terpisah sebelum file BPJS diproses.
2. Role MVP disederhanakan menjadi empat role aplikasi: `platform_admin`, `data_operator`, `verifikator`, `audit_lead`. Pemisahan `analyst`, `data_steward`, `review_supervisor`, `read_only_auditor`, dan `evaluation_steward` ditunda kecuali organisasi membutuhkannya. Evaluasi ground truth tetap offline/terisolasi.
3. State DataBatch tidak lagi berubah menjadi `analysis_locked` setiap kali analisis dijalankan; satu versi batch yang immutable dapat punya beberapa run.
4. Retry mengikuti prinsip immutable: run gagal bersifat terminal, dan retry membuat run baru dengan `retry_of_run_id`. Hasil run selesai tidak ditimpa.
5. Status proses review dibedakan dari outcome manusia. Legacy status `not_substantiated` ditandai sebagai semantik outcome yang perlu pemetaan migrasi terkontrol.
6. PSTV01 diperlakukan sebagai identifier sensitif: tidak ditampilkan/log. Ia dapat digunakan sebagai guard internal untuk repeat-billing yang memang membandingkan peserta sama, tetapi tidak menjadi signature generik untuk pola lintas peserta.

## Hal yang tetap belum terkonfirmasi (tidak diselesaikan dengan asumsi)

- Formula komponen/satuan/tipe dan waktu ketersediaan `FKL47`; `FKL48` tetap field pascaverifikasi dan bukan prediktor pra-verifikasi.
- Apakah `FKL05_NEW` ada pada versi sumber resmi selain kamus yang saat ini diperiksa.
- Join dan cardinality FKRTL ↔ diagnosis sekunder melalui `FKL02`.
- ID fasilitas yang valid, metadata kapasitas, jam/menit layanan, dan inventaris bukti.
- Kebijakan role/authority, taxonomy final review outcome, action lane dan threshold operasional.
- File `proposal-page14.png` tidak ada pada direktori referensi lokal yang diperiksa; angka slide tetap ditandai sebagai transkripsi visual/dummy, bukan hasil terukur.

## Hasil audit

Dokumen cukup kuat sebagai rancangan setelah koreksi di atas, tetapi bukan bukti implementasi end-to-end. Fitur auth, import/batch, AnalysisRun, outcome dan security audit log belum ada di source hingga checkpoint yang diaudit. Tidak ada source code yang diubah dalam paket ini. File dokumentasi audit ini sudah berada di working tree. Perubahan dokumentasi belum staged, committed, atau pushed.

