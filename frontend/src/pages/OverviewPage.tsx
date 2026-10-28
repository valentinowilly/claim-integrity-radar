import { useEffect, useState } from "react";
import { ArrowRight, ArrowUpRight, Building2, ClipboardCheck, FileText, Sparkles, Upload } from "lucide-react";
import { Link } from "react-router-dom";
import { Bar, BarChart, Cell, LabelList, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import {
  flaggedCaseCount, getRunReviews, runReviewStatusLabels, ruleFlaggedListedIds,
  type FacilityGroup, type RunResult, type RunReviewStatus, type RunReviewSummaryItem,
} from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { CountUp, LEVELS, LaneDot, formatCount, formatRupiah, mlFeatureLabel, shortRef } from "../components/Display";
import { RunCandidateLink, RunSelector, RunStateMessage, RunTechnicalDetails, SourcePill } from "../components/PersistedRunWorkspace";
import { usePersistedRunSnapshot } from "../hooks/usePersistedRunSnapshot";

const STATUS_COLORS: Record<string, string> = {
  not_started: "#cbd5e1", in_review: "#0284c7", awaiting_evidence: "#d97706", escalated: "#dc2626", closed: "#047857",
};

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
        <h1>Prioritas <span className="muted">hari ini</span></h1>
        <p>{greeting()}, {username}. {state.status === "empty" ? "Belum ada data klaim yang dianalisis." : "Berikut klaim dan faskes yang paling perlu diperiksa hari ini."}</p>
      </div>
      {state.status === "success" && <div className="page-head-actions">
        {result && <SourcePill source={result.data_source} />}
        <RunSelector runs={state.runs} detail={state.detail} onChange={selectRun} />
      </div>}
    </header>
    {state.status === "empty" ? <FirstRunGuide canUpload={permissions.includes("batches:write")} />
      : state.status !== "success" && <RunStateMessage state={state} retry={reload} />}
    {state.status === "success" && result && available && <Dashboard
      result={result}
      runId={runId}
      reviews={reviews && reviews.runId === runId ? reviews.items : null}
    />}
    {state.status === "success" && (!result || !available) && <div className="card">
      <p className="fine-print">Analisis ini belum memiliki hasil. Pilih analisis lain atau jalankan analisis baru di menu Data & Analisis.</p>
    </div>}
    {state.status === "success" && <RunTechnicalDetails detail={state.detail} />}
  </>;
}

