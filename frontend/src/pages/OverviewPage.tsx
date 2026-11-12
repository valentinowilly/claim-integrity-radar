import { useEffect, useId, useMemo, useState } from "react";
import { ArrowUpRight, Building2, ChartScatter, CircleCheck, CalendarDays, ClipboardCheck, FileCheck2, FileText, ShieldAlert, TriangleAlert, Upload } from "lucide-react";
import { Link } from "react-router-dom";
import { Area, AreaChart, Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import {
  getReviewPipeline, type DailyActivity, type FacilityGroup, type ReviewPipeline, type RunOverview, type RunResult,
} from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { CountUp, FRAUD_PATTERNS, LEVELS, LaneDot, formatCount, formatRupiah, titleCase } from "../components/Display";
import { RunSelector, RunStateMessage, RunTechnicalDetails, SourcePill } from "../components/PersistedRunWorkspace";
import { DayBars, FEW_DAYS } from "../components/DayBars";
import { AmountHelp, BilledBreakdown, FacilityAlert, PATTERN_COLORS, RiskFocus, dominantPattern, type AmountLane } from "../components/RiskFocus";
import { usePersistedRunSnapshot } from "../hooks/usePersistedRunSnapshot";
import { useThemeColors } from "../theme/theme";

// Colour tokens, resolved per theme for the charts.
const CHART_TOKENS = { red: "--lane-red", yellow: "--lane-yellow", brand: "--chart-1", track: "--border-subtle", axis: "--text-muted",
  axisFaint: "--text-faint", tooltipBg: "--surface-bg", tooltipBorder: "--border-subtle", tooltipText: "--text-primary" } as const;
const TODAY = new Intl.DateTimeFormat("id-ID", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
const DAY = new Intl.DateTimeFormat("id-ID", { day: "numeric", month: "short" });
const DAY_LONG = new Intl.DateTimeFormat("id-ID", { weekday: "long", day: "numeric", month: "long" });

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
  // Every rupiah figure opens the same "how is this computed" panel, at the lane it belongs to.
  const [explain, setExplain] = useState<AmountLane | null>(null);
  const runQuery = `?run_id=${encodeURIComponent(runId)}`;

  return <>
    <header className="page-head">
      <div>
        <span className="page-eyebrow"><CalendarDays size={14} aria-hidden="true" />{TODAY.format(new Date())}</span>
        <h1>Prioritas <span className="muted">hari ini</span></h1>
        <p>{greeting()}, {username}. {state.status === "empty" ? "Belum ada data klaim yang dianalisis." : "Berikut klaim dan faskes yang paling perlu diperiksa hari ini."}</p>
        {result && available && <p className="page-head-facts" data-testid="analysis-facts">{formatCount(result.records_considered)} klaim dianalisis
          {result.facility_groups?.exposure?.status === "available" && <> · nilai tagihan {formatRupiah(result.facility_groups.exposure.billed_total)}
            <AmountHelp onClick={() => setExplain("all")} label="Cara menghitung nilai tagihan" /></>}</p>}
      </div>
      {state.status === "success" && <div className="page-head-actions">
        {result && <SourcePill source={result.data_source} />}
        <RunSelector runs={state.runs} detail={state.detail} onChange={selectRun} />
      </div>}
    </header>
    {state.status === "empty" ? <FirstRunGuide canUpload={permissions.includes("batches:write")} />
      : state.status === "loading" ? <DashboardSkeleton />
      : state.status !== "success" && <RunStateMessage state={state} retry={reload} />}
    {state.status === "success" && result && available && <Dashboard result={result} runId={runId} canReadReviews={canReadReviews} onExplain={setExplain} />}
    {explain && result && <BilledBreakdown result={result} runQuery={runQuery} initialLane={explain} onClose={() => setExplain(null)} />}
    {state.status === "success" && (!result || !available) && <div className="card">
      <p className="fine-print">Analisis ini belum memiliki hasil. Pilih analisis lain atau jalankan analisis baru di menu Data & Analisis.</p>
    </div>}
    {state.status === "success" && <RunTechnicalDetails detail={state.detail} />}
  </>;
}

function Dashboard({ result, runId, canReadReviews, onExplain }: {
  result: RunResult; runId: string; canReadReviews: boolean; onExplain: (lane: AmountLane) => void;
}) {
  const chart = useThemeColors(CHART_TOKENS);
  const runQuery = `?run_id=${encodeURIComponent(runId)}`;
  const lanes = result.action_policy.lane_counts ?? {};
  const red = lanes.red ?? 0;
  const yellow = lanes.yellow ?? 0;
  const green = lanes.green ?? 0;
  const groups = result.facility_groups;
  const exposure = groups?.exposure?.status === "available" ? groups.exposure : null;
  const overview = result.overview;
  const days = useMemo(() => result.daily_activity?.status === "available"
    ? result.daily_activity.days.filter(day => day.claims > 0) : [], [result.daily_activity]);

  // Review stages come from their own small read, never from the full result.
  const [pipeline, setPipeline] = useState<ReviewPipeline | null | "error">(null);
  useEffect(() => {
    if (!canReadReviews) return;
    const controller = new AbortController();
    setPipeline(null);
    getReviewPipeline(runId, controller.signal).then(setPipeline).catch(() => {
      if (!controller.signal.aborted) setPipeline("error");
    });
    return () => controller.abort();
  }, [runId, canReadReviews]);

  return <>
    <FacilityAlert result={result} runQuery={runQuery} />
    <RiskFocus result={result} runQuery={runQuery} onExplain={onExplain} />

    <section className="kpi-row" aria-label="Angka utama">
      <HighPerDay days={days} red={red} color={chart.red} runQuery={runQuery} />
      <div className="kpi-tile-wrap">
        <Link className="kpi-tile tone-yellow" to={`/cases${runQuery}&lane=yellow`} data-testid="lane-card-yellow">
          <span className="kpi-tile-label"><TriangleAlert size={15} aria-hidden="true" />Risiko sedang</span>
          <span className="kpi-tile-value"><CountUp value={yellow} /> <small>klaim</small></span>
          {exposure && <span className="kpi-tile-money" data-testid="kpi-yellow-amount">{formatRupiah(exposure.billed_medium)}</span>}
          <span className="kpi-tile-note">Diperiksa setelah risiko tinggi</span>
        </Link>
        {exposure && <AmountHelp onClick={() => onExplain("yellow")} label="Cara menghitung nilai tagihan risiko sedang" />}
      </div>
      <EvidenceTile evidence={overview?.evidence} color={chart.brand} track={chart.track} />
      <article className="kpi-tile" data-testid="kpi-ai-confirmed">
        <span className="kpi-tile-label"><ChartScatter size={15} aria-hidden="true" />Dikuatkan AI pola klaim</span>
        {overview ? <>
          <span className="kpi-tile-value"><CountUp value={overview.ai_confirmed_high} /> <small>klaim</small></span>
          <span className="kpi-tile-note">Klaim risiko tinggi yang polanya juga lebih jarang dari {Math.round(overview.ai_threshold * 100)}% klaim lain</span>
        </> : <>
          <span className="kpi-tile-value muted">Belum dihitung</span>
          <span className="kpi-tile-note">Jalankan ulang analisis ini untuk menghitungnya.</span>
        </>}
      </article>
    </section>

    {canReadReviews && <ReviewFlow pipeline={pipeline} runQuery={runQuery} green={green} onExplain={() => onExplain("all")} />}

    <div className="dash-pair">
      <FacilityBars result={result} runQuery={runQuery} onExplain={onExplain} />
      <DailyRisk days={days} chart={chart} truncated={Boolean(result.daily_activity?.days_truncated)} />
    </div>
  </>;
}

type Day = DailyActivity["days"][number];

/** High-risk claims per service day: the average, the peak, and a small line of every day. */
function HighPerDay({ days, red, color, runQuery }: { days: Day[]; red: number; color: string; runQuery: string }) {
  const gradientId = `high-${useId().replace(/:/g, "")}`;
  const peak = days.reduce<Day | null>((best, day) => !best || day.high > best.high ? day : best, null);
  const average = days.length ? days.reduce((sum, day) => sum + day.high, 0) / days.length : null;
  return <Link className="kpi-tile tone-red" to={`/cases${runQuery}&lane=red`} data-testid="kpi-red">
    <span className="kpi-tile-label"><ShieldAlert size={15} aria-hidden="true" />Risiko tinggi per hari</span>
    {average === null || !peak ? <>
      <span className="kpi-tile-value"><CountUp value={red} /> <small>klaim</small></span>
      <span className="kpi-tile-note">Tanggal layanan tidak tersedia untuk dirinci per hari.</span>
    </> : <>
      <span className="kpi-tile-value">{formatDecimal(average)} <small>klaim/hari rata-rata</small></span>
      {days.length > 1 && <span className="kpi-tile-spark" aria-hidden="true"><ResponsiveContainer>
        <AreaChart data={days} margin={{ top: 2, right: 0, bottom: 2, left: 0 }}>
          <defs><linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.3} /><stop offset="100%" stopColor={color} stopOpacity={0} />
          </linearGradient></defs>
          <YAxis hide domain={[0, "dataMax"]} />
          <Area type="monotone" dataKey="high" stroke={color} strokeWidth={2} fill={`url(#${gradientId})`} isAnimationActive={false} dot={false} />
        </AreaChart>
      </ResponsiveContainer></span>}
      <span className="kpi-tile-note">Puncak {DAY.format(parseDay(peak.date))}: {formatCount(peak.high)} klaim · {dayRange(days)}</span>
    </>}
  </Link>;
}

