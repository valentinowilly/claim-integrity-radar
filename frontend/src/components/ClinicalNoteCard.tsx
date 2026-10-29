import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { ArrowRight, CheckCircle2, ClipboardCheck, Copy, FileText, Loader2, Sparkles, TriangleAlert } from "lucide-react";
import {
  getClinicalNote, getNoteMatches, requestClinicalAnalysis, type ClinicalAnalysis, type ClinicalNoteResponse, type ClinicalVerdictCode,
  type NoteHighlight, type NoteMatchesResponse,
} from "../api/client";
import { useNotify } from "../notifications/NotificationCenter";
import { LANES, LaneDot, formatCount, formatDate, formatDateTime, shortRef } from "./Display";
import { RunCandidateLink } from "./PersistedRunWorkspace";

const VERDICTS: Record<ClinicalVerdictCode, { label: string; headline: string; tone: string }> = {
  sesuai: { label: "Sesuai tagihan", headline: "Catatan klinis mendukung tagihan", tone: "good" },
  perlu_dicek: { label: "Perlu dicek", headline: "Ada hal di catatan klinis yang perlu dicek", tone: "warn" },
  mencurigakan: { label: "Tidak sesuai tagihan", headline: "Catatan klinis tidak sesuai dengan tagihan", tone: "danger" },
};

// ---- the note, laid out by topic ------------------------------------------------------------
type NoteRow = { label: string; text?: string; chips?: string[] };
const VITALS: Array<[RegExp, (m: RegExpMatchArray) => string]> = [
  [/TD\s*(\d{2,3}\/\d{2,3})\s*mmHg/i, m => `TD ${m[1]} mmHg`],
  [/nadi\s*(\d{2,3})\s*x\/menit/i, m => `Nadi ${m[1]}×/menit`],
  [/suhu\s*(\d{2}(?:[.,]\d)?)\s*°?\s*C\b/i, m => `Suhu ${m[1].replace(".", ",")} °C`],
  [/SpO2\s*(\d{2,3})\s*%/i, m => `SpO₂ ${m[1]}%`],
  [/RR\s*(\d{1,2})\s*x\/menit/i, m => `Napas ${m[1]}×/menit`],
];
const LABS: Array<[RegExp, (m: RegExpMatchArray) => string]> = [
  [/Hb\s*(\d{1,2}(?:[.,]\d)?)\s*g\/dL/i, m => `Hb ${m[1].replace(".", ",")} g/dL`],
  [/leukosit\s*(\d{1,3}(?:[.,]\d)?)\s*ribu\/u?L/i, m => `Leukosit ${m[1].replace(".", ",")} rb/µL`],
  [/trombosit\s*(\d{2,4}(?:[.,]\d)?)\s*ribu\/u?L/i, m => `Trombosit ${m[1].replace(".", ",")} rb/µL`],
  [/GDS\s*(\d{2,3})\s*mg\/dL/i, m => `GDS ${m[1]} mg/dL`],
];
const TOPICS: Array<[RegExp, string]> = [
  [/lanjutan perawatan|rawat inap sebelumnya/i, "Riwayat"],
  [/keluhan/i, "Keluhan"],
  [/diagnosis/i, "Diagnosis kerja"],
  // Care before condition: "pulang dengan kondisi membaik" is about the stay, not the condition.
  [/dirawat|pulang|kontrol|terapi|dirujuk|tindakan|edukasi|obat/i, "Perawatan"],
  [/kondisi|komplikasi|komorbid/i, "Kondisi"],
];

function chipsFrom(sentence: string, patterns: Array<[RegExp, (m: RegExpMatchArray) => string]>): string[] {
  return patterns.map(([pattern, format]) => { const m = sentence.match(pattern); return m ? format(m) : null; })
    .filter((item): item is string => Boolean(item));
}

