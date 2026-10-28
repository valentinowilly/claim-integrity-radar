import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { Archive, ArchiveRestore, ArrowRight, Inbox, Check, FileUp, Play, RefreshCw, RotateCcw, ShieldCheck, Trash2 } from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";
import { useNotify } from "../notifications/NotificationCenter";
import {
  getInbox,
  pullInbox,
  type InboxState,
  archiveRun,
  restoreBatch,
  restoreRun,
  createRun,
  removeBatch,
  getBatch,
  getBatches,
  getFkrtlSourceStatus,
  getFkrtlValidation,
  validateFkrtlSource,
  getRun,
  getRuns,
  importSyntheticCsv,
  type BatchDetailResponse,
  type BatchImportResponse,
  type BatchMetadata,
  issueMessage,
  type FkrtlSourceStatus,
  type FkrtlValidationState,
  validationJobActive,
  type RunDetailResponse,
  type RunManifest,
  type RunSourceType,
} from "../api/client";
import { EmptyState, LoadingState } from "../components/DataStates";
import {
  MoreInfo, StatusPill, TechnicalDetails,
  unassessedReasonText,
  formatCount, formatDate, formatDateTime, indicatorLabel, runStatusText, runTitle, sourceLabel,
} from "../components/Display";
import { useAuth } from "../auth/AuthContext";

const ACTION_POLICY_VERSION = "action-policy-evidence-v3-provisional";

