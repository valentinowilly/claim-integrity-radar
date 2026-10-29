import { useEffect, useRef, useState, type ReactNode } from "react";
import { serviceText } from "./serviceText";
import { AlertTriangle, Check, ChevronDown, Copy, Info } from "lucide-react";
import type { MlAnomaly, RunManifest, RunSourceType } from "../api/client";

/* Presentation-only helpers: Indonesian labels for backend values. Raw values stay
   available in "Detail teknis"; nothing here changes analytical results. */

export function formatCount(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : new Intl.NumberFormat("id-ID").format(value);
}

/** Rupiah with a short scale word (ribu, juta, miliar, triliun), Indonesian decimals. */
export function formatRupiah(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  const scales: Array<[number, string]> = [[1e12, "triliun"], [1e9, "miliar"], [1e6, "juta"], [1e3, "ribu"]];
  for (const [size, word] of scales) {
    if (Math.abs(value) >= size) return `Rp${(value / size).toLocaleString("id-ID", { maximumFractionDigits: 1 })} ${word}`;
  }
  return `Rp${Math.round(value).toLocaleString("id-ID")}`;
}
export function formatPercent(part: number, whole: number): string {
  if (!whole) return "0%";
  const percent = (part / whole) * 100;
  return `${new Intl.NumberFormat("id-ID", { maximumFractionDigits: percent < 10 ? 1 : 0 }).format(percent)}%`;
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("id-ID", { dateStyle: "medium", timeStyle: "short" }).format(date);
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("id-ID", { dateStyle: "long" }).format(date);
}

const SOURCE_LABELS: Record<RunSourceType, string> = {
  synthetic_csv: "Berkas unggahan",
  bpjs_fkrtl_local: "Data klaim FKRTL",
};
export function sourceLabel(sourceType: RunSourceType): string {
  return SOURCE_LABELS[sourceType] ?? sourceType;
}
/** A name people can tell apart: the uploaded file name or the FKRTL period, then the time of the analysis. */
export function runTitle(run: Pick<RunManifest, "source_type" | "created_at"> & { configuration?: RunManifest["configuration"] }): string {
  const source = run.configuration?.source;
  const details = source && typeof source === "object" && !Array.isArray(source) ? source : null;
  const selection = details?.selection && typeof details.selection === "object" && !Array.isArray(details.selection) ? details.selection : null;
  const key = typeof details?.batch_key === "string" ? details.batch_key.replace(/^synthetic-/, "") : null;
  const name = run.source_type === "bpjs_fkrtl_local" && typeof selection?.date_from === "string" && typeof selection?.date_to === "string"
    ? `Data klaim ${formatDate(selection.date_from)} – ${formatDate(selection.date_to)}`
    : key && run.source_type !== "bpjs_fkrtl_local" ? `Berkas "${key}"` : `Analisis ${sourceLabel(run.source_type)}`;
  return `${name} · ${formatDateTime(run.created_at)}`;
}
/** Short, non-semantic reference derived from the real ID (last 6 characters). */
export function shortRef(id: string): string {
  return id.slice(-6).toUpperCase();
}