/** Split a free-text note into labelled rows; anything that does not fit a topic stays readable as "Catatan". */
export function noteRows(note: string): NoteRow[] {
  const sentences = note.replace(/\s+/g, " ").split(/(?<=\.)\s+(?=[A-Z])/).map(item => item.trim()).filter(Boolean);
  const rows: NoteRow[] = [];
  const add = (label: string, row: Omit<NoteRow, "label">) => {
    const existing = rows.find(item => item.label === label);
    if (!existing) { rows.push({ label, ...row }); return; }
    if (row.text) existing.text = existing.text ? `${existing.text} ${row.text}` : row.text;
    if (row.chips) existing.chips = [...(existing.chips ?? []), ...row.chips];
  };
  for (const sentence of sentences) {
    const vitals = chipsFrom(sentence, VITALS);
    const labs = chipsFrom(sentence, LABS);
    if (vitals.length >= 2) { add("Tanda vital", { chips: vitals }); continue; }
    if (labs.length) { add("Laboratorium", { chips: labs }); continue; }
    const topic = TOPICS.find(([pattern]) => pattern.test(sentence))?.[1] ?? "Catatan";
    add(topic, { text: topic === "Diagnosis kerja" ? sentence.replace(/^diagnosis kerja\s*/i, "").replace(/\.$/, "") : sentence });
  }
  const order = ["Riwayat", "Keluhan", "Tanda vital", "Diagnosis kerja", "Kondisi", "Laboratorium", "Perawatan", "Catatan"];
  return rows.sort((a, b) => order.indexOf(a.label) - order.indexOf(b.label));
}

// ---- highlights: wording that contradicts the claim ----------------------------------------------
const MARK_KINDS: Record<NoteHighlight["kind"], string> = { stay: "Lama rawat", severity: "Keparahan", continuation: "Lanjutan perawatan" };

/** Marks every occurrence of the highlighted phrases in a (re-spaced) piece of the note. */
function markPhrases(text: string, marks: NoteHighlight[]): ReactNode {
  if (!marks.length) return text;
  const lower = text.toLowerCase();
  const ranges: Array<{ start: number; end: number; mark: NoteHighlight }> = [];
  for (const mark of marks) {
    const needle = mark.text.replace(/\s+/g, " ").toLowerCase();
    for (let at = lower.indexOf(needle); needle && at >= 0; at = lower.indexOf(needle, at + needle.length)) {
      if (!ranges.some(range => at < range.end && range.start < at + needle.length)) ranges.push({ start: at, end: at + needle.length, mark });
    }
  }
  return slices(text, ranges.sort((a, b) => a.start - b.start));
}

function slices(text: string, ranges: Array<{ start: number; end: number; mark: NoteHighlight }>): ReactNode {
  if (!ranges.length) return text;
  const parts: ReactNode[] = [];
  let cursor = 0;
  ranges.forEach((range, index) => {
    if (range.start > cursor) parts.push(text.slice(cursor, range.start));
    parts.push(<mark key={index} className={`note-mark kind-${range.mark.kind}`} title={`${range.mark.reason} ${range.mark.claim_value}.`}>
      {text.slice(range.start, range.end)}</mark>);
    cursor = range.end;
  });
  if (cursor < text.length) parts.push(text.slice(cursor));
  return parts;
}

// ---- what the AI read, against the claim ---------------------------------------------------------
type Fact = { label: string; note: string; claim?: string; mismatch?: boolean };

function severityOf(group: string | null | undefined): string | null {
  const match = /-(0|I|II|III)$/.exec(group ?? "");
  return match ? match[1] : null;
}

