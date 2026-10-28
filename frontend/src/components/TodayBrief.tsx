import { ArrowRight, Building2, Clock3, MapPinned, ShieldAlert, Sun } from "lucide-react";
import { Link } from "react-router-dom";
import type { RunResult, RunTrendItem } from "../api/client";
import { formatCount } from "./Display";
import { provinceName } from "./provinces";

const DAY = 86_400_000;

/** Whole days since the analysis was created (0 = today). */
export function analysisAgeDays(createdAt: string, now = Date.now()): number {
  const created = Date.parse(createdAt);
  return Number.isNaN(created) ? 0 : Math.max(0, Math.floor((now - created) / DAY));
}

/** Age tone of the review queue: amber after a week, red after two weeks with claims still unreviewed. */
export function ageTone(days: number, unreviewed: number): "neutral" | "warn" | "danger" {
  if (unreviewed <= 0) return "neutral";
  return days > 14 ? "danger" : days > 7 ? "warn" : "neutral";
}

export function ageText(days: number): string {
  return days === 0 ? "hari ini" : days === 1 ? "kemarin" : `${formatCount(days)} hari lalu`;
}

type Line = { icon: typeof Sun; tone: string; text: string; to: string; testId: string };

/** A few sentences composed from the analysis (fixed rules, no language model), each opening the page it is about. */
export function TodayBrief({ result, runQuery, createdAt, history, unreviewed }: {
  result: RunResult; runQuery: string; createdAt: string; history: RunTrendItem[]; unreviewed: number | null;
}) {
  const lanes = result.action_policy.lane_counts ?? {};
  const red = lanes.red ?? 0, yellow = lanes.yellow ?? 0;
  const lines: Line[] = [];

  const previous = history.length >= 2 ? history[history.length - 2].lane_counts : null;
  const change = previous ? red - previous.red : null;
  lines.push({
    icon: ShieldAlert, tone: red ? "danger" : "neutral", to: `/cases${runQuery}&lane=red`, testId: "brief-lanes",
    text: `${formatCount(red)} klaim risiko tinggi dan ${formatCount(yellow)} risiko sedang dari ${formatCount(result.records_considered)} klaim yang dianalisis`
      + (change === null || change === 0 ? "." : `; risiko tinggi ${change > 0 ? "naik" : "turun"} ${formatCount(Math.abs(change))} dari analisis sebelumnya.`),
  });

  const groups = result.facility_groups;
  if (groups) {
    const high = groups.level_counts.high ?? 0;
    const top = groups.groups[0];
    lines.push({
      icon: Building2, tone: high ? "danger" : "neutral", to: `/facilities${runQuery}`, testId: "brief-facilities",
      text: high ? `${formatCount(high)} kelompok faskes berisiko tinggi; paling mendesak ${top.title}, ${top.region.toLowerCase().replace(/\b\w/g, c => c.toUpperCase())}.`
        : "Tidak ada kelompok faskes berisiko tinggi.",
    });
    const provinces = groups.fairness?.dimensions.find(item => item.field === "province_code")?.rows
      .filter(row => (row.ratio_to_overall ?? 0) >= 2) ?? [];
    if (provinces.length) lines.push({
      icon: MapPinned, tone: "warn", to: `/map${runQuery}`, testId: "brief-map",
      text: `${formatCount(provinces.length)} provinsi di atas 2× rata-rata nasional: ${provinces.slice(0, 3).map(row => (row.code ? provinceName(row.code) : row.label)).join(", ")}.`,
    });
  }

  if (unreviewed !== null) {
    const days = analysisAgeDays(createdAt);
    lines.push({
      icon: Clock3, tone: ageTone(days, unreviewed), to: `/cases${runQuery}&state=not_started`, testId: "brief-age",
      text: unreviewed ? `${formatCount(unreviewed)} klaim berisiko belum ditinjau; analisis ini dibuat ${ageText(days)}.`
        : "Semua klaim berisiko pada analisis ini sudah ditinjau.",
    });
  }

  return <section className="today-brief card" aria-label="Ringkasan hari ini" data-testid="today-brief">
    <div className="today-brief-head"><Sun size={16} aria-hidden="true" /><h2>Ringkasan hari ini</h2></div>
    <ul>{lines.map(({ icon: Icon, tone, text, to, testId }) => <li key={testId} data-testid={testId}>
      <Link to={to} className={`today-line brief-${tone}`}>
        <span className="today-icon"><Icon size={15} aria-hidden="true" /></span>
        <span className="today-text">{text}</span>
        <ArrowRight size={14} className="today-go" aria-hidden="true" />
      </Link>
    </li>)}</ul>
  </section>;
}