/** Of the services that must carry supporting documents, the share that carries all of them. */
function EvidenceTile({ evidence, color, track }: { evidence: RunOverview["evidence"] | undefined; color: string; track: string }) {
  const share = evidence?.share_complete ?? null;
  return <article className="kpi-tile" data-testid="kpi-evidence">
    <span className="kpi-tile-label"><FileCheck2 size={15} aria-hidden="true" />Kelengkapan berkas layanan</span>
    {share === null || !evidence ? <>
      <span className="kpi-tile-value muted">{evidence ? "Tidak ada" : "Belum dihitung"}</span>
      <span className="kpi-tile-note">{evidence ? "Tidak ada layanan yang wajib berbukti pada data ini." : "Jalankan ulang analisis ini untuk menghitungnya."}</span>
    </> : <>
      <span className="kpi-tile-ring">
        <svg viewBox="0 0 36 36" width="44" height="44" aria-hidden="true">
          <circle cx="18" cy="18" r="15" fill="none" stroke={track} strokeWidth="5" />
          <circle cx="18" cy="18" r="15" fill="none" stroke={color} strokeWidth="5" strokeLinecap="round"
            strokeDasharray={`${share * 94.25} 94.25`} transform="rotate(-90 18 18)" />
        </svg>
        <span className="kpi-tile-value">{formatPercent(share)}</span>
      </span>
      <span className="kpi-tile-note">{formatCount(evidence.services_complete)} dari {formatCount(evidence.services_requiring_evidence)} layanan yang wajib berbukti</span>
    </>}
  </article>;
}