export type Tone = "good" | "warn" | "danger" | "info" | "neutral";
const STATUS: Record<string, [string, Tone]> = {
  // data and analyses
  ready: ["Siap dianalisis", "good"],
  ready_with_warnings: ["Siap, dengan catatan", "warn"],
  rejected: ["Ditolak", "danger"],
  running: ["Sedang berjalan", "info"],
  completed: ["Selesai", "good"],
  failed: ["Gagal", "danger"],
  // check coverage
  complete: ["Semua klaim diperiksa", "good"],
  partial: ["Sebagian klaim dilewati", "info"],
  partial_coverage: ["Sebagian klaim belum diperiksa", "warn"],
  unavailable: ["Tidak tersedia", "neutral"],
  not_applicable: ["Tidak berlaku untuk data ini", "neutral"],
  not_assessable: ["Belum dapat dinilai", "neutral"],
  available: ["Tersedia", "good"],
  insufficient_data: ["Data terlalu sedikit", "neutral"],
  assessed: ["Sudah dinilai", "good"],
  assessed_no_signal: ["Dinilai, tidak ada temuan", "neutral"],
  insufficient_assessed_indicators: ["Skor tidak dihitung", "neutral"],
  // per-claim check state
  triggered: ["Ditandai", "warn"],
  not_triggered: ["Tidak ditandai", "good"],
  not_assessed: ["Belum dapat diperiksa", "neutral"],
  // suggested follow-up (provisional)
  cannot_recommend: ["Belum ada saran tindak lanjut", "neutral"],
  green: ["Risiko rendah", "good"],
  yellow: ["Risiko sedang", "warn"],
  red: ["Risiko tinggi", "danger"],
  // review
  pending_review: ["Belum ditinjau", "neutral"],
  in_review: ["Sedang ditinjau", "info"],
  awaiting_evidence: ["Minta klarifikasi", "warn"],
  escalated: ["Masuk antrean audit", "danger"],
  closed: ["Selesai", "good"],
};
/** Traffic-light lanes as in the proposal: colour, meaning and what the system asks the reviewer to do. */
export const LANES = {
  red: { name: "Risiko tinggi", meaning: "Prioritas pemeriksaan", action: "Prioritaskan audit dan siapkan berkas bukti", tone: "danger" as Tone },
  yellow: { name: "Risiko sedang", meaning: "Perlu penjelasan", action: "Minta klarifikasi ke faskes; pembayaran tidak ditahan", tone: "warn" as Tone },
  green: { name: "Risiko rendah", meaning: "Tidak ada temuan berarti", action: "Proses seperti biasa", tone: "good" as Tone },
} as const;
export const LEVELS = {
  high: { label: "Risiko tinggi", tone: "danger" as Tone },
  medium: { label: "Risiko sedang", tone: "warn" as Tone },
  low: { label: "Risiko rendah", tone: "good" as Tone },
} as const;
export function LaneDot({ lane }: { lane: string }) {
  return <i className={`lane-dot lane-${lane}`} aria-hidden="true" />;
}
export function statusText(value: string): string {
  return STATUS[value]?.[0] ?? value.replace(/_/g, " ");
}
export function statusTone(value: string): Tone {
  return STATUS[value]?.[1] ?? "neutral";
}
/** Run-level wording: a "partial" run still finished; only some claims could not be checked by every check
 * (claim data always has gaps, e.g. claims without a procedure code), so it reads as finished. */
export function runStatusText(value: string): string {
  return value === "partial" ? "Selesai" : statusText(value);
}
export function RunStatusPill({ value }: { value: string }) {
  return <StatusPill value={value === "partial" ? "completed" : value} label={runStatusText(value)} />;
}
export function StatusPill({ value, label }: { value: string; label?: string }) {
  return <span className={`status-pill tone-${statusTone(value)}`}>{label ?? statusText(value)}</span>;
}

/** Rule-based priority score (0–100); a withheld score explains why instead of showing a number. */
export function ruleIndexText(item: {
  risk_score: number | null;
  score_status: string;
  score_basis?: { assessed_indicator_count: number; minimum_assessed_indicators: number } | null;
}): string {
  if (item.risk_score !== null) return `${Math.round(item.risk_score * 100)} dari 100`;
  if (item.score_status === "insufficient_assessed_indicators") return "Tidak dihitung";
  return "Belum dapat dinilai";
}
export function ruleIndexExplanation(item: {
  risk_score: number | null;
  score_status: string;
  score_basis?: { assessed_indicator_count: number; minimum_assessed_indicators: number } | null;
}): string {
  if (item.risk_score !== null) return "Gabungan pemeriksaan aturan untuk mengurutkan tinjauan; bukan peluang fraud.";
  if (item.score_status === "insufficient_assessed_indicators" && item.score_basis)
    return `Hanya ${item.score_basis.assessed_indicator_count} pemeriksaan yang berlaku untuk klaim ini (minimal ${item.score_basis.minimum_assessed_indicators}), jadi skor tidak dihitung.`;
  return "Pemeriksaan yang berlaku terlalu sedikit untuk menghitung skor.";
}