function readFacts(facts: NonNullable<ClinicalAnalysis["fakta_catatan"]>, claim: ClinicalNoteResponse["claim"]): Fact[] {
  const severity = severityOf(claim?.claim_group);
  const severityText = { ringan: "Ringan", sedang: "Sedang", berat: "Berat", tidak_disebut: "Tidak disebut" }[facts.keparahan_menurut_catatan];
  const claimSeverity = severity ? { "0": "Rawat jalan", I: "Ringan (I)", II: "Sedang (II)", III: "Berat (III)" }[severity] : undefined;
  const severeBilled = severity === "II" || severity === "III";
  const stay = claim?.stay_days ?? null;
  const stated = facts.lama_rawat_menurut_catatan_hari;
  const list: Fact[] = [
    { label: "Keparahan", note: severityText, claim: claimSeverity,
      mismatch: severeBilled && facts.keparahan_menurut_catatan === "ringan" },
    { label: "Komplikasi / komorbid", note: { ya: "Ada", tidak: "Tidak ada", tidak_disebut: "Tidak disebut" }[facts.komplikasi_atau_komorbid],
      claim: severeBilled ? "Diperlukan untuk keparahan II/III" : undefined,
      mismatch: severeBilled && facts.komplikasi_atau_komorbid === "tidak" },
    { label: "Lama rawat", note: stated === null ? "Tidak disebut" : `${stated} hari`,
      claim: stay === null ? undefined : stay === 0 ? "Rawat jalan" : `${stay} hari`,
      // One day apart is how days are counted (admission day or nights), as in the server's reading.
      mismatch: stated !== null && stay !== null && stay >= 1 && Math.abs(stated - stay) >= 2 },
  ];
  if (facts.menyebut_lanjutan_perawatan_sebelumnya) list.push({ label: "Riwayat", note: "Lanjutan rawat inap sebelumnya", mismatch: true });
  return list;
}

function codeWithName(code: string | null, name: string | null): string {
  if (!code) return "—";
  return name ? `${code} · ${name}` : code;
}

