import { useEffect, useState } from "react";
import { Target } from "lucide-react";
import { Bar, BarChart, CartesianGrid, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { getReviewAccuracy, type ReviewAccuracyResponse } from "../api/client";
import { useThemeColors } from "../theme/theme";
import { LANES, LaneDot, formatCount } from "./Display";
import { formatPercent } from "./RiskMap";

const SHORT = new Intl.DateTimeFormat("id-ID", { day: "numeric", month: "short", timeZone: "UTC" });
const short = (day: string) => SHORT.format(new Date(`${day}T00:00:00Z`));
const COLORS = { supported: "--chart-1", notSupported: "--border-medium", change: "--text-muted", grid: "--border-subtle",
  axis: "--text-muted", surface: "--surface-bg", ink: "--text-primary" } as const;

/** The week (its Monday) a date falls in, as the chart labels it. */
function weekOf(day: string): string {
  const date = new Date(`${day}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() - ((date.getUTCDay() + 6) % 7));
  return date.toISOString().slice(0, 10);
}

/** How often the verifiers found a flagged claim worth following up, week by week (all analyses). */
export function ReviewAccuracy() {
  const colors = useThemeColors(COLORS);
  const [data, setData] = useState<ReviewAccuracyResponse | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    getReviewAccuracy(12, controller.signal).then(setData).catch(() => { if (!controller.signal.aborted) setFailed(true); });
    return () => controller.abort();
  }, []);
  if (failed || !data) return null;

  const rows = data.weeks.map(week => ({ ...week, label: short(week.week_start),
    share: week.decided ? week.supported / week.decided : null }));
  const lanes = (["red", "yellow", "green"] as const).map(lane => {
    const totals = data.weeks.reduce((sum, week) => ({ decided: sum.decided + (week.lanes[lane]?.decided ?? 0),
      supported: sum.supported + (week.lanes[lane]?.supported ?? 0) }), { decided: 0, supported: 0 });
    return { lane, ...totals };
  });
  const inconclusive = data.weeks.reduce((sum, week) => sum + week.inconclusive, 0);

  return <section className="card trend-card" aria-label="Ketepatan sistem" data-testid="review-accuracy-trend">
    <div className="card-head">
      <div><h2><Target size={16} className="head-icon" aria-hidden="true" />Ketepatan temuan sistem</h2>
        <p>Dari klaim yang sudah diperiksa petugas, berapa persen yang memang bermasalah. Makin tinggi, makin jarang sistem menandai klaim yang ternyata wajar.</p></div>
      {data.totals.share !== null && <div className="accuracy-total">
        <strong>{formatPercent(data.totals.share)}</strong>
        <span>{formatCount(data.totals.supported)} dari {formatCount(data.totals.decided)} klaim memang bermasalah</span>
      </div>}
    </div>
    {data.totals.decided === 0
      ? <div className="accuracy-empty">
        <strong>Belum ada klaim yang diputuskan petugas dalam 12 minggu terakhir.</strong>
        <span>Angka ini muncul setelah petugas mengisi langkah 2 di halaman klaim: <em>Benar, perlu ditindaklanjuti</em> atau <em>Ternyata wajar</em>.</span>
      </div>
      : <>
        <div className="trend-legend" aria-hidden="true" style={{ marginBottom: 8 }}>
          <span><i className="trend-swatch" style={{ background: colors.supported }} />Benar, perlu ditindaklanjuti</span>
          <span><i className="trend-swatch low" />Ternyata wajar</span>
          {data.policy_changes.length > 0 && <span><i className="accuracy-change-swatch" />Mulai memakai aturan baru</span>}
        </div>
        <div className="chart-box" style={{ height: 240 }} role="img"
          aria-label={`Keputusan verifikator per minggu; secara keseluruhan ${data.totals.share === null ? "—" : formatPercent(data.totals.share)} memang perlu ditindaklanjuti.`}>
          <ResponsiveContainer>
            <BarChart data={rows} margin={{ top: 16, right: 8, bottom: 0, left: -12 }} barCategoryGap="22%">
              <CartesianGrid vertical={false} stroke={colors.grid} />
              <XAxis dataKey="week_start" tickFormatter={short} tick={{ fontSize: 11.5, fill: colors.axis }} axisLine={false} tickLine={false} />
              <YAxis allowDecimals={false} tick={{ fontSize: 11.5, fill: colors.axis }} axisLine={false} tickLine={false} width={40} />
              <Tooltip cursor={{ fill: colors.grid, opacity: 0.4 }}
                contentStyle={{ background: colors.surface, border: `1px solid ${colors.grid}`, borderRadius: 12, color: colors.ink, fontSize: 12.5 }}
                labelStyle={{ color: colors.ink, fontWeight: 700 }} itemStyle={{ color: colors.ink }}
                labelFormatter={(_label, payload) => {
                  const week = payload?.[0]?.payload as (typeof rows)[number] | undefined;
                  return week ? `Minggu ${short(week.week_start)}${week.share === null ? "" : ` · ${formatPercent(week.share)} benar`}` : "";
                }}
                formatter={(value: number, name: string) => [formatCount(value), name]} />
              {data.policy_changes.map(change => <ReferenceLine key={change.version} x={weekOf(change.date)} stroke={colors.change}
                strokeDasharray="4 4" label={{ value: "Aturan baru", position: "top", fill: colors.axis, fontSize: 11 }} />)}
              <Bar dataKey="not_supported" name="Ternyata wajar" stackId="d" fill={colors.notSupported} stroke={colors.surface} isAnimationActive={false} />
              <Bar dataKey="supported" name="Benar, perlu ditindaklanjuti" stackId="d" fill={colors.supported} stroke={colors.surface}
                radius={[4, 4, 0, 0]} isAnimationActive={false} />
            </BarChart>
          </ResponsiveContainer>
        </div>
        <ul className="accuracy-lanes">
          {lanes.map(item => <li key={item.lane}>
            <span><LaneDot lane={item.lane} />{LANES[item.lane].name}</span>
            <strong>{item.decided ? formatPercent(item.supported / item.decided) : "—"}</strong>
            <small>{item.decided ? `${formatCount(item.supported)} dari ${formatCount(item.decided)} klaim memang bermasalah` : "Belum ada keputusan"}</small>
          </li>)}
        </ul>
      </>}
    {data.totals.decided > 0 && <p className="fine-print" style={{ marginTop: 10 }}>
      Mencakup semua analisis dalam 12 minggu terakhir. Setiap klaim dihitung sekali, menurut keputusan terakhirnya.
      {inconclusive > 0 ? ` ${formatCount(inconclusive)} klaim yang "belum bisa disimpulkan" tidak dihitung.` : ""}
    </p>}
  </section>;
}