const INDICATORS: Record<string, [string, string, string]> = {
  repeat_billing_candidate: [
    "Layanan berulang",
    "Peserta yang sama tercatat beberapa kali dengan tanggal masuk, diagnosis, INA-CBG, dan prosedur yang sama.",
    "Bandingkan tanggal pulang, resume medis, dan berkas klaim: apakah tiap kunjungan memang layanan terpisah yang sah?",
  ],
  similar_claim_pattern_candidate: [
    "Pola identik antar-peserta",
    "Klaim dari peserta berbeda dengan pola dan nilai klaim yang persis sama.",
    "Periksa apakah klaim-klaim ini memang layanan berbeda yang kebetulan serupa.",
  ],
  near_duplicate_claim_candidate: [
    "Klaim serupa antar-peserta",
    "Klaim dari peserta berbeda pada tanggal yang sama yang hampir semua datanya cocok, dan kecocokan seperti itu jarang terjadi.",
    "Bandingkan kedua klaim: apakah kemiripannya wajar, atau ada tanda salinan klaim?",
  ],
  synthetic_capacity_candidate: [
    "Kapasitas layanan",
    "Volume layanan dibandingkan dengan kapasitas fasilitas; memerlukan data kapasitas faskes.",
    "Periksa apakah volume layanan pada hari itu masuk akal.",
  ],
  temporal_pattern_candidate: [
    "Pola waktu",
    "Kunjungan berulang dalam rentang singkat atau banyak peserta pada menit yang sama; memerlukan jam layanan.",
    "Periksa apakah kunjungan ini satu rangkaian perawatan atau jadwal yang wajar.",
  ],
  supporting_evidence_completeness_candidate: [
    "Kelengkapan dokumen",
    "Dokumen pendukung yang diwajibkan tidak tercatat; memerlukan data kelengkapan berkas.",
    "Periksa apakah dokumen pendukung layanan tersedia.",
  ],
  length_of_stay_extreme_candidate: [
    "Lama rawat ekstrem",
    "Lama rawat inap jauh di atas kebiasaan INA-CBG dan kelas rawat yang sama (minimal 7 hari lebih lama dari nilai tengah di data pembanding).",
    "Periksa resume medis dan catatan harian rawat: apakah ada komplikasi yang membenarkan rawat selama itu?",
  ],
  rapid_readmission_candidate: [
    "Rawat inap ulang cepat",
    "Peserta yang sama dirawat inap lagi dengan diagnosis utama yang sama paling lama 3 hari setelah pulang.",
    "Bandingkan kedua resume medis: apakah ini memang dua episode, atau satu episode yang dipecah menjadi dua klaim?",
  ],
  unusual_severity_candidate: [
    "Keparahan tidak lazim",
    "INA-CBG keparahan II/III dipakai untuk diagnosis utama yang di data pembanding jarang (di bawah 5%) mendapat keparahan setinggi itu.",
    "Periksa diagnosis sekunder dan tindakan di resume medis yang mendasari tingkat keparahan INA-CBG.",
  ],
  cloned_clinical_note_candidate: [
    "Catatan klinis kembar",
    "Catatan klinis klaim ini sama persis kata demi kata, termasuk angka tanda vital dan lab, dengan catatan pasien lain.",
    "Bandingkan rekam medis para pasien: apakah catatan disalin dari pasien lain tanpa pemeriksaan sendiri?",
  ],
  severity_without_secondary_candidate: [
    "Keparahan tanpa diagnosis sekunder",
    "Rawat inap INA-CBG keparahan II/III tanpa satu pun diagnosis sekunder. Keparahan II/III ditentukan komorbid atau komplikasi; hampir semua klaim seperti ini mencatat diagnosis sekunder.",
    "Periksa resume medis: adakah komorbid atau komplikasi yang mendasari tingkat keparahan, atau keparahan dinaikkan tanpa dasar?",
  ],
  unusual_special_topup_candidate: [
    "Tambahan khusus tidak lazim",
    "Obat, alat/prostesis, prosedur, atau pemeriksaan khusus ditagihkan bersama INA-CBG yang di data pembanding jarang mendapat tambahan itu.",
    "Periksa indikasi medis serta bukti pemberian obat, pemasangan alat, atau pelaksanaan tindakannya.",
  ],
};
/** Shown wherever a repeat match is displayed: the server marks it as a pattern without billing evidence. */
export const PATTERN_ONLY_TEXT = "Ini pola layanan, belum bukti tagihan ganda: status pembayaran tidak tersedia di data sumber.";
export function PatternOnlyNotice({ evidence }: { evidence: unknown }) {
  if (evidence !== "not_available") return null;
  return <p className="notice-inline" data-testid="repeat-pattern-only">{PATTERN_ONLY_TEXT}</p>;
}
export function indicatorLabel(code: string): string {
  return INDICATORS[code]?.[0] ?? code.replace(/_/g, " ");
}
export function indicatorDefinition(code: string): string | null {
  return INDICATORS[code]?.[1] ?? null;
}
export function indicatorGuidance(code: string): string | null {
  return INDICATORS[code]?.[2] ?? null;
}

