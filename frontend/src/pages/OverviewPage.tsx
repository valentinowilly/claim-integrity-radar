import { useEffect, useState } from "react";
import {
  ArrowRight, ArrowUpRight, BarChart3, Building2, CalendarDays, ClipboardCheck, FileStack, FileText, ShieldAlert, Sparkles,
  TriangleAlert, Upload, Wallet,
} from "lucide-react";
import { Link } from "react-router-dom";
import { Bar, BarChart, Cell, LabelList, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import {
  flaggedCaseCount, getRunReviews, getRunTrend, runReviewStatusLabels, ruleFlaggedListedIds,
  type FacilityGroup, type RunResult, type RunReviewStatus, type RunReviewSummaryItem, type RunTrendItem,
} from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { CountUp, LEVELS, LaneDot, formatCount, formatRupiah, mlFeatureLabel, shortRef } from "../components/Display";
import { RunCandidateLink, RunSelector, RunStateMessage, RunTechnicalDetails, SourcePill } from "../components/PersistedRunWorkspace";
import { KpiCard } from "../components/KpiCard";
import { TodayBrief } from "../components/TodayBrief";
import { usePersistedRunSnapshot } from "../hooks/usePersistedRunSnapshot";
import { useThemeColors } from "../theme/theme";

// Colour tokens, resolved per theme for the charts.
const STATUS_TOKENS = {
  not_started: "--border-medium", in_review: "--chart-6", awaiting_evidence: "--chart-4", escalated: "--chart-5", closed: "--chart-1",
} as const;
const CHART_TOKENS = { peak: "--chart-1", bar: "--chart-3", axis: "--text-muted", axisFaint: "--text-faint", onPeak: "--surface-bg",
  tooltipBg: "--surface-bg", tooltipBorder: "--border-subtle", tooltipText: "--text-primary" } as const;
const TODAY = new Intl.DateTimeFormat("id-ID", { weekday: "long", day: "numeric", month: "long", year: "numeric" });

/** The selected analysis and the ones before it (oldest first), so comparisons never use a newer analysis. */
function historyUpTo(trend: RunTrendItem[] | null, runId: string): RunTrendItem[] {
  if (!trend) return [];
  const index = trend.findIndex(item => item.run_id === runId);
  return index < 0 ? [] : trend.slice(0, index + 1);
}

function greeting(): string {
  const hour = new Date().getHours();
  if (hour < 11) return "Selamat pagi";
  if (hour < 15) return "Selamat siang";
  if (hour < 19) return "Selamat sore";
  return "Selamat malam";
}

export default function OverviewPage() {
  const { state, selectRun, reload } = usePersistedRunSnapshot();
  const { state: auth } = useAuth();
  const permissions = "session" in auth ? auth.session?.permissions ?? [] : [];
  const username = "session" in auth ? auth.session?.user.username ?? "" : "";
  const canReadReviews = permissions.includes("review:read");
  const result = state.status === "success" ? state.detail.result : null;
  const runId = state.status === "success" ? state.detail.run.run_id : "";
  const available = Boolean(result && result.availability === "available");

  // Review progress comes from its own small read, never from the full result.
  const [reviews, setReviews] = useState<{ runId: string; items: RunReviewSummaryItem[] } | null>(null);
  // Headline numbers of recent analyses, for the comparisons and small trend lines.
  const [trend, setTrend] = useState<RunTrendItem[] | null>(null);
  useEffect(() => {
    if (!runId) return;
    const controller = new AbortController();
    getRunTrend(8, controller.signal).then(response => setTrend(response.items)).catch(() => setTrend(null));
    return () => controller.abort();
  }, [runId]);
  useEffect(() => {
    if (!runId || !available) return;
    const controller = new AbortController();
    if (canReadReviews)
      getRunReviews(runId, controller.signal).then(response => setReviews({ runId, items: response.items })).catch(() => undefined);
    return () => controller.abort();
  }, [runId, available, canReadReviews]);

  return <>
    <header className="page-head">
      <div>
        <span className="page-eyebrow"><CalendarDays size={14} aria-hidden="true" />{TODAY.format(new Date())}</span>
        <h1>Prioritas <span className="muted">hari ini</span></h1>
        <p>{greeting()}, {username}. {state.status === "empty" ? "Belum ada data klaim yang dianalisis." : "Berikut klaim dan faskes yang paling perlu diperiksa hari ini."}</p>
      </div>
      {state.status === "success" && <div className="page-head-actions">
        {result && <SourcePill source={result.data_source} />}
        <RunSelector runs={state.runs} detail={state.detail} onChange={selectRun} />
      </div>}
    </header>
    {state.status === "empty" ? <FirstRunGuide canUpload={permissions.includes("batches:write")} />
      : state.status === "loading" ? <DashboardSkeleton />
      : state.status !== "success" && <RunStateMessage state={state} retry={reload} />}
    {state.status === "success" && result && available && <Dashboard
      result={result}
      runId={runId}
      reviews={reviews && reviews.runId === runId ? reviews.items : null}
      history={historyUpTo(trend, runId)}
      createdAt={state.detail.run.created_at}
    />}
    {state.status === "success" && (!result || !available) && <div className="card">
      <p className="fine-print">Analisis ini belum memiliki hasil. Pilih analisis lain atau jalankan analisis baru di menu Data & Analisis.</p>
    </div>}
    {state.status === "success" && <RunTechnicalDetails detail={state.detail} />}
  </>;
}

function Dashboard({ result, runId, reviews, history, createdAt }: {
  result: RunResult; runId: string; reviews: RunReviewSummaryItem[] | null; history: RunTrendItem[]; createdAt: string;
}) {
  const statusColors = useThemeColors(STATUS_TOKENS);
  const chart = useThemeColors(CHART_TOKENS);
  const runQuery = `?run_id=${encodeURIComponent(runId)}`;
  const lanes = result.action_policy.lane_counts ?? {};
  const red = lanes.red ?? 0;
  const yellow = lanes.yellow ?? 0;
  const green = lanes.green ?? 0;
  const flagged = flaggedCaseCount(result);
  const groups = result.facility_groups;
  const ml = result.ml_anomaly;
  const ruleIds = ruleFlaggedListedIds(result);
  const aiOnly = (ml?.items ?? []).filter(item => !ruleIds.has(item.case_id));
  // The officers' verdicts: share of decided claims they found worth following up.
  const outcomes = (reviews ?? []).map(item => item.review_outcome);
  const confirmed = outcomes.filter(outcome => outcome === "signal_supported").length;
  const decided = confirmed + outcomes.filter(outcome => outcome === "signal_not_supported").length;
  // High-risk claims the AI itself rates above the policy's high-risk threshold (not every high-risk claim:
  // two rule findings alone also make a claim high risk).
  const aiRedMin = Number((result.action_policy as { configuration?: { ml_red_min?: number | null } }).configuration?.ml_red_min ?? 0.95);
  const aiConfirmedRed = Object.entries(result.action_policy.cases).filter(([caseId, item]) => {
    if (item.lane !== "red") return false;
    const score = result.cases[caseId]?.ml_anomaly;
    const percentile = score ? score.reference_percentile ?? score.anomaly_percentile : null;
    return typeof percentile === "number" && percentile >= aiRedMin;
  }).length;
  // Until the user picks one, the chart shows high risk, or medium risk when there is no high-risk claim.
  const [chartChoice, setChartLane] = useState<"red" | "yellow" | null>(null);
  const chartLane = chartChoice ?? (red > 0 ? "red" : "yellow");

  let reviewed = 0;
  const statusCounts: Record<string, number> = { in_review: 0, awaiting_evidence: 0, escalated: 0, closed: 0 };
  for (const item of reviews ?? []) {
    if (item.review_status === "pending_review") continue;
    statusCounts[item.review_status] = (statusCounts[item.review_status] ?? 0) + 1;
    reviewed += 1;
  }
  const donut = [{ key: "not_started", name: "Belum ditinjau", value: Math.max(0, flagged - reviewed) },
    ...Object.entries(statusCounts).map(([key, value]) => ({ key, name: runReviewStatusLabels[key as RunReviewStatus], value }))]
    .filter(item => item.value > 0);

  const bars = [...(groups?.groups ?? [])]
    .sort((a, b) => b.lane_counts[chartLane] - a.lane_counts[chartLane]).slice(0, 6)
    .map(group => ({ name: `#${group.rank}`, title: group.title, value: group.lane_counts[chartLane] }));
  const peak = Math.max(0, ...bars.map(bar => bar.value));

  // Each comparison ends with this analysis; without a stored history only this analysis's number is known.
  const series = (pick: (item: RunTrendItem) => number | null | undefined, current: number) =>
    history.length ? [...history.slice(0, -1).map(item => pick(item) ?? null), current] : [current];
  const exposure = groups?.exposure?.status === "available" ? groups.exposure : null;

  return <>
    <TodayBrief result={result} runQuery={runQuery} createdAt={createdAt} history={history}
      unreviewed={reviews === null ? null : Math.max(0, flagged - reviewed)} />
    <section className="kpi-strip" aria-label="Ringkasan angka">
      <KpiCard icon={FileStack} label="Klaim dianalisis" value={result.records_considered}
        history={series(item => item.records_considered, result.records_considered)}
        footer={<Link className="kpi2-sub" to={`/cases${runQuery}&lane=green`} data-testid="lane-card-green">
          <LaneDot lane="green" />{formatCount(green)} risiko rendah, proses seperti biasa</Link>} />
      <KpiCard icon={ShieldAlert} label="Risiko tinggi" value={red} tone="red" direction="up-is-bad"
        history={series(item => item.lane_counts?.red, red)} to={`/cases${runQuery}&lane=red`} testId="kpi-red" />
      <KpiCard icon={TriangleAlert} label="Risiko sedang" value={yellow} tone="yellow" direction="up-is-bad"
        history={series(item => item.lane_counts?.yellow, yellow)} to={`/cases${runQuery}&lane=yellow`} testId="kpi-yellow" />
      {exposure ? <KpiCard icon={Wallet} label="Nilai tagihan perlu diverifikasi ulang" value={exposure.billed_high_or_medium}
        format={formatRupiah} direction="up-is-bad" history={series(item => item.billed_high_or_medium, exposure.billed_high_or_medium)}
        footer={<span className="kpi2-sub" data-testid="hero-amount">Klaim risiko tinggi dan sedang; bukan nilai kerugian</span>} />
        : <KpiCard icon={Sparkles} label="Temuan tambahan AI" value={aiOnly.length} history={[aiOnly.length]}
          to={`/cases${runQuery}&lane=ai`} />}
    </section>

    <section className="dash-grid">
      <div className="span-4 stack" style={{ gap: 18 }}>
        <Link className="hero-card" to={`/cases${runQuery}&lane=red`}>
          <span className="hero-label">Perlu tindakan</span>
          <span className="hero-num"><CountUp value={red + yellow} /> <small>klaim</small></span>
          <span className="hero-split">
            <span data-testid="lane-card-red"><LaneDot lane="red" />Risiko tinggi {formatCount(red)}</span>
            <span data-testid="lane-card-yellow"><LaneDot lane="yellow" />Risiko sedang {formatCount(yellow)}</span>
          </span>
          <LaneShare red={red} yellow={yellow} green={green} />
          <span className="hero-cta">Buka antrean <ArrowRight size={13} style={{ verticalAlign: "-2px" }} /></span>
        </Link>
      </div>

      <article className="card span-5">
        <div className="card-head">
          <div><h2><BarChart3 size={16} className="head-icon" aria-hidden="true" />Klaim per kelompok faskes</h2><p>Enam kelompok faskes dengan klaim risiko {chartLane === "red" ? "tinggi" : "sedang"} terbanyak.</p></div>
          <div className="segmented-pill" role="group" aria-label="Pilih tingkat risiko grafik">
            <button type="button" aria-pressed={chartLane === "red"} onClick={() => setChartLane("red")}>Tinggi</button>
            <button type="button" aria-pressed={chartLane === "yellow"} onClick={() => setChartLane("yellow")}>Sedang</button>
          </div>
        </div>
        {bars.length === 0 || peak === 0 ? <div className="detail-placeholder" style={{ minHeight: 230 }}><strong>Tidak ada klaim risiko {chartLane === "red" ? "tinggi" : "sedang"}</strong><span>{bars.length === 0 ? "Kelompok faskes belum tersedia untuk analisis ini." : `Tidak ada kelompok faskes dengan klaim risiko ${chartLane === "red" ? "tinggi" : "sedang"} pada analisis ini.`}</span></div> : <div className="chart-box" style={{ height: 250 }}
          role="img" aria-label={bars.map(bar => `${bar.title}: ${bar.value}`).join(", ")}>
          <ResponsiveContainer>
            <BarChart data={bars} margin={{ top: 28, right: 4, bottom: 0, left: -24 }}>
              <XAxis dataKey="name" tick={{ fontSize: 12, fill: chart.axis }} axisLine={false} tickLine={false} />
              <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: chart.axisFaint }} axisLine={false} tickLine={false} />
              <Tooltip cursor={false} formatter={(value: number) => [formatCount(value), "klaim"]} {...tooltipStyle(chart)}
                labelFormatter={(_label, payload) => payload?.[0]?.payload?.title ?? ""} />
              <Bar isAnimationActive animationDuration={650} dataKey="value" radius={[999, 999, 999, 999]} barSize={40}>
                {bars.map(bar => <Cell key={bar.name} fill={bar.value === peak && peak > 0 ? chart.peak : chart.bar} />)}
                <LabelList dataKey="value" position="top" content={({ x, y, width, value }) => Number(value) === peak && peak > 0
                  ? <g><rect x={Number(x) + Number(width) / 2 - 20} y={Number(y) - 26} width={40} height={20} rx={10} fill={chart.peak} />
                    <text x={Number(x) + Number(width) / 2} y={Number(y) - 12} textAnchor="middle" fill={chart.onPeak} fontSize={11} fontWeight={700}>{String(value)}</text></g>
                  : null} />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>}
      </article>

      <article className="card span-3">
        <div className="card-head"><div><h2><ClipboardCheck size={16} className="head-icon" aria-hidden="true" />Status tinjauan</h2><p>Klaim ditandai yang sudah ditangani</p></div></div>
        {reviews === null ? <p className="fine-print">Hanya terlihat oleh peninjau.</p> : reviewed === 0 ? <div className="review-empty">
          <div className="stat-big">0<small> / {formatCount(flagged)}</small></div>
          <p>Belum ada klaim yang ditinjau pada analisis ini.</p>
          <Link className="button button-secondary row-button" to={`/cases${runQuery}&lane=${red > 0 ? "red" : "yellow"}`}>Mulai dari risiko {red > 0 ? "tinggi" : "sedang"} <ArrowRight size={13} /></Link>
        </div> : <>
          <div className="stat-big"><CountUp value={reviewed} /><small> / {formatCount(flagged)}</small></div>
          <div className="chart-box" style={{ height: 150 }}>
            <ResponsiveContainer>
              <PieChart>
                <Pie isAnimationActive animationDuration={650} data={donut} dataKey="value" nameKey="name" innerRadius={44} outerRadius={66} paddingAngle={donut.length > 1 ? 2 : 0} stroke="none">
                  {donut.map(item => <Cell key={item.key} fill={statusColors[item.key as keyof typeof STATUS_TOKENS]} />)}
                </Pie>
                <Tooltip formatter={(value: number) => formatCount(value)} {...tooltipStyle(chart)} />
              </PieChart>
            </ResponsiveContainer>
          </div>
          <ul className="chart-legend">
            {donut.map(item => <li key={item.key}><i className="dot" style={{ background: statusColors[item.key as keyof typeof STATUS_TOKENS] }} />{item.name}<strong>{formatCount(item.value)}</strong></li>)}
          </ul>
          {decided > 0 && <p className="review-accuracy" data-testid="review-accuracy">
            Dari <strong>{formatCount(decided)}</strong> klaim yang sudah diputuskan, <strong>{formatCount(confirmed)}</strong> ({Math.round(100 * confirmed / decided)}%) memang perlu ditindaklanjuti.
          </p>}
        </>}
      </article>

      <article className="card span-8">
        <div className="card-head">
          <div><h2><Building2 size={16} className="head-icon" aria-hidden="true" />Faskes paling mendesak</h2><p>Faskes dengan temuan terbanyak</p></div>
          {groups && <Link className="card-link" to={`/facilities${runQuery}`} aria-label="Semua faskes"><ArrowUpRight size={16} /></Link>}
        </div>
        {!groups ? <p className="fine-print">Jalankan ulang analisis di menu Data & Analisis untuk melihat data per faskes.</p>
          : groups.groups.length === 0 ? <p className="fine-print">Tidak ada kelompok faskes dengan klaim yang cukup untuk dinilai.</p>
          : <FacilityTable groups={groups.groups.slice(0, 5)} runQuery={runQuery} />}
      </article>

      <article className="card span-4" aria-label="Analisis AI">
        <div className="card-head">
          <div><h2><Sparkles size={16} className="head-icon" aria-hidden="true" />Analisis AI</h2>
            <p>Mendeteksi pola klaim yang tidak biasa</p></div>
          {aiOnly.length > 0 && <Link className="card-link" to={`/cases${runQuery}&lane=ai`} aria-label="Lihat temuan tambahan AI"><ArrowUpRight size={16} /></Link>}
        </div>
        {ml?.status !== "available" ? <p className="fine-print">AI tidak tersedia pada analisis ini.</p> : <>
          <div className="stat-big" style={{ marginBottom: 12 }}><CountUp value={ml.records_scored} /><small> klaim dinilai</small></div>
          <ul className="check-rows ai-stats">
            {ml.share_above_training_p99 !== undefined && <li className="check-row"><span>Sangat tidak biasa menurut AI</span>
              <strong>{formatCount(Math.round(ml.share_above_training_p99 * ml.records_scored))}</strong></li>}
            <li className="check-row"><span title="Klaim risiko tinggi yang juga dinilai sangat tidak biasa oleh AI">Menguatkan klaim risiko tinggi</span><strong>{formatCount(aiConfirmedRed)}</strong></li>
            <li className="check-row"><span title="Klaim yang lolos pemeriksaan aturan tetapi dinilai sangat tidak biasa oleh AI">Temuan tambahan AI</span><strong>{formatCount(aiOnly.length)}{ml.items_truncated ? "+" : ""}</strong></li>
          </ul>
          {aiOnly.length > 0 && <ul className="row-list" style={{ marginTop: 12 }}>{aiOnly.slice(0, 2).map(item => <li key={item.case_id}>
            <RunCandidateLink className="row-item interactive-row" runId={runId} caseId={item.case_id}>
              <span className="icon-circle">#{item.rank}</span>
              <span className="row-main"><strong>Ref. {shortRef(item.case_id)}</strong>
                <span>{item.top_deviations.slice(0, 1).map(d => mlFeatureLabel(d.feature, d.description)).join("") || "Gabungan beberapa data yang tidak biasa"}</span></span>
            </RunCandidateLink>
          </li>)}</ul>}
        </>}
      </article>
    </section>
  </>;
}

