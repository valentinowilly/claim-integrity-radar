import { formatCount } from "./Display";

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