const ATTRIBUTES: Record<string, string> = {
  participant_token: "peserta yang sama",
  service_date: "tanggal masuk",
  discharge_date: "tanggal pulang",
  province_code: "provinsi",
  municipality_code: "kabupaten/kota",
  facility_ownership: "kepemilikan fasilitas",
  facility_type: "jenis fasilitas",
  facility_class: "kelas fasilitas",
  care_class: "kelas rawat",
  admission_diagnosis: "diagnosis masuk",
  primary_diagnosis: "diagnosis utama",
  claim_group: "kode INA-CBG",
  procedure_code: "prosedur",
  billed_amount: "nilai tagihan",
  service_type: "jenis layanan",
  facility_id: "fasilitas",
};
/** Readable text for a coverage reason code (field names or the check's fixed reason text; never record values). */
export function unassessedReasonText(code: string): string {
  if (code.startsWith("missing:")) return `${code.slice("missing:".length).split("+").map(attributeLabel).join(" + ")} kosong`;
  if (code === "search_limited") return "tidak terjangkau karena batas pencarian";
  if (code === "not_reached_by_search") return "tidak terjangkau oleh pencarian";
  if (code.startsWith("reason:")) return serviceText(code.slice("reason:".length), attributeLabel);
  // Row-level prerequisite codes reported by source validation.
  const prerequisite: Record<string, string> = {
    missing_participant: "tanpa data peserta",
    too_few_attributes: "atribut yang bisa dibandingkan terlalu sedikit",
    no_complete_blocking_key: "atribut kunci pencarian tidak lengkap",
    missing_date: "tanggal masuk atau pulang kosong",
    invalid_date: "tanggal masuk atau pulang tidak valid",
    reversed_dates: "tanggal pulang sebelum tanggal masuk",
    missing_peer_key: "INA-CBG atau kelas rawat kosong",
  };
  return prerequisite[code] ?? "alasan tidak tercatat";
}
export function attributeLabel(name: string): string {
  return ATTRIBUTES[name] ?? name.replace(/_/g, " ");
}

const EVIDENCE_KEYS: Record<string, string> = {
  matched_attributes: "Data yang sama",
  differing_attributes: "Data yang berbeda",
  context_unavailable_attributes: "Tidak tercatat",
  candidate_record_count: "Jumlah klaim dalam kelompok",
  earlier_claim_count: "Klaim dari data sebelumnya",
  case_count: "Jumlah klaim dalam pola",
  distinct_participant_count: "Jumlah peserta",
  similarity_ratio: "Tingkat kemiripan",
  matched_attribute_count: "Data yang cocok",
  compared_attribute_count: "Data yang dibandingkan",
  match_support: "Klaim pada tanggal yang sama",
  observed_service_units: "Unit layanan tercatat",
  capacity_service_units: "Kapasitas unit",
  utilization_ratio: "Rasio pemakaian",
  missing_evidence: "Dokumen yang tidak ada",
  recorded_evidence: "Dokumen yang tercatat",
};
// Internal detector fields: useful in technical notes, not to a reviewer.
const HIDDEN_EVIDENCE = new Set(["mode", "pattern_type", "period", "supporting_values", "interpretation", "billing_status_evidence",
  "evidence_class", "expected_chance_pairs", "rule", "capacity_threshold_multiplier"]);
