import { useEffect, useRef, useState } from "react";
import { ArrowRight, Building2, CircleHelp, ShieldAlert, TriangleAlert, X } from "lucide-react";
import { Link } from "react-router-dom";
import type { FacilityGroup, RunResult } from "../api/client";
import { LOGIN_ALERT_KEY } from "../auth/AuthContext";
import { Term } from "./Term";
import { FRAUD_PATTERNS, formatCount, formatRupiah, indicatorLabel, shortRef, titleCase } from "./Display";

/** Pattern colours: distinct in lightness as well as hue, used only for the pattern breakdown. */
export const PATTERN_COLORS: Record<string, string> = {
  repeat_billing: "#b91c1c", upcoding_stay: "#ea580c", phantom_billing: "#0f766e", cloning: "#6d28d9", fictitious_claim: "#64748b",
};

/** The pattern most high-risk claims of a facility group show (all flagged claims when it has no high-risk claim). */
export function dominantPattern(group: FacilityGroup): { code: string; count: number } | null {
  const counts = group.pattern_counts_red && Object.keys(group.pattern_counts_red).length ? group.pattern_counts_red : group.pattern_counts;
  const top = Object.entries(counts ?? {}).sort((a, b) => b[1] - a[1])[0];
  return top ? { code: top[0], count: top[1] } : null;
}

/** High-risk facility groups that show a fraud pattern, most urgent first (the server's order). */
export function alertGroups(result: RunResult, limit = 5): FacilityGroup[] {
  return (result.facility_groups?.groups ?? []).filter(group => group.level === "high" && dominantPattern(group)).slice(0, limit);
}


/**
 * The first block after sign-in: how many high-risk claims there are, what they are billed for and where that
 * number comes from, and which patterns hold the money.
 */
export function RiskFocus({ result, runQuery }: { result: RunResult; runQuery: string }) {
  const [explainOpen, setExplainOpen] = useState(false);
  const lanes = result.action_policy.lane_counts ?? {};
  const red = lanes.red ?? 0;
  const exposure = result.facility_groups?.exposure?.status === "available" ? result.facility_groups.exposure : null;
  const patterns = (result.facility_groups?.pattern_summary?.patterns ?? []).filter(row => row.red > 0)
    .sort((a, b) => b.billed_red - a.billed_red);
  const patternTotal = patterns.reduce((sum, row) => sum + row.billed_red, 0);
  const byClaims = [...patterns].sort((a, b) => b.red - a.red)[0];
  const byMoney = patterns[0];
  const queue = `/cases${runQuery}&lane=red`;
  return <section className="risk-focus" aria-labelledby="risk-focus-title" data-testid="risk-focus">
    <div className="risk-focus-main">
      <span className="risk-focus-eyebrow"><ShieldAlert size={14} aria-hidden="true" />Fokus utama: risiko tinggi</span>
      <h2 id="risk-focus-title" className="risk-focus-figures">
        <span className="risk-focus-num"><CountNumber value={red} /></span> <small>klaim</small>
        {exposure && <span className="risk-focus-money" data-testid="focus-amount">{formatRupiah(exposure.billed_high)}</span>}
      </h2>
      {exposure && <p className="risk-focus-source">Jumlah <Term id="fkl47">tagihan rumah sakit (FKL47)</Term> untuk {formatCount(red)} klaim ini, sebelum verifikasi. Bukan nilai kerugian.</p>}
      <div className="risk-focus-actions">
        <Link className="risk-focus-cta" to={queue} data-testid="lane-card-red">Periksa {formatCount(red)} klaim <ArrowRight size={14} aria-hidden="true" /></Link>
        {exposure && <button type="button" className="risk-focus-explain" onClick={() => setExplainOpen(true)} data-testid="focus-explain">
          <CircleHelp size={15} aria-hidden="true" />Dari mana {formatRupiah(exposure.billed_high)}?</button>}
      </div>
    </div>
    {patterns.length > 0 && <div className="risk-focus-patterns">
      <span className="risk-focus-label">Nilai tagihan risiko tinggi per modus</span>
      <div className="pattern-stack" role="img" aria-label={patterns.map(row => `${FRAUD_PATTERNS[row.pattern]?.label ?? row.pattern} ${Math.round(100 * row.billed_red / patternTotal)} persen`).join(", ")}>
        {patterns.map(row => <span key={row.pattern} style={{ width: `${Math.max(0.6, 100 * row.billed_red / patternTotal)}%`, background: PATTERN_COLORS[row.pattern] }} />)}
      </div>
      <ul>{patterns.map(row => <li key={row.pattern}>
        <Link to={`${queue}&check=${encodeURIComponent(`modus:${row.pattern}`)}`} className="risk-focus-row" title={FRAUD_PATTERNS[row.pattern]?.hint}
          data-testid={`focus-pattern-${row.pattern}`}>
          <span className="risk-focus-name"><i style={{ background: PATTERN_COLORS[row.pattern] }} aria-hidden="true" />{FRAUD_PATTERNS[row.pattern]?.label ?? row.pattern}</span>
          <span className="risk-focus-count">{formatCount(row.red)} klaim</span>
          <span className="risk-focus-value">{formatRupiah(row.billed_red)}</span>
        </Link>
      </li>)}</ul>
      {byClaims && byMoney && byClaims.pattern !== byMoney.pattern && <p className="risk-focus-note">
        {FRAUD_PATTERNS[byClaims.pattern]?.label} paling banyak klaimnya, {FRAUD_PATTERNS[byMoney.pattern]?.label?.toLowerCase()} paling besar uangnya. Satu klaim bisa punya dua modus.</p>}
    </div>}
    {explainOpen && exposure && <BilledBreakdown result={result} runQuery={runQuery} onClose={() => setExplainOpen(false)} />}
  </section>;
}

