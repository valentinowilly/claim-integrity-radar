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
| Import/schema | Adapter produksi dirancang (hlm. 11, 18). | Kamus FKRTL hlm. 18–25; `.dta` hanya disebut instruksi proyek sebagai file eksternal, bukan format yang dibuktikan isi dataset oleh audit ini. | Synthetic CSV v1/DataBatch lokal tersedia; BPJS profile/import tetap tidak ada. Generator exporter menghasilkan fitur saja. | I: contract/import tes sintetis; R/C: mapping resmi BPJS dan otorisasi tetap hard gate. |
| Facility/capacity | Sintetis mempunyai jenis/kelas/tenaga/alat/jam (hlm. 11–12). | FKL05/06 lokasi; FKL07–09 kategori; unique facility/capacity tidak terbukti. | Benchmark synthetic punya metadata; API demo tidak. | C: facility key, staff/equipment/capacity; tanpa itu tiada capacity/facility ranking. |
| Repeat/similarity | Empat checker; twin/repeat (hlm. 7, 11). | PSTV01, FKL02–FKL19, FKL30 ada pada kamus; FKL47 berlabel biaya tagih provider dengan formula sirkular yang perlu klarifikasi; FKL48 biaya setelah verifikasi. | Detectors canonical hanya diuji synthetic. | R/C: mapping FKL47/field disahkan, coverage/privacy review, false-positive protocol. |
| Near duplicate | Proposal menyebut MinHash/LSH (hlm. 11–12). | Diagnosis/procedure sebagian tersedia; amount mapping belum jelas. | Blocking deterministik, cap/truncation; bukan MinHash/LSH. | I cap visible in code/tests; R/C validasi schema/in-scope use. |
| Temporal | Waktu seragam/repeat (hlm. 7, 11–12). | Tanggal datang/pulang, bukan jam/menit (hlm. 19). | Detector temporal memerlukan facility ID dan service type untuk pengelompokan; uniform-minute memerlukan timestamp. | R/C: profile tidak boleh mengklaim pemeriksaan hanya dari tanggal; mapping fasilitas/jenis waktu perlu bukti dan izin. |
| Evidence | Aturan bukti direncanakan (hlm. 11–12). | Evidence inventory tidak dicantumkan pada FKRTL dictionary. | Checker synthetic. | R/C: approved evidence metadata and service rules; absent field ≠ absent document. |
| Score/action | Weighted score, green/yellow/red dan priority (hlm. 8–12). | Tidak ada threshold/action policy. | Bobot sama provisional; `risk_level` null; policy lane demo `action-policy-demo-v1-provisional` tersimpan per AnalysisRun; batas 1/3 dan 2/3 belum divalidasi domain. | C: kalibrasi/persetujuan threshold dan dampak; angka dummy halaman 14 bukan threshold. |
| Priority | risk × value ÷ effort; effort berkas rekam medis (hlm. 9–10). | FKL47 berlabel biaya tagih provider; rumusnya perlu klarifikasi. FKL48 biaya verifikasi setelah verifikasi; facility ID tidak terbukti. | Prioritas fasilitas sintetis hanya berindeks dengan facility ID, semua billed amount valid, skor, effort positif, cakupan lengkap dan grup tidak terpotong; adapter runtime tidak membentuk unit. | R/C: klarifikasi FKL47/satuan, validasi facility key/effort; tanpa facility ID valid tidak ada ranking fasilitas. Kandidat kunjungan dipisahkan. |
| Review | Human decision and clarification/correction (hlm. 8, 19). | Tidak menetapkan app workflow. | Four process statuses + local SQLite history; no auth/outcome. | R: run-scoped workflow, authenticated actor, separate outcome and audit. |
| Evaluation | Three approaches/metrics; page 14 dummy per transkripsi pengguna; real validation future. | No ground truth in schema dictionary. | Offline synthetic evaluator; API returns insufficient_data. | I synthetic-only; R/C authorized independent labels/protocol before real claims. |
| Scale | Hundreds of thousands/day proposed but not tested (hlm. 18). | Schema guide not throughput spec. | Small runtime demo; 120k generator/evaluator separate. | R: performance/recovery tests in approved representative environment. |

## P0 — Governance, compatibility, and pipeline foundation

