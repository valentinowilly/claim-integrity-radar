import { useEffect, useState, type FormEvent } from "react";
import { MessageSquareHeart, ThumbsDown, ThumbsUp } from "lucide-react";
import { ApiClientError, getClaimFeedback, sendClaimFeedback, type OwnFeedback } from "../api/client";

const MAX = 500;

/** "Was this explanation helpful?" under a claim's reasons: one vote per person per claim, changeable. */
export function FeedbackPrompt({ runId, caseId }: { runId: string; caseId: string }) {
  const [mine, setMine] = useState<OwnFeedback | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [sentMessage, setSentMessage] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    setLoaded(false); setMine(null); setMessage(""); setError(""); setSentMessage(false);
    getClaimFeedback(runId, caseId, controller.signal)
      .then(response => { setMine(response.mine); setMessage(response.mine?.message ?? ""); setLoaded(true); })
      .catch(() => { if (!controller.signal.aborted) setLoaded(true); });
    return () => controller.abort();
  }, [runId, caseId]);

  async function save(helpful: boolean, text: string | null) {
    setBusy(true); setError("");
    try {
      const response = await sendClaimFeedback(runId, caseId, { helpful, message: text });
      setMine(response.mine);
      return true;
    } catch (reason) {
      setError(reason instanceof ApiClientError ? reason.message : "Masukan belum terkirim. Coba lagi.");
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function vote(helpful: boolean) {
    setSentMessage(false);
    await save(helpful, mine?.message ?? null);
  }

  async function submitMessage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (mine?.helpful === null || mine?.helpful === undefined) return;
    if (await save(mine.helpful, message.trim() || null)) setSentMessage(true);
  }

  if (!loaded) return null;
  const voted = mine?.helpful !== null && mine?.helpful !== undefined;
  return <section className="card feedback-prompt" aria-label="Masukan atas penjelasan" data-testid="claim-feedback">
    <div className="feedback-row">
      <span className="feedback-icon" aria-hidden="true"><MessageSquareHeart size={18} /></span>
      <div className="feedback-copy">
        <strong>Apakah penjelasan klaim ini membantu Anda?</strong>
        <span>{voted ? "Terima kasih. Penilaian Anda dipakai untuk memperbaiki penjelasan sistem; Anda dapat mengubahnya kapan saja."
          : "Penilaian Anda membantu tim pengelola mengetahui penjelasan mana yang perlu diperjelas."}</span>
      </div>
      <div className="feedback-actions" role="group" aria-label="Penilaian penjelasan">
        <button type="button" className={`feedback-vote${mine?.helpful === true ? " chosen" : ""}`} aria-pressed={mine?.helpful === true}
          disabled={busy} onClick={() => void vote(true)}><ThumbsUp size={15} aria-hidden="true" />Membantu</button>
        <button type="button" className={`feedback-vote${mine?.helpful === false ? " chosen" : ""}`} aria-pressed={mine?.helpful === false}
          disabled={busy} onClick={() => void vote(false)}><ThumbsDown size={15} aria-hidden="true" />Kurang membantu</button>
      </div>
    </div>
    {voted && <form className="feedback-form" onSubmit={submitMessage}>
      <label htmlFor="feedback-message">{mine?.helpful ? "Bagian mana yang paling membantu? (opsional)" : "Apa yang perlu diperjelas? (opsional)"}</label>
      <textarea id="feedback-message" value={message} maxLength={MAX} disabled={busy} rows={2}
        placeholder="Tulis singkat. Jangan menulis data peserta atau informasi sensitif lain."
        onChange={event => { setMessage(event.target.value); setSentMessage(false); }} />
      <div className="form-actions">
        <span className="character-count">{message.length}/{MAX}</span>
        {sentMessage && <span className="feedback-sent" role="status">Masukan tersimpan.</span>}
        <button className="button button-secondary row-button" type="submit" disabled={busy || message.trim() === (mine?.message ?? "")}>
          {busy ? "Mengirim…" : "Kirim masukan"}
        </button>
      </div>
    </form>}
    {error && <p className="feedback-error" role="alert">{error}</p>}
  </section>;
}
