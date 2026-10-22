import { useCallback } from "react";
import { BadgeCheck, CircleHelp, Info } from "lucide-react";
import { getEvaluation } from "../api/client";
import { EmptyState, ErrorState, LoadingState, PageHeading, SourceBadge } from "../components/DataStates";
import { useApiResource } from "../hooks/useApiResource";

export default function EvaluationPage() {
  const load = useCallback((signal: AbortSignal) => getEvaluation(signal), []);
  const { state, reload } = useApiResource(load);

  return (
    <>
      <PageHeading eyebrow="VALIDASI" title="Evaluasi" description="Metrik performa hanya ditampilkan setelah tersedia label acuan dan protokol evaluasi yang tervalidasi." action={state.status === "success" ? <SourceBadge source={state.data.data_source} /> : undefined} />
      {state.status === "loading" && <LoadingState label="Memeriksa status evaluasi…" />}
      {state.status === "error" && <ErrorState message={state.message} httpStatus={state.httpStatus} onRetry={reload} />}
      {state.status === "success" && state.data.availability === "available" && state.data.evaluation && (
        <section className="surface-panel"><div className="panel-heading-row"><div><span className="eyebrow muted-eyebrow">HASIL EVALUASI</span><h2>Evaluasi tersedia</h2></div></div><pre className="evaluation-payload">{JSON.stringify(state.data.evaluation, null, 2)}</pre></section>
      )}
      {state.status === "success" && (state.data.availability !== "available" || state.data.evaluation === null) && (
        <>
          <section className="evaluation-status-card surface-panel">
            <div className="evaluation-status-icon"><BadgeCheck size={22} /></div>
            <div><span className="eyebrow muted-eyebrow">STATUS EVALUASI</span><h2>{state.data.availability === "insufficient_data" ? "Metrik belum tersedia" : "Evaluasi belum dijalankan"}</h2><p>{state.data.notice}</p></div>
            <span className="status-pill status-neutral">{state.data.availability}</span>
          </section>
          <section className="surface-panel section-block">
            <div className="panel-heading-row"><div><span className="eyebrow muted-eyebrow">PRASYARAT</span><h2>Yang dibutuhkan sebelum evaluasi</h2></div><span className="metric-icon"><CircleHelp size={17} /></span></div>
            {state.data.requirements_missing.length ? <ul className="requirements-list">{state.data.requirements_missing.map(item => <li key={item}>{item}</li>)}</ul> : <EmptyState title="Tidak ada prasyarat yang dilaporkan" message="Respons API belum memuat daftar prasyarat." />}
          </section>
          <div className="notice-panel"><Info size={17} /><p>Fixture sintetis digunakan untuk menguji alur perangkat lunak, bukan sebagai ground truth atau bukti kinerja sistem.</p></div>
        </>
      )}
    </>
  );
}
