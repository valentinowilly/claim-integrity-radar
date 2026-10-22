import { useCallback } from "react";
import { ArrowUpRight, ClipboardCheck, FileSearch, Radar, ShieldCheck, type LucideIcon } from "lucide-react";
import { Link } from "react-router-dom";
import { getDashboardSummary } from "../api/client";
import { EmptyState, ErrorState, formatNumber, LoadingState, PageHeading, SourceBadge, indicatorLabel } from "../components/DataStates";
import { useApiResource } from "../hooks/useApiResource";

export default function OverviewPage() {
  const loadSummary = useCallback((signal: AbortSignal) => getDashboardSummary({}, signal), []);
  const { state, reload } = useApiResource(loadSummary);

  return (
    <>
      <PageHeading
        eyebrow="RINGKASAN WORKSPACE"
        title="Ruang kendali audit"
        description="Decision Support for Claims Audit. Ringkasan dihitung dari endpoint aktif dan selalu menampilkan sumber datanya."
        action={state.status === "success" ? <SourceBadge source={state.data.data_source} /> : undefined}
      />
      {state.status === "loading" && <LoadingState label="Mengambil ringkasan dashboard…" />}
      {state.status === "error" && <ErrorState message={state.message} httpStatus={state.httpStatus} onRetry={reload} />}
      {state.status === "success" && state.data.availability !== "available" && (
        <EmptyState title="Ringkasan belum tersedia" message={state.data.notice} />
      )}
      {state.status === "success" && state.data.availability === "available" && (
        <>
          <section className="welcome-panel data-welcome">
            <div className="welcome-copy">
              <span className="panel-kicker">CLAIM INTEGRITY RADAR</span>
              <h2>Temuan yang dapat dijelaskan,<br className="desktop-break" /> untuk mendukung tinjauan auditor.</h2>
              <p>{state.data.notice}</p>
              <Link className="text-link" to="/analysis">Lihat indikator aktif <ArrowUpRight size={15} /></Link>
            </div>
            <div className="welcome-visual" aria-hidden="true">
              <div className="radar-orbit orbit-one" /><div className="radar-orbit orbit-two" /><div className="radar-orbit orbit-three" />
              <div className="radar-center"><Radar size={27} strokeWidth={1.3} /></div>
            </div>
            <div className="panel-index">01 <span>/</span> 05</div>
          </section>

          <section className="metric-grid" aria-label="Ringkasan dari API">
            <MetricCard label="Record diproses" value={formatNumber(state.data.summary.claims_reviewed)} detail="Dalam sumber data aktif" icon={FileSearch} />
            <MetricCard label="Case unik di antrean" value={formatNumber(state.data.summary.cases_in_queue)} detail="Kandidat dari indikator aktif" icon={ClipboardCheck} />
            <MetricCard label="Level risiko" value="Belum ditetapkan" detail="Tidak ada distribusi risiko tervalidasi" icon={ShieldCheck} compact />
          </section>

          <section className="surface-panel section-block">
            <div className="panel-heading-row">
              <div><span className="eyebrow muted-eyebrow">HASIL ANALITIK</span><h2>Kandidat per indikator</h2></div>
              <Link className="inline-link" to="/analysis">Detail analisis <ArrowUpRight size={14} /></Link>
            </div>
            {state.data.summary.indicator_counts.length === 0 ? (
              <EmptyState title="Belum ada kandidat" message="API mengembalikan daftar indikator tanpa kandidat untuk cakupan ini." />
            ) : (
              <div className="indicator-summary-list">
                {state.data.summary.indicator_counts.map((item) => (
                  <div className="indicator-summary-row" key={item.indicator}>
                    <div className="indicator-summary-title"><span className="indicator-mark" /><strong>{indicatorLabel(item.indicator)}</strong></div>
                    <div className="indicator-summary-stats">
                      <span><strong>{formatNumber(item.candidate_groups)}</strong> kelompok</span>
                      <span><strong>{formatNumber(item.candidate_records)}</strong> kandidat</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>

          <section className="integrity-note">
            <div className="integrity-mark"><ShieldCheck size={19} /></div>
            <div><strong>Kandidat adalah sinyal, bukan kesimpulan.</strong><p>Hasil ini berasal dari data sintetis dan memerlukan konteks serta tinjauan auditor.</p></div>
            <Link className="integrity-action" to="/cases">Buka antrean <ArrowUpRight size={15} /></Link>
          </section>
        </>
      )}
    </>
  );
}

function MetricCard({ label, value, detail, icon: Icon, compact = false }: {
  label: string;
  value: string;
  detail: string;
  icon: LucideIcon;
  compact?: boolean;
}) {
  return (
    <article className="metric-card">
      <div className="metric-card-top"><span>{label}</span><span className="metric-icon"><Icon size={17} /></span></div>
      <strong className={compact ? "metric-compact" : "metric-value"}>{value}</strong>
      <small>{detail}</small>
    </article>
  );
}