const LIST_KEYS = new Set(["matched_attributes", "differing_attributes", "context_unavailable_attributes", "missing_evidence", "recorded_evidence"]);
const DOCUMENTS: Record<string, string> = {
  clinical_note: "catatan klinis", procedure_order: "perintah tindakan", referral: "surat rujukan", session_record: "catatan sesi",
  lab_result: "hasil laboratorium", radiology_result: "hasil radiologi", prescription: "resep", medical_resume: "resume medis",
};
function listItems(raw: string): string[] {
  const text = raw.trim();
  const inner = text.startsWith("[") && text.endsWith("]") ? text.slice(1, -1) : text;
  return inner.split(",").map(item => item.trim().replace(/^['"]|['"]$/g, "")).filter(Boolean);
}
function itemLabel(key: string, name: string): string {
  return key.endsWith("_evidence") ? DOCUMENTS[name] ?? name.replace(/_/g, " ") : attributeLabel(name);
}
function plainValue(key: string, raw: string): string {
  const number = Number(raw);
  if ((key === "similarity_ratio" || key === "utilization_ratio") && !Number.isNaN(number))
    return key === "similarity_ratio" ? `${Math.round(number * 100)}%` : `${number.toFixed(1).replace(".", ",")}×`;
  return Number.isNaN(number) ? raw : formatCount(number);
}
/** Renders the backend's "key: value" evidence strings as readable chips and values. */
export function EvidenceList({ evidence }: { evidence: string[] }) {
  const rows = evidence.map(line => {
    const split = line.indexOf(": ");
    return { key: split > 0 ? line.slice(0, split) : "", raw: split > 0 ? line.slice(split + 2) : line };
  }).filter(row => !HIDDEN_EVIDENCE.has(row.key));
  if (!rows.length) return null;
  return (
    <dl className="evidence-list">
      {rows.map(({ key, raw }, index) => {
        const items = LIST_KEYS.has(key) ? listItems(raw) : null;
        return (
          <div key={`${index}-${key}`}>
            <dt>{EVIDENCE_KEYS[key] ?? (key ? key.replace(/_/g, " ") : "Detail")}</dt>
            <dd>{items
              ? items.length === 0 ? "Tidak ada" : <span className="chip-row">{items.map(name => (
                  <span key={name} className={`chip ${key === "differing_attributes" || key === "missing_evidence" ? "chip-warn" : key === "matched_attributes" ? "chip-good" : ""}`}>{itemLabel(key, name)}</span>))}</span>
              : plainValue(key, raw)}</dd>
          </div>
        );
      })}
    </dl>
  );
}

export function CopyIdButton({ value, label = "Salin" }: { value: string; label?: string }) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setState("copied");
    } catch {
      setState("failed");
    }
    window.setTimeout(() => setState("idle"), 2000);
  }
  return (
    <button type="button" className="button button-secondary button-compact" onClick={() => void copy()}>
      {state === "copied" ? <Check size={13} /> : <Copy size={13} />}
      {state === "copied" ? "Tersalin" : state === "failed" ? "Gagal menyalin" : label}
    </button>
  );
}

export interface TechnicalItem {
  label: string;
  value: string | null | undefined;
  copy?: boolean;
}
/** Collapsed secondary section for raw IDs, versions and model configuration. */
export function TechnicalDetails({
  items,
  title = "Detail teknis",
  children,
}: {
  items: TechnicalItem[];
  title?: string;
  children?: ReactNode;
}) {
  return (
    <details className="tech-details">
      <summary>
        <ChevronDown size={14} className="tech-details-chevron" />
        {title}
      </summary>
      <dl>
        {items.map((item) => (
          <div key={item.label}>
            <dt>{item.label}</dt>
            <dd>
              <code>{item.value ?? "—"}</code>
              {item.copy && item.value && <CopyIdButton value={item.value} />}
            </dd>
          </div>
        ))}
      </dl>
      {children}
    </details>
  );
}

