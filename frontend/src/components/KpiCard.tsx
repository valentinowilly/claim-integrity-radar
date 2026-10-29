import { useId, type ReactNode } from "react";
import { ArrowDownRight, ArrowUpRight, Minus, type LucideIcon } from "lucide-react";
import { Link } from "react-router-dom";
import { Area, AreaChart, ResponsiveContainer, YAxis } from "recharts";
import { useThemeColors } from "../theme/theme";
import { CountUp, formatCount } from "./Display";

export type KpiTone = "brand" | "red" | "yellow" | "neutral";
/** Whether a rise is good news, bad news, or neither (claim volume). */
export type KpiDirection = "up-is-bad" | "up-is-good" | "neutral";

const TONE_TOKENS = { brand: "--chart-1", red: "--lane-red", yellow: "--lane-yellow", neutral: "--text-muted" } as const;

/** One headline number with its change against the previous analysis and a small trend of the latest analyses. */
export function KpiCard({ icon: Icon, label, value, format = formatCount, history, tone = "brand", direction = "neutral",
  to, footer, testId }: {
  icon: LucideIcon; label: string; value: number; format?: (value: number) => string;
  /** Values of the latest analyses, oldest first, ending with this one; null where an analysis has no number. */
  history: Array<number | null>; tone?: KpiTone; direction?: KpiDirection; to?: string; footer?: ReactNode; testId?: string;
}) {
  const colors = useThemeColors(TONE_TOKENS);
  const gradientId = `spark-${useId().replace(/:/g, "")}`;
  const points = history.filter((item): item is number => typeof item === "number");
  const previous = points.length >= 2 ? points[points.length - 2] : null;
  const change = previous === null ? null : value - previous;
  const body = <>
    <div className="kpi2-top">
      <span className={`kpi2-icon tone-${tone}`}><Icon size={18} aria-hidden="true" /></span>
      <span className="kpi2-label">{label}</span>
      {to && <ArrowUpRight className="kpi2-go" size={16} aria-hidden="true" />}
    </div>
    <div className="kpi2-main">
      <div className="kpi2-value"><CountUp value={value} format={format} /></div>
      {points.length >= 2 && <div className="kpi2-spark" aria-hidden="true">
        <ResponsiveContainer>
          <AreaChart data={points.map((item, index) => ({ index, item }))} margin={{ top: 2, right: 0, bottom: 2, left: 0 }}>
            <defs><linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={colors[tone]} stopOpacity={0.35} />
              <stop offset="100%" stopColor={colors[tone]} stopOpacity={0} />
            </linearGradient></defs>
            <YAxis hide domain={["dataMin", "dataMax"]} />
            <Area type="monotone" dataKey="item" stroke={colors[tone]} strokeWidth={2} fill={`url(#${gradientId})`}
              isAnimationActive={false} dot={false} />
          </AreaChart>
        </ResponsiveContainer>
      </div>}
    </div>
    <div className="kpi2-foot"><Delta change={change} previous={previous} format={format} direction={direction} /></div>
    {footer && <div className="kpi2-extra">{footer}</div>}
  </>;
  return to
    ? <Link className="kpi2 card" to={to} data-testid={testId}>{body}</Link>
    : <article className="kpi2 card" data-testid={testId}>{body}</article>;
}

function Delta({ change, previous, format, direction }: {
  change: number | null; previous: number | null; format: (value: number) => string; direction: KpiDirection;
}) {
  if (change === null || previous === null) return <span className="kpi2-delta tone-neutral">Analisis pertama</span>;
  if (change === 0) return <span className="kpi2-delta tone-neutral"><Minus size={13} aria-hidden="true" />Sama dengan analisis sebelumnya</span>;
  const up = change > 0;
  const tone = direction === "neutral" ? "neutral" : (up === (direction === "up-is-bad")) ? "bad" : "good";
  // A share above 3x says little (the earlier analysis was often of another file); the count change stays.
  const ratio = previous > 0 ? Math.abs(change) / previous : Infinity;
  const percent = ratio <= 3 ? ` (${up ? "+" : "−"}${Math.round(ratio * 100)}%)` : "";
  return <><span className={`kpi2-delta tone-${tone}`} title="Dibandingkan dengan analisis sebelumnya">
    {up ? <ArrowUpRight size={13} aria-hidden="true" /> : <ArrowDownRight size={13} aria-hidden="true" />}
    {up ? "+" : "−"}{format(Math.abs(change))}{percent}
  </span><span className="kpi2-delta-note">vs analisis sebelumnya</span></>;
}
