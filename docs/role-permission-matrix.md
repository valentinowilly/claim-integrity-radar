# Matriks Role dan Permission Claim Integrity Radar

**Status:** empat role dan permission adalah baseline prototipe lokal yang belum disetujui organisasi. Untuk demo E2E sintetis, `platform_admin` memiliki semua permission aplikasi yang saat ini terimplementasi. Perluasan ini tidak memberikan akses atau klaim kompatibilitas terhadap data BPJS asli.

## 1. Fakta implementasi saat ini

- Login/logout, provisioning akun satu kali, sesi cookie, permission backend, dan principal terautentikasi tersedia sebagai prototipe lokal.
- Review API mengambil aktor dari principal server; riwayat review dan event keamanan tersimpan lokal.
- Batch sintetis memiliki permission terpisah, persistence SQLite, dan metadata-only API. Scope assignment belum tersedia.
- Role dan izin tetap baseline desain, bukan kebijakan organisasi yang disahkan.

## 2. Role MVP yang direkomendasikan

Gunakan **empat role aplikasi** untuk fase pertama. Role lebih rinci tidak perlu diimplementasikan sebelum pemilik proses menyetujui pemisahan tugas yang memang dibutuhkan.

| Role | Tanggung jawab | Batas utama |
|---|---|---|
| `platform_admin` | Menjalankan seluruh workflow yang sudah tersedia pada demo sintetis, termasuk administrasi akun, impor batch, run, hasil, kasus, dan review/outcome. | Full access berlaku hanya dalam shared synthetic prototype; tidak ada assignment scope dan bukan otorisasi untuk data BPJS atau data operasional. |
| `data_operator` | Membuat batch, mengimpor data, memperbaiki mapping/validasi sesuai izin, menjalankan AnalysisRun, dan melihat status serta ringkasan proses. | Tidak mengubah hasil detektor, label ground truth, bobot scoring, atau outcome review. |
| `verifikator` | Peran peninjau tunggal dalam prototipe: membaca kasus, mengubah status review, mencatat outcome (benar/ternyata wajar), dan mencatat hasil audit resmi beserta rinciannya (`review:manage`). | Tidak mengubah batch/run, konfigurasi detektor, atau akun pengguna. |
| `audit_lead` | Meninjau eskalasi, menugaskan/menutup review, mencatat outcome manusia yang diizinkan kebijakan, serta membaca riwayat terkait. | Tidak mengubah skor historis; tindakan tetap harus beralasan dan tercatat. |

### Yang bukan role aplikasi pada MVP

- **Read-only auditor** adalah kumpulan permission baca-saja yang dapat diberikan pada scope tertentu, bukan role wajib terpisah.
- **Analyst/data steward** digabung ke `data_operator` untuk MVP. Dapat dipisah kelak jika perlu separation of duties.
- **Review supervisor** digabung ke `audit_lead` untuk MVP.
- **Evaluation steward** bukan akun aplikasi operasional. Ground truth dan evaluasi berada di tool/environment terpisah, tidak dapat diakses dari workflow reviewer.

Perubahan ke role yang lebih banyak harus didasarkan pada struktur kewenangan yang disetujui BPJS/pemilik proses, bukan dibuat hanya untuk menambah kompleksitas matriks.

## 3. Matriks permission MVP

R = baca; W = buat/ubah dalam scope; A = menyetujui/menugaskan; — = tidak diizinkan. Semua permission diperiksa oleh backend dan dibatasi pada batch, run, assignment, serta field yang diizinkan.