/** Expandable list for long qualifications (e.g. check limitations). */
/** "How to read this page": folded, at the top of the page, so it is seen before the content it explains. */
export function ReadingGuide({ title = "Cara membaca halaman ini", items }: { title?: string; items: Array<[string, ReactNode]> }) {
  return <details className="reading-guide-bar" data-testid="reading-guide">
    <summary><Info size={15} aria-hidden="true" />{title}<ChevronDown size={14} className="reading-guide-chevron" aria-hidden="true" /></summary>
    <dl className="reading-guide">{items.map(([term, text]) => <div key={term}><dt>{term}</dt><dd>{text}</dd></div>)}</dl>
  </details>;
}

export function MoreInfo({ title, items, children }: { title: string; items?: string[]; children?: ReactNode }) {
  if (!children && (!items || items.length === 0)) return null;
  return (
    <details className="more-info">
      <summary>
        <ChevronDown size={14} className="tech-details-chevron" />
        {title}
      </summary>
      {items && items.length > 0 && (
        <ul>
          {items.map((item, index) => (
            <li key={`${index}-${item}`}>{serviceText(item, attributeLabel)}</li>
          ))}
        </ul>
      )}
      {children}
    </details>
  );
}

export function Callout({ tone, title, children }: { tone: "warn" | "info"; title: string; children: ReactNode }) {
  return (
    <div className={`callout callout-${tone}`} role={tone === "warn" ? "note" : undefined}>
      {tone === "warn" ? <AlertTriangle size={17} /> : <Info size={17} />}
      <div>
        <strong>{title}</strong>
        <div className="callout-body">{children}</div>
      </div>
    </div>
  );
}

/** Coverage as one stacked bar plus a legend; counts exactly as recorded by the backend. */
export function CoverageMetrics({
  candidates,
  assessed,
  notAssessed,
  notApplicable,
  truncated,
}: {
  candidates: number | null;
  assessed: number;
  notAssessed: number;
  notApplicable: number;
  truncated: boolean;
}) {
  const total = assessed + notAssessed + notApplicable;
  return (
    <div className="coverage-block">
      <div className="coverage-headline">
        <div><strong>{formatCount(candidates)}</strong><span>klaim ditandai</span></div>
        <div><strong>{formatPercent(assessed, total)}</strong><span>klaim dapat diperiksa</span></div>
      </div>
      <CoverageBar assessed={assessed} notAssessed={notAssessed} notApplicable={notApplicable} />
      <ul className="coverage-legend">
        <li><i className="dot dot-good" />Diperiksa <strong>{formatCount(assessed)}</strong></li>
        <li><i className="dot dot-warn" />Belum dapat diperiksa <strong>{formatCount(notAssessed)}</strong></li>
        <li><i className="dot dot-neutral" />Tidak berlaku <strong>{formatCount(notApplicable)}</strong></li>
      </ul>
      {truncated && <p className="notice-inline">Pencarian mencapai batasnya; sebagian kemungkinan temuan belum terjangkau.</p>}
    </div>
  );
}

export function CoverageBar({ assessed, notAssessed, notApplicable }: { assessed: number; notAssessed: number; notApplicable: number }) {
  const total = assessed + notAssessed + notApplicable || 1;
  const width = (value: number) => `${(value / total) * 100}%`;
  return (
    <div className="coverage-bar" role="img" aria-label={`Diperiksa ${formatCount(assessed)}, belum dapat diperiksa ${formatCount(notAssessed)}, tidak berlaku ${formatCount(notApplicable)}`}>
      <span className="seg-good" style={{ width: width(assessed) }} />
      <span className="seg-warn" style={{ width: width(notAssessed) }} />
      <span className="seg-neutral" style={{ width: width(notApplicable) }} />
    </div>
  );
}