const STAGE_LABELS: Record<ReviewPipeline["stages"][number]["stage"], string> = {
  pending_review: "Belum ditinjau", in_review: "Sedang ditinjau", awaiting_evidence: "Minta klarifikasi", escalated: "Masuk audit", closed: "Selesai",
};

/** Claims that need action (high and medium risk) per review stage, with their billed value; each stage filters the queue. */
function ReviewFlow({ pipeline, runQuery, green, onExplain }: {
  pipeline: ReviewPipeline | null | "error"; runQuery: string; green: number; onExplain: () => void;
}) {
  return <section className="card flow-card" aria-labelledby="flow-title" data-testid="review-flow">
    <div className="flow-head">
      <h2 id="flow-title">Alur tinjauan <AmountHelp onClick={onExplain} label="Cara menghitung nilai tagihan per tahap" /></h2>
      {pipeline && pipeline !== "error" && <span>{formatCount(pipeline.decided)} dari {formatCount(pipeline.needs_action)} klaim yang perlu tindakan sudah selesai</span>}
    </div>
    {pipeline === "error" ? <p className="fine-print">Alur tinjauan tidak dapat dimuat. Muat ulang halaman untuk mencoba lagi.</p>
      : pipeline === null ? <div className="flow-stages">{[0, 1, 2, 3, 4].map(index => <div key={index} className="flow-stage skeleton-block" style={{ height: 96 }} />)}</div>
      : <>
        <ol className="flow-stages">{pipeline.stages.map((stage, index) => {
          const filter = stage.stage === "pending_review" ? "not_started" : stage.stage;
          return <li key={stage.stage}>
            <Link className={`flow-stage${stage.count > 0 ? " has-claims" : ""}${index === 0 && stage.count > 0 ? " is-first" : ""}`}
              to={`/cases${runQuery}&lane=all&state=${filter}`} data-testid={`flow-${stage.stage}`}>
              <span className="flow-stage-label">{index + 1}. {STAGE_LABELS[stage.stage]}</span>
              <span className="flow-stage-count">{formatCount(stage.count)}</span>
              <span className="flow-stage-money">{formatRupiah(stage.billed)}</span>
            </Link>
          </li>;
        })}</ol>
        <div className="flow-progress" role="img" aria-label={`Kemajuan tinjauan ${formatPercent(pipeline.needs_action ? pipeline.decided / pipeline.needs_action : 0)}`}>
          <i style={{ width: `${pipeline.needs_action ? 100 * pipeline.decided / pipeline.needs_action : 0}%` }} /></div>
        <p className="fine-print">Klik tahap untuk membuka antrean dengan status itu. Hitungan berisi klaim risiko tinggi dan sedang;{" "}
          <Link to={`/cases${runQuery}&lane=green`} data-testid="lane-card-green">{formatCount(green)} klaim risiko rendah</Link> diproses seperti biasa.</p>
      </>}
  </section>;
}

