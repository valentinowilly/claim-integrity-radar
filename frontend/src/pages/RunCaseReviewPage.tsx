import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { UserRound, ArrowDown, ArrowLeft, FileSearch, History, Lightbulb, Lock, Save, ShieldCheck, Sparkles } from "lucide-react";
import { Link } from "react-router-dom";
import { useNotify } from "../notifications/NotificationCenter";
import {
  auditResultLabels, getRunCase, getRunCaseReview, recordRunCaseAuditConfirmation, recordRunCaseOutcome, reviewOutcomeLabels,
  runReviewStatusLabels, type AuditResult,
  updateRunCaseReview, type ReviewOutcome, type RunCase, type RunDetailResponse,
  type RunReviewResponse, type RunReviewStatus,
  changeAssignment, getRunAssignments, type CaseAssignment,
} from "../api/client";
import { ClinicalNoteCard } from "../components/ClinicalNoteCard";
import { VisitTimeline } from "../components/VisitTimeline";
import { EmptyState, ErrorState, LoadingState } from "../components/DataStates";
import {
  EvidenceList, mlQualification, PatternOnlyNotice, TechnicalDetails, aiScore, formatCount, formatDate, formatDateTime, indicatorDefinition,
  indicatorGuidance, indicatorLabel, mlFeatureLabel, mlLevel, ruleIndexText, runTitle, shortRef, statusText, LANES, LaneDot,
  attributeLabel,
} from "../components/Display";
import { useAuth } from "../auth/AuthContext";

const statusValues = Object.keys(runReviewStatusLabels) as RunReviewStatus[];
const outcomeValues = Object.keys(reviewOutcomeLabels) as ReviewOutcome[];
// Reviewer guidance per check type; generic process steps, not claim-specific facts.
const REVIEW_HINTS: Record<string, string> = {
  repeat_billing_candidate: "Bandingkan tanggal pulang, resume medis, dan berkas klaim. Pastikan tiap kunjungan memang layanan terpisah.",
  similar_claim_pattern_candidate: "Bandingkan berkas pendukung. Pengobatan yang umum memang bisa menghasilkan pola yang sama.",
  near_duplicate_claim_candidate: "Periksa apakah kedua klaim benar-benar layanan yang berbeda. Klaim rutin memang sering mirip.",
  temporal_pattern_candidate: "Periksa apakah kunjungan ini satu rangkaian perawatan atau terapi terjadwal.",
  synthetic_capacity_candidate: "Bandingkan jumlah layanan yang tercatat dengan jumlah tenaga dan kapasitas faskes pada hari itu.",
  supporting_evidence_completeness_candidate: "Periksa apakah dokumen pendukung yang disebutkan benar-benar ada di berkas klaim.",
  length_of_stay_extreme_candidate: "Periksa resume medis dan catatan harian rawat: apakah ada komplikasi yang membenarkan rawat selama itu?",
  rapid_readmission_candidate: "Bandingkan kedua resume medis: apakah ini dua episode, atau satu episode yang dipecah menjadi dua klaim?",
  unusual_severity_candidate: "Periksa diagnosis sekunder dan tindakan di resume medis yang mendasari tingkat keparahan INA-CBG.",
  cloned_clinical_note_candidate: "Bandingkan rekam medis para pasien: apakah catatan disalin dari pasien lain tanpa pemeriksaan sendiri?",
  severity_without_secondary_candidate: "Periksa resume medis: adakah komorbid atau komplikasi yang mendasari tingkat keparahan INA-CBG?",
  unusual_special_topup_candidate: "Periksa indikasi medis serta bukti pemberian obat, pemasangan alat, atau pelaksanaan tindakannya.",
};
const STATUS_HELP: Record<RunReviewStatus, string> = {
  pending_review: "Belum ada yang memeriksa klaim ini.",
  in_review: "Anda sedang memeriksa berkas klaim.",
  awaiting_evidence: "Risiko sedang: minta klarifikasi atau koreksi dari faskes; klaim tidak ditahan.",
  escalated: "Risiko tinggi: masuk antrean audit prioritas.",
  closed: "Tinjauan sudah selesai.",
};
// Records made by the system itself, not by a person.
const SYSTEM_ACTORS: Record<string, string> = {
  "system-continuity": "Sistem (dibawa dari analisis sebelumnya)",
  "system-inbox": "Sistem (sambungan otomatis)",
};
function actorName(id: string): string {
  return SYSTEM_ACTORS[id] ?? id;
}
const NOTE_PLACEHOLDER = "Catatan singkat. Jangan menulis identitas peserta.";