export function LimitedSearchWarning({ indicator }: { indicator: string }) {
  return (
    <Callout tone="warn" title="Pencarian terbatas">
      <p>
        Pemeriksaan {indicatorLabel(indicator).toLowerCase()} mencapai batas pencariannya, sehingga mungkin ada temuan yang
        belum terjangkau. Klaim yang belum diperiksa tidak berarti aman.
      </p>
    </Callout>
  );
}

export function FacilityPriorityNotice({ status, reasons }: { status: string; reasons: string[] }) {
  const unavailable = status !== "available" && status !== "partial";
  return (
    <Callout tone="info" title={unavailable ? "Prioritas per faskes belum tersedia" : "Prioritas per faskes"}>
      {unavailable ? (
        <p>Data tidak memuat identitas faskes, jadi klaim diurutkan satu per satu, bukan per faskes.</p>
      ) : (
        <p>Prioritas per faskes sudah dihitung; sebagian klaim mungkin belum diperiksa.</p>
      )}
      <MoreInfo title="Catatan teknis" items={reasons} />
    </Callout>
  );
}

/* ---- AI: unusual-claim level ---- */

const ML_FEATURES: Record<string, string> = {
  freq_province_code: "Provinsi jarang muncul",
  freq_municipality_code: "Kabupaten/kota jarang muncul",
  freq_facility_ownership: "Kepemilikan fasilitas jarang",
  freq_facility_type: "Jenis fasilitas jarang",
  freq_facility_class: "Kelas fasilitas jarang",
  freq_admission_diagnosis: "Diagnosis masuk jarang",
  freq_primary_diagnosis: "Diagnosis utama jarang",
  freq_claim_group: "Kode INA-CBG jarang",
  freq_procedure_code: "Prosedur jarang atau tidak tercatat",
  pair_primary_diagnosis__claim_group: "Diagnosis dan kode INA-CBG jarang dipasangkan",
  pair_claim_group__procedure_code: "Kode INA-CBG dan prosedur jarang dipasangkan",
  pair_admission_diagnosis__primary_diagnosis: "Diagnosis masuk dan diagnosis utama tidak lazim",
  pair_facility_class__claim_group: "Kode INA-CBG jarang dipakai di RS sekelas ini",
  pair_municipality_code__claim_group: "Kode INA-CBG jarang dipakai di wilayah ini",
  length_of_stay_deviation: "Lama rawat jauh berbeda dari klaim sejenis",
  participant_visit_count: "Peserta berkunjung sangat sering",
  participant_week_visits: "Peserta berkunjung sangat sering dalam seminggu",
  diagnosis_changed: "Diagnosis masuk berbeda dengan diagnosis utama",
};
export function mlFeatureLabel(name: string, fallback: string): string {
  return ML_FEATURES[name] ?? serviceText(fallback);
}

/** Position text: "Peringkat 3 dari 50.000 (0,006% teratas)". Tied scores share a rank. */
export function mlRankText(rank: number, total: number, tieCount?: number): string {
  const tie = tieCount && tieCount > 1 ? ` · nilainya sama dengan ${formatCount(tieCount - 1)} klaim lain` : "";
  if (!total) return `Peringkat ${formatCount(rank)}${tie}`;
  return `Peringkat ${formatCount(rank)} dari ${formatCount(total)}${tie}`;
}

/** Level words for the AI Pola Klaim percentile against the training data: how rare the claim's pattern is. */
export function mlLevel(percentile: number): { label: string; tone: Tone } {
  if (percentile >= 0.99) return { label: "Pola sangat jarang", tone: "danger" };
  if (percentile >= 0.95) return { label: "Pola jarang", tone: "warn" };
  if (percentile >= 0.8) return { label: "Pola agak jarang", tone: "info" };
  return { label: "Pola wajar", tone: "neutral" };
}

