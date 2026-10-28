import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { Activity, Database, Info, ListChecks, ShieldAlert } from "lucide-react";
import { EmptyState } from "../components/DataStates";
import { flaggedCaseCount, ruleFlaggedListedIds, type RunResult } from "../api/client";

type IndicatorSummary = RunResult["indicators"][number];
type IndicatorCoverage = RunResult["indicator_coverage"][number];
import {
  Callout, CoverageMetrics, FacilityPriorityNotice, LimitedSearchWarning, MoreInfo, PatternOnlyNotice, StatusPill, TechnicalDetails,
  formatCount, indicatorDefinition, indicatorLabel, statusText, unassessedReasonText,
} from "../components/Display";
import { MlRankingSection } from "../components/MlRanking";
import { RunSelector, RunStateMessage, RunTechnicalDetails, SourcePill } from "../components/PersistedRunWorkspace";
import { usePersistedRunSnapshot } from "../hooks/usePersistedRunSnapshot";

export default function AnalysisPage() {
  const { state, selectRun, reload } = usePersistedRunSnapshot();
  const result = state.status === "success" ? state.detail.result : null;
  const available = result && result.availability === "available" ? result : null;
  const applicable = available?.indicators.filter(item => item.status !== "not_applicable") ?? [];
  const notApplicable = available?.indicators.filter(item => item.status === "not_applicable") ?? [];
  return <>
    <header className="page-head">
      <div>
        <h1>Rincian <span className="muted">Analisis</span></h1>
        <p>Apa yang ditemukan setiap pemeriksaan, berapa banyak data yang dapat diperiksa, dan apa batasannya.</p>
      </div>
      {state.status === "success" && <div className="page-head-actions">
        {result && <SourcePill source={result.data_source} />}
        <RunSelector runs={state.runs} detail={state.detail} onChange={selectRun} />
      </div>}
    </header>
    {state.status !== "success" && <RunStateMessage state={state} retry={reload} />}
    {state.status === "success" && (!result ? <EmptyState title="Hasil analisis tidak tersedia" message="Analisis yang dipilih belum memiliki hasil tersimpan." />
      : !available ? <EmptyState title="Hasil analisis belum siap" message="Analisis ini belum selesai." />
      : <>
        <section className="dash-grid">
          <Kpi className="span-3" icon={<Database size={18} />} label="Klaim dianalisis" value={formatCount(available.records_considered)} foot="Seluruh klaim di data ini" />
          <Kpi className="span-3" icon={<ShieldAlert size={18} />} label="Klaim ditandai" value={formatCount(flaggedCaseCount(available))} foot="Oleh pemeriksaan aturan" />
          <Kpi className="span-3" icon={<ListChecks size={18} />} label="Pemeriksaan berlaku" value={`${formatCount(applicable.length)} dari ${formatCount(available.indicators.length)}`} foot="Sisanya dilewati karena datanya tidak ada" />
          <Kpi className="span-3" icon={<Activity size={18} />} label="Status analisis" value={available.execution_status === "partial" ? "Sebagian" : statusText(available.execution_status)} foot={available.execution_status === "partial" ? "Ada klaim yang belum dapat diperiksa" : "Semua pemeriksaan berjalan"} />
        </section>

        <section className="card">
          <div className="card-head"><div><h2>Hasil setiap pemeriksaan</h2><p>Jumlah klaim yang ditandai setiap pemeriksaan.</p></div></div>
          {available.indicators.length === 0 ? <EmptyState title="Tidak ada pemeriksaan" message="Belum ada ringkasan pemeriksaan untuk analisis ini." />
            : <div className="dash-grid analysis-indicator-list">
              {applicable.map(indicator => <IndicatorCard key={indicator.code} indicator={indicator}
                coverage={available.indicator_coverage.find(item => item.indicator === indicator.code)}
                reasons={available.result_view?.indicator_reason_summaries?.[indicator.code]
                  ?? [...new Set(Object.values(available.cases).flatMap(item => item.reasons.filter(reason => reason.indicator === indicator.code).map(reason => reason.summary)))]} />)}
            </div>}
          {notApplicable.length > 0 && <details className="tech-details" style={{ marginTop: 14 }}>
            <summary>Tidak berlaku untuk data ini ({formatCount(notApplicable.length)} pemeriksaan)</summary>
            <p className="fine-print">Dilewati karena datanya tidak tersedia, bukan karena tidak ada temuan.</p>
            <ul className="row-list">{notApplicable.map(item => <li key={item.code} className="row-item" data-indicator={item.code}>
              <span className="row-main"><strong>{indicatorLabel(item.code)}</strong><span>{indicatorDefinition(item.code) ?? item.name}</span></span>
              <StatusPill value={item.status} />
            </li>)}</ul>
          </details>}
        </section>

        {available.ml_anomaly && <MlRankingSection runId={state.detail.run.run_id} ml={available.ml_anomaly} ruleCaseIds={ruleFlaggedListedIds(available)} />}

        <section className="card">
          <div className="card-head"><div><h2>Skor aturan dan saran tindak lanjut</h2><p>Cara sistem mengurutkan klaim untuk ditinjau.</p></div></div>
          {available.facility_groups?.status === "available"
            ? <Callout tone="info" title="Urutan per faskes">
                <p>Klaim juga dikelompokkan per kelompok faskes (wilayah, kepemilikan, jenis, dan kelas) dan diurutkan di halaman{" "}
                  <Link to={`/facilities?run_id=${encodeURIComponent(state.detail.run.run_id)}`}>Faskes</Link>.</p>
              </Callout>
            : <FacilityPriorityNotice status={available.audit_priority.status} reasons={available.audit_priority.eligibility_reasons} />}
          <div className="stack" style={{ marginTop: 12 }}>
            <p><strong>Skor aturan</strong> adalah gabungan sementara dari pemeriksaan aturan untuk mengurutkan tinjauan, bukan peluang kecurangan.
              {" "}{formatCount(available.risk_scoring.unassessable_case_count)} klaim belum dapat diberi skor karena tidak ada pemeriksaan yang dapat menilainya.
              {available.risk_scoring.minimum_assessed_indicators !== undefined && ` Skor tidak dihitung untuk ${formatCount(available.risk_scoring.insufficient_indicator_case_count ?? 0)} klaim karena pemeriksaan yang berlaku kurang dari ${available.risk_scoring.minimum_assessed_indicators}.`}</p>
            <p><strong>Saran tindak lanjut</strong> {available.action_policy.input_assessment_status === "assessed"
              ? "tersedia untuk semua klaim yang ditandai."
              : available.action_policy.input_assessment_status === "partial"
                ? "hanya diberikan untuk klaim yang pemeriksaannya lengkap."
                : `belum tersedia (${statusText(available.action_policy.input_assessment_status).toLowerCase()}).`}</p>
          </div>
          <MoreInfo title="Keterbatasan skor dan saran" items={[...available.risk_scoring.limitations, ...available.action_policy.limitations]} />
          <TechnicalDetails items={[
            { label: "Versi skor aturan", value: available.risk_scoring.version },
            { label: "Versi urutan prioritas", value: `${available.audit_priority.priority_version} / ${available.audit_priority.status}` },
            { label: "Versi aturan saran", value: `${available.action_policy.policy_version} / ${available.action_policy.input_assessment_status}` },
          ]} />
        </section>
        <AnalysisQuality result={available} />
        <div className="notice-panel"><Info size={17} /><p>Saran tindak lanjut hanya panduan awal; keputusan tetap di tangan petugas.</p></div>
        <RunTechnicalDetails detail={state.detail} />
      </>)}
  </>;
}

