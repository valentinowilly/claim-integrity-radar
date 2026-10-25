import { ArrowUpRight, ClipboardCheck, Database, FileSearch, ShieldCheck } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { EmptyState, formatNumber, PageHeading, SourceBadge } from "../components/DataStates";
import { RunCandidateLink, RunSelector, RunStateMessage } from "../components/PersistedRunWorkspace";
import { usePersistedRunSnapshot } from "../hooks/usePersistedRunSnapshot";
import { useAuth } from "../auth/AuthContext";

export default function OverviewPage() {
  const { state, selectRun, reload } = usePersistedRunSnapshot();
  const { state: auth } = useAuth();
  const permissions = "session" in auth ? auth.session?.permissions ?? [] : [];
  return <>
    <PageHeading title="Ringkasan pemeriksaan" description="Ringkasan hanya dari satu AnalysisRun tersimpan; hasil tidak dihitung ulang saat halaman dibuka." action={state.status === "success" && state.detail.result ? <SourceBadge source={state.detail.result.data_source}/> : undefined} />
    {state.status === "forbidden" ? <section className="surface-panel section-block access-guidance" data-testid="overview-access-restricted">
      <div className="integrity-mark"><ShieldCheck size={20}/></div>
      <span className="eyebrow muted-eyebrow">AKSES TERBATAS</span>
      <h2>Hasil analisis tersedia untuk peran yang berwenang</h2>
      <p>Akun ini tidak dapat membaca snapshot analisis tersimpan. Hasil tetap terlindungi; halaman ini tidak menggantinya dengan ringkasan dari sumber lain.</p>
      {permissions.includes("batches:read") && <Link className="button button-secondary" to={`/workflow${window.location.search}`}><Database size={15}/>Buka Data Klaim</Link>}
    </section> : state.status !== "success" && <RunStateMessage state={state} retry={reload} />}
    {state.status === "success" && <>
      <RunSelector runs={state.runs} detail={state.detail} onChange={selectRun} />
      {!state.detail.result ? <EmptyState title="Hasil run tidak tersedia" message="Manifest run tersedia, tetapi server tidak menyimpan snapshot hasil." /> : state.detail.result.availability !== "available" ? <EmptyState title="Hasil run belum dapat disajikan" message={`Status ketersediaan: ${state.detail.result.availability}. Ringkasan operasional tidak dibentuk dari hasil yang tidak tersedia.`}/> : <>
        <p className="run-result-meta">{state.detail.notice}</p>
        <section className="metric-grid" aria-label="Ringkasan AnalysisRun tersimpan">
          <Metric label="Klaim dipertimbangkan" value={formatNumber(state.detail.result.records_considered)} icon={<FileSearch size={17} />} />
          <Metric label="Klaim memenuhi syarat" value={formatNumber(state.detail.result.records_eligible)} icon={<ClipboardCheck size={17} />} />
          <Metric label="Kandidat tersimpan" value={formatNumber(Object.keys(state.detail.result.cases).length)} icon={<ShieldCheck size={17} />} />
        </section>
        <section className="surface-panel section-block">
          <div className="panel-heading-row"><div><span className="eyebrow muted-eyebrow">CAKUPAN INDIKATOR</span><h2>Hasil pada snapshot terpilih</h2></div><Link className="inline-link" to={`/analysis?run_id=${encodeURIComponent(state.detail.run.run_id)}`}>Analisis run ini <ArrowUpRight size={14}/></Link></div>
          <div className="indicator-summary-list">{state.detail.result.indicators.map(item => <div className="indicator-summary-row" key={item.code}><div className="indicator-summary-title"><span className="indicator-mark"/><strong>{item.name}</strong></div><div className="indicator-summary-stats"><span><strong>{formatNumber(item.candidate_count)}</strong> kandidat</span><span><strong>{item.status}</strong>{item.search_truncated ? " · pencarian terpotong" : ""}</span></div></div>)}</div>
          {Object.keys(state.detail.result.cases).length === 0 ? <EmptyState title="Snapshot tidak memiliki kandidat" message="Tidak ada kandidat pada hasil run ini. Ketiadaan kandidat bukan penetapan bahwa klaim bebas risiko."/> : <div className="reason-block"><strong>Kandidat pada snapshot yang sama</strong><ul>{Object.values(state.detail.result.cases).slice(0, 5).map(item => <li key={item.case_id}><RunCandidateLink runId={state.detail.run.run_id} caseId={item.case_id}>{item.case_id} · {item.indicators.join(", ") || "alasan pemeriksaan tersedia"}</RunCandidateLink></li>)}</ul></div>}
        </section>
        <div className="notice-panel"><ShieldCheck size={17}/><p>Indeks aturan dan action lane, bila tersedia, bersifat provisional. Hasil sintetis bukan bukti fraud dan bukan validasi pada data JKN nyata.</p></div>
      </>}
    </>}
  </>;
}

function Metric({ label, value, icon }: { label: string; value: string; icon: ReactNode }) {
  return <article className="metric-card"><div className="metric-card-top"><span>{label}</span><span className="metric-icon">{icon}</span></div><strong className="metric-value">{value}</strong><small>Dari snapshot run tersimpan</small></article>;
}