function CountNumber({ value }: { value: number }) {
  return <>{formatCount(value)}</>;
}

/** Where the high-risk amount comes from: its source, its share, per pattern, per facility group, and the largest claims. */
export function BilledBreakdown({ result, runQuery, onClose }: { result: RunResult; runQuery: string; onClose: () => void }) {
  const closeRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    closeRef.current?.focus();
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  const exposure = result.facility_groups?.exposure;
  if (!exposure) return null;
  const red = result.action_policy.lane_counts?.red ?? 0;
  const runId = new URLSearchParams(runQuery).get("run_id") ?? "";
  const patterns = (result.facility_groups?.pattern_summary?.patterns ?? []).filter(row => row.red > 0).sort((a, b) => b.billed_red - a.billed_red);
  const groups = [...(result.facility_groups?.groups ?? [])].filter(group => (group.billed_high ?? 0) > 0)
    .sort((a, b) => (b.billed_high ?? 0) - (a.billed_high ?? 0)).slice(0, 5);
  const top = result.overview?.top_high_claims ?? [];
  const share = exposure.billed_total ? exposure.billed_high / exposure.billed_total : null;
  return <div className="palette-scrim" onMouseDown={onClose}>
    <div className="breakdown" role="dialog" aria-modal="true" aria-labelledby="breakdown-title" data-testid="billed-breakdown"
      onMouseDown={event => event.stopPropagation()}>
      <div className="breakdown-head">
        <h2 id="breakdown-title">Rincian nilai tagihan risiko tinggi: {formatRupiah(exposure.billed_high)}</h2>
        <button ref={closeRef} type="button" className="icon-close" onClick={onClose} aria-label="Tutup rincian"><X size={16} /></button>
      </div>
      <div className="breakdown-facts">
        <div><span>Asal angka</span><p>Jumlah kolom FKL47 (tagihan rumah sakit sebelum verifikasi) dari {formatCount(red)} klaim berjalur merah.</p></div>
        {share !== null && <div><span>Porsi dari seluruh tagihan</span><strong>{(share * 100).toLocaleString("id-ID", { maximumFractionDigits: 1 })}%</strong>
          <p>dari {formatRupiah(exposure.billed_total)} tagihan {formatCount(result.records_considered)} klaim</p></div>}
        <div><span>Bukan</span><p>nilai kerugian. Kerugian baru diketahui setelah verifikator dan audit memutuskan.</p></div>
      </div>
      {patterns.length > 0 && <>
        <h3>Per modus</h3>
        <ul className="breakdown-bars">{patterns.map(row => <li key={row.pattern}>
          <span className="breakdown-bar-label">{FRAUD_PATTERNS[row.pattern]?.label ?? row.pattern} · {formatCount(row.red)} klaim</span>
          <strong>{formatRupiah(row.billed_red)}</strong>
          <span className="breakdown-bar" aria-hidden="true"><i style={{ width: `${100 * row.billed_red / patterns[0].billed_red}%`, background: PATTERN_COLORS[row.pattern] }} /></span>
        </li>)}</ul>
      </>}
      {groups.length > 0 && <>
        <h3>Kelompok faskes dengan nilai terbesar</h3>
        <ul className="breakdown-bars">{groups.map(group => <li key={group.group_id}>
          <Link className="breakdown-bar-label" to={`/facilities/${encodeURIComponent(group.group_id)}${runQuery}`}>{group.title} · {titleCase(group.region)}</Link>
          <strong>{formatRupiah(group.billed_high ?? 0)}</strong>
          <span className="breakdown-bar" aria-hidden="true"><i style={{ width: `${100 * (group.billed_high ?? 0) / (groups[0].billed_high ?? 1)}%` }} /></span>
        </li>)}</ul>
      </>}
      {top.length > 0 && <>
        <h3>Klaim dengan tagihan terbesar</h3>
        <div className="table-scroll"><table className="data-table">
          <thead><tr><th>Ref. klaim</th><th>Temuan</th><th>Modus</th><th className="num">Tagihan</th></tr></thead>
          <tbody>{top.map(item => <tr key={item.case_id}>
            <td><Link to={`/runs/${encodeURIComponent(runId)}/cases/${encodeURIComponent(item.case_id)}`}>{shortRef(item.case_id)}</Link></td>
            <td>{item.indicators.filter(code => code !== "near_duplicate_claim_candidate").map(indicatorLabel).join(" + ") || "Klaim ditandai"}</td>
            <td>{item.fraud_patterns.map(code => FRAUD_PATTERNS[code]?.label ?? code).join(", ")}</td>
            <td className="num"><strong>{formatRupiah(item.amount)}</strong></td>
          </tr>)}</tbody>
        </table></div>
      </>}
      <div className="breakdown-actions"><Link className="button button-primary" to={`/cases${runQuery}&lane=red&sort=billed`}>Buka antrean, tagihan terbesar dulu</Link></div>
    </div>
  </div>;
}

