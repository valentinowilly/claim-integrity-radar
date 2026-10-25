import { Info } from "lucide-react";
import { EmptyState, formatNumber, PageHeading, SourceBadge } from "../components/DataStates";
import { RunSelector, RunStateMessage } from "../components/PersistedRunWorkspace";
import { usePersistedRunSnapshot } from "../hooks/usePersistedRunSnapshot";

const stateLabels: Record<string, string> = {
  triggered: "Ada sinyal", not_triggered: "Tidak terpicu pada penilaian tercakup",
  not_applicable: "Tidak berlaku", not_assessed: "Belum dinilai",
  complete: "Tercakup", partial: "Parsial", unavailable: "Tidak tersedia", not_assessable: "Belum dapat dinilai",
};

export default function AnalysisPage() {
  const { state, selectRun, reload } = usePersistedRunSnapshot();
  return <>
    <PageHeading eyebrow="ANALISIS" title="Analisis Risiko" description="Cakupan, hasil indikator, dan alasan dari snapshot AnalysisRun yang persisten." action={state.status === "success" && state.detail.result ? <SourceBadge source={state.detail.result.data_source}/> : undefined}/>
    {state.status !== "success" && <RunStateMessage state={state} retry={reload}/>}
    {state.status === "success" && <>
      <RunSelector runs={state.runs} detail={state.detail} onChange={selectRun}/>
      {!state.detail.result ? <EmptyState title="Hasil run tidak tersedia" message="Tidak ada snapshot persisten untuk run terpilih."/> : state.detail.result.availability !== "available" ? <EmptyState title="Hasil analisis tidak tersedia" message={`Status ketersediaan: ${state.detail.result.availability}. Tidak ada indikator yang dapat disajikan sebagai hasil operasional.`}/> : <>
        <section className="analysis-overview-grid">
          <Metric label="Record dipertimbangkan" value={formatNumber(state.detail.result.records_considered)}/>
          <Metric label="Record memenuhi syarat" value={formatNumber(state.detail.result.records_eligible)}/>
          <Metric label="Status eksekusi" value={state.detail.result.execution_status}/>
        </section>
        <section className="surface-panel section-block"><div className="panel-heading-row"><div><span className="eyebrow muted-eyebrow">ENAM PEMERIKSA</span><h2>Cakupan dan sinyal</h2></div><span className="small-context">Status hasil, cakupan, dan status run adalah dimensi terpisah.</span></div>
          {state.detail.result.indicators.length === 0 ? <EmptyState title="Tidak ada indikator pada hasil" message="Snapshot tidak menyertakan ringkasan pemeriksa."/> : <div className="analysis-indicator-list">{state.detail.result.indicators.map(indicator => {
            const coverage = state.detail.result!.indicator_coverage.find(item => item.indicator === indicator.code);
            const reasons = Object.values(state.detail.result!.cases).flatMap(item => item.reasons.filter(reason => reason.indicator === indicator.code).map(reason => reason.summary));
            const caseStates = Object.values(state.detail.result!.cases).flatMap(item => item.indicator_coverage.filter(row => row.indicator === indicator.code).map(row => row.status));
            const caseStateCounts = ["triggered", "not_triggered", "not_applicable", "not_assessed"].map(status => ({ status, count: caseStates.filter(item => item === status).length }));
            return <article className="analysis-indicator-card" key={indicator.code}><div className="analysis-card-heading"><div><span className="indicator-pill">{stateLabels[indicator.status] ?? indicator.status}</span><h3>{indicator.name}</h3><code>{indicator.code}</code></div><div className="analysis-count"><strong>{formatNumber(indicator.candidate_count)}</strong><span>kandidat</span></div></div>
              <p className="definition-copy">{indicator.definition}</p>
              <div className="analysis-facts"><span><strong>{formatNumber(indicator.eligible_count)}</strong> memenuhi syarat</span><span><strong>{formatNumber(coverage?.records_assessed)}</strong> dinilai</span><span><strong>{formatNumber(indicator.not_applicable_count)}</strong> tidak berlaku</span><span><strong>{formatNumber(indicator.unassessed_count)}</strong> belum dinilai</span><span><strong>{coverage ? stateLabels[coverage.status] ?? coverage.status : "Belum tersedia"}</strong> status cakupan</span></div>
              <p className="small-context">Status pada kandidat tersimpan: {caseStateCounts.map(item => `${stateLabels[item.status]} ${item.count}`).join(" · ")}. Ringkasan ini hanya meliputi kasus yang disertakan dalam snapshot.</p>
              {(indicator.search_truncated || coverage?.search_truncated) && <p className="notice-inline">Pencarian terpotong; record yang tidak muncul tidak dapat dianggap tidak terpicu.</p>}
              <div className="reason-block"><strong>Alasan kandidat tersimpan</strong>{reasons.length ? <ul>{[...new Set(reasons)].map(text => <li key={text}>{text}</li>)}</ul> : <p>Tidak ada alasan kandidat pada snapshot untuk indikator ini. Ini bukan bukti bahwa populasi bebas anomali.</p>}</div>
              <div className="limitation-block"><strong>Keterbatasan</strong><ul>{indicator.limitations.map(text => <li key={text}>{text}</li>)}</ul></div>
            </article>;
          })}</div>}
        </section>
        <section className="surface-panel section-block"><div className="panel-heading-row"><div><span className="eyebrow muted-eyebrow">PENILAIAN DAN PRIORITAS</span><h2>Informasi tersimpan</h2></div></div>
          <div className="analysis-facts"><span><strong>{state.detail.result.risk_scoring.version}</strong> versi skor</span><span><strong>{formatNumber(state.detail.result.risk_scoring.unassessable_case_count)}</strong> kasus tak dapat dinilai</span><span><strong>{state.detail.result.audit_priority.status}</strong> status prioritas fasilitas</span><span><strong>{state.detail.result.action_policy.policy_version}</strong> versi kebijakan demo</span><span><strong>{state.detail.result.action_policy.input_assessment_status}</strong> status masukan kebijakan</span></div>
          <p className="definition-copy">Skor adalah indeks aturan provisional, bukan probabilitas fraud. Risk level tidak disediakan sebagai nilai tervalidasi.</p>
          {state.detail.result.risk_scoring.limitations.length > 0 && <ul>{state.detail.result.risk_scoring.limitations.map(x => <li key={x}>{x}</li>)}</ul>}
          {state.detail.result.audit_priority.status !== "available" && <p className="notice-inline">Prioritas fasilitas tidak tersedia atau cakupannya parsial sesuai prasyarat yang dicatat server.</p>}
          <ul>{state.detail.result.audit_priority.eligibility_reasons.map(x => <li key={x}>{x}</li>)}</ul>
          <ul>{state.detail.result.action_policy.limitations.map(x => <li key={x}>{x}</li>)}</ul>
        </section>
        <div className="notice-panel"><Info size={17}/><p>{state.detail.notice} Action lane bila ada adalah saran demo provisional; review manusia tetap terpisah.</p></div>
      </>}
    </>}
  </>;
}
function Metric({ label, value }: { label: string; value: string }) { return <article className="metric-card"><div className="metric-card-top"><span>{label}</span></div><strong className="metric-value">{value}</strong><small>Dari hasil run tersimpan</small></article>; }
