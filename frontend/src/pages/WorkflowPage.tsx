import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { ArrowRight, Database, FileUp, RefreshCw, RotateCcw, ShieldCheck } from "lucide-react";
import { Link } from "react-router-dom";
import {
  createRun, getBatch, getBatches, getRun, getRuns, importSyntheticCsv,
  type BatchDetailResponse, type BatchImportResponse, type BatchMetadata, type RunDetailResponse,
  type RunManifest,
} from "../api/client";
import { EmptyState, LoadingState, PageHeading, SourceBadge } from "../components/DataStates";
import { useAuth } from "../auth/AuthContext";

const ACTION_POLICY_VERSION = "action-policy-demo-v1-provisional";

export default function WorkflowPage() {
  const { state: auth } = useAuth();
  const permissions = useMemo(() => new Set("session" in auth ? auth.session?.permissions ?? [] : []), [auth]);
  const canReadBatches = permissions.has("batches:read");
  const canWriteBatches = permissions.has("batches:write");
  const canReadRuns = permissions.has("runs:read");
  const canWriteRuns = permissions.has("runs:write");
  const canReadResults = permissions.has("runs:results:read");
  const [batches, setBatches] = useState<BatchMetadata[]>([]);
  const [runs, setRuns] = useState<RunManifest[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [selectedBatchId, setSelectedBatchId] = useState("");
  const [batchDetail, setBatchDetail] = useState<BatchDetailResponse | null>(null);
  const [selectedRunId, setSelectedRunId] = useState("");
  const [runDetail, setRunDetail] = useState<RunDetailResponse | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [batchKey, setBatchKey] = useState(() => `synthetic-${Date.now()}`);
  const [importResult, setImportResult] = useState<BatchImportResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState("");

  const reload = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true); else setRefreshing(true);
    setError("");
    try {
      const [batchResponse, runResponse] = await Promise.all([
        canReadBatches ? getBatches(50, 0) : Promise.resolve(null),
        canReadRuns ? getRuns(50, 0) : Promise.resolve(null),
      ]);
      setBatches(batchResponse?.items ?? []);
      setRuns(runResponse?.items ?? []);
      if (selectedBatchId && batchResponse?.items.some(item => item.batch_id === selectedBatchId)) {
        setBatchDetail(await getBatch(selectedBatchId));
      } else if (selectedBatchId) { setSelectedBatchId(""); setBatchDetail(null); }
      if (selectedRunId && runResponse?.items.some(item => item.run_id === selectedRunId) && canReadResults) {
        setRunDetail(await getRun(selectedRunId));
      } else if (selectedRunId && (!runResponse?.items.some(item => item.run_id === selectedRunId) || !canReadResults)) {
        setSelectedRunId(""); setRunDetail(null);
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Metadata batch atau run gagal dimuat.");
    } finally { setLoading(false); setRefreshing(false); }
  }, [canReadBatches, canReadRuns, canReadResults, selectedBatchId, selectedRunId]);

  useEffect(() => { void reload(); }, [reload]);

  async function chooseBatch(id: string) {
    setSelectedBatchId(id); setBatchDetail(null); setError("");
    if (!id) return;
    try { setBatchDetail(await getBatch(id)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Detail batch gagal dimuat."); }
  }
  async function chooseRun(id: string) {
    setSelectedRunId(id); setRunDetail(null); setError(""); setFeedback("");
    if (!id || !canReadResults) return;
    try { setRunDetail(await getRun(id)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Hasil run gagal dimuat."); }
  }
  async function submitImport(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file || busy || !/^synthetic-[a-z0-9][a-z0-9-]{0,60}$/.test(batchKey)) return;
    setBusy(true); setError(""); setFeedback(""); setImportResult(null);
    try {
      const result = await importSyntheticCsv(file, batchKey);
      setImportResult(result);
      setFeedback(result.batch.status === "rejected" ? "Impor ditolak; batch tidak dapat digunakan untuk analisis." : "Metadata batch diterima dari server.");
      await reload(true);
      setSelectedBatchId(result.batch.batch_id);
      setBatchDetail(await getBatch(result.batch.batch_id));
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Impor gagal."); }
    finally { setBusy(false); }
  }
  async function submitRun(batchId: string, retryOfRunId?: string) {
    if (busy) return;
    setBusy(true); setError(""); setFeedback("");
    try {
      const response = await createRun({ batch_id: batchId, ...(retryOfRunId ? { retry_of_run_id: retryOfRunId } : {}), action_policy_version: ACTION_POLICY_VERSION });
      setFeedback(response.notice);
      await reload(true);
      setSelectedRunId(response.run.run_id);
      if (canReadResults) setRunDetail(await getRun(response.run.run_id));
      else setRunDetail(null);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Pembuatan AnalysisRun gagal."); }
    finally { setBusy(false); }
  }

  return <>
    <PageHeading eyebrow="ALUR DATA SINTETIS" title="Batch dan AnalysisRun" description="Impor skema CSV sintetis, jalankan analisis tersimpan, lalu tinjau kandidat berdasarkan run yang dipilih." action={<button className="button button-secondary" onClick={() => void reload(true)} disabled={refreshing}><RefreshCw size={14} />Muat ulang</button>} />
    <div className="notice-panel workflow-notice"><ShieldCheck size={18} /><p><strong>Synthetic only.</strong> Jangan unggah berkas BPJS atau data peserta nyata. Deklarasi synthetic-only adalah kontrol prototipe, bukan verifikasi asal data; scope saat ini dibagi antar-pengguna dan belum memiliki assignment-based access control.</p></div>
    {error && <div className="workflow-error" role="alert"><strong>Permintaan gagal</strong><span>{error}</span><small>Periksa sesi, permission, CSRF, dan ketersediaan backend. Respons tidak dianggap sukses.</small></div>}
    {feedback && <div className="workflow-feedback" role="status">{feedback}</div>}
    {loading ? <LoadingState label="Memuat metadata batch dan AnalysisRun…" /> : <div className="workflow-grid">
      <section className="surface-panel workflow-panel">
        <div className="panel-heading-row"><div><span className="eyebrow muted-eyebrow">DATA BATCH</span><h2>Impor dan validasi</h2></div><Database size={18} /></div>
        {canWriteBatches ? <form className="workflow-form" onSubmit={event => void submitImport(event)}>
          <label className="review-field">File CSV sintetis<input type="file" accept=".csv,text/csv" onChange={event => setFile(event.target.files?.[0] ?? null)} disabled={busy} /></label>
          <label className="review-field">Kunci batch<input value={batchKey} maxLength={69} onChange={event => setBatchKey(event.target.value)} disabled={busy} /></label>
          <small>Skema: synthetic-claims-v1 · mapping: synthetic-canonical-v1 · batas unggah mengikuti konfigurasi server.</small>
          <button className="button button-primary" type="submit" disabled={busy || !file || !/^synthetic-[a-z0-9][a-z0-9-]{0,60}$/.test(batchKey)}><FileUp size={15} />{busy ? "Mengirim…" : "Validasi dan simpan batch"}</button>
        </form> : <EmptyState title="Impor tidak diizinkan" message="Role ini tidak memiliki batches:write. Metadata batch dapat dibaca sesuai permission akun." />}
        {importResult && <BatchCard batch={importResult.batch} notice={importResult.notice} />}
        <div className="workflow-list-heading"><strong>Batch tersedia</strong><span>{batches.length} dari maksimum 50</span></div>
        {!canReadBatches ? <EmptyState title="Tidak ada akses baca batch" message="Akun ini tidak memiliki batches:read." /> : batches.length === 0 ? <EmptyState title="Belum ada batch" message="Impor file CSV sintetis yang lolos validasi untuk membuat batch." /> : <div className="workflow-list">{batches.map(batch => <button className={`workflow-list-item${selectedBatchId === batch.batch_id ? " selected" : ""}`} key={batch.batch_id} onClick={() => void chooseBatch(batch.batch_id)}><span><strong>{batch.batch_key} · v{batch.batch_version}</strong><small>{batch.row_count ?? "—"} baris · {batch.created_at}</small></span><StatusPill value={batch.status} /></button>)}</div>}
        {batchDetail && <BatchCard batch={batchDetail.batch} notice={batchDetail.notice} />}
      </section>

      <section className="surface-panel workflow-panel">
        <div className="panel-heading-row"><div><span className="eyebrow muted-eyebrow">ANALYSIS RUN</span><h2>Jalankan dan baca hasil tersimpan</h2></div><SourceBadge source={{ kind: "synthetic", label: "synthetic_data_batch" }} /></div>
        {canWriteRuns && <div className="workflow-run-create"><p>Pembuatan run hanya menerima batch <code>ready</code> atau <code>ready_with_warnings</code>. Policy demo: <code>{ACTION_POLICY_VERSION}</code>.</p><button className="button button-primary" disabled={busy || !batchDetail || !["ready", "ready_with_warnings"].includes(batchDetail.batch.status)} onClick={() => void submitRun(batchDetail!.batch.batch_id)}><ArrowRight size={15} />Buat AnalysisRun dari batch terpilih</button>{batchDetail?.batch.status === "rejected" && <small>Batch ditolak tidak dapat dijalankan.</small>}</div>}
        {!canReadRuns ? <EmptyState title="Tidak ada akses baca run" message="Akun ini tidak memiliki runs:read." /> : runs.length === 0 ? <EmptyState title="Belum ada AnalysisRun" message="Run dibuat secara eksplisit dari batch siap; keberadaan batch tidak menjalankan analisis otomatis." /> : <div className="workflow-list">{runs.map(run => <button className={`workflow-list-item${selectedRunId === run.run_id ? " selected" : ""}`} key={run.run_id} onClick={() => void chooseRun(run.run_id)}><span><strong>{run.run_id}</strong><small>{run.batch_id} · v{run.batch_version} · {run.created_at}</small></span><StatusPill value={run.execution_status} /></button>)}</div>}
        {canWriteRuns && runs.some(run => run.execution_status === "failed") && <div className="workflow-retry-list"><strong>Run gagal yang dapat dicoba ulang</strong>{runs.filter(run => run.execution_status === "failed").map(run => <button key={run.run_id} className="button button-secondary" disabled={busy} onClick={() => void submitRun(run.batch_id, run.run_id)}><RotateCcw size={14} />Coba ulang {run.run_id}</button>)}</div>}
        {selectedRunId && !canReadResults && <div className="notice-panel"><ShieldCheck size={17} /><p>Run terpilih. Role ini dapat membuat run, tetapi tidak memiliki <code>runs:results:read</code>. Minta verifikator/audit lead membuka hasil tersimpan.</p></div>}
        {runDetail && <RunResultPanel detail={runDetail} />}
      </section>
    </div>}
  </>;
}

function StatusPill({ value }: { value: string }) { return <span className={`status-pill status-${value}`}>{value.replace(/_/g, " ")}</span>; }

function BatchCard({ batch, notice }: { batch: BatchMetadata; notice: string }) {
  return <div className="batch-result-card"><div className="batch-result-heading"><strong>{batch.batch_id} · v{batch.batch_version}</strong><StatusPill value={batch.status} /></div><p>{notice}</p><dl><div><dt>Schema / mapping</dt><dd>{batch.schema_version} / {batch.mapping_version}</dd></div><div><dt>Jumlah baris</dt><dd>{batch.row_count ?? "Belum diketahui"}</dd></div><div><dt>Temuan validasi</dt><dd>{batch.validation.error_count} error · {Object.values(batch.validation.warning_counts).reduce<number>((n, item) => n + (typeof item === "number" ? item : 0), 0)} warning</dd></div></dl>
    {Object.keys(batch.validation.error_counts).length > 0 && <div className="validation-errors"><strong>Ringkasan error</strong>{Object.entries(batch.validation.error_counts).map(([code, count]) => <span key={code}>{code}: {count}</span>)}</div>}
    {batch.validation.errors.length > 0 && <details><summary>Referensi aman (maksimum {batch.validation.errors.length})</summary><ul>{batch.validation.errors.map((item, i) => <li key={`${item.code}-${i}`}>{item.code}{item.row ? ` · baris ${item.row}` : ""}{item.column ? ` · kolom ${item.column}` : ""}</li>)}</ul></details>}
  </div>;
}

function RunResultPanel({ detail }: { detail: RunDetailResponse }) {
  const [candidatePage, setCandidatePage] = useState(1);
  const { run, result } = detail;
  const candidateItems = result ? Object.values(result.cases) : [];
  const pageSize = 10;
  const pageCount = Math.max(1, Math.ceil(candidateItems.length / pageSize));
  const currentPage = Math.min(candidatePage, pageCount);
  const visibleCandidates = candidateItems.slice((currentPage - 1) * pageSize, currentPage * pageSize);
  useEffect(() => setCandidatePage(1), [run.run_id]);
  return <div className="run-result-card"><div className="batch-result-heading"><div><span className="eyebrow muted-eyebrow">HASIL PERSISTEN</span><strong>{run.run_id}</strong></div><StatusPill value={run.execution_status} /></div>
    <p>{detail.notice}</p>
    <dl><div><dt>Sumber</dt><dd>{run.batch_id} · versi {run.batch_version}</dd></div><div><dt>Dibuat / selesai</dt><dd>{run.created_at} / {run.completed_at ?? "Belum selesai"}</dd></div><div><dt>Detektor / scoring / priority / policy</dt><dd>{run.detector_suite_version ?? "—"} / {run.scoring_version ?? "—"} / {run.priority_version ?? "—"} / {run.action_policy_version ?? "—"}</dd></div></dl>
    {run.failure_category && <div className="workflow-error">Analisis gagal ({run.failure_category}); tidak ada hasil sukses yang ditampilkan.</div>}
    {!result ? <EmptyState title="Hasil belum tersedia" message="Run belum menyimpan result payload. Muat ulang setelah status terminal atau periksa kategori kegagalan." /> : <>
      <p className="run-result-meta">Data source: <strong>{result.data_source.label ?? result.data_source.kind}</strong> · execution: <strong>{result.execution_status}</strong> · {result.records_considered} record dipertimbangkan, {result.records_eligible} eligible.</p>
      <div className="result-section"><strong>Cakupan enam pemeriksaan</strong><div className="result-indicator-grid">{result.indicators.map(item => <article key={item.code}><div><strong>{item.name}</strong><StatusPill value={item.status} /></div><p>{item.candidate_count === null ? "Jumlah kandidat tidak tersedia" : `${item.candidate_count} kandidat`} · ${item.eligible_count} assessed · ${item.not_applicable_count} N/A · ${item.unassessed_count} belum dinilai${item.search_truncated ? " · pencarian terpotong" : ""}</p><small>{item.definition}</small>{item.limitations.length > 0 && <ul>{item.limitations.map(x => <li key={x}>{x}</li>)}</ul>}</article>)}</div></div>
      <div className="result-summary-grid"><article><span>Risk score</span><strong>{Object.keys(result.cases).length ? "Indeks per kandidat" : "Belum tersedia"}</strong><p>Skor individual hanya ditampilkan untuk kandidat yang disertakan; indeks aturan provisional, bukan probabilitas fraud.</p></article><article><span>Facility audit priority</span><strong>{result.audit_priority.status === "available" || result.audit_priority.status === "partial" ? "Tersedia sesuai hasil server" : "Tidak dapat dinilai"}</strong><p>{result.audit_priority.eligibility_reasons?.join("; ") || result.audit_priority.limitations.join("; ") || "Tidak ada alasan tambahan dari server."}</p></article><article><span>Action policy · {result.action_policy.policy_version}</span><strong>{result.action_policy.input_assessment_status}</strong><p>{Object.entries(result.action_policy.lane_counts).map(([lane, count]) => `${lane}: ${count}`).join(" · ") || "Ringkasan lane tidak tersedia."}</p><small>Lane adalah saran demo provisional. Kandidat yang tidak ada dalam snapshot tidak dianggap green.</small></article></div>
      {(result.audit_priority.status === "available" || result.audit_priority.status === "partial") && result.audit_priority.items.length > 0 && <div className="result-section"><strong>Unit prioritas fasilitas yang dikembalikan server</strong><div className="priority-unit-list">{result.audit_priority.items.map((item, index) => { const unit = asJsonObject(item); const amount = unit ? valueText(unit.priority_index) : null; const id = unit ? valueText(unit.unit_id) : null; const count = unit ? valueText(unit.triggered_claim_count) : null; return <article key={`${id ?? "unit"}-${index}`}><strong>{id ?? `Unit ${index + 1}`}</strong><span>Indeks prioritas: {amount ?? "tidak tersedia"} · kandidat: {count ?? "tidak tersedia"}</span>{unit?.priority_status === "partial" && <small>Cakupan parsial; posisi dapat berubah bila pemeriksaan lebih lengkap.</small>}</article>; })}</div></div>}
      <div className="result-section"><strong>Kandidat dalam snapshot</strong>{candidateItems.length === 0 ? <EmptyState title="Run tidak menghasilkan kandidat" message="Kasus yang tidak muncul bukan hasil green dan tidak dinyatakan bebas risiko." /> : <><div className="workflow-list">{visibleCandidates.map(item => { const lane = result.action_policy.cases[item.case_id]; return <Link className="workflow-list-item result-case-link" key={item.case_id} to={`/runs/${encodeURIComponent(run.run_id)}/cases/${encodeURIComponent(item.case_id)}`}><span><strong>{item.case_id}</strong><small>{item.indicators.join(", ")} · score {item.risk_score === null ? "tidak dapat dinilai" : item.risk_score.toFixed(3)} · {item.score_status}</small></span><span>{lane ? <StatusPill value={lane.lane} /> : <small>Lane tidak disediakan</small>}<ArrowRight size={15} /></span></Link>; })}</div><div className="workflow-pagination"><span>{candidateItems.length} kandidat · halaman {currentPage}/{pageCount}</span><div><button className="button button-secondary" disabled={currentPage <= 1} onClick={() => setCandidatePage(currentPage - 1)}>Sebelumnya</button><button className="button button-secondary" disabled={currentPage >= pageCount} onClick={() => setCandidatePage(currentPage + 1)}>Berikutnya</button></div></div></>}</div>
      {(result.limitations.length > 0 || result.action_policy.limitations.length > 0) && <div className="result-section"><strong>Keterbatasan</strong><ul>{[...result.limitations, ...result.action_policy.limitations].map((x, i) => <li key={`${i}-${x}`}>{x}</li>)}</ul></div>}
      <p className="workflow-disclaimer">Hasil hanya berasal dari synthetic CSV/fixture; bukan bukti fraud dan bukan validasi kinerja pada data JKN nyata.</p>
    </>}
  </div>;
}

function asJsonObject(value: import("../api/client").JsonValue): Record<string, import("../api/client").JsonValue> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value : null;
}
function valueText(value: import("../api/client").JsonValue | undefined): string | null {
  return typeof value === "string" || typeof value === "number" ? String(value) : null;
}
