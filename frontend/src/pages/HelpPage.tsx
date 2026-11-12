import { useEffect, useMemo, useState } from "react";
import {
  BookOpenText, Calculator, ClipboardCheck, Copy, FileSearch, FileText, Ghost, LayoutDashboard, ListChecks, Pill, Repeat,
  Search, TrendingUp, type LucideIcon,
} from "lucide-react";
import { Link, useLocation } from "react-router-dom";
import { FRAUD_PATTERNS, INDICATOR_CODES, LANES, indicatorDefinition, indicatorLabel } from "../components/Display";
import { PATTERN_COLORS } from "../components/RiskFocus";
import { GLOSSARY } from "../components/Term";

/** Which pattern each check looks for (the same mapping the server uses to label claims). */
const PATTERN_OF: Record<string, string> = {
  synthetic_capacity_candidate: "phantom_billing", temporal_pattern_candidate: "phantom_billing",
  supporting_evidence_completeness_candidate: "phantom_billing",
  cloned_clinical_note_candidate: "cloning",
  repeat_billing_candidate: "repeat_billing", rapid_readmission_candidate: "repeat_billing",
  unusual_special_topup_candidate: "fictitious_claim",
  length_of_stay_extreme_candidate: "upcoding_stay", unusual_severity_candidate: "upcoding_stay", severity_without_secondary_candidate: "upcoding_stay",
};
const PATTERN_CARD: Record<string, { icon: LucideIcon; line: string }> = {
  phantom_billing: { icon: Ghost, line: "Layanan ditagih tanpa pernah diberikan" },
  cloning: { icon: Copy, line: "Catatan klinis disalin dari pasien lain" },
  repeat_billing: { icon: Repeat, line: "Layanan sama ditagih berulang" },
  fictitious_claim: { icon: Pill, line: "Obat atau alat ditagih tanpa bukti" },
  upcoding_stay: { icon: TrendingUp, line: "Keparahan atau lama rawat dinaikkan" },
};
const STEPS: Array<{ icon: LucideIcon; title: string; line: string; to: string }> = [
  { icon: LayoutDashboard, title: "Lihat Beranda", line: "Jumlah dan nilai klaim risiko tinggi", to: "/" },
  { icon: ListChecks, title: "Buka antrean", line: "Mulai dari risiko tinggi", to: "/cases?lane=red" },
  { icon: FileSearch, title: "Baca alasan", line: "Modus, data pemicu, dan berkas", to: "/cases?lane=red" },
  { icon: ClipboardCheck, title: "Catat keputusan", line: "Klarifikasi, audit, atau selesai", to: "/cases?lane=red" },
  { icon: FileText, title: "Paket bukti", line: "Minta rekam medis ke faskes", to: "/facilities" },
];
const LANE_ICON = { red: "!", yellow: "?", green: "✓" } as const;

/** How to use the system, what the colours and patterns mean, and every term, as cards to scan rather than text to read. */
export default function HelpPage() {
  const { hash } = useLocation();
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState<Set<string>>(new Set());
  useEffect(() => {
    if (hash) document.getElementById(decodeURIComponent(hash.slice(1)))?.scrollIntoView({ block: "start" });
  }, [hash]);
  const terms = useMemo(() => Object.entries(GLOSSARY).filter(([, entry]) =>
    !query.trim() || `${entry.term} ${entry.text}`.toLowerCase().includes(query.trim().toLowerCase())), [query]);
  return <>
    <section className="help-hero" aria-labelledby="help-title">
      <div className="help-hero-text">
        <span className="help-hero-kicker"><BookOpenText size={15} aria-hidden="true" />Panduan singkat</span>
        <h1 id="help-title">Bantuan</h1>
        <p>Lima langkah kerja, arti warna, modus kecurangan, dan istilah.</p>
        <nav className="help-jumps" aria-label="Bagian bantuan">
          <a href="#alur">Alur kerja</a><a href="#warna">Tingkat risiko</a><a href="#modus">Modus</a><a href="#istilah">Istilah</a>
        </nav>
      </div>
      <div className="help-hero-art" aria-hidden="true">
        <span className="art-card art-red"><b>!</b><i /><i /></span>
        <span className="art-card art-yellow"><b>?</b><i /><i /></span>
        <span className="art-card art-green"><b>✓</b><i /><i /></span>
        <span className="art-badge"><Calculator size={18} /></span>
      </div>
    </section>

    <section className="card help-section" id="alur" aria-labelledby="help-steps">
      <h2 id="help-steps">Alur kerja verifikator</h2>
      <ol className="help-stepper">{STEPS.map((step, index) => <li key={step.title}>
        <Link to={step.to} className="help-step">
          <span className="help-step-icon"><step.icon size={20} aria-hidden="true" /><em>{index + 1}</em></span>
          <strong>{step.title}</strong><span>{step.line}</span>
        </Link></li>)}</ol>
    </section>

    <section className="card help-section" id="warna" aria-labelledby="help-lanes">
      <h2 id="help-lanes">Tiga tingkat risiko</h2>
      <ul className="help-lanes">{(["red", "yellow", "green"] as const).map(lane => <li key={lane} className={`help-lane is-${lane}`}>
        <span className="help-lane-mark" aria-hidden="true">{LANE_ICON[lane]}</span>
        <strong>{LANES[lane].name}</strong><span>{LANES[lane].meaning}</span>
        <small>{LANES[lane].action}</small>
      </li>)}</ul>
    </section>

    <section className="card help-section" id="modus" aria-labelledby="help-patterns">
      <h2 id="help-patterns">Modus dan pemeriksaannya</h2>
      <div className="help-patterns">{Object.entries(FRAUD_PATTERNS).map(([code, pattern]) => {
        const card = PATTERN_CARD[code];
        const Icon = card?.icon ?? Search;
        const checks = INDICATOR_CODES.filter(check => PATTERN_OF[check] === code);
        return <article key={code} className="help-pattern" style={{ ["--pattern" as string]: PATTERN_COLORS[code] }}>
          <span className="help-pattern-icon"><Icon size={20} aria-hidden="true" /></span>
          <h3>{pattern.label}</h3>
          <p>{card?.line ?? pattern.hint}</p>
          <span className="help-pattern-count">{checks.length} pemeriksaan</span>
          <ul>{checks.map(check => <li key={check} title={indicatorDefinition(check) ?? undefined}>{indicatorLabel(check)}</li>)}</ul>
        </article>;
      })}</div>
    </section>

    <section className="card help-section" id="istilah" aria-labelledby="help-terms">
      <div className="help-terms-head"><h2 id="help-terms">Istilah</h2>
        <label className="help-search"><Search size={15} aria-hidden="true" />
          <input type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="Cari istilah" aria-label="Cari istilah" /></label></div>
      <dl className="help-terms">{terms.map(([id, entry]) => {
        const long = entry.text.length > 150 && !open.has(id) && hash !== `#istilah-${id}`;
        return <div key={id} id={`istilah-${id}`}>
          <dt>{entry.term}</dt><dd className={long ? "is-clamped" : undefined}>{entry.text}</dd>
          {long && <button type="button" className="help-more" onClick={() => setOpen(current => new Set(current).add(id))}>Selengkapnya</button>}
        </div>;
      })}</dl>
      {terms.length === 0 && <p className="fine-print">Tidak ada istilah yang cocok.</p>}
    </section>
  </>;
}