const SEEN_KEY = "cir:facility-alert:seen";

function seenRuns(): string[] {
  try { return JSON.parse(window.localStorage.getItem(SEEN_KEY) ?? "[]") as string[]; } catch { return []; }
}

/**
 * Shown after sign-in when facility groups are indicated for a pattern, but only for an analysis this browser has
 * not shown it for yet: the same warning on every sign-in is soon dismissed unread.
 */
export function FacilityAlert({ result, runQuery }: { result: RunResult; runQuery: string }) {
  const groups = alertGroups(result);
  const runId = new URLSearchParams(runQuery).get("run_id") ?? "";
  const [open, setOpen] = useState(() => {
    try { return window.sessionStorage.getItem(LOGIN_ALERT_KEY) === "1" && !seenRuns().includes(runId); } catch { return false; }
  });
  const closeRef = useRef<HTMLButtonElement>(null);
  const close = () => {
    try {
      window.sessionStorage.removeItem(LOGIN_ALERT_KEY);
      window.localStorage.setItem(SEEN_KEY, JSON.stringify([runId, ...seenRuns().filter(id => id !== runId)].slice(0, 30)));
    } catch { /* nothing to remember */ }
    setOpen(false);
  };
  useEffect(() => {
    if (!open || !groups.length) return;
    closeRef.current?.focus();
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") close(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, groups.length]);
  if (!open || !groups.length) return null;
  return <div className="palette-scrim" onMouseDown={close}>
    <div className="facility-alert" role="alertdialog" aria-modal="true" aria-labelledby="facility-alert-title"
      aria-describedby="facility-alert-desc" data-testid="facility-alert" onMouseDown={event => event.stopPropagation()}>
      <div className="facility-alert-head">
        <span className="facility-alert-icon"><TriangleAlert size={18} aria-hidden="true" /></span>
        <div>
          <h2 id="facility-alert-title">Peringatan: {formatCount(groups.length)} kelompok faskes terindikasi modus</h2>
          <p id="facility-alert-desc">Hasil analisis yang belum Anda lihat. Ini prioritas pemeriksaan, bukan bukti kecurangan.</p>
        </div>
        <button ref={closeRef} type="button" className="icon-close" onClick={close} aria-label="Tutup peringatan"><X size={16} /></button>
      </div>
      <ul className="facility-alert-list">{groups.map(group => {
        const top = dominantPattern(group)!;
        return <li key={group.group_id}>
          <Link to={`/facilities/${encodeURIComponent(group.group_id)}${runQuery}`} onClick={close} className="facility-alert-row"
            data-testid="facility-alert-row">
            <span className="facility-alert-name"><Building2 size={14} aria-hidden="true" />{group.title}<small>{titleCase(group.region)}</small></span>
            <span className="facility-alert-pattern">Indikasi <strong>{FRAUD_PATTERNS[top.code]?.label ?? top.code}</strong> · {formatCount(top.count)} klaim</span>
            <span className="facility-alert-meta">{formatCount(group.lane_counts.red)} risiko tinggi
              {typeof group.billed_high === "number" ? ` · ${formatRupiah(group.billed_high)}` : ""}</span>
          </Link>
        </li>;
      })}</ul>
      <div className="facility-alert-actions">
        <Link className="button button-secondary" to={`/facilities${runQuery}`} onClick={close}>Lihat semua faskes</Link>
        <Link className="button button-primary" to={`/cases${runQuery}&lane=red`} onClick={close}>Mulai periksa risiko tinggi</Link>
      </div>
    </div>
  </div>;
}
