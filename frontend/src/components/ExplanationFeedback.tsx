import { useEffect, useState } from "react";
import { MessageSquareHeart, ThumbsDown, ThumbsUp } from "lucide-react";
import { ApiClientError, getFeedbackSummary, getMyFeedback, rateExplanation, type FeedbackReason, type FeedbackSummary, type MyFeedback } from "../api/client";
import { formatCount, indicatorLabel } from "./Display";

const REASONS: Array<[FeedbackReason, string]> = [
  ["unclear", "Kurang jelas"], ["not_matching", "Tidak sesuai berkas"], ["too_long", "Terlalu panjang"], ["other", "Lainnya"],
];

/** This person's answers on one claim, loaded once and shared by its reason cards. */
export function useMyFeedback(runId: string, caseId: string) {
  const [items, setItems] = useState<Record<string, MyFeedback>>({});
  useEffect(() => {
    const controller = new AbortController();
    getMyFeedback(runId, caseId, controller.signal).then(response => setItems(response.items)).catch(() => undefined);
    return () => controller.abort();
  }, [runId, caseId]);
  return [items, setItems] as const;
}

/** "Was this explanation helpful?" under one reason card; a "no" asks why, in one tap. */
export function ExplanationFeedback({ runId, caseId, indicator, current, onSaved, canRate }: {
  runId: string; caseId: string; indicator: string; current?: MyFeedback; onSaved: (value: MyFeedback) => void; canRate: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (!canRate) return null;
  const save = async (helpful: boolean, reason: FeedbackReason | null = null) => {
    setBusy(true); setError(null);
    try { await rateExplanation(runId, caseId, indicator, helpful, reason); onSaved({ helpful, reason }); }
    catch (problem) { setError(problem instanceof ApiClientError ? problem.message : "Penilaian tidak tersimpan."); }
    finally { setBusy(false); }
  };
  return <div className="explain-rate" data-testid="explanation-feedback">
    <span className="explain-rate-question">Penjelasan ini membantu?</span>
    <button type="button" className={`explain-rate-button${current?.helpful === true ? " is-yes" : ""}`} aria-pressed={current?.helpful === true}
      disabled={busy} onClick={() => void save(true)}><ThumbsUp size={14} aria-hidden="true" />Membantu</button>
    <button type="button" className={`explain-rate-button${current?.helpful === false ? " is-no" : ""}`} aria-pressed={current?.helpful === false}
      disabled={busy} onClick={() => void save(false, current?.reason ?? null)}><ThumbsDown size={14} aria-hidden="true" />Tidak</button>
    {current?.helpful === false && <span className="explain-rate-reasons" role="group" aria-label="Kenapa tidak membantu">
      {REASONS.map(([value, label]) => <button key={value} type="button" className={`chip-button${current.reason === value ? " is-active" : ""}`}
        aria-pressed={current.reason === value} disabled={busy} onClick={() => void save(false, value)}>{label}</button>)}
    </span>}
    {current?.helpful === true && <span className="explain-rate-thanks">Terima kasih, tercatat.</span>}
    {error && <span className="explain-rate-error" role="alert">{error}</span>}
  </div>;
}

const REASON_LABEL: Record<FeedbackReason, string> = Object.fromEntries(REASONS) as Record<FeedbackReason, string>;

/** How often the reasons helped the verifiers, per check, with why they did not (proposal indicator 20). */
export function FeedbackSummaryCard() {
  const [data, setData] = useState<FeedbackSummary | null | "error">(null);
  useEffect(() => {
    const controller = new AbortController();
    getFeedbackSummary(controller.signal).then(setData).catch(() => { if (!controller.signal.aborted) setData("error"); });
    return () => controller.abort();
  }, []);
  return <section className="card trend-card feedback-summary" aria-labelledby="feedback-title" data-testid="feedback-summary">
    <div className="card-head"><div><h2 id="feedback-title"><MessageSquareHeart size={16} className="head-icon" aria-hidden="true" />Kepuasan petugas terhadap penjelasan</h2>
      <p>Dari tombol "Penjelasan ini membantu?" di setiap alasan klaim.</p></div></div>
    {data === "error" ? <p className="fine-print">Rekap tidak dapat dimuat.</p>
      : data === null ? <p className="fine-print">Memuat…</p>
      : data.total === 0 ? <div className="review-empty"><strong>Belum ada penilaian.</strong>
        <span className="fine-print">Rekap terisi setelah petugas menilai alasan pada klaim yang ditinjau.</span></div>
      : <div className="feedback-body">
        <div className="feedback-score">
          <b>{Math.round(100 * (data.share_helpful ?? 0))}%</b><span>penjelasan dinilai membantu</span>
          <small>{formatCount(data.helpful)} dari {formatCount(data.total)} penilaian</small>
        </div>
        <ul className="feedback-rows">{data.items.map(item => {
          const total = item.helpful + item.not_helpful;
          const top = Object.entries(item.reasons).sort((a, b) => (b[1] ?? 0) - (a[1] ?? 0))[0];
          return <li key={item.indicator}>
            <span className="feedback-name">{indicatorLabel(item.indicator)}</span>
            <span className="feedback-bar" aria-label={`${item.helpful} membantu, ${item.not_helpful} tidak`}>
              <i className="is-yes" style={{ width: `${100 * item.helpful / total}%` }} /><i className="is-no" style={{ width: `${100 * item.not_helpful / total}%` }} /></span>
            <span className="feedback-count">{formatCount(item.helpful)}/{formatCount(total)}</span>
            {top && <span className="feedback-reason">{REASON_LABEL[top[0] as FeedbackReason]}</span>}
          </li>;
        })}</ul>
      </div>}
  </section>;
}
