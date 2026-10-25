import { useMemo, useState } from "react";
import { ChevronLeft, ChevronRight, Search } from "lucide-react";
import { EmptyState, formatNumber, indicatorLabel, PageHeading, SourceBadge } from "../components/DataStates";
import { RunCandidateLink, RunSelector, RunStateMessage } from "../components/PersistedRunWorkspace";
import { usePersistedRunSnapshot } from "../hooks/usePersistedRunSnapshot";
import type { IndicatorCode } from "../api/client";

export default function CasesPage() {
  const { state, selectRun, reload } = usePersistedRunSnapshot();
  const [search, setSearch] = useState("");
  const [indicator, setIndicator] = useState("");
  const [page, setPage] = useState(1);
  const pageSize = 10;
  const all = state.status === "success" && state.detail.result ? Object.values(state.detail.result.cases) : [];
  const filtered = useMemo(() => all.filter(item => (!indicator || item.indicators.includes(indicator))
    && (!search.trim() || item.case_id.toLowerCase().includes(search.trim().toLowerCase()))), [all, indicator, search]);
  const pageCount = Math.max(1, Math.ceil(filtered.length / pageSize));
  const visible = filtered.slice((Math.min(page, pageCount) - 1) * pageSize, Math.min(page, pageCount) * pageSize);
  return <>
    <PageHeading eyebrow="TINDAK LANJUT" title="Antrean Audit" description="Kandidat diambil dari satu AnalysisRun tersimpan. Daftar ini bukan ranking risiko dan status review terbaru tampil pada detail run/kasus." action={state.status === "success" && state.detail.result ? <SourceBadge source={state.detail.result.data_source}/> : undefined}/>
    {state.status !== "success" && <RunStateMessage state={state} retry={reload}/>}
    {state.status === "success" && <>
      <RunSelector runs={state.runs} detail={state.detail} onChange={runId => { setPage(1); selectRun(runId); }}/>
      {!state.detail.result ? <EmptyState title="Hasil run tidak tersedia" message="Tidak ada antrean legacy yang akan dipakai sebagai pengganti."/> : state.detail.result.availability !== "available" ? <EmptyState title="Antrean run tidak tersedia" message={`Status ketersediaan: ${state.detail.result.availability}. Tidak ada kandidat yang disimpulkan dari ketiadaan hasil.`}/> : <>
        <section className="queue-toolbar surface-panel"><div className="filter-controls">
          <label>Cari ID kasus<input aria-label="Cari ID kasus" value={search} onChange={event => { setSearch(event.target.value); setPage(1); }} placeholder="ID kasus pada snapshot"/></label>
          <label>Indikator pemicu<select aria-label="Filter indikator" value={indicator} onChange={event => { setIndicator(event.target.value as IndicatorCode | ""); setPage(1); }}><option value="">Semua indikator</option>{state.detail.result.indicators.map(item => <option key={item.code} value={item.code}>{item.name}</option>)}</select></label>
        </div></section>
        <section className="surface-panel queue-panel"><div className="queue-header"><div><span className="eyebrow muted-eyebrow">KANDIDAT SNAPSHOT</span><h2>{formatNumber(filtered.length)} kasus</h2></div><span className="queue-header-note">{state.detail.run.run_id}</span></div>
          {visible.length === 0 ? <EmptyState title="Tidak ada kandidat untuk filter ini" message="Filter kosong adalah hasil yang sah. Kasus yang tidak muncul tidak diberi lane green."/> : <><div className="table-scroll"><table className="case-table"><thead><tr><th>ID kasus</th><th>Indikator pemicu</th><th>Alasan ringkas</th><th>Skor aturan</th><th>Action lane</th><th/></tr></thead><tbody>{visible.map(item => {
            const lane = state.detail.result!.action_policy.cases[item.case_id];
            return <tr key={item.case_id}><td><RunCandidateLink runId={state.detail.run.run_id} caseId={item.case_id}>{item.case_id} <Search size={13}/></RunCandidateLink></td><td><div className="table-badges">{item.indicators.map(code => <span className="indicator-pill" key={code}>{indicatorLabel(code)}</span>)}</div></td><td className="reason-cell">{item.reasons[0]?.summary ?? "Alasan tidak tersedia pada snapshot."}</td><td>{item.risk_score === null ? "Tidak dapat dinilai" : `${item.risk_score.toFixed(3)} · ${item.score_status}`}</td><td>{lane?.lane ?? "Tidak disediakan"}</td><td><RunCandidateLink runId={state.detail.run.run_id} caseId={item.case_id}>Buka</RunCandidateLink></td></tr>;
          })}</tbody></table></div><div className="pagination-row"><span>Halaman {Math.min(page,pageCount)} dari {pageCount}</span><div><button className="button button-secondary" disabled={page <= 1} onClick={() => setPage(value => Math.max(1,value-1))}><ChevronLeft size={15}/>Sebelumnya</button><button className="button button-secondary" disabled={page >= pageCount} onClick={() => setPage(value => value + 1)}>Berikutnya<ChevronRight size={15}/></button></div></div></>}
        </section>
      </>}
    </>}
  </>;
}
