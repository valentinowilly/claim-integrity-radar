import { useCallback, useEffect, useState, type FormEvent } from "react";
import { ArrowLeft, History, Save, ShieldCheck } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import {
  getRun, getRunCaseReview, recordRunCaseOutcome, reviewOutcomeLabels, runReviewStatusLabels,
  updateRunCaseReview, type ReviewOutcome, type RunCase, type RunDetailResponse,
  type RunReviewResponse, type RunReviewStatus,
} from "../api/client";
import { EmptyState, LoadingState, PageHeading, SourceBadge } from "../components/DataStates";
import { useAuth } from "../auth/AuthContext";

const statusValues = Object.keys(runReviewStatusLabels) as RunReviewStatus[];
const outcomeValues = Object.keys(reviewOutcomeLabels) as ReviewOutcome[];

export default function RunCaseReviewPage() {
  const { runId = "", caseId = "" } = useParams();
  const { state: auth } = useAuth();
  const permissions = "session" in auth ? auth.session?.permissions ?? [] : [];
  const canRead = permissions.includes("review:read") && permissions.includes("runs:results:read");
  const canUpdateStatus = permissions.includes("review:write");
  const canUpdateOutcome = permissions.includes("review:manage");
  const [run, setRun] = useState<RunDetailResponse | null>(null);
  const [review, setReview] = useState<RunReviewResponse | null>(null);
  const [status, setStatus] = useState<RunReviewStatus>("pending_review");
  const [outcome, setOutcome] = useState<ReviewOutcome>("inconclusive");
  const [note, setNote] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [feedback, setFeedback] = useState("");
  const [notFound, setNotFound] = useState(false);

  const reload = useCallback(async () => {
    if (!canRead) { setLoading(false); return; }
    setLoading(true); setError(""); setNotFound(false);
    try {
      const savedRun = await getRun(runId);
      const candidate = savedRun.result?.cases[caseId];
      if (!candidate) { setNotFound(true); setRun(savedRun); setReview(null); return; }
      const savedReview = await getRunCaseReview(runId, caseId);
      setRun(savedRun); setReview(savedReview); setStatus(savedReview.review_status);
      setOutcome(savedReview.review_outcome ?? "inconclusive"); setNote(savedReview.note ?? "");
    } catch (reason) {
      if (reason && typeof reason === "object" && "status" in reason && (reason as { status: unknown }).status === 404) setNotFound(true);
      else setError(reason instanceof Error ? reason.message : "Konteks run atau review gagal dimuat.");
    } finally { setLoading(false); }
  }, [runId, caseId, canRead]);
  useEffect(() => { void reload(); }, [reload]);

  async function submitStatus(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || !canUpdateStatus || note.length > 1000) return;
    setBusy(true); setError(""); setFeedback("");
    try {
      await updateRunCaseReview(runId, caseId, { review_status: status, note: note.trim() || null });
      await reload(); setFeedback("Status dan riwayat dimuat ulang dari penyimpanan server.");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Perubahan status tidak tersimpan."); }
    finally { setBusy(false); }
  }
  async function submitOutcome(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || !canUpdateOutcome || note.length > 1000) return;
    setBusy(true); setError(""); setFeedback("");
    try {
      await recordRunCaseOutcome(runId, caseId, { review_outcome: outcome, note: note.trim() || null });
      await reload(); setFeedback("Outcome dan riwayat dimuat ulang dari penyimpanan server.");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Outcome tidak tersimpan."); }
    finally { setBusy(false); }
  }

  if (!canRead) return <section className="empty-state-panel"><span className="panel-kicker">AKSES DIBATASI</span><h2>Hasil run tidak dapat dibaca</h2><p>Halaman membutuhkan runs:results:read dan review:read. Backend tetap menjadi sumber otorisasi.</p><Link className="button button-secondary" to="/workflow"><ArrowLeft size={15} />Kembali ke batch dan run</Link></section>;
  if (loading) return <LoadingState label="Memuat hasil run dan review tersimpan…" />;
  if (notFound) return <section className="surface-panel not-found-case"><span className="panel-kicker">KASUS RUN TIDAK DITEMUKAN</span><h2>Pasangan run dan kasus tidak tersedia</h2><p>Kasus harus menjadi kandidat pada hasil AnalysisRun yang persis dipilih.</p><Link className="button button-secondary" to="/workflow"><ArrowLeft size={15} />Kembali ke AnalysisRun</Link></section>;

  const result = run?.result;
  const candidate: RunCase | undefined = result?.cases[caseId];
  const lane = result?.action_policy.cases[caseId];
  if (!run || !result || !candidate || !review) return <EmptyState title="Detail review belum tersedia" message="Server tidak mengembalikan kandidat dan review lengkap untuk pasangan run/kasus ini." />;

  return <>
    <PageHeading eyebrow="TINJAUAN TERIKAT RUN" title="Detail kandidat" description="Identitas review adalah pasangan AnalysisRun dan case ID; hasil analitik tetap immutable." action={<Link className="button button-secondary" to="/workflow"><ArrowLeft size={15} />Kembali ke run</Link>} />
    <div className="notice-panel workflow-notice"><ShieldCheck size={18} /><p>Semua sumber saat ini sintetis. Review adalah metadata proses, bukan keputusan fraud. Catatan disimpan lokal; aplikasi demo belum memiliki assignment-based access control. Jangan memasukkan data peserta, klaim nyata, atau informasi sensitif.</p></div>
    {error && <div className="workflow-error" role="alert"><strong>Permintaan gagal</strong><span>{error}</span></div>}
    {feedback && <div className="workflow-feedback" role="status">{feedback}</div>}
    <section className="detail-hero surface-panel"><div className="detail-identity"><span className="detail-icon"><History size={19} /></span><div><span className="eyebrow muted-eyebrow">{run.run.run_id}</span><h2>{candidate.case_id}</h2></div></div><div className="detail-meta"><span className="status-pill status-neutral">Skor: {candidate.risk_score === null ? "tidak dapat dinilai" : candidate.risk_score.toFixed(3)} · {candidate.score_status}</span><StatusBadge status={review.review_status} /><SourceBadge source={result.data_source} /></div></section>
    <div className="result-summary-grid review-run-context"><article><span>Batch sumber</span><strong>{run.run.batch_id} · v{run.run.batch_version}</strong><p>Run dibuat {new Date(run.run.created_at).toLocaleString()}</p></article><article><span>Action lane</span><strong>{lane?.lane ?? "Tidak disediakan"}</strong><p>{lane?.reasons.join("; ") ?? "Tidak ada rekomendasi lane untuk kandidat ini."}</p></article><article><span>Versi policy</span><strong>{lane?.policy_version ?? run.run.action_policy_version ?? "—"}</strong><p>{lane?.limitations.join("; ") ?? "Lane tidak ditafsirkan sebagai keputusan fraud."}</p></article></div>
    <section className="surface-panel section-block run-case-reasons"><div className="panel-heading-row"><div><span className="eyebrow muted-eyebrow">ALASAN DAN CAKUPAN</span><h2>Sinyal untuk diperiksa auditor</h2></div></div>{candidate.reasons.length ? candidate.reasons.map((reason, i) => <article className="run-reason" key={`${reason.indicator}-${i}`}><strong>{reason.indicator.replace(/_/g, " ")}</strong><p>{reason.summary}</p>{reason.evidence.length > 0 && <ul>{reason.evidence.map((item, j) => <li key={j}>{item}</li>)}</ul>}{reason.limitations.length > 0 && <small>{reason.limitations.join("; ")}</small>}</article>) : <EmptyState title="Alasan tidak disediakan" message="Hasil run tidak mengandung teks alasan untuk kandidat ini." />}
      <div className="coverage-chip-list">{candidate.indicator_coverage.map(item => <span className="coverage-chip" key={item.indicator}><strong>{item.indicator.replace(/_/g, " ")}</strong> · {item.status}{item.reason ? ` — ${item.reason}` : ""}</span>)}</div>{candidate.limitations.length > 0 && <ul>{candidate.limitations.map(item => <li key={item}>{item}</li>)}</ul>}</section>
    <section className="workflow-review-grid">
      <form className="surface-panel workflow-form" onSubmit={event => void submitStatus(event)}><div className="panel-heading-row"><div><span className="eyebrow muted-eyebrow">STATUS PROSES</span><h2>Tindak lanjut</h2></div><StatusBadge status={review.review_status} /></div><label className="review-field">Status<select value={status} onChange={event => setStatus(event.target.value as RunReviewStatus)} disabled={!canUpdateStatus || busy}>{statusValues.map(value => <option value={value} key={value}>{runReviewStatusLabels[value]}</option>)}</select></label><label className="review-field">Catatan sintetis opsional<textarea value={note} onChange={event => setNote(event.target.value)} maxLength={1000} disabled={!canUpdateStatus || busy} placeholder="Ringkasan aman untuk tinjauan, tanpa identitas atau nilai klaim nyata." /></label><div className="review-form-footer"><span className={`character-count${note.length > 1000 ? " character-count-error" : ""}`}>{note.length}/1000</span><button className="button button-primary" type="submit" disabled={!canUpdateStatus || busy || note.length > 1000}><Save size={14} />{busy ? "Menyimpan…" : "Simpan status"}</button></div>{!canUpdateStatus && <small>Role ini tidak memiliki review:write.</small>}</form>
      <form className="surface-panel workflow-form" onSubmit={event => void submitOutcome(event)}><div className="panel-heading-row"><div><span className="eyebrow muted-eyebrow">KESIMPULAN MANUSIA</span><h2>Outcome tinjauan</h2></div><span className="status-pill status-neutral">{review.review_outcome_label ?? "Belum dicatat"}</span></div><label className="review-field">Outcome<select value={outcome} onChange={event => setOutcome(event.target.value as ReviewOutcome)} disabled={!canUpdateOutcome || busy}>{outcomeValues.map(value => <option value={value} key={value}>{reviewOutcomeLabels[value]}</option>)}</select></label><p className="workflow-muted">Taksonomi prototipe sementara; menyatakan dukungan pada sinyal yang diperiksa, bukan keputusan hukum/operasional atau fraud terverifikasi.</p><div className="review-form-footer"><span className="reviewer-demo-label">Aktor berasal dari sesi tervalidasi server.</span><button className="button button-primary" type="submit" disabled={!canUpdateOutcome || busy}><Save size={14} />{busy ? "Menyimpan…" : "Simpan outcome"}</button></div>{!canUpdateOutcome && <small>Hanya role berpermission review:manage yang dapat mencatat outcome.</small>}</form>
    </section>
    <section className="surface-panel review-history-panel"><div className="panel-heading-row"><div><span className="eyebrow muted-eyebrow">RIWAYAT APPEND-ONLY</span><h2><History size={16} />Perubahan review</h2></div><span className="history-count">{review.history.length} event</span></div>{review.history.length === 0 ? <EmptyState title="Belum ada perubahan" message="Status awal Menunggu Tinjauan; GET tidak membuat baris atau event review." /> : <ol className="review-history-list">{review.history.map((event, index) => <li className={`review-history-item${index === review.history.length - 1 ? " review-history-current" : ""}`} key={event.event_id}><span className="history-marker" /><div className="history-event-content"><div className="history-event-heading"><strong className="history-event-label">{event.event_type.replace(/_/g, " ")} · aktor {event.actor_user_id}</strong><time dateTime={event.occurred_at}>{new Date(event.occurred_at).toLocaleString()}</time></div><div className="history-status-transition">{event.previous_status && <StatusBadge status={event.previous_status} />}<span>→</span>{event.new_status && <StatusBadge status={event.new_status} />}{event.previous_outcome && <span>{reviewOutcomeLabels[event.previous_outcome]}</span>}{event.new_outcome && <strong>{reviewOutcomeLabels[event.new_outcome]}</strong>}</div>{event.note && <p className="history-note">{event.note}</p>}</div></li>)}</ol>}</section>
    <p className="workflow-disclaimer">Current review status: <strong>{review.review_status_label}</strong> · outcome: <strong>{review.review_outcome_label ?? "belum dicatat"}</strong> · terakhir diubah {review.updated_at ? new Date(review.updated_at).toLocaleString() : "belum pernah"}.</p>
  </>;
}

function StatusBadge({ status }: { status: string }) { return <span className={`status-pill status-${status}`}>{runReviewStatusLabels[status as RunReviewStatus] ?? status.replace(/_/g, " ")}</span>; }
