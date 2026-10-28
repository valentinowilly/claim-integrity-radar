import { useCallback, useEffect, useState } from "react";
import { CheckCircle2, ClipboardCheck, FileText, Sparkles } from "lucide-react";
import { getClinicalNote, requestClinicalAnalysis, type ClinicalAnalysis, type ClinicalNoteResponse, type ClinicalVerdictCode } from "../api/client";
import { useNotify } from "../notifications/NotificationCenter";
import { formatDateTime, shortRef } from "./Display";

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
      mismatch: stated !== null && stay !== null && stay >= 1 && stated !== stay },
  ];
  if (facts.menyebut_lanjutan_perawatan_sebelumnya) list.push({ label: "Riwayat", note: "Lanjutan rawat inap sebelumnya", mismatch: true });
  return list;
}

function codeWithName(code: string | null, name: string | null): string {
  if (!code) return "—";
  return name ? `${code} · ${name}` : code;
}

/** The claim's clinical note and the AI's reading of it next to the billed codes. */
export function ClinicalNoteCard({ runId, caseId, canAsk }: { runId: string; caseId: string; canAsk: boolean }) {
  const notify = useNotify();
  const [data, setData] = useState<ClinicalNoteResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const load = useCallback(async (signal?: AbortSignal) => {
    try { setData(await getClinicalNote(runId, caseId, signal)); } catch { if (!signal?.aborted) setData(null); }
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
        <dd>{row.text && <span>{row.text}</span>}
          {row.chips && <span className="clinical-chips">{row.chips.map(chip => <span key={chip} className="clinical-chip">{chip}</span>)}</span>}</dd>
      </div>)}
    </dl>
    <details className="clinical-note-raw"><summary>Lihat teks asli</summary><p className="clinical-note-text">{data.clinical_note}</p></details>

    <div className="clinical-ai" data-testid="clinical-ai">
      <div className="clinical-ai-head">
        <div><strong><Sparkles size={15} style={{ verticalAlign: "-2px", color: "var(--brand)" }} /> Pembacaan AI</strong>
          <span className="fine-print">{data.ai_configured
            ? "AI membaca catatan ini lalu mencocokkannya dengan diagnosis, tingkat keparahan, dan lama rawat yang ditagihkan."
            : "Layanan AI sedang tidak aktif; pembacaan memakai pemeriksaan teks otomatis."}</span></div>
        {canAsk && <button type="button" className="button button-primary row-button" disabled={busy}
          onClick={() => void ask()} data-testid="clinical-ai-ask">{busy ? "Sedang membaca…" : analysis ? "Baca ulang" : "Baca dengan AI"}</button>}
      </div>
      {error && <p className="notice-inline" role="alert">{error}</p>}
      {busy && <div className="clinical-ai-wait" role="status"><span /><span /><span /><em>AI sedang membaca catatan; biasanya kurang dari satu menit.</em></div>}
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