/** The claim's clinical note and the AI's reading of it next to the billed codes. */
export function ClinicalNoteCard({ runId, caseId, canAsk, onLoaded }: {
  runId: string; caseId: string; canAsk: boolean; onLoaded?: (hasNote: boolean) => void;
}) {
  const notify = useNotify();
  const [data, setData] = useState<ClinicalNoteResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const reported = useRef(onLoaded);
  reported.current = onLoaded;
  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      const fresh = await getClinicalNote(runId, caseId, signal);
      setData(fresh);
      reported.current?.(Boolean(fresh.clinical_note));
    } catch { if (!signal?.aborted) { setData(null); reported.current?.(false); } }
  }, [runId, caseId]);
  useEffect(() => {
    const controller = new AbortController();
    setData(null); setError("");
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  // Claims without a clinical note show nothing.
  if (!data?.clinical_note) return null;
  const analysis = data.analysis;
  const rows = noteRows(data.clinical_note);
  const marks = data.highlights ?? [];

  async function ask() {
    if (busy) return;
    setBusy(true); setError("");
    try {
      const { analysis: fresh } = await requestClinicalAnalysis(runId, caseId);
      setData(current => current ? { ...current, analysis: fresh } : current);
      notify({ tone: fresh.engine === "llm" ? "success" : "info", title: "Catatan klinis selesai dibaca",
        message: `Klaim ${shortRef(caseId)}: ${VERDICTS[fresh.verdict].label.toLowerCase()}.` });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Catatan ini tidak dapat dibaca.");
    } finally { setBusy(false); }
  }

  return <section className="card run-case-reasons clinical-note-card" aria-label="Catatan klinis" data-testid="clinical-note">
    <div className="card-head">
      <div><h2><FileText size={16} style={{ verticalAlign: "-2px" }} /> Catatan klinis</h2>
        <p>Resume medis yang menyertai klaim.</p></div>
    </div>
    {data.claim && <dl className="clinical-claim-facts" data-testid="clinical-claim-facts">
      <div><dt>Diagnosis utama</dt><dd>{codeWithName(data.claim.primary_diagnosis, data.claim.primary_diagnosis_name)}</dd></div>
      <div><dt>INA-CBG</dt><dd>{codeWithName(data.claim.claim_group, data.claim.claim_group_name)}</dd></div>
      <div><dt>Lama rawat</dt><dd>{data.claim.stay_days === null ? "—" : data.claim.stay_days === 0 ? "Rawat jalan" : `${data.claim.stay_days} hari`}</dd></div>
    </dl>}
    <dl className="clinical-note-rows" data-testid="clinical-note-rows">
      {rows.map(row => <div key={row.label} className="clinical-note-row">
        <dt>{row.label}</dt>
        <dd>{row.text && <span>{markPhrases(row.text, marks)}</span>}
          {row.chips && <span className="clinical-chips">{row.chips.map(chip => <span key={chip} className="clinical-chip">{chip}</span>)}</span>}</dd>
      </div>)}
    </dl>
    {marks.length > 0 && <div className="note-conflicts" data-testid="note-conflicts">
      <strong><TriangleAlert size={15} aria-hidden="true" />Bertentangan dengan data klaim</strong>
      <ul>{marks.map(mark => <li key={`${mark.start}-${mark.kind}`}>
        <span className={`note-kind kind-${mark.kind}`}>{MARK_KINDS[mark.kind]}</span>
        <q>{mark.text}</q>
        <ArrowRight size={14} aria-hidden="true" />
        <span className="note-claim-value">{mark.claim_value}</span>
      </li>)}</ul>
    </div>}
    <details className="clinical-note-raw"><summary>Lihat teks asli</summary>
      <p className="clinical-note-text">{slices(data.clinical_note, marks.map(mark => ({ start: mark.start, end: mark.end, mark })))}</p></details>
    <NoteMatches runId={runId} caseId={caseId} />

    <div className="clinical-ai" data-testid="clinical-ai">
      <div className="clinical-ai-head">
        <div><strong><Sparkles size={15} style={{ verticalAlign: "-2px", color: "var(--brand-ink)" }} /> Pembacaan AI</strong>
          <span className="fine-print">{data.ai_configured
            ? "AI membaca catatan ini lalu mencocokkannya dengan diagnosis, tingkat keparahan, dan lama rawat yang ditagihkan."
            : "Layanan AI sedang tidak aktif; pembacaan memakai pemeriksaan teks otomatis."}</span></div>
        {canAsk && <button type="button" className="button button-primary row-button" disabled={busy} aria-busy={busy || undefined}
          onClick={() => void ask()} data-testid="clinical-ai-ask">
          {busy ? <Loader2 size={14} className="spin" aria-hidden="true" /> : <Sparkles size={14} aria-hidden="true" />}
          {busy ? "Sedang membaca…" : analysis ? "Baca ulang" : "Baca dengan AI"}</button>}
      </div>
      {error && <p className="notice-inline" role="alert">{error}</p>}
      {busy && <AiWait />}
      {analysis && !busy && <div className={`clinical-ai-result tone-${VERDICTS[analysis.verdict].tone}`} data-testid="clinical-ai-result">
        <div className="clinical-ai-verdict">
          <span className={`status-pill tone-${VERDICTS[analysis.verdict].tone}`}>{VERDICTS[analysis.verdict].label}</span>
          <strong>{VERDICTS[analysis.verdict].headline}</strong>
        </div>
        <p className="clinical-ai-summary">{analysis.ringkasan.replace(/^Fakta yang dibaca dari catatan bertentangan dengan data klaim\.\s*/, "")}</p>

        {analysis.fakta_catatan && <div className="clinical-facts" data-testid="clinical-ai-facts">
          <div className="clinical-facts-head"><span>Yang dibaca dari catatan</span><span>Data klaim</span></div>
          {readFacts(analysis.fakta_catatan, data.claim).map(fact => <div key={fact.label} className={`clinical-fact${fact.mismatch ? " mismatch" : ""}`}>
            <span className="clinical-fact-label">{fact.label}</span>
            <span className="clinical-fact-note">{fact.note}</span>
            <span className="clinical-fact-claim">{fact.claim ?? "—"}</span>
          </div>)}
        </div>}

        {analysis.alasan.length > 0 && <div className="clinical-ai-block">
          <span className="clinical-ai-label">Alasan</span>
          <ul className="clinical-ai-list">{analysis.alasan.slice(0, 3).map((item, index) => <li key={index}>{item}</li>)}</ul>
        </div>}
        {analysis.yang_perlu_diperiksa.length > 0 && <div className="clinical-ai-block">
          <span className="clinical-ai-label"><ClipboardCheck size={14} /> Cek di rekam medis</span>
          <ul className="clinical-ai-checks">{analysis.yang_perlu_diperiksa.map((item, index) => <li key={index}><CheckCircle2 size={14} />{item}</li>)}</ul>
        </div>}
        <span className="ai-meta" title={analysis.engine === "llm" ? `Model: ${analysis.model}` : `Aturan: ${analysis.model}`}>
          <span data-testid="clinical-ai-engine">{analysis.engine === "llm" ? "Dibaca AI" : "Pembacaan otomatis"}</span>
          {" · "}{formatDateTime(analysis.created_at)} · diminta oleh {analysis.requested_by}</span>
      </div>}
      {!analysis && !busy && !canAsk && <p className="fine-print">Catatan ini belum dibaca AI.</p>}
      <p className="ai-meta">Hasil pembacaan adalah alat bantu. Keputusan tetap pada verifikator dan tidak mengubah tingkat risiko klaim.</p>
    </div>
  </section>;
}

/** Other claims of the same file whose note is identical word for word: different patients, one note. */
function NoteMatches({ runId, caseId }: { runId: string; caseId: string }) {
  const [data, setData] = useState<NoteMatchesResponse | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    setData(null);
    getNoteMatches(runId, caseId, controller.signal).then(setData).catch(() => undefined);
    return () => controller.abort();
  }, [runId, caseId]);
  if (!data?.available || data.total_claims < 2) return null;
  return <div className="note-matches" data-testid="note-matches">
    <div className="note-matches-head">
      <span className="note-matches-icon"><Copy size={16} aria-hidden="true" /></span>
      <div><strong>Catatan ini sama persis dengan {formatCount(data.total_claims - 1)} klaim lain</strong>
        <span>{formatCount(data.distinct_participants)} peserta berbeda, teks dan angka pemeriksaan identik kata demi kata.</span></div>
    </div>
    {data.numbers.length > 0 && <div className="note-matches-numbers">
      <span>Angka yang sama persis</span>
      {data.numbers.slice(0, 10).map(number => <code key={number}>{number}</code>)}
    </div>}
    <table className="note-matches-table">
      <thead><tr><th>Klaim</th><th>Tanggal masuk</th><th>Diagnosis</th><th>INA-CBG</th><th>Tingkat</th></tr></thead>
      <tbody>{data.matches.map(item => <tr key={item.case_id}>
        <td><RunCandidateLink runId={runId} caseId={item.case_id} className="note-matches-link">Ref. {shortRef(item.case_id)}</RunCandidateLink></td>
        <td>{formatDate(item.service_date)}</td>
        <td>{item.primary_diagnosis ?? "—"}</td>
        <td>{item.claim_group ?? "—"}</td>
        <td><span className="status-dot-text"><LaneDot lane={item.lane} />{LANES[item.lane].name}</span></td>
      </tr>)}</tbody>
    </table>
    {data.matches_truncated && <p className="fine-print">Ditampilkan {formatCount(data.matches.length)} klaim pertama.</p>}
  </div>;
}

/** While the AI reads: what it is doing, how long it has taken, and a moving strip (a reading can take ±40 s). */
function AiWait() {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    const timer = window.setInterval(() => setSeconds(value => value + 1), 1000);
    return () => window.clearInterval(timer);
  }, []);
  const step = seconds < 4 ? "Mengirim catatan ke AI" : seconds < 30 ? "AI membaca catatan dan mencocokkannya dengan data klaim" : "Hampir selesai";
  return <div className="clinical-ai-wait" role="status" aria-live="polite">
    <div className="clinical-ai-wait-row"><span /><span /><span /><em>{step}… {seconds} detik</em></div>
    <div className="busy-strip" aria-hidden="true" />
    <small className="fine-print">Biasanya kurang dari satu menit.</small>
  </div>;
}