export function FacilityTable({ groups, runQuery, showPriority = false }: { groups: FacilityGroup[]; runQuery: string; showPriority?: boolean }) {
  return <div className="table-scroll">
    <table className="data-table facility-table">
      <thead><tr><th>Kelompok faskes</th><th>Risiko tinggi</th><th>Risiko sedang</th><th>Nilai tagihan berisiko</th>
        {showPriority && <th>Indeks prioritas</th>}<th>Tingkat</th><th><span className="sr-only">Aksi</span></th></tr></thead>
      <tbody>{groups.map(group => (
        <tr key={group.group_id} data-group-id={group.group_id}>
          <td><div className="cell-flex"><span className="icon-circle"><Building2 size={16} /></span>
            <div className="facility-cell"><strong>{group.title}</strong><span>{group.region} · {formatCount(group.claim_count)} klaim</span></div></div></td>
          <td><span className="status-dot-text"><LaneDot lane="red" />{formatCount(group.lane_counts.red)}</span></td>
          <td><span className="status-dot-text"><LaneDot lane="yellow" />{formatCount(group.lane_counts.yellow)}</span></td>
          <td>{group.billed_high_or_medium !== undefined ? formatRupiah(group.billed_high_or_medium) : "—"}</td>
          {showPriority && <td><PriorityIndex group={group} /></td>}
          <td><span className={`status-pill tone-${LEVELS[group.level].tone}`}>{LEVELS[group.level].label}</span></td>
          <td><Link className="card-link" to={`/facilities/${group.group_id}${runQuery}`} aria-label={`Lihat ${group.title}`}><ArrowUpRight size={16} /></Link></td>
        </tr>))}</tbody>
    </table>
  </div>;
}