function failureText(reason: unknown, fallback: string): string {
  return reason instanceof Error ? reason.message : fallback;
}

/** One claim of one analysis: why it was flagged, and the human decisions for it. */
export function CaseReviewPanel({ runId, caseId, backTo, onSaved }: { runId: string; caseId: string; backTo: string; onSaved?: () => void }) {
  const notify = useNotify();
  const { state: auth } = useAuth();
  const permissions = "session" in auth ? auth.session?.permissions ?? [] : [];
  const canRead = permissions.includes("review:read") && permissions.includes("runs:results:read");
  const canUpdateStatus = permissions.includes("review:write");
  const canUpdateOutcome = permissions.includes("review:manage");
  const [run, setRun] = useState<RunDetailResponse | null>(null);
  const [review, setReview] = useState<RunReviewResponse | null>(null);
  const [status, setStatus] = useState<RunReviewStatus>("pending_review");
  const [outcome, setOutcome] = useState<ReviewOutcome>("inconclusive");
  const [auditResult, setAuditResult] = useState<AuditResult>("confirmed_issue");
  const [auditReference, setAuditReference] = useState("");
  const [auditNote, setAuditNote] = useState("");
  const [note, setNote] = useState("");
  const [loading, setLoading] = useState(true);
  // What the evidence cards found for this claim, so each finding links only to evidence that exists.
  const [evidence, setEvidence] = useState<Evidence>({ note: false, visits: 0 });
  useEffect(() => { setEvidence({ note: false, visits: 0 }); }, [runId, caseId]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [feedback, setFeedback] = useState("");
  const [notFound, setNotFound] = useState(false);
  const [holder, setHolder] = useState<CaseAssignment | null>(null);
  const loadHolder = useCallback(async () => {
    if (!canRead) return;
    try { setHolder((await getRunAssignments(runId)).items[caseId] ?? null); } catch { setHolder(null); }
  }, [runId, caseId, canRead]);
  useEffect(() => { void loadHolder(); }, [loadHolder]);
  async function assign(action: "take" | "release") {
    if (busy) return;
    setBusy(true); setError(""); setFeedback("");
    try {
      setHolder((await changeAssignment(runId, caseId, action)).assignment);
      setFeedback(action === "take" ? "Klaim ini sekarang Anda tangani." : "Klaim dilepas; petugas lain dapat mengambilnya.");
      onSaved?.();
    } catch (reason) {
      setError(failureText(reason, "Penanggung jawab tidak dapat diubah."));
      void loadHolder();
    } finally { setBusy(false); }
  }

  // Each load gets a sequence number; a response from an older or cancelled load is ignored.
  // Without this, a late duplicate load (e.g. React StrictMode running the effect twice) reset
  // the form to the saved status after the user had already changed it.
  const loadSequence = useRef(0);
  const reload = useCallback(async () => {
    if (!canRead) { setLoading(false); return; }
    const sequence = ++loadSequence.current;
    const current = () => sequence === loadSequence.current;
    setLoading(true); setError(""); setNotFound(false);
    try {
      // Only this claim's slice of the stored result is downloaded (server returns 404 if absent).
      const savedRun = await getRunCase(runId, caseId);
      if (!current()) return;
      const candidate = savedRun.result?.cases[caseId]
        ?? savedRun.result?.ml_anomaly?.items.find(item => item.case_id === caseId);
      if (!candidate) { setNotFound(true); setRun(savedRun); setReview(null); return; }
      const savedReview = await getRunCaseReview(runId, caseId);
      if (!current()) return;
      setRun(savedRun); setReview(savedReview); setStatus(savedReview.review_status);
      setOutcome(savedReview.review_outcome ?? "inconclusive"); setNote(savedReview.note ?? "");
    } catch (reason) {
      if (!current()) return;
      if (reason && typeof reason === "object" && "status" in reason && (reason as { status: unknown }).status === 404) setNotFound(true);
      else setError(failureText(reason, "Klaim atau tinjauannya tidak dapat dimuat."));
    } finally { if (current()) setLoading(false); }
  }, [runId, caseId, canRead]);
  useEffect(() => {
    setFeedback("");
    void reload();
    return () => { loadSequence.current += 1; };  // unmount or new case: drop the pending load
  }, [reload]);

  // One-click status from the bar that stays at the bottom while the reasons are read.
  async function quickStatus(next: RunReviewStatus) {
    if (busy || !canUpdateStatus) return;
    setBusy(true); setError(""); setFeedback("");
    try {
      await updateRunCaseReview(runId, caseId, { review_status: next, note: note.trim() || null });
      setStatus(next);
      await reload(); setFeedback("Status tinjauan tersimpan."); onSaved?.();
      notify({ tone: "success", title: "Status tinjauan tersimpan", message: `Klaim ${shortRef(caseId)}: ${runReviewStatusLabels[next].toLowerCase()}.` });
    } catch (reason) {
      setError(failureText(reason, "Status tinjauan tidak tersimpan."));
    } finally { setBusy(false); }
  }
  async function submitStatus(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || !canUpdateStatus || note.length > 1000) return;
    setBusy(true); setError(""); setFeedback("");
    try {
      await updateRunCaseReview(runId, caseId, { review_status: status, note: note.trim() || null });
      await reload(); setFeedback("Status tinjauan tersimpan."); onSaved?.();
      notify({ tone: "success", title: "Status tinjauan tersimpan", message: `Klaim ${shortRef(caseId)}: ${runReviewStatusLabels[status].toLowerCase()}.` });
    } catch (reason) {
      setError(failureText(reason, "Status tinjauan tidak tersimpan."));
      notify({ tone: "danger", title: "Status tinjauan tidak tersimpan", message: reason instanceof Error ? reason.message : undefined });
    }
    finally { setBusy(false); }
  }
  async function submitAudit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || !canUpdateOutcome || !auditReference.trim() || auditNote.length > 1000) return;
    setBusy(true); setError(""); setFeedback("");
    try {
      await recordRunCaseAuditConfirmation(runId, caseId, { audit_result: auditResult, audit_reference: auditReference.trim(), note: auditNote.trim() || null });
      await reload(); setAuditReference(""); setAuditNote(""); setFeedback("Hasil audit resmi tersimpan."); onSaved?.();
      notify({ tone: "success", title: "Hasil audit resmi tersimpan", message: `Klaim ${shortRef(caseId)}.` });
    } catch (reason) {
      setError(failureText(reason, "Hasil audit tidak tersimpan."));
      notify({ tone: "danger", title: "Hasil audit tidak tersimpan", message: reason instanceof Error ? reason.message : undefined });
    }
    finally { setBusy(false); }
  }
  async function submitOutcome(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || !canUpdateOutcome || note.length > 1000) return;
    setBusy(true); setError(""); setFeedback("");
    try {
      await recordRunCaseOutcome(runId, caseId, { review_outcome: outcome, note: note.trim() || null });
      await reload(); setFeedback("Keputusan tinjauan tersimpan."); onSaved?.();
      notify({ tone: "success", title: "Keputusan tinjauan tersimpan", message: `Klaim ${shortRef(caseId)}: ${reviewOutcomeLabels[outcome].toLowerCase()}.` });
    } catch (reason) {
      setError(failureText(reason, "Keputusan tinjauan tidak tersimpan."));
      notify({ tone: "danger", title: "Keputusan tinjauan tidak tersimpan", message: reason instanceof Error ? reason.message : undefined });
    }
    finally { setBusy(false); }
  }

  const back = (always = false) => <Link className={`button button-secondary button-compact case-back${always ? " always" : ""}`} to={backTo}><ArrowLeft size={14} />Kembali ke daftar</Link>;
  if (!canRead) return <section className="card"><EmptyState title="Rincian klaim tidak dapat dibuka" message="Halaman ini membutuhkan izin membaca hasil analisis dan tinjauan." /></section>;
  if (loading) return <section className="card"><LoadingState label="Memuat klaim dan tinjauannya…" /></section>;
  if (notFound) return <section className="card not-found-case">{back(true)}<EmptyState title="Klaim tidak ada di analisis ini" message="Klaim hanya dapat ditinjau di dalam analisis tempat klaim itu ditandai atau diperingkat." /></section>;
  if (error && !review) return <section className="card">{back(true)}<ErrorState message={error} httpStatus={null} onRetry={() => void reload()} /></section>;

  const result = run?.result;
  const ruleCandidate: RunCase | undefined = result?.cases[caseId];
  const mlItem = result?.ml_anomaly?.items.find(item => item.case_id === caseId);
  // Claims surfaced only by the ML ranking have no rule reasons or coverage rows.
  const candidate: RunCase | undefined = ruleCandidate ?? (mlItem ? {
    case_id: caseId, risk_score: null, score_status: "not_assessable", indicators: [],
    indicator_coverage: [], reasons: [], limitations: [], ml_anomaly: mlItem ?? null,
  } : undefined);
  const mlRank = candidate?.ml_anomaly ?? null;
  const mlNotAssessed = ruleCandidate?.ml_inference ?? null;
  const lane = result?.action_policy.cases[caseId];
  if (!run || !result || !candidate || !review) return <section className="card">{back(true)}<EmptyState title="Rincian tinjauan tidak tersedia" message="Server tidak mengirim data klaim dan tinjauan yang lengkap." /></section>;
  const heading = ruleCandidate
    ? (ruleCandidate.indicators.map(indicatorLabel).join(" + ") || "Klaim ditandai")
    : "Temuan tambahan AI";
  const scored = result.ml_anomaly?.records_scored ?? 0;
  const percentile = mlRank ? mlRank.reference_percentile ?? mlRank.anomaly_percentile : null;
  const level = percentile !== null ? mlLevel(percentile) : null;
  const laneKey = lane && lane.lane in LANES ? lane.lane as keyof typeof LANES : null;
  // Plain-language reason: never the raw policy band text.
  const verdictReason = candidate.risk_score !== null
    ? `Skor temuan ${Math.round(candidate.risk_score * 100)} dari 100.`
    : laneKey === "red" ? "Ditandai pemeriksaan aturan dan dinilai sangat tidak biasa oleh AI."
    : laneKey === "yellow" ? "Ditandai pemeriksaan aturan dan dinilai tidak biasa oleh AI."
    : laneKey === "green" ? "Ditandai pemeriksaan aturan, tetapi AI menilai polanya wajar." : "";
  // Factors behind the AI score: per-claim signals against the training data, else the stored top-list deviations.
  const factors = (mlRank?.supporting_signals ?? []).map(item => ({ feature: item.feature, description: item.description, percentile: item.training_percentile }))
    .concat(!(mlRank?.supporting_signals?.length) ? (mlItem?.top_deviations ?? []) : []).slice(0, 4);
  const training = result.ml_anomaly?.training_reference;
  const trainingText = training?.rows_eligible
    ? `Model dilatih dengan ${formatCount(training.rows_eligible)} klaim rumah sakit${training.date_from && training.date_to ? ` (${formatDate(training.date_from)} – ${formatDate(training.date_to)})` : ""}, lalu membandingkan klaim ini dengan pola klaim tersebut.`
    : "AI membandingkan klaim ini dengan pola seluruh klaim pada analisis ini.";
  const suggested: RunReviewStatus | null = laneKey === "red" ? "escalated" : laneKey === "yellow" ? "awaiting_evidence" : null;

  return <div className="case-panel stack">
    {error && <div className="workflow-error" role="alert"><strong>Permintaan gagal</strong><span>{error}</span></div>}
    {feedback && <div className="workflow-feedback" role="status">{feedback}</div>}

    <section className="case-hero-panel" aria-label="Ringkasan klaim">
      {back()}
      <div className="case-hero">
        <div>
          <span className="eyebrow-text">{runTitle(run.run)} · Ref. klaim {shortRef(caseId)}</span>
          <h2>{heading}</h2>
        </div>
        <div className="case-hero-badges"><StatusBadge status={review.review_status} />{review.review_outcome && <span className="status-pill tone-neutral">{reviewOutcomeLabels[review.review_outcome]}</span>}</div>
      </div>
      {laneKey && <div className={`verdict-box ${laneKey === "red" ? "high" : laneKey === "yellow" ? "medium" : "low"}`} style={{ marginTop: 16 }} data-testid="case-lane">
        <span className="verdict-level"><LaneDot lane={laneKey} /> {LANES[laneKey].name.toUpperCase()} · {LANES[laneKey].meaning}</span>
        <p>{verdictReason} <strong>Saran: {LANES[laneKey].action}.</strong></p>
      </div>}
      <div className="fact-grid">
        <div className="fact">
          <span>Tingkat risiko</span>
          <strong>{laneKey ? LANES[laneKey].name : "Belum dinilai"}</strong>
          <small>{laneKey ? LANES[laneKey].action : "Data belum cukup untuk memberi saran."}</small>
        </div>
        <div className="fact">
          <span>Skor AI</span>
          <strong>{percentile !== null ? `${aiScore(percentile)} / 100` : mlNotAssessed ? "Tidak dinilai" : "—"}</strong>
          <small>{level ? level.label : mlNotAssessed ? "Data untuk AI tidak lengkap." : "Klaim ini tidak dinilai AI."}</small>
        </div>
        <div className="fact">
          <span>Pemeriksaan yang menandai</span>
          <strong>{candidate.indicators.length || "—"}</strong>
          <small>{candidate.indicators.map(indicatorLabel).join(", ") || "Hanya ditandai AI"}</small>
        </div>
      </div>
    </section>

    <section className="card run-case-reasons" aria-label="Alasan ditandai">
      <div className="card-head"><div><h2>Mengapa klaim ini perlu diperiksa?</h2><p>Temuan dari pemeriksaan aturan.</p></div></div>
      <div className="stack">
        {candidate.reasons.length ? candidate.reasons.map((reason, i) => <article className="reason-card run-reason" key={`${reason.indicator}-${i}`}>
          <h4>{indicatorLabel(reason.indicator)}</h4>
          <PatternOnlyNotice evidence={reason.supporting_values?.billing_status_evidence} />
          {indicatorDefinition(reason.indicator) && <p>{indicatorDefinition(reason.indicator)}</p>}
          <EvidenceList evidence={reason.evidence} />
          {(REVIEW_HINTS[reason.indicator] ?? indicatorGuidance(reason.indicator)) && <div className="guidance review-hint"><Lightbulb size={15} /><span><strong>Yang perlu diperiksa:</strong> {REVIEW_HINTS[reason.indicator] ?? indicatorGuidance(reason.indicator)}</span></div>}
          <EvidenceLink indicator={reason.indicator} evidence={evidence} />
        </article>) : <p className="fine-print">Lolos pemeriksaan aturan. Klaim ini masuk daftar karena penilaian AI di bawah.</p>}
      </div>
    </section>

    {(mlRank || mlNotAssessed) && <section className="card run-case-reasons" aria-label="Penilaian AI">
      <div className="card-head">
        <div><h2><Sparkles size={16} style={{ verticalAlign: "-2px", color: "var(--brand-ink)" }} /> Analisis AI</h2>
          <p>{trainingText}</p></div>
      </div>
      {mlNotAssessed && !mlRank && <p>AI tidak dapat menilai klaim ini karena data {mlNotAssessed.reason.replace(/^missing:/, "").split("+").map(field => attributeLabel(field)).join(", ")} kosong.</p>}
      {mlRank && percentile !== null && <div className="ai-card">
        <div className="ai-score">
          <span className="fine-print">Skor AI</span>
          <span className="ai-num">{aiScore(percentile)}<small> / 100</small></span>
          {level && <span className={`status-pill tone-${level.tone}`} style={{ justifySelf: "start" }}>{level.label}</span>}
          <span className="ai-meta">Peringkat {formatCount(mlRank.rank)} dari {formatCount(scored)} klaim pada periode ini{mlRank.tie_count && mlRank.tie_count > 1 ? ` (nilainya sama dengan ${formatCount(mlRank.tie_count - 1)} klaim lain)` : ""}.</span>
        </div>
        <div>
          <strong style={{ display: "block", marginBottom: 12 }}>Faktor yang membuat klaim ini tidak biasa</strong>
          {factors.length > 0 ? <ul className="ai-factors">{factors.map(item => (
            <li className="ai-factor" key={item.feature}>
              <div className="ai-factor-head"><span>{mlFeatureLabel(item.feature, item.description)}</span>
                <span>lebih tidak biasa daripada {Math.floor(item.percentile * 100)}% klaim lain</span></div>
              <div className="ai-bar" aria-hidden="true"><span style={{ width: `${Math.max(4, item.percentile * 100)}%` }} /></div>
            </li>))}</ul>
            : <p className="fine-print">Tidak ada satu faktor yang menonjol; yang tidak biasa adalah gabungan beberapa data.</p>}
        </div>
      </div>}
      <p className="ai-meta" style={{ marginTop: 14 }}>{ruleCandidate ? "" : "Klaim ini lolos pemeriksaan aturan; AI menemukannya dari pola data. "}{mlQualification(result.ml_anomaly)}</p>
    </section>}

    {(evidence.note || evidence.visits > 1) && <div className="evidence-heading" id="bukti">
      <h2><FileSearch size={17} className="head-icon" aria-hidden="true" />Bukti pendukung</h2>
      <p>Catatan klinis dan riwayat kunjungan yang mendasari temuan di atas.</p>
    </div>}
    <div id="bukti-catatan" className="evidence-anchor">
      <ClinicalNoteCard runId={runId} caseId={caseId} canAsk={canUpdateStatus} onLoaded={hasNote => setEvidence(current => ({ ...current, note: hasNote }))} />
    </div>
    <div id="bukti-kunjungan" className="evidence-anchor">
      <VisitTimeline runId={runId} caseId={caseId} relevant={candidate.indicators.some(code => VISIT_FINDINGS.has(code))}
        onLoaded={count => setEvidence(current => ({ ...current, visits: count }))} />
    </div>

    <section className="card" aria-label="Keputusan tinjauan">
      <div className="card-head"><div><h2>Keputusan tinjauan</h2><p>Isi dari langkah 1 sampai 3.</p></div></div>
      <div className="assignment-bar" data-testid="case-assignment">
        <span><UserRound size={15} aria-hidden="true" /> Penanggung jawab: <strong>{holder ? (holder.is_me ? "Anda" : holder.username) : "belum ada"}</strong></span>
        {canUpdateStatus && !holder && <button className="button button-secondary row-button" disabled={busy} onClick={() => void assign("take")}>Ambil klaim ini</button>}
        {canUpdateStatus && holder?.is_me && <button className="button button-secondary row-button" disabled={busy} onClick={() => void assign("release")}>Lepaskan</button>}
      </div>
      <div className="decision-steps">
        <div className={`decision-step${canUpdateStatus ? "" : " locked"}`}>
          <span className="step-num">1</span>
          <form className="form-stack" onSubmit={event => void submitStatus(event)} aria-label="Status tinjauan">
            <h4>Tindakan</h4>
            <p>{suggested ? `Untuk ${LANES[laneKey!].name.toLowerCase()}, tindak lanjut yang disarankan: ${runReviewStatusLabels[suggested]}.` : "Tandai sejauh mana Anda sudah memeriksa klaim ini."}</p>
            <fieldset className="option-grid" disabled={!canUpdateStatus || busy}>
              <legend className="sr-only">Status tinjauan</legend>
              {statusValues.map(value => <label className="option" key={value} title={STATUS_HELP[value]}>
                <input type="radio" name="review-status" value={value} checked={status === value} onChange={() => setStatus(value)} />
                {runReviewStatusLabels[value]}
              </label>)}
            </fieldset>
            <label htmlFor="review-note">Catatan (opsional)</label><textarea id="review-note" value={note} onChange={event => setNote(event.target.value)} maxLength={1000} disabled={!canUpdateStatus || busy} placeholder={NOTE_PLACEHOLDER} />
            <div className="form-actions">
              <span className={`character-count${note.length > 1000 ? " character-count-error" : ""}`}>{note.length}/1000</span>
              <button className="button button-primary" type="submit" disabled={!canUpdateStatus || busy || note.length > 1000}><Save size={14} />{busy ? "Menyimpan…" : "Simpan status"}</button>
            </div>
            {!canUpdateStatus && <small className="fine-print"><Lock size={12} /> Peran Anda dapat melihat tinjauan ini, tetapi tidak dapat mengubah statusnya.</small>}
          </form>
        </div>

        {!canUpdateOutcome && <>
          <div className="decision-step locked">
            <span className="step-num">2</span>
            <div><h4>Umpan balik: benar atau ternyata wajar? <span className="status-pill tone-neutral">{review.review_outcome ? reviewOutcomeLabels[review.review_outcome] : "Belum diputuskan"}</span></h4>
              <small className="fine-print"><Lock size={12} /> Hanya verifikator dan administrator yang dapat menyimpan keputusan.</small></div>
          </div>
          <div className="decision-step locked">
            <span className="step-num">3</span>
            <div><h4>Hasil audit resmi <span className="status-pill tone-neutral" data-testid="audit-result-status">{review.audit_result ? auditResultLabels[review.audit_result] : "Belum ada hasil audit resmi"}</span></h4>
              {review.audit_result && review.audit_details_visible === false
                ? <p className="fine-print" data-testid="audit-details-restricted">Nomor referensi, catatan, dan pencatat audit hanya dapat dilihat oleh verifikator dan administrator.</p>
                : <small className="fine-print"><Lock size={12} /> Dicatat setelah audit resmi selesai.</small>}</div>
          </div>
        </>}
        {canUpdateOutcome && <>
        <div className={`decision-step${canUpdateOutcome ? "" : " locked"}`}>
          <span className="step-num">2</span>
          <form className="form-stack" onSubmit={event => void submitOutcome(event)} aria-label="Keputusan tinjauan">
            <h4>Umpan balik: benar atau ternyata wajar? <span className="status-pill tone-neutral">{review.review_outcome ? reviewOutcomeLabels[review.review_outcome] : "Belum diputuskan"}</span></h4>
            <p>Setelah memeriksa berkas, apakah klaim ini memang bermasalah? Jawaban Anda menjadi tolok ukur ketepatan sistem dan dasar penyesuaian ambang oleh administrator.</p>
            <fieldset className="option-grid" disabled={!canUpdateOutcome || busy}>
              <legend className="sr-only">Keputusan tinjauan</legend>
              {outcomeValues.map(value => <label className="option" key={value}>
                <input type="radio" name="review-outcome" value={value} checked={outcome === value} onChange={() => setOutcome(value)} />
                {reviewOutcomeLabels[value]}
              </label>)}
            </fieldset>
            <div className="form-actions">
              <span className="fine-print">Tercatat atas nama akun Anda.</span>
              <button className="button button-primary" type="submit" disabled={!canUpdateOutcome || busy}><Save size={14} />{busy ? "Menyimpan…" : "Simpan keputusan"}</button>
            </div>
            {!canUpdateOutcome
              ? <small className="fine-print"><Lock size={12} /> Hanya verifikator dan administrator yang dapat menyimpan keputusan.</small>
              : null}
          </form>
        </div>

        <div className={`decision-step${canUpdateOutcome ? "" : " locked"}`}>
          <span className="step-num">3</span>
          <div className="form-stack" aria-label="Hasil audit resmi">
            <h4>Hasil audit resmi <span className="status-pill tone-neutral" data-testid="audit-result-status">{review.audit_result ? auditResultLabels[review.audit_result] : "Belum ada hasil audit resmi"}</span></h4>
            {canUpdateOutcome ? <details className="audit-form" open={Boolean(review.audit_result) || undefined}>
              <summary>Catat hasil audit resmi <small>diisi setelah audit resmi selesai</small></summary>
              <form className="form-stack" onSubmit={event => void submitAudit(event)}>
              <fieldset className="option-grid" disabled={busy}>
                <legend className="sr-only">Hasil audit</legend>
                {(Object.keys(auditResultLabels) as AuditResult[]).map(value => <label className="option" key={value}>
                  <input type="radio" name="audit-result" value={value} checked={auditResult === value} onChange={() => setAuditResult(value)} />
                  {auditResultLabels[value]}
                </label>)}
              </fieldset>
              <label htmlFor="audit-reference">Nomor referensi audit</label><input id="audit-reference" value={auditReference} onChange={event => setAuditReference(event.target.value)} placeholder="mis. AUD-2026/014" maxLength={64} required disabled={busy} />
              <label htmlFor="audit-note">Catatan audit (opsional)</label><textarea id="audit-note" value={auditNote} onChange={event => setAuditNote(event.target.value)} maxLength={1000} disabled={busy} placeholder={NOTE_PLACEHOLDER} />
              <div className="form-actions">
                <span className="fine-print">Simpan status di langkah 1 terlebih dahulu.</span>
                <button className="button button-primary" type="submit" disabled={busy || !auditReference.trim()}><ShieldCheck size={14} />{busy ? "Menyimpan…" : "Simpan hasil audit"}</button>
              </div>
              </form>
            </details> : <small className="fine-print"><Lock size={12} /> Hanya verifikator dan administrator yang dapat mencatat hasil audit resmi.</small>}
            {review.audit_result && review.audit_details_visible === false && <p className="fine-print" data-testid="audit-details-restricted">Nomor referensi, catatan, dan pencatat audit hanya dapat dilihat oleh verifikator dan administrator.</p>}
            {(review.audit_confirmations ?? []).length > 0 && <ol className="timeline">{(review.audit_confirmations ?? []).map(item => <li key={item.confirmation_id}>
              <strong>{auditResultLabels[item.audit_result]} · ref. {item.audit_reference}</strong>
              <span>oleh {actorName(item.recorded_by_user_id)} · {formatDateTime(item.recorded_at)}</span>
              {item.note && <p className="history-note">{item.note}</p>}
            </li>)}</ol>}
          </div>
        </div>
        </>}
      </div>
    </section>

    <details className="card review-history-panel" aria-label="Riwayat tinjauan">
      <summary className="history-summary"><span><History size={16} style={{ verticalAlign: "-2px" }} /> Riwayat tinjauan</span>
        <span className="history-count">{review.history.length} perubahan</span></summary>
      <p className="fine-print">Setiap perubahan tercatat dan tidak dapat dihapus.</p>
      {review.history.length === 0
        ? <p className="fine-print">Belum ada perubahan.</p>
        : <ol className="timeline">{review.history.map(event => <li key={event.event_id}>
          <strong>{historyLabel(event.event_type)}{event.new_status ? `: ${runReviewStatusLabels[event.new_status]}` : ""}{event.new_outcome ? `: ${reviewOutcomeLabels[event.new_outcome]}` : ""}</strong>
          <span>oleh {actorName(event.actor_user_id)} · <time dateTime={event.occurred_at}>{formatDateTime(event.occurred_at)}</time>{event.previous_status ? ` · sebelumnya ${runReviewStatusLabels[event.previous_status]}` : ""}{event.previous_outcome ? ` · sebelumnya ${reviewOutcomeLabels[event.previous_outcome]}` : ""}</span>
          {event.note && <p className="history-note">{event.note}</p>}
        </li>)}</ol>}
    </details>

    {canUpdateStatus && <div className="quick-actions" role="group" aria-label="Tindakan cepat" data-testid="quick-actions">
      <span className="quick-actions-label">Tindakan cepat{review.review_status !== "pending_review" ? ` · sekarang: ${runReviewStatusLabels[review.review_status]}` : ""}</span>
      <div className="quick-actions-buttons">
        {!holder && <button type="button" className="button button-secondary row-button" disabled={busy} onClick={() => void assign("take")}>Ambil klaim</button>}
        {QUICK_STATUSES.map(([value, label]) => <button key={value} type="button" disabled={busy}
          className={`button row-button ${review.review_status === value ? "button-primary" : "button-secondary"}`}
          aria-pressed={review.review_status === value} onClick={() => void quickStatus(value)}>{label}</button>)}
      </div>
    </div>}

    <div className="notice-panel workflow-notice"><ShieldCheck size={18} /><p>Catatan tinjauan bukan putusan kecurangan. Jangan menulis data peserta atau informasi sensitif lain.</p></div>
    <TechnicalDetails items={[
      { label: "ID klaim", value: caseId, copy: true },
      { label: "ID analisis", value: run.run.run_id, copy: true },
      { label: "ID data", value: `${run.run.batch_id} (versi ${run.run.batch_version})` },
      { label: "Versi aturan saran", value: lane?.policy_version ?? run.run.action_policy_version },
      { label: "Skor temuan", value: ruleIndexText(candidate) },
      { label: "Status skor", value: statusText(candidate.score_status) },
      { label: "Pembaruan tinjauan terakhir", value: review.updated_at ? formatDateTime(review.updated_at) : "belum pernah" },
    ]} />
  </div>;
}

