import { useMemo } from "react";
import { CalendarDays, CalendarRange, Flame, TrendingUp } from "lucide-react";
import { Bar, BarChart, CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { DailyActivity } from "../api/client";
import { EmptyState } from "../components/DataStates";
import { LaneDot, ReadingGuide, formatCount, formatRupiah } from "../components/Display";
import { RunSelector, RunStateMessage, SourcePill } from "../components/PersistedRunWorkspace";
import { formatPercent } from "../components/RiskMap";
import { ReviewAccuracy } from "../components/ReviewAccuracy";
import { usePersistedRunSnapshot } from "../hooks/usePersistedRunSnapshot";
import { useThemeColors } from "../theme/theme";

// Days with fewer claims than this are left out of the share line: a few claims make the share jump.
const MIN_DAY_CLAIMS = 20;
const SHORT = new Intl.DateTimeFormat("id-ID", { day: "numeric", month: "short", timeZone: "UTC" });
const LONG = new Intl.DateTimeFormat("id-ID", { weekday: "short", day: "numeric", month: "long", year: "numeric", timeZone: "UTC" });
const short = (day: string) => SHORT.format(new Date(`${day}T00:00:00Z`));
const long = (day: string) => LONG.format(new Date(`${day}T00:00:00Z`));
const COLORS = { high: "--lane-red", medium: "--lane-yellow", low: "--border-medium", share: "--map-3", average: "--text-muted",
  grid: "--border-subtle", axis: "--text-muted", surface: "--surface-bg", ink: "--text-primary" } as const;

/** Claims per service date: how many were high or medium risk, and on which days the share stood out. */
export default function TrendPage() {
  const { state, selectRun, reload } = usePersistedRunSnapshot();
  const result = state.status === "success" ? state.detail.result : null;
  const activity = result?.daily_activity;
  return <>
    <header className="page-head">
      <div><h1>Tren</h1><p>Klaim berisiko per tanggal layanan, dan seberapa tepat sistem menurut keputusan verifikator.</p></div>
      {state.status === "success" && <div className="page-head-actions">
        {result && <SourcePill source={result.data_source} />}
        <RunSelector runs={state.runs} detail={state.detail} onChange={selectRun} />
      </div>}
    </header>
    {state.status !== "success" ? <RunStateMessage state={state} retry={reload} />
      : !activity ? <div className="card"><EmptyState title="Tren tersedia untuk analisis berikutnya"
        message="Analisis ini disimpan sebelum ringkasan per tanggal dicatat. Jalankan ulang analisis di menu Data & Analisis." /></div>
      : activity.status !== "available" ? <div className="card"><EmptyState title="Tanggal layanan tidak tersedia"
        message="Data klaim pada analisis ini tidak memuat tanggal layanan." /></div>
      : <TrendWorkspace activity={activity} />}
    {state.status === "success" && <ReviewAccuracy />}
  </>;
}

function TrendWorkspace({ activity }: { activity: DailyActivity }) {
  const colors = useThemeColors(COLORS);
  const rows = useMemo(() => activity.days.map(day => ({
    ...day, low: Math.max(0, day.claims - day.high - day.medium), label: short(day.date),
    share: day.claims >= MIN_DAY_CLAIMS ? (day.high + day.medium) / day.claims : null,
  })), [activity]);
  const total = rows.reduce((sum, day) => sum + day.claims, 0);
  const atRisk = rows.reduce((sum, day) => sum + day.high + day.medium, 0);
  const average = total ? atRisk / total : 0;
  const busiest = rows.reduce((best, day) => (day.claims > best.claims ? day : best), rows[0]);
  const peak = rows.filter(day => day.share !== null).reduce<(typeof rows)[number] | null>((best, day) => (!best || (day.share ?? 0) > (best.share ?? 0) ? day : best), null);
  const hasBilled = rows.some(day => day.billed_high_or_medium !== null);
  const tooltip = {
    contentStyle: { background: colors.surface, border: `1px solid ${colors.grid}`, borderRadius: 12, color: colors.ink, fontSize: 12.5,
      boxShadow: "0 12px 28px -14px rgb(0 0 0 / 0.35)" },
    labelStyle: { color: colors.ink, fontWeight: 700 }, itemStyle: { color: colors.ink },
  };
  const axis = { tick: { fontSize: 11.5, fill: colors.axis }, axisLine: false, tickLine: false };

  return <>
    <ReadingGuide title="Cara membaca tren" items={[
      ["Klaim per hari", "Tinggi batang = semua klaim pada tanggal layanan itu. Bagian merah dan kuning di atas = klaim risiko tinggi dan sedang."],
      ["Porsi berisiko", `Persen klaim risiko tinggi dan sedang per hari. Garis putus-putus = rata-rata seluruh periode. Hari dengan kurang dari ${MIN_DAY_CLAIMS} klaim tidak digambar karena persennya mudah melonjak.`],
      ["Ketepatan temuan sistem", "Di bagian bawah: dari klaim yang sudah diputuskan petugas, berapa persen yang memang bermasalah."],
      ["Arti angka", "Petunjuk pemeriksaan, bukan bukti kecurangan."],
    ]} />
    <section className="map-stats" aria-label="Ringkasan tren">
      <div className="map-stat card"><span className="map-stat-icon"><CalendarRange size={18} aria-hidden="true" /></span>
        <div><span>Rentang tanggal layanan</span><strong>{formatCount(rows.length)}<small> hari · {short(rows[0].date)} – {short(rows[rows.length - 1].date)}</small></strong></div></div>
      <div className="map-stat card"><span className="map-stat-icon"><CalendarDays size={18} aria-hidden="true" /></span>
        <div><span>Hari tersibuk</span><strong>{formatCount(busiest.claims)}<small> klaim · {short(busiest.date)}</small></strong></div></div>
      <div className="map-stat card"><span className="map-stat-icon tone-warn"><Flame size={18} aria-hidden="true" /></span>
        <div><span>Porsi berisiko tertinggi</span><strong>{peak ? formatPercent(peak.share ?? 0) : "—"}<small>{peak ? ` · ${short(peak.date)} (rata-rata ${formatPercent(average)})` : ""}</small></strong></div></div>
    </section>

    <section className="card trend-card">
      <div className="card-head"><div><h2><TrendingUp size={16} className="head-icon" aria-hidden="true" />Klaim per hari</h2>
        <p>Tinggi dan sedang ditumpuk di atas klaim risiko rendah.</p></div>
        <div className="trend-legend" aria-hidden="true">
          <span><LaneDot lane="red" />Risiko tinggi</span><span><LaneDot lane="yellow" />Risiko sedang</span>
          <span><i className="trend-swatch low" />Risiko rendah</span>
        </div>
      </div>
      <div className="chart-box" style={{ height: 300 }} role="img"
        aria-label={`Klaim per hari dari ${long(rows[0].date)} sampai ${long(rows[rows.length - 1].date)}; rincian per hari ada di tabel di bawah.`}>
        <ResponsiveContainer>
          <BarChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: -12 }} barCategoryGap="18%">
            <CartesianGrid vertical={false} stroke={colors.grid} />
            <XAxis dataKey="label" {...axis} interval="preserveStartEnd" minTickGap={18} />
            <YAxis allowDecimals={false} {...axis} width={48} />
            <Tooltip cursor={{ fill: colors.grid, opacity: 0.4 }} {...tooltip}
              labelFormatter={(_label, payload) => (payload?.[0]?.payload?.date ? long(payload[0].payload.date) : "")}
              formatter={(value: number, name: string) => [formatCount(value), name]} />
            <Bar dataKey="low" name="Risiko rendah" stackId="claims" fill={colors.low} stroke={colors.surface} strokeWidth={1} isAnimationActive={false} />
            <Bar dataKey="medium" name="Risiko sedang" stackId="claims" fill={colors.medium} stroke={colors.surface} strokeWidth={1} isAnimationActive={false} />
            <Bar dataKey="high" name="Risiko tinggi" stackId="claims" fill={colors.high} stroke={colors.surface} strokeWidth={1} radius={[4, 4, 0, 0]} isAnimationActive={false} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </section>

    <section className="card trend-card">
      <div className="card-head"><div><h2>Porsi klaim berisiko per hari</h2>
        <p>Garis putus-putus = rata-rata seluruh periode ({formatPercent(average)}). Hari dengan kurang dari {MIN_DAY_CLAIMS} klaim tidak digambar.</p></div></div>
      <div className="chart-box" style={{ height: 240 }} role="img" aria-label={`Porsi klaim risiko tinggi dan sedang per hari; rata-rata ${formatPercent(average)}.`}>
        <ResponsiveContainer>
          <LineChart data={rows} margin={{ top: 12, right: 12, bottom: 0, left: -12 }}>
            <CartesianGrid vertical={false} stroke={colors.grid} />
            <XAxis dataKey="label" {...axis} interval="preserveStartEnd" minTickGap={18} />
            <YAxis {...axis} width={48} tickFormatter={(value: number) => formatPercent(value)} />
            <Tooltip {...tooltip} labelFormatter={(_label, payload) => (payload?.[0]?.payload?.date ? long(payload[0].payload.date) : "")}
              formatter={(value: number) => [formatPercent(value), "Porsi berisiko"]} />
            <ReferenceLine y={average} stroke={colors.average} strokeDasharray="5 5" />
            <Line type="monotone" dataKey="share" stroke={colors.share} strokeWidth={2} dot={{ r: 3, fill: colors.share, stroke: colors.surface, strokeWidth: 2 }}
              activeDot={{ r: 5 }} connectNulls={false} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </section>

    <section className="card">
      <div className="card-head"><div><h2>Rincian per hari</h2><p>Hari terbaru di atas.</p></div></div>
      <div className="table-scroll trend-table-scroll">
        <table className="data-table">
          <thead><tr><th>Tanggal layanan</th><th>Klaim</th><th>Risiko tinggi</th><th>Risiko sedang</th><th>Porsi berisiko</th>
            {hasBilled && <th>Nilai tagihan berisiko</th>}</tr></thead>
          <tbody>{[...rows].reverse().map(day => <tr key={day.date}>
            <td>{long(day.date)}</td>
            <td>{formatCount(day.claims)}</td>
            <td><span className="status-dot-text"><LaneDot lane="red" />{formatCount(day.high)}</span></td>
            <td><span className="status-dot-text"><LaneDot lane="yellow" />{formatCount(day.medium)}</span></td>
            <td>{day.share !== null ? formatPercent(day.share) : <span className="fine-print" title={`Kurang dari ${MIN_DAY_CLAIMS} klaim; porsi tidak dihitung`}>terlalu sedikit</span>}</td>
            {hasBilled && <td>{day.billed_high_or_medium === null ? "—" : formatRupiah(day.billed_high_or_medium)}</td>}
          </tr>)}</tbody>
        </table>
      </div>
      {(activity.undated_claims > 0 || activity.days_truncated) && <p className="fine-print" style={{ marginTop: 10 }}>
        {activity.undated_claims > 0 ? `${formatCount(activity.undated_claims)} klaim tanpa tanggal tidak dihitung.` : ""}
        {activity.days_truncated ? " Hanya tanggal terbaru yang ditampilkan." : ""}</p>}
    </section>
  </>;
}
