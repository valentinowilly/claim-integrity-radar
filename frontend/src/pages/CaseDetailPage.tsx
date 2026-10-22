import { useCallback, useEffect, useState, type FormEvent } from "react";
import { ArrowLeft, CircleAlert, FileSearch, History, Save, ShieldCheck } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import {
  getCaseDetail,
  getCaseReview,
  reviewStatusLabels,
  updateCaseReview,
  type CaseReviewResponse,
  type ReviewStatus,
} from "../api/client";
import { EmptyState, ErrorState, indicatorLabel, LoadingState, PageHeading, SourceBadge } from "../components/DataStates";
import { useApiResource } from "../hooks/useApiResource";

const statusOptions = Object.keys(reviewStatusLabels) as ReviewStatus[];

export default function CaseDetailPage() {
  const { caseId = "" } = useParams();
  const loadDetail = useCallback((signal: AbortSignal) => getCaseDetail(caseId, signal), [caseId]);
  const loadReview = useCallback((signal: AbortSignal) => getCaseReview(caseId, signal), [caseId]);
  const detailResource = useApiResource(loadDetail);
  const reviewResource = useApiResource(loadReview);
  const [reviewOverride, setReviewOverride] = useState<CaseReviewResponse | null>(null);
  const [draftStatus, setDraftStatus] = useState<ReviewStatus>("pending_review");
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [feedback, setFeedback] = useState<{ kind: "success" | "warning" | "error"; message: string } | null>(null);

  const review = reviewOverride ?? (reviewResource.state.status === "success" ? reviewResource.state.data : null);

  useEffect(() => {
    setReviewOverride(null);
    setDraftStatus("pending_review");
    setNote("");
    setFeedback(null);
  }, [caseId]);

  useEffect(() => {
    if (review) {
      setDraftStatus(review.status);
      setNote(review.note ?? "");
    }
  }, [caseId, review?.status, review?.updated_at]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (saving || note.length > 1000) return;
    setSaving(true);
    setFeedback(null);
    try {
      const saved = await updateCaseReview(caseId, { status: draftStatus, note: note.trim() || null });
      setReviewOverride(saved);
      try {
        const refreshed = await getCaseReview(caseId);
        setReviewOverride(refreshed);
        setFeedback({ kind: "success", message: "Status dan riwayat berhasil dimuat ulang dari backend." });
      } catch {
        setFeedback({ kind: "warning", message: "Perubahan tersimpan menurut respons server, tetapi pembacaan ulang gagal. Coba muat ulang untuk memastikan status terkini." });
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : "Perubahan tinjauan gagal disimpan.";
      setFeedback({ kind: "error", message });
    } finally {
      setSaving(false);
    }
  }

  const detailNotFound = detailResource.state.status === "error" && detailResource.state.httpStatus === 404;
  const reviewNotFound = reviewResource.state.status === "error" && reviewResource.state.httpStatus === 404;

  return (
    <>
      <PageHeading eyebrow="TINJAUAN KASUS" title="Detail kandidat" description="Alasan deteksi yang dapat diperiksa, status tindak lanjut, dan riwayat tinjauan." action={<Link className="button button-secondary" to="/cases"><ArrowLeft size={15} />Kembali ke antrean</Link>} />

      {(detailNotFound || reviewNotFound) ? (
        <section className="surface-panel not-found-case"><div className="empty-state-icon"><FileSearch size={21} /></div><span className="eyebrow muted-eyebrow">404 · KASUS TIDAK DITEMUKAN</span><h2>Kasus ini tidak tersedia</h2><p>ID mungkin tidak dikenal atau sudah tidak ada dalam sumber kandidat aktif.</p><Link className="button button-primary" to="/cases"><ArrowLeft size={15} />Kembali ke antrean</Link></section>
      ) : (
        <>
          {detailResource.state.status === "loading" && <LoadingState label="Mengambil detail kasus…" />}
          {detailResource.state.status === "error" && <ErrorState message={detailResource.state.message} httpStatus={detailResource.state.httpStatus} onRetry={detailResource.reload} />}
          {detailResource.state.status === "success" && detailResource.state.data.availability !== "available" && <EmptyState title="Detail belum tersedia" message="API belum menyediakan detail untuk sumber aktif." />}

          {detailResource.state.status === "success" && detailResource.state.data.availability === "available" && (
            <>
              <section className="detail-hero surface-panel">
                <div className="detail-identity"><span className="detail-icon"><FileSearch size={19} /></span><div><span className="eyebrow muted-eyebrow">ID KASUS APLIKASI</span><h2>{detailResource.state.data.case.case_id}</h2></div></div>
                <div className="detail-meta">
                  {review ? <span className={`status-pill status-review-${review.status}`}>{review.status_label}</span> : <span className="status-pill status-neutral">Status belum dimuat</span>}
                  <SourceBadge source={detailResource.state.data.data_source} />
                </div>
              </section>

              <section className="detail-context notice-panel"><ShieldCheck size={18} /><p>{detailResource.state.data.notice} Keputusan akhir tetap memerlukan tinjauan auditor dan konteks layanan.</p></section>

              <section className="section-block detail-section">
                <div className="panel-heading-row"><div><span className="eyebrow muted-eyebrow">INDIKATOR PEMICU</span><h2>{detailResource.state.data.case.indicators.length} indikator</h2></div></div>
                {detailResource.state.data.case.reasons.length === 0 ? <EmptyState title="Alasan tidak tersedia" message="API tidak mengembalikan alasan untuk kandidat ini." /> : (
                  <div className="detail-reason-list">
                    {detailResource.state.data.case.reasons.map((reason, index) => (
                      <article className="surface-panel detail-reason-card" key={`${reason.indicator}-${index}`}>
                        <div className="reason-title-row"><span className="indicator-pill indicator-active">{indicatorLabel(reason.indicator)}</span><span className="candidate-label">Kandidat tinjauan</span></div>
                        <p className="detail-reason-summary">{reason.summary}</p>
                        <div className="reason-evidence"><strong>Atribut dan konteks yang cocok</strong><ul>{reason.evidence.map((item, itemIndex) => <li key={`${itemIndex}-${item}`}>{item}</li>)}</ul></div>
                        <div className="limitation-block"><strong>Batas interpretasi</strong><ul>{reason.limitations.map(text => <li key={text}>{text}</li>)}</ul></div>
                      </article>
                    ))}
                  </div>
                )}
              </section>

              <section className="section-block detail-section review-section">
                <div className="panel-heading-row"><div><span className="eyebrow muted-eyebrow">HUMAN-IN-THE-LOOP</span><h2>Tindak lanjut auditor</h2></div></div>
                {reviewResource.state.status === "loading" && !review && <LoadingState label="Mengambil status dan riwayat tinjauan…" />}
                {reviewResource.state.status === "error" && !review && <ErrorState message={reviewResource.state.message} httpStatus={reviewResource.state.httpStatus} onRetry={reviewResource.reload} />}
                {review && (
                  <>
                    <div className="review-safety-note" role="note">
                      <CircleAlert size={17} />
                      <p><strong>Data demo sintetis.</strong> Status adalah metadata workflow, bukan keputusan fraud yang terbukti. Catatan disimpan pada database lokal. Aplikasi belum memiliki autentikasi atau kontrol akses; jangan masukkan data peserta, klaim nyata, identitas, atau informasi sensitif.</p>
                    </div>
                    <form className="surface-panel review-form" onSubmit={handleSubmit}>
                      <div className="review-form-heading"><div><span className="eyebrow muted-eyebrow">STATUS SAAT INI</span><span className={`status-pill status-review-${review.status}`}>{review.status_label}</span></div><span className="reviewer-demo-label">{review.reviewer_label ?? "Belum ada catatan reviewer"}</span></div>
                      <label className="review-field">Status tindak lanjut
                        <select value={draftStatus} onChange={event => setDraftStatus(event.target.value as ReviewStatus)} disabled={saving}>
                          {statusOptions.map(status => <option value={status} key={status}>{reviewStatusLabels[status]}</option>)}
                        </select>
                      </label>
                      <label className="review-field">Catatan tinjauan (opsional)
                        <textarea value={note} onChange={event => setNote(event.target.value)} maxLength={1000} rows={4} disabled={saving} placeholder="Catat tindak lanjut tanpa memasukkan informasi sensitif." />
                      </label>
                      <div className="review-form-footer"><span className={note.length > 1000 ? "character-count character-count-error" : "character-count"}>{note.length}/1000 karakter</span><button className="button button-primary" type="submit" disabled={saving || note.length > 1000}>{saving ? "Menyimpan…" : <><Save size={14} />Simpan tinjauan</>}</button></div>
                      {feedback && <div className={`review-feedback review-feedback-${feedback.kind}`} role={feedback.kind === "error" ? "alert" : "status"}>{feedback.message}</div>}
                    </form>

                    <section className="surface-panel review-history-panel">
                      <div className="panel-heading-row"><div><span className="eyebrow muted-eyebrow">AUDIT TRAIL LOKAL</span><h2><History size={16} /> Riwayat tinjauan</h2></div><span className="history-count">{review.history.length} kejadian</span></div>
                      {review.history.length === 0 ? <EmptyState title="Belum ada riwayat" message="Perubahan status yang disimpan akan muncul di sini." /> : (
                        <ol className="review-history-list">
                          {review.history.map((event, index) => (
                            <li className={`review-history-item${index === review.history.length - 1 ? " review-history-current" : ""}`} key={`${event.changed_at}-${index}`}>
                              <span className="history-marker" aria-hidden="true" />
                              <div className="history-event-content">
                                <div className="history-event-heading"><div><span className="history-event-label">{index === review.history.length - 1 ? "Status terkini" : `Perubahan ${index + 1}`}</span><div className="history-status-transition"><span className="status-pill status-review-muted">{event.previous_status ? reviewStatusLabels[event.previous_status] : "Awal tinjauan"}</span><span aria-hidden="true">→</span><span className={`status-pill status-review-${event.status}`}>{reviewStatusLabels[event.status]}</span></div></div><time dateTime={event.changed_at} title={event.changed_at}>{formatLocalTime(event.changed_at)}</time></div>
                                {event.note && <p className="history-note">{event.note}</p>}
                                <span className="reviewer-demo-label">{event.reviewer_label}</span>
                              </div>
                            </li>
                          ))}
                        </ol>
                      )}
                    </section>
                  </>
                )}
              </section>

              <section className="detail-warning"><CircleAlert size={18} /><div><strong>Kecocokan pola bukan bukti fraud.</strong><p>Kandidat dan alasan berasal dari data sintetis. Penilaian akhir membutuhkan tinjauan auditor; status tindak lanjut tidak mengubah kesimpulan analitik.</p></div></section>
            </>
          )}
        </>
      )}
    </>
  );
}

function formatLocalTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("id-ID", { dateStyle: "medium", timeStyle: "short" }).format(date);
}