/** The proposal's audit priority index with its parts, so the number can be checked by hand. */
export function PriorityIndex({ group }: { group: FacilityGroup }) {
  if (group.audit_priority_index == null || group.risk_score == null) return <span className="fine-print">—</span>;
  const millions = (group.billed_high_or_medium ?? 0) / 1_000_000;
  const parts = `${group.risk_score.toLocaleString("id-ID", { maximumFractionDigits: 2 })} × Rp${millions.toLocaleString("id-ID", { maximumFractionDigits: 1 })} juta ÷ ${formatCount(group.records_to_request)} berkas`;
  return <span className="priority-index" title={`Skor risiko × nilai klaim berisiko ÷ berkas yang perlu diminta: ${parts}`}>
    <strong>{group.audit_priority_index.toLocaleString("id-ID", { maximumFractionDigits: 2 })}</strong><small>{parts}</small></span>;
}

/** What a new user sees before any analysis: three steps, starting with bringing in claim data. */
function FirstRunGuide({ canUpload }: { canUpload: boolean }) {
  const steps = [
    { icon: Upload, title: "Masukkan data klaim", text: "Unggah file klaim berformat kolom BPJS, atau biarkan sambungan otomatis mengambil file harian dari server." },
    { icon: ClipboardCheck, title: "Tinjau klaim prioritas", text: "Sistem memeriksa setiap klaim dan mengurutkannya: mulai dari risiko tinggi, lengkap dengan alasannya." },
    { icon: FileText, title: "Tindak lanjuti faskes", text: "Faskes dengan temuan terbanyak bisa langsung dibuatkan paket bukti untuk meminta rekam medis." },
  ];
  return <section className="card first-run" data-testid="first-run-guide">
    <div className="card-head"><div><h2>Mulai di sini</h2><p>Belum ada analisis. Tiga langkah untuk memulai:</p></div></div>
    <ol className="first-run-steps">
      {steps.map(({ icon: Icon, title, text }, index) => <li key={title}>
        <span className="first-run-icon"><Icon size={18} aria-hidden="true" /></span>
        <div><strong>{index + 1}. {title}</strong><p>{text}</p></div>
      </li>)}
    </ol>
    <div className="inline-actions">
      {canUpload ? <Link className="button button-primary" to="/workflow?unggah=1"><Upload size={15} />Unggah data klaim</Link>
        : <p className="fine-print">Data klaim dimasukkan oleh operator data. Hasilnya akan tampil di sini.</p>}
    </div>
  </section>;
}