| ID | Testable acceptance criterion | Current evidence |
|---|---|---|
| P0-01 | Owner approves role/permission and authority; public signup disabled; administrator bootstrap has no hardcoded/default credential; backend tests deny unauthenticated and cross-assignment access. | I: local auth/RBAC and bootstrap tests exist; organizational approval and object/assignment scope remain R/C. |
| P0-01a | Session tests prove logout revokes access, disabled accounts are denied on the next protected request, and role changes take effect according to the approved session policy. | I: session lifecycle tests; session policy still prototype-only. |
| P0-01b | Review/import/run actor is derived from validated server session; forged identity/role fields in request bodies are rejected or ignored and never determine attribution. | I: review/import/run actor derives from session; run import fields are extra-forbidden; API tests cover creator attribution. |
| P0-02 | Data-use authorization, purpose, environment, retention/deletion, incident process documented before sample access. | R/C: this audit touched guide only, not sample data. |
| P0-03 | Kontrak mapping untuk fixture sintetis terdokumentasi dan berversi. Sebelum mode BPJS sample-compatible dibuka, mapping resmi, perbedaan FKL05/FKL05_NEW, formula/satuan/waktu FKL47, join FKL02, dan semantik key/null harus dikonfirmasi. Jangan mewajibkan FKL05_NEW bila mapping resmi menggunakan FKL05. | R/C: gap skema nyata tetap memblokir mode sampel terkait, tetapi tidak menghalangi pengembangan synthetic-only. |
| P0-04 | Synthetic CSV importer returns aggregate errors only; no source rows, participant IDs, local paths or secrets in logs/API. | I: batch parser/API tests verify safe errors; independent content provenance is not verified. |
| P0-05 | Synthetic DataBatch versions persist; rejected imports contain no partial records; ready versions are immutable; changed content/mapping creates a distinct version/batch. Unsupported/partial profiles cannot silently run checks. | I: synthetic v1 importer and tests; BPJS import remains R/C. |
| P0-06 | Run manifest stores batch ID/version, digest, mapping, detector/config, scoring/policy/priority versions, status, times, coverage and result references; retries create a new run; partial/failure states are persisted. GET by run ID returns stored results and never silently reruns detectors. | I: persistent synchronous synthetic runs, exact batch pinning, persisted snapshots, retry links, immutable terminal state and no-rerun GET are covered by API/service tests. `detector-suite-v1-manual` is manually maintained, not a source hash; interruption recovery remains R. |
| P0-06a | Test that facility priority is produced only with valid facility identity, eligible signals, valid unique claim amounts, positive audit effort and sufficient assessment coverage; otherwise return explicit not-assessable status/reasons. Visit-level findings remain separate and are not described as a facility ranking. | I: synthetic priority tests cover missing facility IDs, invalid values, incomplete/truncated coverage, positive effort validation, formula and deduplication. BPJS facility ID/amount eligibility remains R/C. |
| P0-07 | Profile capability matrix applies; statuses distinguish triggered/not-triggered-in-assessed-scope, N/A, unassessed, unavailable, partial/truncated. | I for synthetic pipeline; R for import profile. |
| P0-08 | Ground truth is excluded from operational detector/scoring/API; regression test rejects forbidden label fields. | I: evaluator checks feature keys; scoring/detector interfaces omit labels. |
| P0-09 | UI/API tidak menyebut sinyal sebagai fraud terbukti; null tetap null. MVP synthetic-only memiliki action policy demo eksplisit, provisional, berversi, dan diuji untuk green/yellow/red/cannot_recommend; policy bukan risk level, outcome manusia, atau threshold BPJS. `risk_level` tetap null. | I: policy pada AnalysisRun dengan registry versi/config immutable serta tes empat lane dan coverage. UI integrasi lane belum tersedia; threshold belum disetujui/validasi domain (R/C). |
| P0-10 | Case/review key is run-scoped; the run must be completed/partial with a persisted result and the case must exist in that run. Reusing a case ID in another run does not inherit state. GET creates no review row; state/history survive app reinitialization; run result remains unchanged. | I: run-scoped API and isolated tests validate run/case membership, independent runs, read-only GET, persistence, and result immutability. Browser reload journey remains R. |
| P0-11 | Authenticated actor from session; status and outcome are separate; status writes use `review:write`, outcome writes use `review:manage`, all mutations require CSRF; append-only history records actor/time/old-new values. Legacy statuses remain unmigrated. | I: API/service tests cover role deny, CSRF, forged fields, history and no legacy migration. Outcome vocabulary/role policy are provisional; owner approval remains C. |
| P0-12 | API schema covers loading/empty/error/unavailable/partial and provenance; no hardcoded success metrics. | I: API contracts include analytics, batches, runs, review and auth; frontend batch/run journey remains R. |
| P0-13 | Browser/API E2E using synthetic fixture covers login/logout, forbidden role action, import→validation→run→results→queue→detail→review→reload; verifies run-scoped persistence, partial/N/A coverage, and unavailable/error state. | R: current tests are partial API smoke and user-reported manual visual check; no full import/run/auth E2E. |

## P1 — Review workflow and observability

| ID | Testable acceptance criterion | Status |
|---|---|---|
| P1-01 | Reviewer sees assigned run/case, source profile, reasons, safe evidence and coverage in same run scope. | R; current UI shows demo snapshot. |
| P1-02 | Search/filter/page use server response with stable run-scoped IDs; sorting does not imply validated priority if unavailable. | I for synthetic API; extend for persisted runs. |
| P1-03 | Perluas workflow: transition matrix, reopen/close/reassignment, persetujuan taxonomy outcome oleh pemilik proses, dan migrasi legacy history bila dibutuhkan. | R/C; P0 Stage 6 provides free status updates and no legacy migration. |
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