| Kapabilitas | Admin | Data operator | Verifikator | Audit lead |
|---|---:|---:|---:|---:|
| Kelola akun dan role | W | — | — | — |
| Baca/ubah konfigurasi akses | W | — | — | — |
| Mengusulkan mapping untuk profil sintetis | A | W | — | R |
| Menyetujui mapping yang dapat dipakai pada profil sumber | A sesuai otorisasi | W hanya pada mapping yang diizinkan | — | R/konfirmasi domain |
| Buat batch dan validasi input sintetis v1 | W (`batches:write`) | W (`batches:write`) | — | — |
| Jalankan/mantau AnalysisRun | W (`runs:write`) | W (`runs:write`) | R status | R status |
| Baca metadata/ringkasan batch | R metadata sintetis | R seluruh batch sintetis | R metadata sintetis | R metadata sintetis |
| Baca metadata/status run (`runs:read`) | R metadata/coverage | R metadata/coverage | R metadata/coverage | R metadata/coverage |
| Baca hasil run (`runs:results:read`) | R hasil sintetis bersama | — | R hasil sintetis bersama | R hasil sintetis bersama |
| Baca detail alasan/coverage kasus | R sintetis | — | R hasil sintetis bersama | R hasil sintetis bersama |
| Ubah status/catatan review | W (`review:write`) | — | W (`review:write`) | W (`review:write`) |
| Mencatat outcome review | W sementara (`review:manage`) | — | — secara default | W sementara (`review:manage`) |
| Membaca review history | R review sintetis | — | R review sintetis | R review sintetis |
| Membaca security audit events | Permission ada; API baca belum tersedia | — | — | — |
| Mengubah threshold/weights/action policy | Tidak boleh langsung mengubah production; harus melalui approval dan versioning | — | — | Mengusulkan/menyetujui hanya bila diberi kewenangan |
| Mengakses ground truth evaluasi | — | — | — | — |

`platform_admin` menerima akses operasional penuh agar satu akun dapat menjalankan demo E2E sintetis secara mandiri. Ini asumsi prototipe yang perlu ditinjau pemilik proses/security. Semua permission tetap ditegakkan backend melalui dependency permission yang sama; tidak ada bypass per endpoint. Batch/run/review sintetis tetap shared tanpa assignment scope. Jangan gunakan konfigurasi ini untuk data BPJS atau data operasional.

## 4. Kontrol autentikasi dan provisioning

1. **Tidak ada registrasi publik.** Akun dibuat/diaktifkan secara terkontrol oleh admin berwenang.
2. Bootstrap admin awal tidak boleh memakai username/password default atau credential hardcoded. Gunakan prosedur setup/operator yang disetujui, secret yang dimasukkan di luar source code, dan tutup bootstrap setelah berhasil.
3. Backend memvalidasi sesi pada setiap endpoint terlindungi dan menegakkan role serta object/assignment scope. Menyembunyikan tombol di frontend bukan kontrol keamanan.
4. Logout mencabut/mengakhiri sesi sesuai mekanisme sesi; akun yang dinonaktifkan harus kehilangan akses pada request terlindungi berikutnya.
5. Pelaku pada import/run/review/admin action diambil dari sesi tervalidasi di server. Jangan menerima `reviewer_id`, nama, atau role dari payload sebagai sumber identitas.
6. Review history mencatat aktor, timestamp, status sebelumnya/baru, dan catatan yang telah dimininimalkan. Security audit event terpisah mencatat peristiwa administratif dan keamanan.
7. Error/log tidak boleh mengandung row klaim, token peserta, kredensial, path lokal, atau stack trace yang ditujukan ke pengguna.
8. Ground truth evaluator terpisah dari aplikasi operasional agar label tidak bocor ke detektor, scoring, ranking, atau reviewer.

## 5. Review status dan outcome

Tahap kerja dan kesimpulan manusia harus terpisah.

- Target `review_status`: `pending_review`, `in_review`, `awaiting_evidence`, `escalated`, `closed`.
- API run-scoped memisahkan status `pending_review`, `in_review`, `awaiting_evidence`, `escalated`, `closed` dari outcome sementara `signal_supported`, `signal_not_supported`, `inconclusive`. Dalam prototipe, outcome dan hasil audit resmi dapat dicatat `platform_admin`, `verifikator`, dan `audit_lead` melalui `review:manage`; satu peran peninjau mengisi semua langkah. Pemisahan tugas (empat mata) dapat dipulihkan dengan mencabut `review:manage` dari verifikator. Ini baseline prototipe, bukan delegasi kewenangan yang disahkan.
- Run-scoped review menggunakan `(run_id, case_id)` dan status awal `pending_review`; legacy status/history tidak dipetakan atau ditulis ulang. Scope tetap `shared_synthetic`, tanpa assignment.
- Status API lama saat ini meliputi `pending_review`, `needs_more_evidence`, `not_substantiated`, `escalated`. `not_substantiated` semantik hasil, bukan status proses yang ideal. Saat perubahan dilakukan, tentukan migrasi/compatibility mapping dan pertahankan history; jangan melakukan migrasi otomatis tanpa tes.
- Eskalasi adalah status/proses tindak lanjut, bukan bukti fraud atau outcome final.
- **Hasil audit berwenang** (`confirmed_issue`, `confirmed_no_issue`) dicatat terpisah dari outcome reviewer melalui `POST /api/v1/runs/{run_id}/cases/{case_id}/review/audit-confirmation`, hanya oleh `review:manage` (`audit_lead`, `platform_admin`), dengan CSRF, rujukan audit wajib (kode rujukan singkat, bukan data klaim; disimpan sebagaimana diketik, tidak diverifikasi ke sistem audit eksternal), dan hanya setelah kasus memiliki rekaman tinjauan. Rekaman bersifat append-only. Outcome reviewer `signal_supported` tidak pernah otomatis menjadi hasil audit. **Least privilege:** rujukan audit, catatan audit, dan pencatatnya hanya dikembalikan kepada `review:manage`; peran `review:read` lain hanya melihat status hasil audit (mis. "Issue confirmed by authorized audit") agar tidak meninjau ulang kasus yang sudah diaudit. Perluasan akses rujukan memerlukan alur kerja yang disetujui pemilik proses. Siapa yang berwenang menerbitkan hasil audit adalah keputusan organisasi di luar aplikasi.

