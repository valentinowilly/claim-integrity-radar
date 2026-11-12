import { useEffect } from "react";
import { useLocation } from "react-router-dom";
import { FRAUD_PATTERNS, INDICATOR_CODES, LANES, LaneDot, indicatorDefinition, indicatorLabel } from "../components/Display";
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

const STEPS = [
  { title: "Buka Beranda", text: "Lihat jumlah klaim risiko tinggi dan nilai tagihannya. Tekan “Dari mana Rp…?” untuk melihat asal angkanya." },
  { title: "Periksa klaim di Antrean Tinjauan", text: "Mulai dari risiko tinggi. Urutkan “Tagihan terbesar” bila ingin mendahulukan nilai terbesar." },
  { title: "Baca alasan dan bukti", text: "Setiap klaim menunjukkan modus, data yang memicunya, berkas faskes, dan catatan klinis. AI pembaca dokumen bisa diminta membaca catatan." },
  { title: "Catat keputusan", text: "Pilih tindakan (sedang ditinjau, minta klarifikasi, masuk audit, selesai), lalu catat apakah klaim memang bermasalah." },
  { title: "Tindak lanjuti faskes", text: "Di menu Faskes, buat paket bukti untuk meminta rekam medis klaim sampel dari kelompok faskes yang terindikasi." },
];

/** How to use the system, what the colours and patterns mean, and every term in plain words. */
export default function HelpPage() {
  const { hash } = useLocation();
  useEffect(() => {
    if (hash) document.getElementById(decodeURIComponent(hash.slice(1)))?.scrollIntoView({ block: "start" });
  }, [hash]);
  return <>
    <header className="page-head"><div><h1>Bantuan</h1><p>Cara memakai sistem ini, arti warna dan modus, serta penjelasan istilah.</p></div></header>
    <div className="stack help-page" style={{ gap: 18 }}>
      <section className="card" aria-labelledby="help-steps">
        <div className="card-head"><div><h2 id="help-steps">Alur kerja verifikator</h2><p>Lima langkah dari angka di Beranda sampai keputusan.</p></div></div>
        <ol className="help-steps">{STEPS.map((step, index) => <li key={step.title}>
          <span className="verdict-num">{index + 1}</span><div><strong>{step.title}</strong><p>{step.text}</p></div></li>)}</ol>
      </section>

      <section className="card" aria-labelledby="help-lanes">
        <div className="card-head"><div><h2 id="help-lanes">Tiga tingkat risiko</h2><p>Tingkat risiko menentukan urutan pemeriksaan, bukan kesimpulan kecurangan.</p></div></div>
        <ul className="help-lanes">{(["red", "yellow", "green"] as const).map(lane => <li key={lane}>
          <strong><LaneDot lane={lane} />{LANES[lane].name}</strong><span>{LANES[lane].meaning}. {LANES[lane].action}.</span></li>)}</ul>
      </section>

      <section className="card" aria-labelledby="help-patterns">
        <div className="card-head"><div><h2 id="help-patterns">Modus dan pemeriksaannya</h2><p>Setiap pemeriksaan mencari satu modus. Satu klaim bisa punya lebih dari satu modus.</p></div></div>
        <div className="help-patterns">{Object.entries(FRAUD_PATTERNS).map(([code, pattern]) => <article key={code}>
          <h3>{pattern.label}</h3><p>{pattern.hint}.</p>
          <ul>{INDICATOR_CODES.filter(check => PATTERN_OF[check] === code).map(check => <li key={check}>
            <strong>{indicatorLabel(check)}</strong>{indicatorDefinition(check) ? `: ${indicatorDefinition(check)}` : ""}</li>)}</ul>
        </article>)}</div>
      </section>

      <section className="card" aria-labelledby="help-terms">
        <div className="card-head"><div><h2 id="help-terms">Istilah</h2><p>Kata yang bergaris titik di layar bisa diketuk untuk melihat artinya.</p></div></div>
        <dl className="help-terms">{Object.entries(GLOSSARY).map(([id, entry]) => <div key={id} id={`istilah-${id}`}>
          <dt>{entry.term}</dt><dd>{entry.text}</dd></div>)}</dl>
      </section>
    </div>
  </>;
}
