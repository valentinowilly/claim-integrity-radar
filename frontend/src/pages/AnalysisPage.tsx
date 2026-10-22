import { useCallback } from "react";
import { CircleHelp, Info, Radar } from "lucide-react";
import { getAnalysis, getCases, type AnalysisResponse, type CasesResponse } from "../api/client";
import { EmptyState, ErrorState, formatNumber, LoadingState, PageHeading, SourceBadge } from "../components/DataStates";
import { useApiResource } from "../hooks/useApiResource";

interface AnalysisPayload {
  analysis: AnalysisResponse;
  cases: CasesResponse;
}

export default function AnalysisPage() {
  const load = useCallback(async (signal: AbortSignal): Promise<AnalysisPayload> => {
    const [analysis, cases] = await Promise.all([
      getAnalysis({}, signal),
      getCases({ page: 1, page_size: 100, sort_by: "risk_score", sort_order: "desc" }, signal),
    ]);
    return { analysis, cases };
  }, []);
  const { state, reload } = useApiResource(load);

  return (
    <>
      <PageHeading eyebrow="ANALISIS" title="Analisis Risiko" description="Indikator, cakupan data, alasan kecocokan, dan batas interpretasi dari API." action={state.status === "success" ? <SourceBadge source={state.data.analysis.data_source} /> : undefined} />
      {state.status === "loading" && <LoadingState label="Memuat indikator dan alasan dari API…" />}
      {state.status === "error" && <ErrorState message={state.message} httpStatus={state.httpStatus} onRetry={reload} />}
      {state.status === "success" && state.data.analysis.availability !== "available" && (
        <EmptyState title="Analisis belum tersedia" message="Sumber belum menyediakan hasil analisis untuk ditampilkan." />
      )}
      {state.status === "success" && state.data.analysis.availability === "available" && (
        <>
          <section className="analysis-overview-grid">
            <div className="metric-card"><div className="metric-card-top"><span>Record dipertimbangkan</span><span className="metric-icon"><Radar size={17} /></span></div><strong className="metric-value">{formatNumber(state.data.analysis.coverage.records_considered)}</strong><small>Dalam fixture sintetis aktif</small></div>
            <div className="metric-card"><div className="metric-card-top"><span>Record layak</span><span className="metric-icon"><Info size={17} /></span></div><strong className="metric-value">{formatNumber(state.data.analysis.coverage.records_eligible)}</strong><small>Layak untuk setidaknya satu indikator</small></div>
            <div className="metric-card"><div className="metric-card-top"><span>Indikator berjalan</span><span className="metric-icon"><CircleHelp size={17} /></span></div><strong className="metric-value">{formatNumber(state.data.analysis.indicators.length)}</strong><small>Rencana ditampilkan terpisah</small></div>
          </section>

          <section className="surface-panel section-block">
            <div className="panel-heading-row"><div><span className="eyebrow muted-eyebrow">AKTIF</span><h2>Indikator yang dijalankan</h2></div><span className="small-context">Jumlah dan definisi berasal dari API</span></div>
            {state.data.analysis.indicators.length === 0 ? <EmptyState title="Tidak ada indikator aktif" message="Respons API tidak memuat indikator yang dijalankan." /> : (
              <div className="analysis-indicator-list">
                {state.data.analysis.indicators.map((indicator) => {
                  const reasons = state.data.cases.items.flatMap(item => item.reasons.filter(reason => reason.indicator === indicator.code).map(reason => reason.summary));
                  const distinctReasons = [...new Set(reasons)];
                  return (
                    <article className="analysis-indicator-card" key={indicator.code}>
                      <div className="analysis-card-heading">
                        <div><span className="indicator-pill indicator-active">Berjalan</span><h3>{indicator.name}</h3><code>{indicator.code}</code></div>
                        <div className="analysis-count"><strong>{formatNumber(indicator.candidate_count)}</strong><span>kandidat</span></div>
                      </div>
                      <p className="definition-copy">{indicator.definition}</p>
                      <div className="analysis-facts"><span><strong>{formatNumber(indicator.candidate_group_count)}</strong> kelompok kandidat</span><span><strong>{formatNumber(indicator.eligible_count)}</strong> record layak</span></div>
                      <div className="reason-block"><strong>Alasan deteksi dari API</strong>
                        {distinctReasons.length ? <ul>{distinctReasons.map(reason => <li key={reason}>{reason}</li>)}</ul> : <p>Belum ada alasan kandidat untuk indikator ini pada cakupan aktif.</p>}
                      </div>
                      <div className="limitation-block"><strong>Batas interpretasi</strong><ul>{indicator.limitations.map(text => <li key={text}>{text}</li>)}</ul></div>
                    </article>
                  );
                })}
              </div>
            )}
          </section>

          <section className="surface-panel section-block">
            <div className="panel-heading-row"><div><span className="eyebrow muted-eyebrow">BELUM AKTIF</span><h2>Indikator yang masih direncanakan</h2></div><span className="planned-count">{formatNumber(state.data.analysis.planned_indicators.length)} rencana</span></div>
            {state.data.analysis.planned_indicators.length === 0 ? <EmptyState title="Tidak ada rencana tambahan" message="API tidak mengembalikan indikator rencana." /> : (
              <div className="planned-list">
                {state.data.analysis.planned_indicators.map(item => <article className="planned-row" key={item.code}><span className="planned-mark" /><div><strong>{item.name}</strong><code>{item.code}</code><p>{item.definition}</p></div><span className="indicator-pill indicator-planned">Rencana</span></article>)}
              </div>
            )}
          </section>

          <div className="notice-panel"><Info size={17} /><p>{state.data.analysis.limitations.join(" ")} Pola serupa adalah sinyal untuk ditinjau auditor, bukan bukti fraud.</p></div>
        </>
      )}
    </>
  );
}
