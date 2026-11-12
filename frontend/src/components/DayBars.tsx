import { CalendarDays } from "lucide-react";
import { formatCount, formatRupiah } from "./Display";

/** Below this many days a column chart is mostly empty space; the days are listed as rows instead. */
export const FEW_DAYS = 7;

const DAY = new Intl.DateTimeFormat("id-ID", { weekday: "short", day: "numeric", month: "short" });

function parseDay(date: string): Date {
  const [year, month, day] = date.split("-").map(Number);
  return new Date(year, (month || 1) - 1, day || 1);
}

/** Risky claims of a few service days: one row per day, a stacked bar (high, medium) and its billed value. */
export function DayBars({ days }: { days: Array<{ date: string; high: number; medium: number; billed_high_or_medium?: number | null }> }) {
  const most = Math.max(1, ...days.map(day => day.high + day.medium));
  return <ul className="day-bars" aria-label="Klaim berisiko per hari">
    {days.map(day => {
      const total = day.high + day.medium;
      return <li key={day.date}>
        <span className="day-bars-date"><CalendarDays size={14} aria-hidden="true" />{DAY.format(parseDay(day.date))}</span>
        <span className="day-bars-track" role="img" aria-label={`${formatCount(day.high)} risiko tinggi, ${formatCount(day.medium)} risiko sedang`}>
          <i className="is-high" style={{ width: `${100 * day.high / most}%` }} />
          <i className="is-medium" style={{ width: `${100 * day.medium / most}%` }} />
        </span>
        <span className="day-bars-count"><b>{formatCount(total)}</b> klaim
          <small><em className="is-high">{formatCount(day.high)}</em> tinggi · <em className="is-medium">{formatCount(day.medium)}</em> sedang</small></span>
        {typeof day.billed_high_or_medium === "number" && <strong className="day-bars-money">{formatRupiah(day.billed_high_or_medium)}</strong>}
      </li>;
    })}
  </ul>;
}
