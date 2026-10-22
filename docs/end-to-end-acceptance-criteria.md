# Acceptance Criteria End-to-End Claim Integrity Radar

**Status:** kriteria untuk roadmap/review desain. Kriteria berlabel belum ada bukan fitur selesai. **P0 berarti wajib untuk MVP synthetic-only yang benar-benar end-to-end.** Akses/pemrosesan sampel BPJS memiliki hard gate terpisah berupa otorisasi penggunaan, mapping yang disetujui, dan kontrol data. Kategori: **I** = implementasi/test saat ini; **R** = rekomendasi; **C** = perlu konfirmasi resmi/ahli. Synthetic-only pass tidak memberi acceptance produksi.

## Prinsip evaluasi dan keputusan

- Sinyal, risk_score, risk_level, action lane, review_status, dan review_outcome adalah dimensi terpisah.
- Null, not applicable, not assessed, unavailable, partial dan truncated tidak boleh diubah menjadi zero/negative.
- Pola deteksi bukan bukti fraud.
- Proposal hlm. 14 (transkripsi visual pengguna) menyatakan angka dummy simulasi dan hasil kuantitatif belum tersedia/tervalidasi pada data riil. Angka bukan target, threshold, acceptance gate, atau baseline wajib.
- Seluruh eksperimen saat ini memakai data sintetis; tidak membuktikan efektivitas pada data JKN nyata.

## Matriks gap proposal vs panduan vs implementasi

| Area | Proposal | Panduan sample | Implementasi aktual | Gap/acceptance mendatang |
|---|---|---|---|---|
| Pengguna/auth | Verifikator/Tim Anti Kecurangan; RBAC dirancang (hlm. 6, 11, 19). | Tidak mengatur aplikasi. | Auth/RBAC tidak ada. | R/C: provisioning, least privilege, test authorization failure. |
| Import/schema | Adapter produksi dirancang (hlm. 11, 18). | Kamus FKRTL hlm. 18–25; `.dta` hanya disebut instruksi proyek sebagai file eksternal, bukan format yang dibuktikan isi dataset oleh audit ini. | Import/profile API tidak ada; generator saat ini tidak menyediakan CSV importer/exporter. | R/C: batch validation, mapping version, official schema; CSV dapat dipilih sebagai format pertukaran sintetis, bukan kemampuan saat ini. |
| Facility/capacity | Sintetis mempunyai jenis/kelas/tenaga/alat/jam (hlm. 11–12). | FKL05/06 lokasi; FKL07–09 kategori; unique facility/capacity tidak terbukti. | Benchmark synthetic punya metadata; API demo tidak. | C: facility key, staff/equipment/capacity; tanpa itu tiada capacity/facility ranking. |
| Repeat/similarity | Empat checker; twin/repeat (hlm. 7, 11). | PSTV01, FKL02–FKL19, FKL30 ada pada kamus; FKL47 berlabel biaya tagih provider dengan formula sirkular yang perlu klarifikasi; FKL48 biaya setelah verifikasi. | Detectors canonical hanya diuji synthetic. | R/C: mapping FKL47/field disahkan, coverage/privacy review, false-positive protocol. |
| Near duplicate | Proposal menyebut MinHash/LSH (hlm. 11–12). | Diagnosis/procedure sebagian tersedia; amount mapping belum jelas. | Blocking deterministik, cap/truncation; bukan MinHash/LSH. | I cap visible in code/tests; R/C validasi schema/in-scope use. |
| Temporal | Waktu seragam/repeat (hlm. 7, 11–12). | Tanggal datang/pulang, bukan jam/menit (hlm. 19). | Detector temporal memerlukan facility ID dan service type untuk pengelompokan; uniform-minute memerlukan timestamp. | R/C: profile tidak boleh mengklaim pemeriksaan hanya dari tanggal; mapping fasilitas/jenis waktu perlu bukti dan izin. |
| Evidence | Aturan bukti direncanakan (hlm. 11–12). | Evidence inventory tidak dicantumkan pada FKRTL dictionary. | Checker synthetic. | R/C: approved evidence metadata and service rules; absent field ≠ absent document. |
| Score/action | Weighted score, green/yellow/red dan priority (hlm. 8–12). | Tidak ada threshold/action policy. | Equal provisional weights; risk_level null; lanes absent. | C: calibrate/approve threshold, bias/impact review; dummy slide numbers not thresholds. |
| Priority | risk × value ÷ effort; effort berkas rekam medis (hlm. 9–10). | FKL47 berlabel biaya tagih provider; rumusnya perlu klarifikasi. FKL48 biaya verifikasi setelah verifikasi; facility ID tidak terbukti. | Synthetic facility unit with assumptions; runtime cannot build facility units. | R/C: klarifikasi FKL47/satuan, validasi facility key/effort; tanpa facility ID valid tidak ada ranking fasilitas. Kandidat kunjungan dipisahkan. |
| Review | Human decision and clarification/correction (hlm. 8, 19). | Tidak menetapkan app workflow. | Four process statuses + local SQLite history; no auth/outcome. | R: run-scoped workflow, authenticated actor, separate outcome and audit. |
| Evaluation | Three approaches/metrics; page 14 dummy per transkripsi pengguna; real validation future. | No ground truth in schema dictionary. | Offline synthetic evaluator; API returns insufficient_data. | I synthetic-only; R/C authorized independent labels/protocol before real claims. |
| Scale | Hundreds of thousands/day proposed but not tested (hlm. 18). | Schema guide not throughput spec. | Small runtime demo; 120k generator/evaluator separate. | R: performance/recovery tests in approved representative environment. |

