# Protokol pilot audit — pengumpulan outcome nyata

Status: **disiapkan, belum dijalankan.** Pilot ini membutuhkan auditor berwenang, izin penggunaan data, dan sumber hasil audit resmi yang berada di luar aplikasi. Tidak ada outcome audit yang dibuat, disimulasikan, atau diklaim dalam dokumen ini.

## 1. Tujuan

Mengumpulkan outcome tinjauan dan hasil audit berwenang untuk kandidat Claim Integrity Radar pada sampel FKRTL lokal, agar sinyal transparan (repeat_service_v1, similar-claim screening, duration screen, ranking ML eksploratif) dapat dievaluasi pada data aktual untuk pertama kalinya.

## 2. Taksonomi outcome (sesuai implementasi)

| Makna | Cara dicatat di aplikasi | Siapa |
|---|---|---|
| Potensi masalah — perlu bukti lanjutan | status `awaiting_evidence` (dapat disertai outcome `signal_supported`) | verifikator (`review:write`) / audit lead |
| Tidak ditemukan masalah setelah tinjauan | outcome `signal_not_supported` | audit lead (`review:manage`) |
| Dieskalasi untuk investigasi lanjutan | status `escalated` | verifikator / audit lead |
| Tidak dapat disimpulkan / bukti tidak cukup | outcome `inconclusive` | audit lead |
| **Hasil audit terkonfirmasi** | rekaman terpisah `confirmed_issue` / `confirmed_no_issue` dengan **rujukan audit wajib** | audit lead / admin (`review:manage`), hanya setelah ada rekaman tinjauan |

Outcome reviewer (`signal_supported`) **bukan** temuan terkonfirmasi. Hanya rekaman hasil audit dengan rujukan ke hasil audit berwenang yang boleh disebut terkonfirmasi. Semua rekaman tercatat dengan waktu dan aktor, bersifat append-only, dan tidak mengubah hasil analisis.

## 3. Sampling

1. **Run:** satu run FKRTL per jendela tanggal yang disepakati (konfigurasi server; hasil hanya berlaku untuk jendela tersebut). Catat `run_id`, jendela, dan versi profil dari halaman Claim Data.
2. **Kandidat:** sampel acak berstrata per pemeriksaan (repeat, similar-claim screening, duration screen, Top-K ranking ML), jumlah per strata ditetapkan sebelum tinjauan; jangan memilih kandidat berdasarkan kesan reviewer.
3. **Kontrol (mengurangi bias seleksi dan verifikasi):** sampel acak record yang **dinilai tetapi tidak ditandai** dan record **tidak dinilai** (mis. FKL30 kosong) dari jendela yang sama. **Keterbatasan aplikasi:** halaman Case Review hanya menerima kasus kandidat run, sehingga kontrol ditinjau di sistem audit berwenang; aplikasi hanya menerima ringkasan agregat outcome kontrol.
4. **Pembutaan sebagian:** bila memungkinkan, auditor yang menerbitkan hasil audit tidak diberi tahu strata (kandidat/kontrol) asal kasus.

## 4. Pencatatan

* Reviewer mencatat status, outcome, dan catatan singkat di Case Review. Catatan tidak boleh memuat nomor peserta, ID kunjungan, nilai klaim, nama, atau isi dokumen; validasi server menolak deret angka panjang dan istilah identifier.
* Bukti dirujuk dengan **kode rujukan** dokumen/berkas audit (mis. `AUD-2026/014`), bukan salinan isinya.
* Hasil audit terkonfirmasi dicatat di panel "Authorized audit result" hanya setelah hasil audit resmi terbit, dengan rujukan audit tersebut. Aplikasi **tidak memverifikasi** rujukan ke sistem audit; kebenaran rujukan menjadi tanggung jawab audit lead dan dicek ulang dalam rekonsiliasi pilot.
* Tidak ada ekspor per kasus. Rekap pilot memakai hitungan agregat.

## 5. Ketidaksepakatan dan inconclusive

* Sekitar 20% kandidat ditinjau dua reviewer secara independen (status/outcome dicatat sebelum melihat penilaian pihak lain, di luar aplikasi bila perlu).
* Ketidaksepakatan → status `escalated` → adjudikasi audit lead; keputusan akhir dan alasannya dicatat sebagai catatan singkat.
* `inconclusive` dipertahankan sebagai kategori tersendiri; tidak dibuang dan tidak digabung ke "tidak ada masalah".

## 6. Metrik agregat yang boleh dilaporkan

* Jumlah kasus per strata dan per outcome/hasil audit, termasuk inconclusive dan yang belum selesai.
* Proporsi `confirmed_issue` di antara kasus yang memiliki hasil audit, per strata, dengan interval kepercayaan sampel.
* Perbandingan proporsi kandidat vs kontrol (hanya bila kontrol diaudit dengan protokol yang sama).
* Kesepakatan antar-reviewer pada subset ganda (mis. Cohen's kappa).
* Waktu tinjauan per kasus, jumlah eskalasi.

## 7. Kesimpulan yang dilarang sampai label terverifikasi tersedia

* Akurasi, presisi, recall, atau tingkat fraud untuk populasi BPJS.
* Recall atau "tidak ada fraud" untuk record yang tidak ditandai atau tidak dinilai.
* Peringkat fasilitas (tidak ada ID fasilitas terverifikasi).
* Ekstrapolasi ke populasi tanpa bobot sampel (PSTV15) dan desain sampling yang disetujui.
* Menyebut outcome reviewer sebagai temuan fraud.

## 8. Prasyarat eksternal

Auditor berwenang dan penunjukan peran `audit_lead`; izin penggunaan data untuk tinjauan berbasis kasus; akses ke berkas klaim/rekam medis melalui saluran resmi; definisi resmi "hasil audit terkonfirmasi" dan sumbernya; persetujuan protokol oleh pemilik proses.