/** The proposal's fraud patterns, as named on screen. */
export const FRAUD_PATTERNS: Record<string, { label: string; hint: string }> = {
  phantom_billing: { label: "Phantom billing", hint: "Layanan melebihi kapasitas, tanpa bukti, atau dicatat serentak" },
  cloning: { label: "Cloning", hint: "Catatan klinis disalin dari klaim lain" },
  repeat_billing: { label: "Repeat billing", hint: "Layanan yang sama ditagih lagi atau episode dipecah" },
  fictitious_claim: { label: "Klaim fiktif obat/alkes", hint: "Obat atau alat khusus tanpa bukti pemberian, atau tidak lazim untuk INA-CBG-nya" },
  upcoding_stay: { label: "Upcoding / lama rawat", hint: "Keparahan atau lama rawat tidak sesuai klaim sejenis" },
};
export function PatternTags({ patterns }: { patterns?: string[] | null }) {
  if (!patterns?.length) return null;
  return <span className="pattern-tags">{patterns.map(code => <span key={code} className={`pattern-tag pattern-${code}`}
    title={FRAUD_PATTERNS[code]?.hint}>{FRAUD_PATTERNS[code]?.label ?? code}</span>)}</span>;
}
/** AI anomaly score 0–100: the share of reference claims that are less unusual than this one. */
export function aiScore(percentile: number): string {
  return (Math.floor(percentile * 1000) / 10).toLocaleString("id-ID", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
}

export const ML_QUALIFICATION =
  "Skor AI membantu menentukan urutan pemeriksaan, bukan bukti kecurangan. Keputusan tetap di tangan petugas.";

export const ML_PRETRAINED_QUALIFICATION = ML_QUALIFICATION;

export function mlQualification(ml: MlAnomaly | undefined): string {
  return ml?.mode === "pretrained_artifact" ? ML_PRETRAINED_QUALIFICATION : ML_QUALIFICATION;
}

export function mlTechnicalItems(ml: MlAnomaly): TechnicalItem[] {
  const training = ml.training_reference;
  return [
    ...(ml.mode === "pretrained_artifact" ? [
      { label: "Cara kerja", value: "Model yang sudah dilatih (tidak dilatih ulang setiap analisis)" },
      { label: "Data latih", value: training?.date_from && training?.date_to ? `${training.date_from} s.d. ${training.date_to} (${formatCount(training.rows_eligible ?? 0)} klaim)` : null },
      { label: "Kode file model", value: ml.artifact_checksum ?? null },
      { label: "Klaim yang tidak dinilai AI", value: ml.records_not_assessed !== undefined ? formatCount(ml.records_not_assessed) : null },
    ] : []),
    { label: "Metode", value: ml.model ?? "IsolationForest (scikit-learn)" },
    { label: "Versi model", value: ml.model_version },
    { label: "Cara menghitung skor", value: ml.score_type ?? null },
    { label: "Klaim dibaca / dinilai AI", value: `${formatCount(ml.records_considered)} / ${formatCount(ml.records_scored)}` },
    { label: "Klaim yang ditampilkan", value: `${formatCount(ml.items.length)}${ml.items_truncated ? " (yang paling tidak biasa)" : ""}` },
  ];
}

/** A number that counts up once when it first appears (skipped when the user prefers reduced motion). */
const prefersReducedMotion = () => typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/** A number that counts up from zero when it first appears, and glides to a new value when it changes. */
export function CountUp({ value, format = formatCount }: { value: number; format?: (value: number) => string }) {
  // Start at zero (not at the final value), so the first paint does not flash the end number before counting.
  const [shown, setShown] = useState(() => prefersReducedMotion() || !Number.isFinite(value) ? value : 0);
  const from = useRef(0);
  useEffect(() => {
    if (prefersReducedMotion() || !Number.isFinite(value) || value === 0) { setShown(value); from.current = value; return; }
    const start = performance.now(), begin = from.current, duration = 1100;
    let frame = 0;
    const step = (now: number) => {
      const t = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - t, 3);
      setShown(Math.round(begin + (value - begin) * eased));
      if (t < 1) frame = requestAnimationFrame(step); else from.current = value;
    };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [value]);
  return <>{format(shown)}</>;
}

/** Compact analysis name for pickers: the file name (or FKRTL period) and the time, without a prefix. */
export function shortRunTitle(run: Parameters<typeof runTitle>[0]): string {
  return runTitle(run).replace(/^Berkas "(.*?)"/, "$1");
}