## P0 — Governance, compatibility, and pipeline foundation

| ID | Testable acceptance criterion | Current evidence |
|---|---|---|
| P0-01 | Owner approves role/permission and authority; public signup disabled; administrator bootstrap has no hardcoded/default credential; backend tests deny unauthenticated and cross-assignment access. | R/C: no auth implemented; required before authorized sample data. |
| P0-01a | Session tests prove logout revokes access, disabled accounts are denied on the next protected request, and role changes take effect according to the approved session policy. | R/C: no session or account lifecycle implementation. |
| P0-01b | Review/import/run actor is derived from validated server session; forged identity/role fields in request bodies are rejected or ignored and never determine attribution. | R/C: current demo review actor is unauthenticated server label. |
| P0-02 | Data-use authorization, purpose, environment, retention/deletion, incident process documented before sample access. | R/C: this audit touched guide only, not sample data. |
| P0-03 | Kontrak mapping untuk fixture sintetis terdokumentasi dan berversi. Sebelum mode BPJS sample-compatible dibuka, mapping resmi, perbedaan FKL05/FKL05_NEW, formula/satuan/waktu FKL47, join FKL02, dan semantik key/null harus dikonfirmasi. Jangan mewajibkan FKL05_NEW bila mapping resmi menggunakan FKL05. | R/C: gap skema nyata tetap memblokir mode sampel terkait, tetapi tidak menghalangi pengembangan synthetic-only. |
| P0-04 | Import profiler returns aggregate errors only; no source rows, participant IDs, local paths or secrets in logs/API. | R: importer absent. |
| P0-05 | DataBatch transitions persisted; rejected/partial profiles cannot silently run unsupported checks; changed data/mapping creates immutable new version. Source input type is explicit (`.dta` sample profile only when authorized/supported; CSV synthetic exchange only if implemented); errors expose aggregate safe diagnostics. | R: no DataBatch/importer; current generator is Python-object API. |
| P0-06 | Run manifest stores batch ID/version, digest, mapping, detector/config, scoring/policy/priority versions, status, times, coverage and result references; retries create a new run; partial/failure states are persisted. GET by run ID returns stored results and never silently reruns detectors. | R: no AnalysisRun persistence; current GET recomputes synthetic snapshot. |
| P0-07 | Profile capability matrix applies; statuses distinguish triggered/not-triggered-in-assessed-scope, N/A, unassessed, unavailable, partial/truncated. | I for synthetic pipeline; R for import profile. |
| P0-08 | Ground truth is excluded from operational detector/scoring/API; regression test rejects forbidden label fields. | I: evaluator checks feature keys; scoring/detector interfaces omit labels. |
| P0-09 | UI/API tidak menyebut sinyal sebagai fraud terbukti; null tetap null. MVP synthetic-only harus memiliki action policy demo yang eksplisit, provisional, berversi, dan diuji untuk hijau/kuning/merah serta kondisi tidak dapat merekomendasikan; labeli sebagai aturan demo yang belum divalidasi domain. `risk_level` tetap null sampai definisi threshold terpisah disetujui. Mode BPJS tidak boleh menggunakan action policy demo; policy operasional memerlukan persetujuan domain. | I: risk_level null dan action lane belum ada. R/C: policy belum disetujui/diimplementasikan. |
| P0-10 | Case/review key is run-scoped; reusing source IDs cannot attach old review to a new finding. Run, finding, current review and each history event retain their run/case relation across reload. | R: current case IDs stable only for fixed demo. |
| P0-11 | Review write requires authenticated actor from session; append-only history records actor, time, previous/new process status and note policy. `review_status` is separate from `review_outcome`; outcomes are recorded only under an approved taxonomy. Security audit events cover batch, run, role and review actions with minimized fields. | I only synthetic local review events; no auth/security audit log or separate outcome. |
| P0-12 | API schema covers loading/empty/error/unavailable/partial and provenance; no hardcoded success metrics. | I existing API contract tests; future run APIs absent. |
| P0-13 | Browser/API E2E using synthetic fixture covers login/logout, forbidden role action, import→validation→run→results→queue→detail→review→reload; verifies run-scoped persistence, partial/N/A coverage, and unavailable/error state. | R: current tests are partial API smoke and user-reported manual visual check; no full import/run/auth E2E. |