function IndicatorCard({ indicator, coverage, reasons }: { indicator: IndicatorSummary; coverage: IndicatorCoverage | undefined; reasons: string[] }) {
  const truncated = indicator.search_truncated || Boolean(coverage?.search_truncated);
  const reasonCounts = Object.entries(coverage?.unassessed_reason_counts ?? {}).sort(([, a], [, b]) => b - a);
  return <article className="reason-card analysis-indicator-card span-6" data-indicator={indicator.code}>
    <div className="card-head" style={{ marginBottom: 0 }}>
      <div><h3>{indicatorLabel(indicator.code)}</h3><p>{indicatorDefinition(indicator.code) ?? indicator.name}</p></div>
      <StatusPill value={indicator.status} />
    </div>
    <PatternOnlyNotice evidence={indicator.interpretation?.billing_status_evidence} />
    <CoverageMetrics candidates={indicator.candidate_count} assessed={coverage?.records_assessed ?? indicator.eligible_count} notAssessed={indicator.unassessed_count} notApplicable={indicator.not_applicable_count} truncated={truncated} />
    {truncated && <LimitedSearchWarning indicator={indicator.code} />}
    {!truncated && indicator.unassessed_count > 0 && <p className="fine-print">{formatCount(indicator.unassessed_count)} klaim tidak dapat diperiksa oleh pemeriksaan ini karena datanya tidak lengkap.</p>}
    {indicator.unassessed_count > 0 && reasonCounts.length > 0 && <ul className="unassessed-reasons" aria-label={`Alasan klaim tidak diperiksa oleh ${indicatorLabel(indicator.code)}`}>
      {reasonCounts.map(([code, count]) => <li key={code}><strong>{formatCount(count)}</strong> {unassessedReasonText(code)}</li>)}
    </ul>}
    <MoreInfo title="Catatan teknis temuan" items={reasons.slice(0, 5)} />
    <MoreInfo title="Keterbatasan pemeriksaan" items={[indicator.definition, ...indicator.limitations]} />
    <TechnicalDetails items={[
      { label: "Kode pemeriksaan", value: indicator.code },
      { label: "Kelompok klaim", value: formatCount(indicator.candidate_group_count) },
      { label: "Cakupan pemeriksaan", value: coverage?.status ?? indicator.status },
    ]} />
  </article>;
}