## 6. Scope untuk demo dan sampel BPJS

- MVP dapat menguji role dan permission menggunakan fixture sintetis.
- Jangan memproses/import sampel BPJS sebelum ada otorisasi penggunaan, mapping dan tujuan yang disetujui, kebijakan lokasi/retensi, akses, serta logging aman.
- Kontrol seperti MFA/SSO organisasi, break-glass, legal hold, dan multi-tenant policy adalah pertimbangan produksi; jangan menambahkannya sebagai prasyarat MVP lokal tanpa keputusan kebutuhan.

## 7. Status kontrol dalam implementasi aktual (setelah P0 Stage 6)

| Kontrol | Status |
|---|---|
| Login/logout/session dan provisioning akun | Tersedia sebagai prototipe lokal: password scrypt, sesi cookie dengan token hanya tersimpan sebagai hash, expiry/revocation, endpoint login/logout/me, dan provisioning admin terproteksi. |
| Tidak ada register publik / bootstrap administrator aman | Tersedia: tidak ada register publik; bootstrap CLI memerlukan secret dari environment dan berhasil satu kali per database. Kebijakan delivery secret masih perlu persetujuan. |
| Enforcement role/permission pada API | Tersedia untuk analytics/review/auth provisioning, batch, dan AnalysisRun. `platform_admin` memiliki semua permission terimplementasi untuk demo sintetis; `data_operator` tetap dapat menulis batch/run tetapi tidak membaca hasil; verifikator/audit lead dapat membaca hasil serta mencatat outcome dan hasil audit (`review:manage`). Baseline sementara. |
| Scope batch/run/assignment dan akses row-level | Belum ada. Batch sintetis bersama; hasil run dapat dibaca platform_admin/verifikator/audit lead tanpa assignment. Run-scoped review memastikan case ada pada run, tetapi bukan kontrol assignment atau akses data operasional. |
| Aktor review dari sesi tervalidasi | Tersedia: actor ID dan reviewer label diambil dari principal server; payload aktor ditolak. |
| Review status/history lokal | Legacy snapshot workflow tetap tersedia. Run-scoped review dan event history persisten berada terpisah pada SQLite batch/run; security audit event disimpan pada tabel berbeda tanpa note. |
| Outcome review terpisah | Tersedia pada API run-scoped untuk `platform_admin` dan `audit_lead` (`review:manage`), dengan kosakata sementara `signal_supported`, `signal_not_supported`, `inconclusive`; belum disahkan. Tidak ada migrasi dari status legacy. |
| Security audit events | Auth, legacy/run-scoped review, impor batch, serta pembuatan dan status terminal AnalysisRun dicatat pada tabel SQLite terpisah sesuai store. Belum ada API baca audit log. |
| Ground truth terisolasi dari aplikasi operasional | Evaluator offline terpisah; belum berarti ada kontrol akun/role operasional. |

## 8. Sumber

- Proposal, hlm. 11: RBAC dan audit trail sebagai rancangan; hlm. 19: pseudonimisasi, minimisasi, role access, enkripsi, human review.
- Repository: `AGENTS.md`; `backend/app/main.py`; `backend/app/api/routes/reviews.py`; `backend/app/services/reviews.py`; `backend/app/schemas/analytics.py`; `backend/tests/test_review_workflow.py`; `docs/api-contracts.md`.
