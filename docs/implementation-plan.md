# Rencana Implementasi

Rencana bertahap ini menjaga pengembangan dapat ditinjau. Tahap 1 adalah fondasi dokumentasi dan kontrak; rencana setelahnya belum memberi izin untuk mengubah kode atau mengakses dataset. Data sintetis digunakan untuk pengembangan, pengujian, screenshot, dan demo.

## Tahap 1 — Fondasi kontrak

**Cakupan:** instruksi proyek bernama `AGENTS.md`, kontrak endpoint, spesifikasi analitik, dan rencana implementasi.

**Selesai bila:** dokumen menetapkan bentuk respons/status/error, filtering dan pagination, alasan risiko dan batas analitik; contoh JSON diberi label ilustrasi; tidak ada angka yang diklaim sebagai hasil; skrip lama utuh.

**Pemeriksaan:** tinjau konsistensi lintas dokumen dan nama/path repository. Tidak menjalankan skrip analisis.

## Tahap 2 — Kerangka backend dan skema

**Cakupan:** FastAPI, konfigurasi aman, router health, model Pydantic yang sesuai kontrak, format error, serta adapter sumber data sintetis/lokal terpisah. Health check tidak membuka data.

**Selesai bila:** aplikasi dapat dijalankan melalui konfigurasi terdokumentasi; OpenAPI sesuai kontrak; sumber belum terkonfigurasi dinyatakan eksplisit; tidak ada path dataset tertanam atau data sensitif dalam log.

**Verifikasi:** uji health, validasi parameter/error, dan kontrak respons memakai fixture sintetis. Tidak memakai dataset BPJS.

## Tahap 3 — Mesin analitik terisolasi

**Cakupan:** definisi indikator di modul terpisah dari route dan repository; mulai dengan kandidat repeat dan pola serupa yang sudah ditinjau; agregasi pandas/NumPy seperlunya. Evaluasi scikit-learn hanya jika ada label dan rancangan evaluasi yang dapat diuji.

**Selesai bila:** tiap indikator memiliki versi, definisi kelayakan, alasan, field, dan keterbatasan; `FKL48` tidak menjadi prediktor pra-verifikasi; tidak ada asumsi ID fasilitas unik; indikator yang belum dibuat tetap ditandai rencana.

**Verifikasi:** unit test kasus sintetis termasuk duplikasi sah, missing value, batas normalisasi, dan variasi signature. Hasil uji sintetis diberi label yang jelas.

## Tahap 4 — API dashboard, analisis, antrean, dan evaluasi

**Cakupan:** endpoint summary, analysis, list/detail cases, evaluation; filter dan pagination tervalidasi; minimisasi data dan kebijakan akses untuk detail kasus.

**Selesai bila:** output berasal dari adapter aktif; status ketersediaan tepat; tidak ada angka default fiktif; daftar stabil dengan pagination deterministik; alasan tidak menyatakan fraud.

**Verifikasi:** tes kontrak dan integrasi endpoint memakai data sintetis dan kondisi sumber kosong/gagal. Evaluasi tanpa label acuan mengembalikan status belum memadai.

## Tahap 5 — Shell frontend dan halaman

**Cakupan:** React + TypeScript + Vite + Tailwind CSS + Recharts; routing untuk overview, analisis risiko, antrean audit, detail kasus, dan evaluasi; API client bertipe; state loading/error/empty.

**Selesai bila:** kelima halaman memakai kontrak backend; grafik hanya menampilkan data respons; sumber sintetis ditandai; aksesibilitas dasar dan layout responsif ditangani.

**Verifikasi:** typecheck/build frontend, tes komponen alur state, dan pemeriksaan visual pada respons ilustratif/sintetis yang jelas dilabeli.

## Tahap 6 — Integrasi dan ketahanan

**Cakupan:** sambungkan frontend-backend, konfigurasi CORS dan environment, logging aman, batas permintaan, pagination, dan dokumentasi operasi lokal.

**Selesai bila:** alur halaman bekerja terhadap API lokal; error backend ditampilkan aman; tidak ada payload/baris sensitif di log; data sintetis dan sumber lokal tidak tercampur.

**Verifikasi:** tes integrasi end-to-end sintetis, pemeriksaan log dan artefak repository, serta uji kegagalan sumber.

## Tahap 7 — Persiapan demo

**Cakupan:** skenario demo sintetis yang dapat diulang, label sumber data, panduan menjalankan, dan penjelasan batas penggunaan.

**Selesai bila:** semua angka demo dapat ditelusuri ke fixture sintetis; materi tidak mengesankan temuan nyata BPJS; dataset nyata tidak disalin atau disertakan; alur tinjauan manusia terlihat.

**Verifikasi:** jalankan demo dari awal dengan sumber sintetis, cocokkan tampilan dan API, periksa file/artefak yang akan dibagikan, dan pastikan tidak ada klaim metrik evaluasi tanpa label acuan.

## Gerbang integrasi dataset nyata

Integrasi data lokal nyata adalah pekerjaan terpisah. Sebelum dimulai, pastikan izin penggunaan, sumber/path yang dikonfigurasi lokal, field yang disetujui, minimisasi dan retensi, kontrol akses, serta cara membatasi log dan keluaran agregat. Jangan mengunggah atau memasukkan dataset ke repository. Tahap ini tidak mengizinkan agent menjalankan skrip analisis lama.

## Tahap 8 — Alur tinjauan auditor (backend)

**Cakupan:** status proses review, endpoint baca/perbarui, riwayat append-only, SQLite lokal terpisah dari hasil analitik, filter antrean `review_status`, dokumentasi kontrak dan tes terisolasi. Tidak mengubah frontend.

**Selesai bila:** status awal `pending_review`; hanya enum status proses yang diizinkan; catatan dibatasi; setiap update menghasilkan riwayat; ID harus berasal dari kandidat aktif; health check tidak menginisialisasi database; tes memakai database sementara; tidak ada status fraud terverifikasi.

**Verifikasi:** seluruh suite backend, validasi payload/error, persistensi setelah koneksi dibuat ulang, filter antrean, kebocoran data minimal, serta pemeriksaan bahwa health check tidak membuat database. Penyimpanan lokal demo bukan autentikasi atau sistem audit produksi.