const QUICK_STATUSES: Array<[RunReviewStatus, string]> = [
  ["in_review", "Sedang ditinjau"], ["awaiting_evidence", "Minta klarifikasi"], ["escalated", "Masuk antrean audit"], ["closed", "Selesai"],
];

function historyLabel(type: string): string {
  if (type === "status_changed") return "Status diubah";
  if (type === "outcome_recorded") return "Keputusan dicatat";
  if (type === "outcome_changed") return "Keputusan diubah";
  return "Perubahan";
}
function StatusBadge({ status }: { status: string }) { return <span className={`status-pill status-${status}`}>{runReviewStatusLabels[status as RunReviewStatus] ?? statusText(status)}</span>; }

type Evidence = { note: boolean; visits: number };
// Findings whose evidence is the participant's other visits.
const VISIT_FINDINGS = new Set(["repeat_billing_candidate", "rapid_readmission_candidate"]);
// Findings whose evidence is in the clinical note.
const NOTE_FINDINGS = new Set(["cloned_clinical_note_candidate", "length_of_stay_extreme_candidate", "unusual_severity_candidate",
  "severity_without_secondary_candidate", "rapid_readmission_candidate"]);

/** A jump from a finding to the evidence card that supports it (only when that evidence exists). */
function EvidenceLink({ indicator, evidence }: { indicator: string; evidence: Evidence }) {
  const links: Array<[string, string]> = [];
  if (VISIT_FINDINGS.has(indicator) && evidence.visits > 1) links.push(["bukti-kunjungan", "kunjungan peserta"]);
  if (NOTE_FINDINGS.has(indicator) && evidence.note) links.push(["bukti-catatan", "catatan klinis"]);
  if (!links.length) return null;
  const jump = (target: string) => {
    const element = document.getElementById(target);
    element?.querySelector("details:not([open])")?.setAttribute("open", "");
    element?.scrollIntoView({ behavior: "smooth", block: "start" });
  };
  return <div className="evidence-links">{links.map(([target, label]) => <button key={target} type="button" className="evidence-link" onClick={() => jump(target)}>
    <ArrowDown size={13} aria-hidden="true" />Lihat bukti: {label}</button>)}</div>;
}