## P1 — Review workflow and observability

| ID | Testable acceptance criterion | Status |
|---|---|---|
| P1-01 | Reviewer sees assigned run/case, source profile, reasons, safe evidence and coverage in same run scope. | R; current UI shows demo snapshot. |
| P1-02 | Search/filter/page use server response with stable run-scoped IDs; sorting does not imply validated priority if unavailable. | I for synthetic API; extend for persisted runs. |
| P1-03 | Perluas workflow setelah pemisahan field P0: transition matrix lengkap, reopen/close/reassignment, validasi taxonomy outcome oleh pemilik proses, dan tes migrasi legacy history. | R/C setelah implementasi pemisahan dasar P0. |
| P1-04 | Evidence reference/access follows role; raw record not duplicated into review store. | I separate review SQLite demo; R secure evidence store. |
| P1-05 | Structured API errors exclude sensitive values; UI distinguishes error, empty and unavailable. | I for current contracts; extend auth/batch/run. |
| P1-06 | Run history reports complete/partial/N/A/unassessed/truncation per detector. | I coverage in snapshot; R persisted history. |
| P1-07 | Audit trail records config changes, case access, reviews, outcomes, exports, admin actions. | R; current SQLite is review history only. |
| P1-08 | Extend E2E coverage to narrow viewports, interruption/recovery, concurrent reviews, retention/archival and longer run history, using isolated synthetic fixtures. | R after core P0 E2E passes. |

P0 authentication/RBAC, DataBatch, AnalysisRun persistence, review linkage, and a UI/API journey are required to call the **synthetic-only MVP** end-to-end. Separate hard gates (data-use authorization, approved source mapping, privacy/retention and secure logging) must pass before any BPJS sample file is imported or processed. These two acceptance contexts must not be conflated. Browser tests do not substitute for backend authorization tests.

## P2 — Evaluation, fairness, and operational readiness

| ID | Testable acceptance criterion | Status |
|---|---|---|
| P2-01 | Domain experts approve rule, schema mapping, capacity/evidence assumptions and false-positive protocol per service. | R/C. |
| P2-02 | Evaluation protocol freezes label source, eligible population, unassessed handling, grouping, seeds, K/budget and version before result inspection. | I for synthetic v4 evaluator; R/C operational. |
| P2-03 | Independent authorized ground truth exists and is linked without feature leakage. | R/C; current labels are scenario-created truth. |
| P2-04 | Baselines, uncertainty, subgroup burden, coverage/truncation and sensitivity reported; slide dummy numbers never used as target. | R/C; synthetic metrics are not world performance. |
| P2-05 | Load, memory, concurrency, durability, recovery, backup and retention pass approved targets. | R; generator row count alone is not detector/API scale evidence. |
| P2-06 | Authorized user acceptance confirms usability, explanations and human-owned decisions. | R/C; proposal states no pilot (hlm. 13, 17). |
| P2-07 | Deployment, encryption, federation, secrets, monitoring, vulnerability management and support approved. | R; local prototype not production-ready. |

## Bukti acceptance saat ini

- **Backend:** test suite previously 68 passed at Stage 18; tests cover API, review, detector/scoring/priority and synthetic evaluation.
- **Frontend:** production build succeeded previously. Visual pass for Stage 18 is user-reported, not a browser artifact in repository.
- **Runtime:** synthetic demo snapshot only; review uses local SQLite. Offline benchmark/evaluator is separate from runtime API.
- **Bukan bukti:** angka dummy proposal hlm. 14; generator mencapai row target; tidak adanya sinyal; kosongnya facility priority pada demo.

## Sumber

- Proposal hlm. 2, 6–13, 14 (transkripsi visual pengguna; dummy/unverified), 16–19.
- Panduan hlm. 6–7, 18–25, 30–31.
- Repository AGENTS.md; docs/api-contracts.md, analytics-spec.md, synthetic-data-spec.md, evaluation-spec.md; backend/app, backend/tests, frontend/src dan README.
