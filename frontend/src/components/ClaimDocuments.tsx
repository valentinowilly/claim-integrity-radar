import { useEffect, useState, type FormEvent } from "react";
import { ExternalLink, FileSearch, FileText, Loader2, MessageSquareText, ScanText, TriangleAlert } from "lucide-react";
import {
  ApiClientError, askClaimDocuments, documentFileUrl, getClaimDocuments, type ClaimDocument, type ClaimDocumentsResponse, type DocumentAnswer,
} from "../api/client";
import { formatCount } from "./Display";
import { AiWait } from "./ClinicalNoteCard";

const EXAMPLES = ["Berapa hari pasien dirawat menurut berkas?", "Apakah ada komplikasi atau penyakit penyerta?", "Apakah obat atau alat benar-benar diserahkan?"];
const READERS: Record<string, string> = {
  formulir: "isian formulir", ai: "AI pembaca dokumen", "formulir+ai": "isian formulir + AI pembaca dokumen", "aturan teks": "aturan teks",
};
// Long text is shown once, in the note card; here it would only repeat.
const HIDDEN_FIELDS = new Set(["catatan_klinis"]);

export function formatDocumentValue(field: string, value: string): string {
  if (field === "total_tagihan" && /^\d+$/.test(value)) return `Rp${Number(value).toLocaleString("id-ID")}`;
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return new Date(`${value}T00:00:00`).toLocaleDateString("id-ID", { day: "numeric", month: "short", year: "numeric" });
  return value.replace(/;/g, ", ");
}

/** The claim's facility documents: what was read from each, on which page, and where it disagrees with the claim data. */
export function ClaimDocuments({ runId, caseId, canAsk, onLoaded }: {
  runId: string; caseId: string; canAsk: boolean; onLoaded?: (count: number) => void;
}) {
  const [data, setData] = useState<ClaimDocumentsResponse | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    setData(null);
    getClaimDocuments(runId, caseId, controller.signal).then(response => {
      setData(response);
      setOpen(response.items.find(item => item.mismatches.length)?.document_id ?? response.items[0]?.document_id ?? null);
      onLoaded?.(response.items.length);
    }).catch(() => onLoaded?.(0));
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, caseId]);
  if (!data || !data.items.length) return null;
  const scanned = data.items.filter(item => item.scanned_pages > 0).length;
  return <section className="card run-case-reasons claim-documents" aria-label="Berkas klaim" data-testid="claim-documents">
    <div className="card-head">
      <div><h2><FileSearch size={17} className="head-icon" aria-hidden="true" />Berkas klaim dari faskes</h2>
        <p>{formatCount(data.items.length)} berkas PDF dibaca{scanned ? `, ${formatCount(scanned)} di antaranya hasil pindai (OCR)` : ""}. Setiap nilai menunjuk halaman sumbernya.</p></div>
      {data.mismatch_count > 0 && <span className="status-pill tone-danger" data-testid="documents-mismatch-count">
        <TriangleAlert size={13} aria-hidden="true" />{formatCount(data.mismatch_count)} tidak cocok dengan data klaim</span>}
    </div>
    <ul className="doc-list">{data.items.map(item => <DocumentRow key={item.document_id} item={item}
      open={open === item.document_id} onToggle={() => setOpen(current => current === item.document_id ? null : item.document_id)} />)}</ul>
    <AskDocuments runId={runId} caseId={caseId} canAsk={canAsk} engine={data.question_engine} />
  </section>;
}