function Kpi({ className, icon, label, value, foot }: { className: string; icon: ReactNode; label: string; value: string; foot: string }) {
  return <article className={`card kpi ${className}`}>
    <div className="kpi-top"><span>{label}</span><span className="kpi-icon">{icon}</span></div>
    <strong className="kpi-value">{value}</strong>
    <span className="kpi-foot">{foot}</span>
  </article>;
}

/** Is the AI still working on familiar data, and is risk spread evenly across regions and facility types? */
function AnalysisQuality({ result }: { result: RunResult }) {
  const ml = result.ml_anomaly;
  const observed = ml?.status === "available" ? ml.share_above_training_p99 : undefined;
  const ratio = observed !== undefined ? observed / 0.01 : null;
  const stable = ratio !== null && ratio >= 0.5 && ratio <= 2;
  const fairness = result.facility_groups?.fairness;
  const outliers = (fairness?.dimensions ?? []).flatMap(dimension => dimension.rows
    .filter(row => (row.ratio_to_overall ?? 0) > 2 || ((row.ratio_to_overall ?? 1) < 0.5 && row.claims >= 300))
    .map(row => ({ title: dimension.title, label: row.label, ratio: row.ratio_to_overall ?? 0 })));
  if (ratio === null && !fairness) return null;
  return <section className="card" aria-label="Mutu analisis" data-testid="analysis-quality">
    <div className="card-head"><div><h2>Mutu analisis</h2><p>Pemantauan model AI dan pemerataan penandaan antarwilayah.</p></div></div>
    <div className="quality-rows">
      {ratio !== null && <div className="quality-row">
        <span className={`status-pill tone-${stable ? "good" : "warn"}`}>{stable ? "Stabil" : "Perlu dicek"}</span>
        <div><strong>Model AI</strong>
          <p>{stable
            ? "Pola klaim pada analisis ini masih serupa dengan data yang dipakai melatih model."
            : ratio < 0.5
              ? "Klaim yang dinilai sangat tidak biasa lebih sedikit dari biasanya; pola data mungkin berbeda dari data latih."
              : "Klaim yang dinilai sangat tidak biasa lebih banyak dari biasanya; pola data mungkin berubah dan model perlu ditinjau."}</p></div>
      </div>}
      {fairness && <div className="quality-row">
        <span className={`status-pill tone-${outliers.length ? "warn" : "good"}`}>{outliers.length ? `${formatCount(outliers.length)} perlu ditelaah` : "Merata"}</span>
        <div><strong>Pemerataan antarwilayah dan jenis faskes</strong>
          <p>{outliers.length
            ? `Porsi klaim berisiko jauh berbeda dari rata-rata pada: ${outliers.slice(0, 4).map(item => `${item.label} (${item.ratio.toLocaleString("id-ID", { maximumFractionDigits: 1 })}×)`).join(", ")}. Pastikan perbedaannya karena pola klaim, bukan karena data yang tidak lengkap.`
            : "Tidak ada wilayah atau jenis faskes yang ditandai jauh lebih sering dari rata-rata."}</p></div>
      </div>}
    </div>
  </section>;
}

