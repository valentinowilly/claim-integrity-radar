import { useCallback } from "react";
import { ArrowUpRight, ClipboardCheck, FileSearch, ShieldCheck, type LucideIcon } from "lucide-react";
import { Link } from "react-router-dom";
import { getDashboardSummary } from "../api/client";
import {
  EmptyState,
  ErrorState,
  formatNumber,
  LoadingState,
  PageHeading,
  indicatorLabel,
} from "../components/DataStates";
import { useApiResource } from "../hooks/useApiResource";
import { useAuth } from "../auth/AuthContext";

export default function OverviewPage() {
  const loadSummary = useCallback((signal: AbortSignal) => getDashboardSummary({}, signal), []);
  const { state, reload } = useApiResource(loadSummary);
  const { state: auth } = useAuth();
  const permissions = new Set("session" in auth ? (auth.session?.permissions ?? []) : []);
  const canReadAnalysis = permissions.has("analytics:read");
  const canReadCases = permissions.has("cases:read");

  return (
    <>
      <PageHeading
        title="Ringkasan pemeriksaan"
        description="Tinjau indikator aktif dan kandidat klaim yang perlu diperiksa lebih lanjut."
      />
      {state.status === "loading" && <LoadingState label="Mengambil ringkasan dashboard…" />}
      {state.status === "error" && (
        <ErrorState message={state.message} httpStatus={state.httpStatus} onRetry={reload} />
      )}
      {state.status === "success" && state.data.availability !== "available" && (
        <EmptyState title="Ringkasan belum tersedia" message={state.data.notice} />
      )}
      {state.status === "success" && state.data.availability === "available" && (
        <>
          <section className="metric-grid" aria-label="Ringkasan dari API">
            <MetricCard
              label="Klaim diperiksa"
              value={formatNumber(state.data.summary.claims_reviewed)}
              detail="Berdasarkan sumber data aktif"
              icon={FileSearch}
            />
            <MetricCard
              label="Kasus unik di antrean"
              value={formatNumber(state.data.summary.cases_in_queue)}
              detail="Kandidat dari indikator aktif"
              icon={ClipboardCheck}
            />
            <MetricCard
              label="Level risiko"
              value="Belum ditetapkan"
              detail="Distribusi risiko belum tersedia"
              icon={ShieldCheck}
              compact
            />
          </section>

          <section className="surface-panel section-block">
            <div className="panel-heading-row">
              <div>
                <span className="eyebrow muted-eyebrow">HASIL ANALITIK</span>
                <h2>Kandidat berdasarkan indikator</h2>
              </div>
              {canReadAnalysis && (
                <Link className="inline-link" to="/analysis">
                  Detail analisis <ArrowUpRight size={14} />
                </Link>
              )}
            </div>
            {state.data.summary.indicator_counts.length === 0 ? (
              <EmptyState
                title="Belum ada kandidat"
                message="API mengembalikan daftar indikator tanpa kandidat untuk cakupan ini."
              />
            ) : (
              <div className="indicator-summary-list">
                {state.data.summary.indicator_counts.map((item) => (
                  <div className="indicator-summary-row" key={item.indicator}>
                    <div className="indicator-summary-title">
                      <span className="indicator-mark" />
                      <strong>{indicatorLabel(item.indicator)}</strong>
                    </div>
                    <div className="indicator-summary-stats">
                      <span>
                        <strong>{formatNumber(item.candidate_groups)}</strong> kelompok
                      </span>
                      <span>
                        <strong>{formatNumber(item.candidate_records)}</strong> kandidat
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>

          <section className="integrity-note">
            <div className="integrity-mark">
              <ShieldCheck size={19} />
            </div>
            <div>
              <strong>Kandidat adalah sinyal, bukan kesimpulan.</strong>
              <p>Setiap temuan memerlukan konteks serta tinjauan auditor.</p>
            </div>
            {canReadCases && (
              <Link className="integrity-action" to="/cases">
                Buka antrean <ArrowUpRight size={15} />
              </Link>
            )}
          </section>
        </>
      )}
    </>
  );
}

function MetricCard({
  label,
  value,
  detail,
  icon: Icon,
  compact = false,
}: {
  label: string;
  value: string;
  detail: string;
  icon: LucideIcon;
  compact?: boolean;
}) {
  return (
    <article className="metric-card">
      <div className="metric-card-top">
        <span>{label}</span>
        <span className="metric-icon">
          <Icon size={17} />
        </span>
      </div>
      <strong className={compact ? "metric-compact" : "metric-value"}>{value}</strong>
      <small>{detail}</small>
    </article>
  );
}