function DocumentRow({ item, open, onToggle }: { item: ClaimDocument; open: boolean; onToggle: () => void }) {
  const facts = item.facts.filter(fact => !HIDDEN_FIELDS.has(fact.field));
  const Icon = item.scanned_pages ? ScanText : FileText;
  return <li className={`doc-item${item.mismatches.length ? " has-mismatch" : ""}`} data-testid="document-row">
    <div className="doc-head">
      <button type="button" className="doc-toggle" aria-expanded={open} onClick={onToggle}>
        <Icon size={16} aria-hidden="true" />
        <span className="doc-title"><strong>{item.doc_type_label}</strong><small>{item.file_name}</small></span>
      </button>
      <span className="doc-tags">
        <span className="status-pill tone-neutral">{item.scanned_pages
          ? `Hasil pindai · OCR${item.ocr_confidence !== null ? ` ${(item.ocr_confidence * 100).toLocaleString("id-ID", { maximumFractionDigits: 0 })}%` : ""}` : "PDF digital"}</span>
        {item.mismatches.length > 0 && <span className="status-pill tone-danger">Tidak cocok</span>}
      </span>
      <a className="button button-secondary button-compact" href={documentFileUrl(item.document_id)} target="_blank" rel="noreferrer">
        Buka PDF <ExternalLink size={12} aria-hidden="true" /></a>
    </div>
    {open && <div className="doc-body">
      {item.mismatches.map((mismatch, index) => <div className="doc-mismatch" key={index} role="alert" data-testid="document-mismatch">
        <TriangleAlert size={15} aria-hidden="true" />
        <span><strong>{mismatch.label} berbeda.</strong> Data klaim: {formatDocumentValue(mismatch.field, mismatch.data_value)}; di berkas ini (hal. {mismatch.page}):{" "}
          <strong>{formatDocumentValue(mismatch.field, mismatch.document_value)}</strong>. Analisis memakai data klaim; cek ke berkas asli.</span>
      </div>)}
      {item.warnings.map((warning, index) => <p className="fine-print doc-warning" key={index}><TriangleAlert size={13} aria-hidden="true" /> {warning}</p>)}
      {facts.length > 0 ? <div className="table-scroll"><table className="data-table doc-facts">
        <thead><tr><th>Yang dibaca</th><th>Nilai</th><th>Halaman</th><th>Kutipan di berkas</th></tr></thead>
        <tbody>{facts.map(fact => <tr key={fact.field} className={fact.verified ? undefined : "unverified"}>
          <td>{fact.label}</td>
          <td><strong>{formatDocumentValue(fact.field, fact.value)}</strong>{fact.note && <small className="doc-fact-note">{fact.note}</small>}</td>
          <td><a href={documentFileUrl(item.document_id, fact.page)} target="_blank" rel="noreferrer">hal. {fact.page}</a></td>
          <td className="doc-quote">“{fact.quote}”</td>
        </tr>)}</tbody>
      </table></div> : <p className="fine-print">Tidak ada isian yang dikenali pada berkas ini.</p>}
      <p className="ai-meta">Dibaca dengan {READERS[item.reader] ?? item.reader}{item.model ? ` (${item.model})` : ""}.
        {item.evidence_code ? " Berkas ini dihitung sebagai bukti pendukung layanan." : ""}</p>
    </div>}
  </li>;
}

function AskDocuments({ runId, caseId, canAsk, engine }: {
  runId: string; caseId: string; canAsk: boolean; engine: "llm" | "text_search";
}) {
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [answer, setAnswer] = useState<DocumentAnswer | null>(null);
  const [error, setError] = useState<string | null>(null);
  if (!canAsk) return null;
  const ask = async (text: string) => {
    const value = text.trim();
    if (value.length < 3 || busy) return;
    setBusy(true);
    setError(null);
    try {
      setAnswer(await askClaimDocuments(runId, caseId, value));
    } catch (problem) {
      setError(problem instanceof ApiClientError ? problem.message : "Pertanyaan tidak dapat dijawab.");
    } finally {
      setBusy(false);
    }
  };
  const submit = (event: FormEvent) => { event.preventDefault(); void ask(question); };
  return <div className="doc-ask" data-testid="document-ask">
    <h3><MessageSquareText size={15} aria-hidden="true" />Tanya berkas</h3>
    <p className="fine-print">{engine === "llm" ? "Dijawab AI pembaca dokumen hanya dari isi berkas klaim ini; setiap jawaban menyertakan kutipan dan halamannya."
      : "Pertanyaan dijawab dengan mencari kata-katanya di berkas klaim ini, lengkap dengan halamannya."}</p>
    <form onSubmit={submit} className="doc-ask-form">
      <input value={question} onChange={event => setQuestion(event.target.value)} maxLength={400} aria-label="Pertanyaan tentang berkas"
        placeholder="mis. Berapa hari pasien dirawat menurut berkas?" disabled={busy} />
      <button className="button button-primary" type="submit" disabled={busy || question.trim().length < 3}>
        {busy ? <Loader2 size={14} className="spin" aria-hidden="true" /> : <MessageSquareText size={14} aria-hidden="true" />}{busy ? "Membaca…" : "Tanya"}</button>
    </form>
    <div className="doc-ask-examples">{EXAMPLES.map(example => <button key={example} type="button" className="chip-button" disabled={busy}
      onClick={() => { setQuestion(example); void ask(example); }}>{example}</button>)}</div>
    {busy && engine === "llm" && <AiWait what="pertanyaan dan berkas" against="halaman berkas" />}
    {error && <p className="fine-print doc-warning" role="alert">{error}</p>}
    {answer && <div className="doc-answer" role="status" data-testid="document-answer">
      <p>{answer.answer}</p>
      {answer.note && <p className="fine-print doc-warning"><TriangleAlert size={13} aria-hidden="true" /> {answer.note}</p>}
      {answer.citations.length > 0 && <ul>{answer.citations.map((citation, index) => <li key={index}>
        <a href={documentFileUrl(citation.document_id, citation.page)} target="_blank" rel="noreferrer">{citation.doc_type_label}, hal. {citation.page}</a>
        <span className="doc-quote">“{citation.quote}”</span>
      </li>)}</ul>}
      <p className="ai-meta">{answer.engine === "llm" ? "Jawaban AI pembaca dokumen; kutipan sudah dicocokkan dengan halaman berkas" : "Hasil pencarian kata di berkas"}
        {answer.unverified_citations ? `; ${formatCount(answer.unverified_citations)} kutipan dibuang karena tidak ditemukan di berkas` : ""}. Keputusan tetap pada verifikator.</p>
    </div>}
  </div>;
}