/** Recharts tooltips follow the theme. */
function tooltipStyle(chart: Record<"tooltipBg" | "tooltipBorder" | "tooltipText", string>) {
  return {
    contentStyle: { background: chart.tooltipBg, border: `1px solid ${chart.tooltipBorder}`, borderRadius: 12, color: chart.tooltipText,
      boxShadow: "0 12px 28px -14px rgb(0 0 0 / 0.35)", fontSize: 12.5 },
    labelStyle: { color: chart.tooltipText, fontWeight: 700 },
    itemStyle: { color: chart.tooltipText },
  };
}

/** Share of the analysed claims per risk level, as one bar on the action card. */
function LaneShare({ red, yellow, green }: { red: number; yellow: number; green: number }) {
  const total = red + yellow + green;
  if (!total) return null;
  const percent = (value: number) => `${(value / total * 100).toFixed(value / total < 0.01 && value > 0 ? 1 : 0)}%`;
  return <span className="hero-share" title={`Tinggi ${percent(red)} · Sedang ${percent(yellow)} · Rendah ${percent(green)}`}>
    <span className="hero-share-bar" aria-hidden="true">
      <i className="r" style={{ width: `${Math.max(red ? 1.5 : 0, red / total * 100)}%` }} />
      <i className="y" style={{ width: `${Math.max(yellow ? 1.5 : 0, yellow / total * 100)}%` }} />
    </span>
    <span className="hero-share-text">{percent(red + yellow)} dari klaim yang dianalisis perlu tindakan</span>
  </span>;
}

/** Placeholder shapes while the analysis loads, so the page keeps its layout. */
function DashboardSkeleton() {
  return <div className="dash-skeleton" role="status" aria-label="Memuat hasil analisis…">
    <div className="kpi-strip">{[0, 1, 2, 3].map(index => <div key={index} className="card skeleton-block" style={{ height: 150 }} />)}</div>
    <div className="dash-grid">
      <div className="card skeleton-block span-4" style={{ height: 300 }} />
      <div className="card skeleton-block span-5" style={{ height: 300 }} />
      <div className="card skeleton-block span-3" style={{ height: 300 }} />
    </div>
  </div>;
}