function Dashboard({ result, runId, reviews }: {
  result: RunResult; runId: string; reviews: RunReviewSummaryItem[] | null;
}) {
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
  const [chartLane, setChartLane] = useState<"red" | "yellow">("red");

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

  return <>
    <section className="dash-grid">
      <div className="span-4 stack" style={{ gap: 18 }}>
        <Link className="hero-card" to={`/cases${runQuery}&lane=red`}>
          <span className="hero-label">Perlu tindakan</span>
          <span className="hero-num"><CountUp value={red + yellow} /> <small>klaim</small></span>
          <span className="hero-split">
            <span data-testid="lane-card-red"><LaneDot lane="red" />Risiko tinggi {formatCount(red)}</span>
            <span data-testid="lane-card-yellow"><LaneDot lane="yellow" />Risiko sedang {formatCount(yellow)}</span>
          </span>
          {groups?.exposure?.status === "available" && <span className="hero-amount" data-testid="hero-amount">
            Nilai tagihan perlu diverifikasi ulang <strong><CountUp value={groups.exposure.billed_high_or_medium} format={formatRupiah} /></strong></span>}
          <span className="hero-cta">Buka antrean <ArrowRight size={13} style={{ verticalAlign: "-2px" }} /></span>
        </Link>
        <Link className="card" to={`/cases${runQuery}&lane=green`} style={{ color: "inherit", textDecoration: "none" }} data-testid="lane-card-green">
          <div className="card-head" style={{ marginBottom: 6 }}><div><h2>Risiko rendah</h2><p>Proses seperti biasa</p></div>
            <span className="card-link" aria-hidden="true"><ArrowUpRight size={16} /></span></div>
          <div className="cell-flex"><span className="stat-big"><CountUp value={green} /></span>
            <span className="chip-green">{formatCount(result.records_considered)} dianalisis</span></div>
        </Link>
      </div>

      <article className="card span-5">
        <div className="card-head">
          <div><h2>Klaim per kelompok faskes</h2><p>Enam kelompok dengan klaim risiko {chartLane === "red" ? "tinggi" : "sedang"} terbanyak</p></div>
          <div className="segmented-pill" role="group" aria-label="Pilih tingkat risiko grafik">
            <button type="button" aria-pressed={chartLane === "red"} onClick={() => setChartLane("red")}>Tinggi</button>
            <button type="button" aria-pressed={chartLane === "yellow"} onClick={() => setChartLane("yellow")}>Sedang</button>
          </div>
        </div>
        {bars.length === 0 || peak === 0 ? <div className="detail-placeholder" style={{ minHeight: 230 }}><strong>Tidak ada klaim risiko {chartLane === "red" ? "tinggi" : "sedang"}</strong><span>{bars.length === 0 ? "Kelompok faskes belum tersedia untuk analisis ini." : "Belum ada kelompok faskes dengan klaim pada tingkat ini."}</span></div> : <div className="chart-box" style={{ height: 250 }}
          role="img" aria-label={bars.map(bar => `${bar.title}: ${bar.value}`).join(", ")}>
          <ResponsiveContainer>
            <BarChart data={bars} margin={{ top: 28, right: 4, bottom: 0, left: -24 }}>
              <XAxis dataKey="name" tick={{ fontSize: 12, fill: "#8b95a1" }} axisLine={false} tickLine={false} />
              <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: "#b6bdc6" }} axisLine={false} tickLine={false} />
              <Tooltip cursor={false} formatter={(value: number) => [formatCount(value), "klaim"]}
                labelFormatter={(_label, payload) => payload?.[0]?.payload?.title ?? ""} />
              <Bar isAnimationActive animationDuration={650} dataKey="value" radius={[999, 999, 999, 999]} barSize={40}>
                {bars.map(bar => <Cell key={bar.name} fill={bar.value === peak && peak > 0 ? "#047857" : "#a7d8c1"} />)}
                <LabelList dataKey="value" position="top" content={({ x, y, width, value }) => Number(value) === peak && peak > 0
                  ? <g><rect x={Number(x) + Number(width) / 2 - 20} y={Number(y) - 26} width={40} height={20} rx={10} fill="#047857" />
                    <text x={Number(x) + Number(width) / 2} y={Number(y) - 12} textAnchor="middle" fill="#fff" fontSize={11} fontWeight={700}>{String(value)}</text></g>
                  : null} />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>}
      </article>

      <article className="card span-3">
        <div className="card-head"><div><h2>Status tinjauan</h2><p>Klaim ditandai yang sudah ditangani</p></div></div>
        {reviews === null ? <p className="fine-print">Hanya terlihat oleh peninjau.</p> : reviewed === 0 ? <div className="review-empty">
          <div className="stat-big">0<small> / {formatCount(flagged)}</small></div>
          <p>Belum ada klaim yang ditinjau pada analisis ini.</p>
          <Link className="button button-secondary row-button" to={`/cases${runQuery}&lane=red`}>Mulai dari risiko tinggi <ArrowRight size={13} /></Link>
        </div> : <>
          <div className="stat-big">{formatCount(reviewed)}<small> / {formatCount(flagged)}</small></div>
          <div className="chart-box" style={{ height: 150 }}>
            <ResponsiveContainer>
              <PieChart>
                <Pie isAnimationActive animationDuration={650} data={donut} dataKey="value" nameKey="name" innerRadius={44} outerRadius={66} paddingAngle={donut.length > 1 ? 2 : 0} stroke="none">
                  {donut.map(item => <Cell key={item.key} fill={STATUS_COLORS[item.key]} />)}
                </Pie>
                <Tooltip formatter={(value: number) => formatCount(value)} />
              </PieChart>
            </ResponsiveContainer>
          </div>
          <ul className="chart-legend">
            {donut.map(item => <li key={item.key}><i className="dot" style={{ background: STATUS_COLORS[item.key] }} />{item.name}<strong>{formatCount(item.value)}</strong></li>)}
          </ul>
          {decided > 0 && <p className="review-accuracy" data-testid="review-accuracy">
            Dari <strong>{formatCount(decided)}</strong> klaim yang sudah diputuskan, <strong>{formatCount(confirmed)}</strong> ({Math.round(100 * confirmed / decided)}%) memang perlu ditindaklanjuti.
          </p>}
        </>}
      </article>

      <article className="card span-8">
        <div className="card-head">
          <div><h2>Faskes paling mendesak</h2><p>Faskes dengan temuan terbanyak</p></div>
          {groups && <Link className="card-link" to={`/facilities${runQuery}`} aria-label="Semua faskes"><ArrowUpRight size={16} /></Link>}
        </div>
        {!groups ? <p className="fine-print">Jalankan ulang analisis di menu Data & Analisis untuk melihat data per faskes.</p>
          : groups.groups.length === 0 ? <p className="fine-print">Tidak ada kelompok faskes dengan klaim yang cukup untuk dinilai.</p>
          : <FacilityTable groups={groups.groups.slice(0, 5)} runQuery={runQuery} />}
      </article>

      <article className="card span-4" aria-label="Analisis AI">
        <div className="card-head">
          <div><h2><Sparkles size={16} style={{ verticalAlign: "-2px", color: "var(--brand)" }} /> Analisis AI</h2>
            <p>Mendeteksi pola klaim yang tidak biasa</p></div>
          {aiOnly.length > 0 && <Link className="card-link" to={`/cases${runQuery}&lane=ai`} aria-label="Lihat temuan tambahan AI"><ArrowUpRight size={16} /></Link>}
        </div>
        {ml?.status !== "available" ? <p className="fine-print">AI tidak tersedia pada analisis ini.</p> : <>
          <div className="stat-big" style={{ marginBottom: 12 }}>{formatCount(ml.records_scored)}<small> klaim dinilai</small></div>
          <ul className="check-rows ai-stats">
            {ml.share_above_training_p99 !== undefined && <li className="check-row"><span>Anomali sangat tinggi</span>
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

export function FacilityTable({ groups, runQuery }: { groups: FacilityGroup[]; runQuery: string }) {
  return <div className="table-scroll">
    <table className="data-table facility-table">
      <thead><tr><th>Kelompok faskes</th><th>Risiko tinggi</th><th>Risiko sedang</th><th>Nilai tagihan berisiko</th><th>Tingkat</th><th><span className="sr-only">Aksi</span></th></tr></thead>
      <tbody>{groups.map(group => (
        <tr key={group.group_id} data-group-id={group.group_id}>
          <td><div className="cell-flex"><span className="icon-circle"><Building2 size={16} /></span>
            <div className="facility-cell"><strong>{group.title}</strong><span>{group.region} · {formatCount(group.claim_count)} klaim</span></div></div></td>
          <td><span className="status-dot-text"><LaneDot lane="red" />{formatCount(group.lane_counts.red)}</span></td>
          <td><span className="status-dot-text"><LaneDot lane="yellow" />{formatCount(group.lane_counts.yellow)}</span></td>
          <td>{group.billed_high_or_medium !== undefined ? formatRupiah(group.billed_high_or_medium) : "—"}</td>
          <td><span className={`status-pill tone-${LEVELS[group.level].tone}`}>{LEVELS[group.level].label}</span></td>
          <td><Link className="card-link" to={`/facilities/${group.group_id}${runQuery}`} aria-label={`Lihat ${group.title}`}><ArrowUpRight size={16} /></Link></td>
        </tr>))}</tbody>
    </table>
  </div>;
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