/** Facility groups with high-risk claims, most first; the bar is their high-risk billed value. */
function FacilityBars({ result, runQuery, onExplain }: { result: RunResult; runQuery: string; onExplain: (lane: AmountLane) => void }) {
  const groups = result.facility_groups;
  const all = groups?.groups ?? [];
  // No group with high-risk claims: the medium-risk ones are the next to check, so they are shown instead.
  const lane: "red" | "yellow" = all.some(group => group.lane_counts.red > 0) ? "red" : "yellow";
  const billedOf = (group: FacilityGroup) => lane === "red" ? group.billed_high
    : typeof group.billed_high_or_medium === "number" ? group.billed_high_or_medium - (group.billed_high ?? 0) : undefined;
  const rows = all.filter(group => group.lane_counts[lane] > 0)
    .sort((a, b) => b.lane_counts[lane] - a.lane_counts[lane] || (billedOf(b) ?? 0) - (billedOf(a) ?? 0)).slice(0, 5);
  const hasMoney = rows.some(group => typeof billedOf(group) === "number");
  const most = Math.max(1, ...rows.map(group => hasMoney ? billedOf(group) ?? 0 : group.lane_counts[lane]));
  const level = lane === "red" ? "tinggi" : "sedang";
  return <section className="card" aria-labelledby="facility-bars-title">
    <div className="card-head">
      <div><h2 id="facility-bars-title">Kelompok faskes yang perlu diperiksa{hasMoney && <AmountHelp onClick={() => onExplain(lane)} label="Cara menghitung nilai tagihan per faskes" />}</h2>
        {rows.length > 0 && <p>{lane === "yellow" ? "Belum ada risiko tinggi. " : ""}Urut jumlah klaim risiko {level}{hasMoney ? "; bilah = nilai tagihannya" : ""}.</p>}</div>
      {groups && <Link className="card-link" to={`/facilities${runQuery}`} aria-label="Semua kelompok faskes"><ArrowUpRight size={16} /></Link>}
    </div>
    {!groups ? <EmptyNote icon={Building2} title="Data per faskes belum ada" text="Jalankan ulang analisis di Data & Analisis." />
      : rows.length === 0 ? <EmptyNote icon={CircleCheck} tone="good" title="Tidak ada faskes berisiko" text={`${formatCount(all.length)} kelompok faskes dinilai, semuanya risiko rendah.`} />
      : <ul className={`facility-bars is-${lane}`}>{rows.map(group => {
        const pattern = dominantPattern(group);
        const value = hasMoney ? billedOf(group) ?? 0 : group.lane_counts[lane];
        return <li key={group.group_id}>
          <Link to={`/facilities/${encodeURIComponent(group.group_id)}${runQuery}`} className="facility-bar" data-testid="facility-bar">
            <span className="facility-bar-name">{group.title} · {titleCase(group.region)}</span>
            {hasMoney && <strong>{formatRupiah(billedOf(group) ?? 0)}</strong>}
            <span className="facility-bar-meta">{formatCount(group.lane_counts[lane])} klaim risiko {level}{pattern ? ` · ${(FRAUD_PATTERNS[pattern.code]?.label ?? pattern.code).toLowerCase()}` : ""}</span>
            <span className="facility-bar-track" aria-hidden="true"><i style={{ width: `${Math.max(2, 100 * value / most)}%` }} /></span>
          </Link>
        </li>;
      })}</ul>}
  </section>;
}

