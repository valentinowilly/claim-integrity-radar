# Matriks Role dan Permission Claim Integrity Radar

**Status:** rancangan untuk MVP; belum diimplementasikan dan belum disetujui organisasi. Proposal menyebut RBAC dan pengguna berwenang, tetapi tidak menetapkan nama role atau permission detail.

## 1. Fakta implementasi saat ini

- Belum ada login/logout, provisioning akun, session, middleware role/permission, atau authenticated identity.
- Endpoint review menerima status/note tanpa identitas pengguna yang tervalidasi; service menetapkan label `demo_reviewer (unauthenticated)`.
- SQLite menyimpan status serta riwayat workflow review. Itu bukan security audit log.
- Role dan izin pada dokumen ini adalah desain target, bukan kemampuan aplikasi yang sudah tersedia.

## 2. Role MVP yang direkomendasikan

Gunakan **empat role aplikasi** untuk fase pertama. Role lebih rinci tidak perlu diimplementasikan sebelum pemilik proses menyetujui pemisahan tugas yang memang dibutuhkan.

| Role | Tanggung jawab | Batas utama |
|---|---|---|
| `platform_admin` | Membuat/menonaktifkan akun, menetapkan role, dan mengelola konfigurasi akses. | Tidak otomatis mendapat akses row-level klaim atau kewenangan menetapkan outcome review. |
| `data_operator` | Membuat batch, mengimpor data, memperbaiki mapping/validasi sesuai izin, menjalankan AnalysisRun, dan melihat status serta ringkasan proses. | Tidak mengubah hasil detektor, label ground truth, bobot scoring, atau outcome review. |
| `verifikator` | Membaca kasus sesuai scope, memeriksa alasan/cakupan, mengubah status review, mencatat catatan minimal, dan menandai kebutuhan bukti tambahan. | Tidak mengubah batch/run, konfigurasi detektor, atau outcome akhir di luar kewenangannya. |
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
| Buat batch dan validasi input | — secara default | W | — | — |
| Jalankan/mantau AnalysisRun | — secara default | W | R status | R status/A sesuai kebijakan |
| Baca ringkasan batch/run | R metadata | R batch sendiri | R sesuai assignment | R sesuai kewenangan |
| Baca detail alasan/coverage kasus | — secara default | Metadata minimum | R assigned | R assigned |
| Ubah status/catatan review | — | — | W assigned | W assigned/A |
| Mencatat outcome review | — | — | — secara default; hanya jika disahkan | W/A sesuai policy |
| Membaca review history | Log administrasi saja | Aktivitas batch sendiri | Review yang ditugaskan | Review dalam scope |
| Membaca security audit events | Akses administrasi sesuai policy | Aktivitas yang perlu untuk operasi | Aktivitas review sendiri | Aktivitas dalam scope |
| Mengubah threshold/weights/action policy | Tidak boleh langsung mengubah production; harus melalui approval dan versioning | — | — | Mengusulkan/menyetujui hanya bila diberi kewenangan |
| Mengakses ground truth evaluasi | — | — | — | — |

Akses detail klaim tidak otomatis diberikan kepada administrator hanya karena ia dapat mengelola akun. Akses row-level hanya diberikan jika memang diperlukan untuk tugas dan disetujui.

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
- `review_outcome` menyimpan hasil substantif yang disetujui kebijakan, misalnya `not_substantiated`, `clarified_or_corrected`, atau `inconclusive`. Label final harus dikonfirmasi pemilik proses; jangan membuat outcome otomatis dari skor detektor.
- Status API lama saat ini meliputi `pending_review`, `needs_more_evidence`, `not_substantiated`, `escalated`. `not_substantiated` semantik hasil, bukan status proses yang ideal. Saat perubahan dilakukan, tentukan migrasi/compatibility mapping dan pertahankan history; jangan melakukan migrasi otomatis tanpa tes.
- Eskalasi adalah status/proses tindak lanjut, bukan bukti fraud atau outcome final.

## 6. Scope untuk demo dan sampel BPJS

- MVP dapat menguji role dan permission menggunakan fixture sintetis.
- Jangan memproses/import sampel BPJS sebelum ada otorisasi penggunaan, mapping dan tujuan yang disetujui, kebijakan lokasi/retensi, akses, serta logging aman.
- Kontrol seperti MFA/SSO organisasi, break-glass, legal hold, dan multi-tenant policy adalah pertimbangan produksi; jangan menambahkannya sebagai prasyarat MVP lokal tanpa keputusan kebutuhan.

## 7. Status kontrol dalam implementasi aktual

| Kontrol | Status |
|---|---|
| Login/logout/session dan provisioning akun | Belum ada. |
| Tidak ada register publik / bootstrap administrator aman | Belum ada. |
| Enforcement role/permission pada API | Belum ada. |
| Scope batch/run/assignment dan akses row-level | Belum ada. |
| Aktor review dari sesi tervalidasi | Belum ada; label saat ini unauthenticated. |
| Review status/history lokal | Ada untuk fixture demo; bukan security audit log. |
| Outcome review terpisah | Belum ada. |
| Security audit events untuk batch/run/role/review | Belum ada. |
| Ground truth terisolasi dari aplikasi operasional | Evaluator offline terpisah; belum berarti ada kontrol akun/role operasional. |

## 8. Sumber

- Proposal, hlm. 11: RBAC dan audit trail sebagai rancangan; hlm. 19: pseudonimisasi, minimisasi, role access, enkripsi, human review.
- Repository: `AGENTS.md`; `backend/app/main.py`; `backend/app/api/routes/reviews.py`; `backend/app/services/reviews.py`; `backend/app/schemas/analytics.py`; `backend/tests/test_review_workflow.py`; `docs/api-contracts.md`.