export default function WorkflowPage() {
  const notify = useNotify();
  const { state: auth } = useAuth();
  // "Unggah data" (top bar, first-run guide) lands here with ?unggah=1: the upload form is opened and shown.
  const [searchParams] = useSearchParams();
  const openUpload = searchParams.get("unggah") === "1";
  useEffect(() => {
    if (openUpload) document.getElementById("unggah")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [openUpload]);
  const isAdministrator = "session" in auth && auth.session?.user.role === "platform_admin";
  const permissions = useMemo(() => new Set("session" in auth ? (auth.session?.permissions ?? []) : []), [auth]);
  const canReadBatches = permissions.has("batches:read");
  const canWriteBatches = permissions.has("batches:write");
  const canReadRuns = permissions.has("runs:read");
  const canWriteRuns = permissions.has("runs:write");
  const canReadResults = permissions.has("runs:results:read");
  const [batches, setBatches] = useState<BatchMetadata[]>([]);
  const [runs, setRuns] = useState<RunManifest[]>([]);
  const [fkrtlStatus, setFkrtlStatus] = useState<FkrtlSourceStatus | null>(null);
  const [fkrtlValidation, setFkrtlValidation] = useState<FkrtlValidationState | null>(null);
  // While a validation job is pending or running, poll its state; stops once it has finished.
  const pollingJob = validationJobActive(fkrtlValidation) ? fkrtlValidation?.job?.job_id ?? null : null;
  useEffect(() => {
    if (!pollingJob) return;
    let cancelled = false;
    const timer = window.setTimeout(() => {
      getFkrtlValidation()
        .then(next => { if (!cancelled) setFkrtlValidation(next); })
        .catch(() => { if (!cancelled) setFkrtlValidation(current => current ? { ...current } : current); });
    }, 2000);
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [pollingJob, fkrtlValidation]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [selectedBatchId, setSelectedBatchId] = useState("");
  const [batchDetail, setBatchDetail] = useState<BatchDetailResponse | null>(null);
  const [selectedRunId, setSelectedRunId] = useState("");
  const [runDetail, setRunDetail] = useState<RunDetailResponse | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [fileInputKey, setFileInputKey] = useState(0);
  const [batchKey, setBatchKey] = useState("");
  const importKey = toBatchKey(batchKey);
  const [importResult, setImportResult] = useState<BatchImportResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState("");
  // Bumped after archiving or removing so the archive list reloads.
  const [archiveVersion, setArchiveVersion] = useState(0);

  // Only the first load replaces the page with a loading state. Later reloads (e.g. after the
  // selected batch or run changes) refresh in place: unmounting the import form mid-selection
  // dropped the newly chosen file while the previous one stayed in state and was uploaded.
  const loadedOnce = useRef(false);
  const reload = useCallback(
    async (quiet = false) => {
      if (!quiet && !loadedOnce.current) setLoading(true);
      else setRefreshing(true);
      setError("");
      try {
        const [batchResponse, runResponse, sourceStatus, validationState] = await Promise.all([
          canReadBatches ? getBatches(50, 0) : Promise.resolve(null),
          canReadRuns ? getRuns(50, 0) : Promise.resolve(null),
          canReadBatches ? getFkrtlSourceStatus() : Promise.resolve(null),
          canReadBatches ? getFkrtlValidation() : Promise.resolve(null),
        ]);
        setBatches(batchResponse?.items ?? []);
        setFkrtlStatus(sourceStatus);
        setFkrtlValidation(validationState);
        setRuns(runResponse?.items ?? []);
        if (selectedBatchId && batchResponse?.items.some((item) => item.batch_id === selectedBatchId)) {
          setBatchDetail(await getBatch(selectedBatchId));
        } else if (selectedBatchId) {
          setSelectedBatchId("");
          setBatchDetail(null);
        }
        const selectedRunExists = runResponse?.items.some((item) => item.run_id === selectedRunId) ?? false;
        if (selectedRunId && selectedRunExists && canReadResults) {
          setRunDetail(await getRun(selectedRunId));
        } else if (selectedRunId && !selectedRunExists) {
          setSelectedRunId("");
          setRunDetail(null);
        } else if (selectedRunId && !canReadResults) {
          setRunDetail(null);
        }
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : "Data atau riwayat analisis tidak dapat dimuat.");
      } finally {
        loadedOnce.current = true;
        setLoading(false);
        setRefreshing(false);
      }
    },
    [canReadBatches, canReadRuns, canReadResults, selectedBatchId, selectedRunId],
  );

  useEffect(() => {
    void reload();
  }, [reload]);

  async function chooseBatch(id: string) {
    setSelectedBatchId(id);
    setBatchDetail(null);
    setError("");
    if (!id) return;
    try {
      setBatchDetail(await getBatch(id));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Rincian data tidak dapat dimuat.");
    }
  }
  async function chooseRun(id: string) {
    setSelectedRunId(id);
    setRunDetail(null);
    setError("");
    setFeedback("");
    if (!id || !canReadResults) return;
    try {
      setRunDetail(await getRun(id));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Hasil analisis tidak dapat dimuat.");
    }
  }
  async function submitImport(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file || busy) return;
    setBusy(true);
    setError("");
    setFeedback("");
    setImportResult(null);
    try {
      const result = await importSyntheticCsv(file, importKey);
      // The server has answered for this file: clear the selection so it cannot be sent again
      // by mistake (after a network error it is kept for a retry).
      setFile(null);
      setFileInputKey(key => key + 1);
      setImportResult(result);
      const rejected = result.batch.status === "rejected";
      setFeedback(rejected ? "File ditolak; data ini tidak dapat dianalisis." : "File valid. Analisis dimulai…");
      if (rejected) notify({ tone: "warning", title: "File ditolak", message: "Format file tidak sesuai. Lihat rincian pemeriksaan." });
      await reload(true);
      setSelectedBatchId(result.batch.batch_id);
      setBatchDetail(await getBatch(result.batch.batch_id));
      // One step for the user: a valid file is analysed right away.
      if (!rejected && canWriteRuns) setAnalyseAfterImport(result.batch.batch_id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unggah gagal.");
      notify({ tone: "danger", title: "Unggah gagal", message: reason instanceof Error ? reason.message : undefined });
    } finally {
      setBusy(false);
    }
  }
  async function archive(run: RunManifest) {
    if (busy || !window.confirm(`Arsipkan "${runTitle(run)}"?\n\nAnalisis tidak tampil lagi di daftar. Hasil dan keputusan tinjauannya tetap tersimpan.`)) return;
    setBusy(true);
    setError("");
    try {
      await archiveRun(run.run_id);
      notify({ tone: "success", title: "Analisis diarsipkan", message: "Lihat di bagian Arsip di bawah halaman." });
      setArchiveVersion(v => v + 1);
      await reload(true);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Analisis tidak dapat diarsipkan.");
    } finally {
      setBusy(false);
    }
  }
  async function remove(batch: BatchMetadata) {
    if (busy || !window.confirm(`Hapus file "${batchName(batch.batch_key)}" dari daftar?\n\nHasil analisis dari file ini tetap tersimpan.`)) return;
    setBusy(true);
    setError("");
    try {
      await removeBatch(batch.batch_id);
      notify({ tone: "success", title: "File dihapus dari daftar", message: "Lihat di bagian Arsip di bawah halaman." });
      setArchiveVersion(v => v + 1);
      await reload(true);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "File tidak dapat dihapus.");
    } finally {
      setBusy(false);
    }
  }
  async function submitRun(batchId: string | null, retryOfRunId?: string, sourceType: RunSourceType = "synthetic_csv") {
    if (busy) return;
    setBusy(true);
    setError("");
    setFeedback("");
    try {
      const response = await createRun({
        // The FKRTL source is configured server-side; the client never selects its batch or path.
        ...(batchId && sourceType === "synthetic_csv" ? { batch_id: batchId } : {}),
        source_type: sourceType,
        ...(retryOfRunId ? { retry_of_run_id: retryOfRunId } : {}),
        action_policy_version: ACTION_POLICY_VERSION,
      });
      setFeedback("Analisis selesai. Buka Antrean Tinjauan untuk mulai meninjau klaim.");
      await reload(true);
      setSelectedRunId(response.run.run_id);
      if (canReadResults) setRunDetail(await getRun(response.run.run_id));
      else setRunDetail(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Analisis tidak dapat dijalankan.");
      notify({ tone: "danger", title: "Analisis tidak dimulai", message: reason instanceof Error ? reason.message : undefined });
    } finally {
      setBusy(false);
    }
  }

  const [analyseAfterImport, setAnalyseAfterImport] = useState<string | null>(null);
  useEffect(() => {
    if (!analyseAfterImport || busy) return;
    setAnalyseAfterImport(null);
    void submitRun(analyseAfterImport);
  });

  // "Proses data klaim" is one action: the server checks the data quality in the background, and the
  // analysis starts by itself once that check passes. A failed check stops the flow with its reasons.
  const [autoRun, setAutoRun] = useState(false);
  async function submitValidation(thenAnalyse = true) {
    if (busy) return;
    setBusy(true);
    setError("");
    setFeedback("");
    try {
      setFkrtlValidation(await validateFkrtlSource());
      setAutoRun(thenAnalyse);
      notify({ tone: "info", title: "Data klaim sedang diproses", message: "Pemeriksaan kualitas data berjalan; analisis dimulai otomatis setelahnya." });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Data klaim tidak dapat diproses.");
      notify({ tone: "danger", title: "Data klaim tidak dapat diproses", message: reason instanceof Error ? reason.message : undefined });
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    if (!autoRun || !fkrtlValidation || validationJobActive(fkrtlValidation)) return;
    setAutoRun(false);
    if (fkrtlValidation.phase === "passed" || fkrtlValidation.phase === "passed_with_warnings")
      void submitRun(null, undefined, "bpjs_fkrtl_local");
  });

  const batchReady = Boolean(batchDetail && batchDetail.batch.source_type === "synthetic_csv"
    && ["ready", "ready_with_warnings"].includes(batchDetail.batch.status));
  const latestRun = runs[0];
  return (
    <>
      <header className="page-head">
        <div>
          <h1>Data & <span className="muted">Analisis</span></h1>
          <p>Tambahkan data klaim dan kelola hasil analisisnya.</p>
        </div>
        <div className="page-head-actions">
          <button className="button button-secondary" onClick={() => void reload(true)} disabled={refreshing}>
            <RefreshCw size={14} />
            {refreshing ? "Memuat ulang…" : "Muat ulang"}
          </button>
        </div>
      </header>
      {error && (
        <div className="workflow-error" role="alert">
          <strong>Permintaan gagal</strong>
          <span>{error}</span>
        </div>
      )}
      {feedback && <div className="workflow-feedback" role="status">{feedback}</div>}
      {loading ? (
        <LoadingState label="Memuat data klaim dan riwayat analisis…" />
      ) : (
        <div className="stack" style={{ gap: 18 }}>
          <section className="card upload-section" aria-label="Tambah data klaim" id="unggah" data-open={openUpload || undefined}>
            <div className="card-head">
              <div><h2><FileUp size={17} style={{ verticalAlign: "-3px", color: "var(--brand-ink)" }} /> Tambah data klaim</h2>
                <p>Unggah berkas CSV berformat kolom data klaim FKRTL (PSTV01, FKL02, FKL03, …). Berkas diperiksa lalu langsung dianalisis.</p></div>
            </div>
            {canWriteBatches ? (
              <form className="upload-form" onSubmit={(event) => void submitImport(event)}>
                <label className="upload-drop">
                  <FileUp size={22} aria-hidden="true" />
                  <span><strong>{file ? file.name : "Pilih berkas CSV"}</strong>
                    <small>{file ? `${(file.size / 1024 / 1024).toLocaleString("id-ID", { maximumFractionDigits: 1 })} MB` : "Satu berkas per unggahan"}</small></span>
                  <input key={fileInputKey} type="file" accept=".csv,text/csv" aria-label="Berkas CSV" onChange={(event) => setFile(event.target.files?.[0] ?? null)} disabled={busy} />
                </label>
                <label className="upload-name">
                  <span>Nama data <small>(opsional)</small></span>
                  <input value={batchKey} maxLength={60} placeholder="mis. Klaim RS 1–7 Maret" onChange={(event) => setBatchKey(event.target.value)} disabled={busy} />
                </label>
                <button className="button button-primary upload-submit" type="submit" disabled={busy || !file}>
                  <FileUp size={15} />{busy ? "Memproses…" : "Unggah dan analisis"}
                </button>
              </form>
            ) : <p className="fine-print">Unggah berkas hanya dapat dilakukan oleh operator data.</p>}
            <p className="fine-print upload-policy">Kebijakan data: nomor peserta harus anonim (berawalan SYN); kolom biaya pasca-verifikasi (FKL48) tidak diterima.</p>
            {importResult && !batchDetail && <BatchCard batch={importResult.batch} />}
            {canReadBatches && batches.length > 0 && (<>
              <h3 className="section-subtitle">Berkas tersimpan</h3>
              <div className="table-scroll" role="region" aria-label="File tersimpan">
                <table className="data-table">
                  <thead><tr><th>Berkas</th><th>Jumlah klaim</th><th>Diunggah</th><th>Status</th>{canWriteBatches && <th><span className="sr-only">Tindakan</span></th>}</tr></thead>
                  <tbody>
                    {batches.map((batch) => (
                      <tr key={batch.batch_id} className={selectedBatchId === batch.batch_id ? "selected" : ""}>
                        <td>
                          <button className="table-select" aria-pressed={selectedBatchId === batch.batch_id} onClick={() => void chooseBatch(batch.batch_id)}>
                            <strong>{batchName(batch.batch_key)}</strong>
                            <small>{sourceLabel(batch.source_type)} · versi {batch.batch_version}</small>
                          </button>
                        </td>
                        <td>{formatCount(batch.row_count)}</td>
                        <td>{formatDateTime(batch.created_at)}</td>
                        <td><StatusPill value={batch.status} /></td>
                        {canWriteBatches && <td>{batch.source_type === "synthetic_csv" && (
                          <button className="button button-danger row-button" disabled={busy} onClick={() => void remove(batch)} aria-label={`Hapus ${batchName(batch.batch_key)}`}>
                            <Trash2 size={14} />Hapus
                          </button>)}</td>}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>)}
            {batchDetail && <BatchCard batch={batchDetail.batch} />}
            {canWriteRuns && batchReady && (
              <div className="inline-actions" style={{ marginTop: 12 }}>
                <button className="button button-secondary" disabled={busy} onClick={() => void submitRun(batchDetail!.batch.batch_id)}>
                  <Play size={15} />{busy ? "Menganalisis…" : "Analisis ulang berkas ini"}
                </button>
                <span className="fine-print">Hasil baru menggantikan analisis sebelumnya atas berkas ini; yang lama dipindahkan ke Arsip.</span>
              </div>
            )}
          </section>

          {canReadRuns && <InboxCard canPull={canWriteRuns} onFinished={() => void reload(true)} />}

          {fkrtlStatus && isAdministrator && !fkrtlStatus.configured && (
            <p className="fine-print" data-testid="fkrtl-not-configured">Sumber data klaim FKRTL belum diatur di server ini.</p>
          )}
          {fkrtlStatus && isAdministrator && fkrtlStatus.configured && (
            <ProcessCard
              status={fkrtlStatus}
              validation={fkrtlValidation}
              latestRun={latestRun}
              canRun={canWriteRuns}
              canValidate={canWriteBatches}
              busy={busy}
              autoRun={autoRun}
              onProcess={() => void submitValidation(true)}
              onAnalyse={() => void submitRun(null, undefined, "bpjs_fkrtl_local")}
            />
          )}

          <section className="card" aria-label="Riwayat analisis">
            <div className="card-head">
              <div><h2>Riwayat analisis</h2><p>Pilih salah satu untuk melihat ringkasannya.</p></div>
            </div>
            {!canReadRuns ? (
              <EmptyState title="Riwayat analisis tidak tersedia" message="Akun Anda tidak dapat melihat hasil analisis." />
            ) : runs.length === 0 ? (
              <EmptyState title="Belum ada analisis" message="Unggah berkas data klaim untuk menjalankan analisis pertama." />
            ) : (
              <div className="table-scroll">
                <table className="data-table">
                  <thead><tr><th>Analisis</th><th>Data</th><th>Dibuat</th><th>Status</th>{canWriteRuns && <th><span className="sr-only">Tindakan</span></th>}</tr></thead>
                  <tbody>
                    {runs.map((run) => (
                      <tr key={run.run_id} className={selectedRunId === run.run_id ? "selected" : ""}>
                        <td>
                          <button className="table-select" data-run-id={run.run_id} aria-pressed={selectedRunId === run.run_id} onClick={() => void chooseRun(run.run_id)}>
                            <strong>{runTitle(run)}</strong>
                            <small>{canReadResults ? "Lihat ringkasan" : "Hasil hanya untuk petugas peninjau"}</small>
                          </button>
                        </td>
                        <td>{sourceLabel(run.source_type)}</td>
                        <td>{formatDateTime(run.created_at)}</td>
                        <td><StatusPill value={run.execution_status} label={runStatusText(run.execution_status)} /></td>
                        {canWriteRuns && <td>{run.execution_status !== "running" && (
                          <button className="button button-secondary row-button" disabled={busy} onClick={() => void archive(run)} aria-label={`Arsipkan ${runTitle(run)}`}>
                            <Archive size={14} />Arsipkan
                          </button>)}</td>}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {canWriteRuns && runs.some((run) => run.execution_status === "failed") && (
              <div className="inline-actions" style={{ marginTop: 12 }}>
                {runs.filter((run) => run.execution_status === "failed").map((run) => (
                  <button key={run.run_id} className="button button-secondary" disabled={busy}
                    onClick={() => void submitRun(run.batch_id, run.run_id, run.source_type)}>
                    <RotateCcw size={14} />Ulangi {runTitle(run)}
                  </button>
                ))}
              </div>
            )}
            {selectedRunId && !canReadResults && (
              <div className="notice-panel" style={{ marginTop: 12 }}>
                <ShieldCheck size={17} />
                <p>Peran Anda dapat menjalankan analisis tetapi tidak dapat melihat hasilnya.</p>
              </div>
            )}
            {runDetail && <RunResultPanel detail={runDetail} />}
          </section>

          {(canReadRuns || canReadBatches) && (
            <ArchiveSection canReadRuns={canReadRuns} canReadBatches={canReadBatches}
              canWriteRuns={canWriteRuns} canWriteBatches={canWriteBatches} version={archiveVersion}
              onRestored={() => void reload(true)} />
          )}

        </div>
      )}
    </>
  );
}

const VALIDATION_STATUS: Record<string, [string, string]> = {
  passed: ["ready", "Kualitas data baik"],
  passed_with_warnings: ["ready_with_warnings", "Kualitas data baik, ada catatan"],
  failed: ["failed", "Kualitas data bermasalah"],
};

/** Aggregate quality report of the server-side claim file; no rows, identifiers or paths are shown. */
function FkrtlValidationSummary({ validation }: { validation: FkrtlValidationState | null }) {
  if (!validation || validation.state === "not_validated" || !validation.report) {
    return <p className="fine-print" data-testid="fkrtl-validation-state">Data periode ini belum diproses.</p>;
  }
  const report = validation.report;
  const scan = report.scan;
  const [tone, label] = VALIDATION_STATUS[report.status] ?? ["neutral", report.status];
  return (
    <div className="stack" style={{ gap: 10 }} data-testid="fkrtl-validation-state">
      <div className="cell-flex" style={{ justifyContent: "space-between" }}>
        <strong>Hasil pemeriksaan kualitas data</strong>
        <StatusPill value={tone} label={validation.current ? label : `${label} (perlu diperiksa ulang)`} />
      </div>
      {scan?.rows_total !== undefined && (
        <div className="fact-grid compact">
          <div className="fact"><span>Klaim pada periode</span><strong>{formatCount(scan.rows_in_window ?? 0)}</strong></div>
          <div className="fact"><span>Tanggal tidak valid</span><strong>{formatCount((scan.admission_date_invalid ?? 0) + (scan.discharge_date_invalid ?? 0))}</strong></div>
          <div className="fact"><span>Kode tindakan kosong</span><strong>{formatCount(scan.missing_value_counts?.FKL30 ?? 0)}</strong></div>
        </div>
      )}
      {report.errors.length > 0 && (
        <div className="validation-errors" role="alert">
          <strong>Perlu diperbaiki sebelum analisis</strong>
          {report.errors.map((item) => <span key={item.code}>{issueMessage(item.code, item.message)}</span>)}
        </div>
      )}
      {report.warnings.length > 0 && (
        <ul className="plain-list" aria-label="Catatan kualitas data">
          {report.warnings.map((item) => <li key={item.code}>{issueMessage(item.code, item.message)}</li>)}
        </ul>
      )}
      {report.checks.length > 0 && (
        <details className="tech-details">
          <summary>Kesiapan setiap pemeriksaan</summary>
          <div className="table-scroll">
            <table className="data-table compact-table" aria-label="Kesiapan pemeriksaan di rentang tanggal">
              <thead><tr><th>Pemeriksaan</th><th>Klaim yang dapat diperiksa</th><th>Tidak dapat diperiksa</th></tr></thead>
              <tbody>{report.checks.map((item) => (
                <tr key={item.check} data-check={item.check}>
                  <td><strong>{item.check === "length_of_stay" ? "Lama rawat (masukan AI)" : indicatorLabel(item.check)}</strong></td>
                  <td>{item.status === "not_applicable" ? "Tidak berlaku untuk data ini" : `${formatCount(item.rows_meeting_prerequisites)} dari ${formatCount(item.rows_in_window)}`}</td>
                  <td>{item.status === "not_applicable" ? "—" : Object.keys(item.rows_excluded).length === 0 ? "Tidak ada"
                    : Object.entries(item.rows_excluded).map(([code, count]) => `${formatCount(count)} ${unassessedReasonText(code)}`).join("; ")}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        </details>
      )}
    </div>
  );
}

/** Describes the recorded FKRTL selection; older runs used a first-N row window. */
const ARCHIVE_REASONS: Record<string, string> = {
  manual: "Diarsipkan petugas",
  superseded: "Digantikan analisis yang lebih baru atas data yang sama",
  older: "Otomatis: lebih dari 30 hari",
};

const INBOX_STATUS: Record<string, [string, string]> = { analysed: ["ready", "Dianalisis"], rejected: ["failed", "Ditolak"], failed: ["failed", "Gagal"], processing: ["running", "Diproses"] };

/** Automatic intake: the claim system drops the day's file in a server folder; it is analysed on schedule. */
function InboxCard({ canPull, onFinished }: { canPull: boolean; onFinished: () => void }) {
  const notify = useNotify();
  const [state, setState] = useState<InboxState | null>(null);
  const [error, setError] = useState("");
  const [requested, setRequested] = useState(false);
  // The pull shown before the click: "finished" means a newer pull has finished, never the previous one.
  const previousPull = useRef<string | null>(null);
  const load = useCallback(async () => {
    try {
      setState(await getInbox());
      setError("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Status folder kiriman tidak dapat dimuat.");
    }
  }, []);
  useEffect(() => { void load(); }, [load]);
  const active = Boolean(state?.running || requested);
  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => void load(), 2500);
    return () => window.clearInterval(timer);
  }, [active, load]);
  useEffect(() => {
    if (requested && state && !state.running && state.last_pull?.finished_at && state.last_pull.started_at !== previousPull.current) {
      setRequested(false);
      notify({ tone: "success", title: "Pengambilan selesai", message: `${formatCount(state.last_pull.files_processed)} file baru diproses.` });
      onFinished();
    }
  }, [requested, state, notify, onFinished]);
  async function pull() {
    setError("");
    try {
      previousPull.current = state?.last_pull?.started_at ?? null;
      await pullInbox();
      setRequested(true);
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Pengambilan tidak dapat dimulai.");
    }
  }
  if (!state && !error) return <section className="card"><LoadingState label="Memuat sambungan otomatis…" /></section>;
  return (
    <section className="card" aria-label="Sambungan otomatis">
      <div className="card-head">
        <div>
          <h2><Inbox size={17} style={{ verticalAlign: "-3px", color: "var(--brand-ink)" }} /> Sambungan otomatis</h2>
          <p>Sistem klaim mengirim file harian ke folder kiriman di server; file itu diperiksa dan dianalisis otomatis sesuai jadwal.</p>
        </div>
        {state && <StatusPill value={state.configured ? "ready" : "unavailable"} label={state.configured ? "Aktif" : "Belum diatur"} />}
      </div>
      {error && <p className="notice-inline" role="alert">{error}</p>}
      {state && !state.configured && (
        <p className="fine-print">Folder kiriman belum diatur di server. Administrator sistem mengaturnya sekali; setelah itu data harian masuk tanpa diunggah.</p>
      )}
      {state?.configured && <>
        <div className="fact-grid compact">
          <div className="fact"><span>Jadwal</span><strong>Setiap hari {state.daily_at}</strong><small>Folder: {state.folder_name}</small></div>
          <div className="fact"><span>Pengambilan berikutnya</span><strong>{state.next_pull_at ? formatDateTime(state.next_pull_at) : "—"}</strong></div>
          <div className="fact"><span>Terakhir diambil</span><strong>{state.last_pull ? formatDateTime(state.last_pull.started_at) : "Belum pernah"}</strong>
            {state.last_pull && <small>{state.last_pull.trigger === "schedule" ? "Terjadwal" : "Manual"} · {formatCount(state.last_pull.files_processed)} file diproses</small>}</div>
          <div className="fact"><span>Menunggu diambil</span><strong>{formatCount(state.waiting_count)} file</strong></div>
        </div>
        {canPull && (
          <div className="inline-actions" style={{ marginTop: 12 }}>
            <button className="button button-secondary" disabled={active} onClick={() => void pull()}>
              <RefreshCw size={14} />{active ? "Sedang mengambil…" : "Ambil sekarang"}
            </button>
          </div>
        )}
        {state.files.length > 0 && (
          <div className="table-scroll" style={{ marginTop: 14 }}>
            <table className="data-table" aria-label="File dari folder kiriman">
              <thead><tr><th>File</th><th>Klaim</th><th>Diambil</th><th>Status</th><th><span className="sr-only">Hasil</span></th></tr></thead>
              <tbody>{state.files.map((item) => {
                const [tone, label] = INBOX_STATUS[item.status] ?? ["neutral", item.status];
                return <tr key={`${item.file_name}-${item.received_at}`}>
                  <td><strong>{item.file_name}</strong>{item.message_code && <small className="fine-print" style={{ display: "block" }}>{issueMessage(item.message_code, item.message_code.replace(/_/g, " "))}</small>}</td>
                  <td>{formatCount(item.row_count)}</td>
                  <td>{formatDateTime(item.received_at)}</td>
                  <td><StatusPill value={tone} label={label} /></td>
                  <td>{item.run_id && <Link to={`/?run_id=${encodeURIComponent(item.run_id)}`}>Lihat hasil</Link>}</td>
                </tr>;
              })}</tbody>
            </table>
          </div>
        )}
      </>}
    </section>
  );
}

/** Archived analyses and removed files, each with a restore button. Loaded when opened. */
function ArchiveSection({ canReadRuns, canReadBatches, canWriteRuns, canWriteBatches, version, onRestored }: {
  canReadRuns: boolean; canReadBatches: boolean; canWriteRuns: boolean; canWriteBatches: boolean;
  version: number; onRestored: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [runs, setRuns] = useState<RunManifest[] | null>(null);
  const [files, setFiles] = useState<BatchMetadata[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    setError("");
    try {
      const [runList, fileList] = await Promise.all([
        canReadRuns ? getRuns(100, 0, undefined, undefined, true) : Promise.resolve(null),
        canReadBatches ? getBatches(100, 0, undefined, true) : Promise.resolve(null),
      ]);
      setRuns(runList?.items ?? []);
      setFiles(fileList?.items ?? []);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Arsip tidak dapat dimuat.");
    }
  }, [canReadRuns, canReadBatches]);
  useEffect(() => { if (open) void load(); }, [open, version, load]);
  async function restore(action: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await action();
      await load();
      onRestored();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Gagal memulihkan.");
    } finally {
      setBusy(false);
    }
  }
  const empty = runs !== null && files !== null && runs.length === 0 && files.length === 0;
  return (
    <details className="card upload-section" aria-label="Arsip" onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary className="archive-summary">
        <span><Archive size={16} /> Arsip</span>
        <span className="fine-print">Analisis yang diarsipkan dan file yang dihapus</span>
      </summary>
      {error && <p className="notice-inline" role="alert">{error}</p>}
      {open && (
        <ul className="policy-points" data-testid="archive-policy">
          <li><strong>Masuk arsip otomatis</strong><span>Analisis yang digantikan analisis baru atas data yang sama, atau berumur lebih dari 30 hari.</span></li>
          <li><strong>Tidak pernah dihapus</strong><span>Hasil, keputusan, dan hasil audit tetap tersimpan dan dapat dipulihkan.</span></li>
        </ul>
      )}
      {!open ? null : runs === null && !error ? <LoadingState label="Memuat arsip…" /> : empty ? (
        <p className="fine-print" style={{ marginTop: 12 }}>Arsip masih kosong.</p>
      ) : (
        <div className="table-scroll" style={{ marginTop: 12 }}>
          <table className="data-table">
            <thead><tr><th>Nama</th><th>Jenis</th><th>Dibuat</th><th><span className="sr-only">Tindakan</span></th></tr></thead>
            <tbody>
              {(runs ?? []).map((run) => (
                <tr key={run.run_id}>
                  <td><strong>{runTitle(run)}</strong>
                    {run.archive_reason && <span className="archive-reason">{ARCHIVE_REASONS[run.archive_reason]}</span>}</td>
                  <td>Analisis</td>
                  <td>{formatDateTime(run.created_at)}</td>
                  <td>{canWriteRuns && <button className="button button-secondary row-button" disabled={busy}
                    onClick={() => void restore(() => restoreRun(run.run_id))} aria-label={`Pulihkan ${runTitle(run)}`}>
                    <ArchiveRestore size={14} />Pulihkan</button>}</td>
                </tr>
              ))}
              {(files ?? []).map((batch) => (
                <tr key={batch.batch_id}>
                  <td><strong>{batchName(batch.batch_key)}</strong></td>
                  <td>File CSV · {formatCount(batch.row_count)} klaim</td>
                  <td>{formatDateTime(batch.created_at)}</td>
                  <td>{canWriteBatches && <button className="button button-secondary row-button" disabled={busy}
                    onClick={() => void restore(() => restoreBatch(batch.batch_id))} aria-label={`Pulihkan ${batchName(batch.batch_key)}`}>
                    <ArchiveRestore size={14} />Pulihkan</button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </details>
  );
}

/** Uploaded files are stored as "synthetic-<name>"; people see and type only the name. */
function batchName(key: string): string {
  return key.replace(/^synthetic-/, "");
}
function toBatchKey(name: string): string {
  const slug = name.toLowerCase().replace(/^synthetic-/, "").replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 60);
  return `synthetic-${slug || `data-${Date.now()}`}`;
}

function selectionText(configuration: RunManifest["configuration"]): string {
  const source = configuration.source;
  const selection = source && typeof source === "object" && !Array.isArray(source) ? source.selection : null;
  if (selection && typeof selection === "object" && !Array.isArray(selection) && typeof selection.date_from === "string") {
    return `Periode ${selection.date_from} s.d. ${String(selection.date_to)}: ${formatCount(typeof selection.processed_rows === "number" ? selection.processed_rows : null)} klaim dianalisis.`;
  }
  return "Analisis lama dari sebagian data klaim.";
}

/** The daily action: process the latest claims of the configured period in one step. */
function ProcessCard({ status, validation, latestRun, canRun, canValidate, busy, autoRun, onProcess, onAnalyse }: {
  status: FkrtlSourceStatus; validation: FkrtlValidationState | null; latestRun: RunManifest | undefined;
  canRun: boolean; canValidate: boolean; busy: boolean; autoRun: boolean; onProcess: () => void; onAnalyse: () => void;
}) {
  const job = validation?.job;
  const jobActive = validationJobActive(validation);
  const passed = validation?.phase === "passed" || validation?.phase === "passed_with_warnings";
  const progress = job && job.rows_total ? Math.min(100, (job.rows_scanned / job.rows_total) * 100) : null;
  const step = jobActive || autoRun ? 1 : busy ? 2 : passed ? 3 : 0;
  const steps = ["Periksa kualitas data", "Analisis klaim", "Hasil siap"];
  return (
    <section className="card process-card batch-result-card" aria-label="Proses data klaim">
      <div className="process-head">
        <div>
          <span className="eyebrow-text">Data klaim FKRTL · khusus administrator</span>
          <h2>{status.date_from && status.date_to ? `Periode ${formatDate(status.date_from)} – ${formatDate(status.date_to)}` : "Periode belum diatur"}</h2>
          <p className="fine-print">Diambil langsung dari server. Identitas peserta tidak pernah ditampilkan.
            {status.max_rows !== null ? ` Maksimal ${formatCount(status.max_rows)} klaim per analisis.` : ""}</p>
        </div>
        <StatusPill value={status.available ? "ready" : "unavailable"} label={status.available ? "Terhubung" : "Belum terhubung"} />
      </div>

      {status.issues.length > 0 ? (
        <div className="validation-errors">
          <strong>Data klaim belum tersedia</strong>
          {[...new Set(status.issues.map((item) => issueMessage(item.code, item.message)))].map((text) => <span key={text}>{text}</span>)}
        </div>
      ) : (
        <>
          <ol className="process-steps" aria-label="Tahap pemrosesan">
            {steps.map((label, index) => (
              <li key={label} className={step > index + 1 || (index === 2 && step === 3) ? "done" : step === index + 1 ? "current" : ""}>
                <span className="step-num">{step > index + 1 || (index === 2 && step === 3) ? <Check size={14} /> : index + 1}</span>{label}
              </li>
            ))}
          </ol>
          {jobActive && job && (
            <div className="stack" style={{ gap: 6 }} role="status" data-testid="fkrtl-validation-job">
              <span className="fine-print">{job.status === "pending" ? "Menunggu antrean di server…"
                : `Memeriksa ${formatCount(job.rows_scanned)}${job.rows_total ? ` dari ${formatCount(job.rows_total)}` : ""} baris data…`}</span>
              <div className="progress-line"><span style={{ width: `${progress ?? 8}%` }} /></div>
            </div>
          )}
          {!jobActive && job?.status === "failed" && validation?.phase === "failed" && (
            <p className="notice-inline" role="alert" data-testid="fkrtl-validation-job">Proses sebelumnya terhenti. Silakan proses ulang.</p>
          )}
          <div className="inline-actions">
            {canValidate && (
              <button className="button button-primary button-large" disabled={busy || jobActive || !status.configured} onClick={onProcess}>
                <Play size={16} />{jobActive ? "Sedang memeriksa data…" : busy ? "Sedang menganalisis…" : "Proses data klaim"}
              </button>
            )}
            {canRun && passed && !jobActive && (
              <button className="button button-secondary" disabled={busy || !status.available} onClick={onAnalyse}>
                <RotateCcw size={15} />Analisis ulang tanpa pemeriksaan
              </button>
            )}
            {canRun && !canValidate && !passed && (
              <small className="fine-print" data-testid="fkrtl-run-requirement">Data periode ini perlu diproses operator data lebih dulu.</small>
            )}
            {latestRun && latestRun.source_type === "bpjs_fkrtl_local" && !busy && !jobActive && (
              <span className="fine-print">Analisis terakhir: {formatDateTime(latestRun.created_at)}</span>
            )}
          </div>
          <FkrtlValidationSummary validation={validation} />
        </>
      )}
      {status.ml_model && !status.ml_model.available && (
        <p className="notice-inline" role="status">AI sedang tidak tersedia; analisis tetap berjalan dengan pemeriksaan aturan.</p>
      )}
      <TechnicalDetails items={[
        { label: "Versi format data", value: `${status.schema_profile} / ${status.mapping_version}` },
        { label: "Jenis sumber data", value: status.classification },
        ...status.issues.map((item) => ({ label: "Kode masalah", value: item.code })),
      ]} />
    </section>
  );
}

function BatchCard({ batch }: { batch: BatchMetadata }) {
  const warnings = Object.values(batch.validation.warning_counts).reduce<number>(
    (n, item) => n + (typeof item === "number" ? item : 0),
    0,
  );
  return (
    <div className="sub-card stack batch-result-card" style={{ gap: 10 }}>
      <div className="sub-card-head">
        <strong>{sourceLabel(batch.source_type)} · {batchName(batch.batch_key)}</strong>
        <StatusPill value={batch.status} />
      </div>
      <p className="fine-print">
        {batch.status === "rejected"
          ? "Format file tidak sesuai. Berikut jenis kesalahannya."
          : batch.source_type === "bpjs_fkrtl_local"
            ? "Data klaim tidak disalin ke aplikasi; hanya keterangannya yang disimpan."
            : "File valid dan siap dianalisis."}
      </p>
      <div className="fact-grid compact">
        <div className="fact"><span>Jumlah klaim</span><strong>{formatCount(batch.row_count)}</strong></div>
        <div className="fact"><span>Kesalahan</span><strong>{formatCount(batch.validation.error_count)}</strong></div>
        <div className="fact"><span>Catatan</span><strong>{formatCount(warnings)}</strong></div>
      </div>
      {Object.keys(batch.validation.error_counts).length > 0 && (
        <div className="validation-errors">
          <strong>Ringkasan kesalahan</strong>
          {Object.entries(batch.validation.error_counts).map(([code, count]) => (
            <span key={code}>
              {issueMessage(code, code.replace(/_/g, " "))}: {formatCount(count)}
            </span>
          ))}
        </div>
      )}
      {batch.validation.errors.length > 0 && (
        <MoreInfo
          title={`Lokasi kesalahan (maks. ${batch.validation.errors.length})`}
          items={batch.validation.errors.map(
            (item) => `${issueMessage(item.code, item.code.replace(/_/g, " "))}${item.row ? ` · baris ${item.row}` : ""}${item.column ? ` · kolom ${item.column}` : ""}`,
          )}
        />
      )}
      <TechnicalDetails
        items={[
          { label: "ID data", value: batch.batch_id, copy: true },
          { label: "Skema / pemetaan", value: `${batch.schema_version} / ${batch.mapping_version}` },
          { label: "Dibuat", value: formatDateTime(batch.created_at) },
        ]}
      />
    </div>
  );
}

/** Short summary of one saved analysis; the full lists live in the Review Queue and Analysis Details. */
function RunResultPanel({ detail }: { detail: RunDetailResponse }) {
  const { run, result } = detail;
  const runQuery = `?run_id=${encodeURIComponent(run.run_id)}`;
  const applicable = result?.indicators.filter(item => item.status !== "not_applicable") ?? [];
  return (
    <div className="sub-card stack run-result-card" style={{ marginTop: 16 }}>
      <div className="sub-card-head">
        <div>
          <span className="fine-print">Ringkasan analisis</span>
          <strong style={{ display: "block", fontSize: 16 }}>{runTitle(run)}</strong>
        </div>
        <StatusPill value={run.execution_status} label={runStatusText(run.execution_status)} />
      </div>
      {run.failure_category && (
        <div className="workflow-error">Analisis gagal ({run.failure_category.replace(/_/g, " ").toLowerCase()}). Tidak ada hasil yang ditampilkan.</div>
      )}
      {!result ? (
        <EmptyState title="Hasil belum tersedia" message="Analisis belum menyimpan hasil. Muat ulang setelah selesai, atau lihat alasan kegagalan." />
      ) : (
        <>
          <div className="fact-grid" style={{ gridTemplateColumns: "repeat(4, minmax(0, 1fr))" }}>
            <div className="fact"><span>Klaim dianalisis</span><strong>{formatCount(result.records_considered)}</strong></div>
            <div className="fact"><span>Risiko tinggi</span><strong style={{ color: "var(--lane-red)" }}>{formatCount(result.action_policy.lane_counts?.red ?? 0)}</strong></div>
            <div className="fact"><span>Risiko sedang</span><strong style={{ color: "var(--lane-yellow)" }}>{formatCount(result.action_policy.lane_counts?.yellow ?? 0)}</strong></div>
            <div className="fact"><span>Dinilai AI</span><strong>{result.ml_anomaly?.status === "available" ? formatCount(result.ml_anomaly.records_scored) : "Tidak tersedia"}</strong></div>
          </div>
          <div className="inline-actions">
            <Link className="button button-primary" to={`/cases${runQuery}`}>Buka Antrean Tinjauan <ArrowRight size={14} /></Link>
            <Link className="button button-secondary" to={`/${runQuery}`}>Lihat Beranda</Link>
            <span className="fine-print">{run.source_type === "bpjs_fkrtl_local" ? selectionText(run.configuration) : "Hasil dari file CSV yang diunggah."}</span>
          </div>
          {applicable.length > 0 && <details className="tech-details">
            <summary>Rincian per pemeriksaan</summary>
            <div className="table-scroll">
              <table className="data-table" aria-label="Hasil pemeriksaan">
                <thead><tr><th>Pemeriksaan</th><th>Klaim terdeteksi</th><th>Klaim diperiksa</th></tr></thead>
                <tbody>{applicable.map((item) => {
                  const coverage = result.indicator_coverage.find((row) => row.indicator === item.code);
                  return (
                    <tr key={item.code} data-indicator={item.code}>
                      <td><strong>{indicatorLabel(item.code)}</strong></td>
                      <td>{formatCount(item.candidate_count)}</td>
                      <td>{formatCount(coverage?.records_assessed ?? item.eligible_count)}</td>
                    </tr>
                  );
                })}</tbody>
              </table>
            </div>
            <Link className="fine-print" to={`/analysis${runQuery}`}>Buka rincian analisis lengkap</Link>
          </details>}
          <TechnicalDetails
            items={[
              { label: "ID analisis", value: run.run_id, copy: true },
              { label: "ID data", value: `${run.batch_id} (versi ${run.batch_version})`, copy: false },
              { label: "Jenis sumber data", value: run.source_classification },
              { label: "Versi format data", value: `${run.source_schema_version} / ${run.source_mapping_version}` },
              { label: "Versi aturan pemeriksaan", value: [run.detector_suite_version, run.scoring_version, run.priority_version, run.action_policy_version].map((x) => x ?? "—").join(" / ") },
              { label: "Dibuat / selesai", value: `${formatDateTime(run.created_at)} / ${formatDateTime(run.completed_at)}` },
              { label: "Catatan sumber data", value: detail.notice },
            ]}
          />
        </>
      )}
    </div>
  );
}