/** An empty card that still says something: an icon, a short title and one line. */
function EmptyNote({ icon: Icon, title, text, tone = "neutral" }: { icon: typeof Building2; title: string; text: string; tone?: "neutral" | "good" }) {
  return <div className={`empty-note tone-${tone}`}><span className="empty-note-icon"><Icon size={22} aria-hidden="true" /></span>
    <strong>{title}</strong><span>{text}</span></div>;
}

/** High- and medium-risk claims per service day, stacked. */
function DailyRisk({ days, chart, truncated }: { days: Day[]; chart: Record<keyof typeof CHART_TOKENS, string>; truncated: boolean }) {
  const risky = days.reduce((sum, day) => sum + day.high + day.medium, 0);
  const billedDays = days.filter(day => typeof day.billed_high_or_medium === "number");
  const billed = billedDays.reduce((sum, day) => sum + (day.billed_high_or_medium ?? 0), 0);
  return <section className="card" aria-labelledby="daily-title">
    <div className="card-head"><div><h2 id="daily-title">Klaim berisiko per hari</h2>
      <p>Risiko tinggi dan sedang menurut tanggal layanan{days.length ? `, ${dayRange(days)}` : ""}</p></div></div>
    {days.length === 0 ? <EmptyNote icon={CalendarDays} title="Tanggal layanan tidak ada" text="Data ini tidak memuat tanggal layanan." /> : <>
      {days.length <= FEW_DAYS ? <DayBars days={days} /> : <>
      <div className="chart-box" style={{ height: 210 }} role="img"
        aria-label={`Grafik batang bertumpuk klaim risiko tinggi dan sedang per hari, ${dayRange(days)}`}>
        <ResponsiveContainer>
          <BarChart data={days} margin={{ top: 8, right: 4, bottom: 0, left: -22 }} barCategoryGap="18%" maxBarSize={36}>
            <XAxis dataKey="date" tickFormatter={value => DAY.format(parseDay(String(value)))} tick={{ fontSize: 11, fill: chart.axis }}
              axisLine={false} tickLine={false} minTickGap={24} />
            <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: chart.axisFaint }} axisLine={false} tickLine={false} />
            <Tooltip cursor={{ fill: chart.track }} {...tooltipStyle(chart)}
              labelFormatter={value => DAY_LONG.format(parseDay(String(value)))}
              formatter={(value: number, name: string) => [`${formatCount(value)} klaim`, name === "high" ? "Risiko tinggi" : "Risiko sedang"]} />
            <Bar isAnimationActive={false} dataKey="high" stackId="risk" fill={chart.red} />
            <Bar isAnimationActive={false} dataKey="medium" stackId="risk" fill={chart.yellow} radius={[3, 3, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <ul className="chart-legend inline">
        <li><i className="dot" style={{ background: chart.red }} />Risiko tinggi</li>
        <li><i className="dot" style={{ background: chart.yellow }} />Risiko sedang</li>
      </ul>
      </>}
      <p className="fine-print">Rata-rata {formatDecimal(risky / days.length)} klaim berisiko per hari
        {billedDays.length ? `, nilai tagihan ${formatRupiah(Math.round(billed / billedDays.length))} per hari` : ""}.
        {truncated ? " Hanya hari-hari terbaru yang ditampilkan." : ""}</p>
    </>}
  </section>;
}

function parseDay(date: string): Date {
  const [year, month, day] = date.split("-").map(Number);
  return new Date(year, (month || 1) - 1, day || 1);
}

function dayRange(days: Day[]): string {
  if (!days.length) return "";
  const first = parseDay(days[0].date), last = parseDay(days[days.length - 1].date);
  return days.length === 1 ? DAY.format(first) : `${DAY.format(first)} sampai ${DAY.format(last)}`;
}

function formatDecimal(value: number): string {
  return value.toLocaleString("id-ID", { maximumFractionDigits: value < 10 ? 1 : 0 });
}

function formatPercent(share: number): string {
  return `${(share * 100).toLocaleString("id-ID", { maximumFractionDigits: 1 })}%`;
}


export function FacilityTable({ groups, runQuery, showPriority = false }: { groups: FacilityGroup[]; runQuery: string; showPriority?: boolean }) {
  return <div className="table-scroll">
    <table className="data-table facility-table">
      <thead><tr><th>Kelompok faskes</th><th>Modus utama</th><th>Risiko tinggi</th><th>Risiko sedang</th><th>Nilai tagihan berisiko</th>
        {showPriority && <th>Indeks prioritas</th>}<th>Tingkat</th><th><span className="sr-only">Aksi</span></th></tr></thead>
      <tbody>{groups.map(group => (
        <tr key={group.group_id} data-group-id={group.group_id}>
          <td><div className="cell-flex"><span className="icon-circle"><Building2 size={16} /></span>
            <div className="facility-cell"><strong>{group.title}</strong><span>{titleCase(group.region)} · {formatCount(group.claim_count)} klaim</span>
              <span className="facility-share" title={`${formatCount(group.lane_counts.red + group.lane_counts.yellow)} dari ${formatCount(group.claim_count)} klaim berisiko`} aria-hidden="true">
                <i className="is-red" style={{ width: `${100 * group.lane_counts.red / Math.max(1, group.claim_count)}%` }} />
                <i className="is-yellow" style={{ width: `${100 * group.lane_counts.yellow / Math.max(1, group.claim_count)}%` }} /></span></div></div></td>
          <td>{(() => { const top = dominantPattern(group); return top
            ? <span className="pattern-chip" style={{ ["--pattern" as string]: PATTERN_COLORS[top.code] }}>{FRAUD_PATTERNS[top.code]?.label ?? top.code}</span>
            : <span className="fine-print">Tidak ada</span>; })()}</td>
          <td><span className="status-dot-text"><LaneDot lane="red" />{formatCount(group.lane_counts.red)}</span></td>
          <td><span className="status-dot-text"><LaneDot lane="yellow" />{formatCount(group.lane_counts.yellow)}</span></td>
          <td>{group.billed_high_or_medium !== undefined ? formatRupiah(group.billed_high_or_medium) : "Tidak ada"}</td>
          {showPriority && <td><PriorityIndex group={group} /></td>}
          <td><span className={`status-pill tone-${LEVELS[group.level].tone}`}>{LEVELS[group.level].label}</span></td>
          <td><Link className="card-link" to={`/facilities/${group.group_id}${runQuery}`} aria-label={`Lihat ${group.title}`}><ArrowUpRight size={16} /></Link></td>
        </tr>))}</tbody>
    </table>
  </div>;
}

/** The proposal's audit priority index with its parts, so the number can be checked by hand. */
export function PriorityIndex({ group }: { group: FacilityGroup }) {
  if (group.audit_priority_index == null || group.risk_score == null) return <span className="fine-print">Tidak dihitung</span>;
  const millions = (group.billed_high_or_medium ?? 0) / 1_000_000;
  const parts = `${group.risk_score.toLocaleString("id-ID", { maximumFractionDigits: 2 })} × Rp${millions.toLocaleString("id-ID", { maximumFractionDigits: 1 })} juta ÷ ${formatCount(group.records_to_request)} berkas`;
  return <span className="priority-index" title={`Tingkat risiko × nilai klaim berisiko ÷ berkas yang perlu diminta: ${parts}`}>
    <strong>{group.audit_priority_index.toLocaleString("id-ID", { maximumFractionDigits: 2 })}</strong><small>{formatCount(group.records_to_request)} berkas diminta</small></span>;
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

/** Placeholder shapes while the analysis loads, so the page keeps its layout. */
function DashboardSkeleton() {
  return <div className="dash-skeleton" role="status" aria-label="Memuat hasil analisis…">
    <div className="card skeleton-block" style={{ height: 230, marginBottom: 18 }} />
    <div className="kpi-row">{[0, 1, 2, 3].map(index => <div key={index} className="card skeleton-block" style={{ height: 150 }} />)}</div>
    <div className="dash-pair">
      <div className="card skeleton-block" style={{ height: 300 }} />
      <div className="card skeleton-block" style={{ height: 300 }} />
    </div>
  </div>;
}
