import { createPortal } from "react-dom";
import { useEffect, useRef, useState } from "react";
import { ArrowRight, Building2, Calculator, Files, Filter, Info, ShieldAlert, Sigma, X } from "lucide-react";
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
export function RiskFocus({ result, runQuery, onExplain }: { result: RunResult; runQuery: string; onExplain: (lane: AmountLane) => void }) {
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
        {exposure && <button type="button" className="risk-focus-explain" onClick={() => onExplain("red")} data-testid="focus-explain">
          <Calculator size={15} aria-hidden="true" />Dari mana {formatRupiah(exposure.billed_high)}?</button>}
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
  </section>;
}

function CountNumber({ value }: { value: number }) {
  return <>{formatCount(value)}</>;
}

export type AmountLane = "red" | "yellow" | "all";
const LANE_TEXT: Record<AmountLane, { label: string; short: string }> = {
  red: { label: "Risiko tinggi", short: "risiko tinggi" },
  yellow: { label: "Risiko sedang", short: "risiko sedang" },
  all: { label: "Semua berisiko", short: "risiko tinggi dan sedang" },
};

/** How every billed amount on screen is computed: the steps, the share, per pattern, per facility group, largest claims. */
export function BilledBreakdown({ result, runQuery, onClose, initialLane = "red" }: {
  result: RunResult; runQuery: string; onClose: () => void; initialLane?: AmountLane;
}) {
  const [lane, setLane] = useState<AmountLane>(initialLane);
  const closeRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    closeRef.current?.focus();
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  const exposure = result.facility_groups?.exposure;
  if (!exposure) return null;
  const counts = result.action_policy.lane_counts ?? {};
  const claims = lane === "red" ? counts.red ?? 0 : lane === "yellow" ? counts.yellow ?? 0 : (counts.red ?? 0) + (counts.yellow ?? 0);
  const billed = lane === "red" ? exposure.billed_high : lane === "yellow" ? exposure.billed_medium : exposure.billed_high_or_medium;
  const share = exposure.billed_total ? billed / exposure.billed_total : null;
  const runId = new URLSearchParams(runQuery).get("run_id") ?? "";
  const patternValue = (row: { billed_red: number; billed_yellow: number }) => lane === "red" ? row.billed_red : lane === "yellow" ? row.billed_yellow : row.billed_red + row.billed_yellow;
  const patternCount = (row: { red: number; yellow: number }) => lane === "red" ? row.red : lane === "yellow" ? row.yellow : row.red + row.yellow;
  const patterns = (result.facility_groups?.pattern_summary?.patterns ?? []).filter(row => patternCount(row) > 0).sort((a, b) => patternValue(b) - patternValue(a));
  const groupValue = (group: FacilityGroup) => lane === "red" ? group.billed_high ?? 0
    : lane === "yellow" ? Math.max(0, (group.billed_high_or_medium ?? 0) - (group.billed_high ?? 0)) : group.billed_high_or_medium ?? 0;
  const groups = [...(result.facility_groups?.groups ?? [])].filter(group => groupValue(group) > 0).sort((a, b) => groupValue(b) - groupValue(a)).slice(0, 5);
  const top = lane === "yellow" ? result.overview?.top_medium_claims ?? []
    : lane === "red" ? result.overview?.top_high_claims ?? []
    : [...(result.overview?.top_high_claims ?? []), ...(result.overview?.top_medium_claims ?? [])].sort((a, b) => b.amount - a.amount).slice(0, 10);
  const percent = (value: number) => `${(value * 100).toLocaleString("id-ID", { maximumFractionDigits: 1 })}%`;
  const queueLane = lane === "all" ? "all" : lane;
  return createPortal(<div className="palette-scrim" onMouseDown={onClose}>
    <div className="breakdown" role="dialog" aria-modal="true" aria-labelledby="breakdown-title" data-testid="billed-breakdown"
      onMouseDown={event => event.stopPropagation()}>
      <div className="breakdown-head">
        <div><span className="breakdown-kicker"><Calculator size={15} aria-hidden="true" />Cara menghitung nilai tagihan</span>
          <h2 id="breakdown-title">{LANE_TEXT[lane].label}: {formatRupiah(billed)}</h2></div>
        <button ref={closeRef} type="button" className="icon-close" onClick={onClose} aria-label="Tutup rincian"><X size={16} /></button>
      </div>
      <div className="segmented-pill breakdown-lanes" role="group" aria-label="Pilih tingkat risiko">
        {(["red", "yellow", "all"] as const).map(key => <button key={key} type="button" aria-pressed={lane === key} onClick={() => setLane(key)}>
          {key !== "all" && <i className={`lane-chip is-${key}`} aria-hidden="true" />}{LANE_TEXT[key].label}</button>)}
      </div>

      <ol className="calc-flow" aria-label="Langkah perhitungan">
        <li><span className="calc-icon"><Files size={18} aria-hidden="true" /></span>
          <b>{formatCount(result.records_considered)}</b><span>klaim dianalisis</span><small>tagihan {formatRupiah(exposure.billed_total)}</small></li>
        <li className={`calc-step is-${lane}`}><span className="calc-icon"><Filter size={18} aria-hidden="true" /></span>
          <b>{formatCount(claims)}</b><span>klaim {LANE_TEXT[lane].short}</span><small>ditandai pemeriksaan</small></li>
        <li className={`calc-result is-${lane}`}><span className="calc-icon"><Sigma size={18} aria-hidden="true" /></span>
          <b>{formatRupiah(billed)}</b><span>jumlah kolom <Term id="fkl47">FKL47</Term></span><small>{share !== null ? `${percent(share)} dari total` : "sebelum verifikasi"}</small></li>
      </ol>
      {share !== null && <div className="calc-share" role="img" aria-label={`${percent(share)} dari seluruh tagihan`}>
        <i className={`is-${lane}`} style={{ width: `${Math.max(0.8, share * 100)}%` }} /></div>}
      <p className="breakdown-warning"><Info size={14} aria-hidden="true" />Tagihan sebelum verifikasi, <strong>bukan nilai kerugian</strong>. Kerugian baru diketahui setelah verifikator dan audit memutuskan.</p>

      <div className="breakdown-cols">
        {patterns.length > 0 && <section>
          <h3>Per modus</h3>
          <ul className="breakdown-bars">{patterns.map(row => <li key={row.pattern}>
            <span className="breakdown-bar-label"><i style={{ background: PATTERN_COLORS[row.pattern] }} aria-hidden="true" />{FRAUD_PATTERNS[row.pattern]?.label ?? row.pattern} · {formatCount(patternCount(row))}</span>
            <strong>{formatRupiah(patternValue(row))}</strong>
            <span className="breakdown-bar" aria-hidden="true"><i style={{ width: `${100 * patternValue(row) / patternValue(patterns[0])}%`, background: PATTERN_COLORS[row.pattern] }} /></span>
          </li>)}</ul>
          <small className="breakdown-hint">Satu klaim bisa punya dua modus, jadi jumlah per modus bisa melebihi total.</small>
        </section>}
        {groups.length > 0 && <section>
          <h3>Kelompok faskes terbesar</h3>
          <ul className="breakdown-bars">{groups.map(group => <li key={group.group_id}>
            <Link className="breakdown-bar-label" to={`/facilities/${encodeURIComponent(group.group_id)}${runQuery}`}>{group.title} · {titleCase(group.region)}</Link>
            <strong>{formatRupiah(groupValue(group))}</strong>
            <span className="breakdown-bar" aria-hidden="true"><i style={{ width: `${100 * groupValue(group) / groupValue(groups[0])}%` }} /></span>
          </li>)}</ul>
        </section>}
      </div>
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
      <div className="breakdown-actions"><Link className="button button-primary" to={`/cases${runQuery}&lane=${queueLane}&sort=billed`} onClick={onClose}>
        Buka antrean, tagihan terbesar dulu</Link></div>
    </div>
  </div>, document.body);
}

/** A small "how is this computed?" button placed next to a rupiah figure. */
export function AmountHelp({ onClick, label }: { onClick: () => void; label: string }) {
  return <button type="button" className="amount-help" onClick={event => { event.preventDefault(); event.stopPropagation(); onClick(); }}
    aria-label={label} title={label}><Calculator size={14} aria-hidden="true" /></button>;
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
  const highRisk = result.action_policy.lane_counts?.red ?? 0;
  // Mentor note: high risk is put in front of the verifier at every sign-in, as a summary screen. "Baru" marks an
  // analysis this browser has not shown yet.
  const [open, setOpen] = useState(() => {
    try { return window.sessionStorage.getItem(LOGIN_ALERT_KEY) === "1"; } catch { return false; }
  });
  const [isNew] = useState(() => !seenRuns().includes(runId));
  const closeRef = useRef<HTMLButtonElement>(null);
  const close = () => {
    try {
      window.sessionStorage.removeItem(LOGIN_ALERT_KEY);
      window.localStorage.setItem(SEEN_KEY, JSON.stringify([runId, ...seenRuns().filter(id => id !== runId)].slice(0, 30)));
    } catch { /* nothing to remember */ }
    setOpen(false);
  };
  const shown = open && (highRisk > 0 || groups.length > 0);
  useEffect(() => {
    if (open && !shown) close();  // nothing at high risk: no screen, and no screen later in this session
    if (!shown) return;
    closeRef.current?.focus();
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") close(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shown]);
  if (!shown) return null;
  const red = result.action_policy.lane_counts?.red ?? 0;
  const exposure = result.facility_groups?.exposure?.status === "available" ? result.facility_groups.exposure : null;
  const patterns = (result.facility_groups?.pattern_summary?.patterns ?? []).filter(row => row.red > 0).sort((x, y) => y.billed_red - x.billed_red);
  const patternTotal = patterns.reduce((sum, row) => sum + row.billed_red, 0) || 1;
  const most = Math.max(1, ...groups.map(group => group.billed_high ?? group.lane_counts.red));
  return createPortal(<div className="palette-scrim alert-scrim" onMouseDown={close}>
    <div className="facility-alert" role="alertdialog" aria-modal="true" aria-labelledby="facility-alert-title"
      aria-describedby="facility-alert-desc" data-testid="facility-alert" onMouseDown={event => event.stopPropagation()}>
      <div className="alert-hero">
        <span className="alert-hero-icon"><ShieldAlert size={26} aria-hidden="true" /></span>
        <div className="alert-hero-text">
          <span className="alert-hero-kicker">{isNew ? "Hasil analisis baru" : "Ringkasan risiko hari ini"}</span>
          <h2 id="facility-alert-title">{groups.length ? `${formatCount(groups.length)} kelompok faskes terindikasi modus`
            : `${formatCount(red)} klaim risiko tinggi menunggu pemeriksaan`}</h2>
          <p id="facility-alert-desc">Prioritas pemeriksaan hari ini, bukan bukti kecurangan.</p>
        </div>
        <button ref={closeRef} type="button" className="icon-close alert-close" onClick={close} aria-label="Tutup peringatan"><X size={16} /></button>
      </div>
      <div className="alert-figures">
        <div><b>{formatCount(red)}</b><span>klaim risiko tinggi</span></div>
        {exposure && <div><b>{formatRupiah(exposure.billed_high)}</b><span>tagihan risiko tinggi</span></div>}
        {groups.length > 0 ? <div><b>{formatCount(groups.length)}</b><span>faskes terindikasi</span></div>
          : <div><b>{formatCount(result.action_policy.lane_counts?.yellow ?? 0)}</b><span>klaim risiko sedang</span></div>}
      </div>
      {patterns.length > 0 && <div className="alert-patterns">
        <div className="pattern-stack" aria-hidden="true">{patterns.map(row =>
          <span key={row.pattern} style={{ width: `${Math.max(1, 100 * row.billed_red / patternTotal)}%`, background: PATTERN_COLORS[row.pattern] }} />)}</div>
        <ul>{patterns.slice(0, 4).map(row => <li key={row.pattern}><i style={{ background: PATTERN_COLORS[row.pattern] }} aria-hidden="true" />
          {FRAUD_PATTERNS[row.pattern]?.label ?? row.pattern}<b>{formatCount(row.red)}</b></li>)}</ul>
      </div>}
      {groups.length > 0 && <ul className="facility-alert-list">{groups.map((group, index) => {
        const top = dominantPattern(group)!;
        const value = group.billed_high ?? group.lane_counts.red;
        return <li key={group.group_id}>
          <Link to={`/facilities/${encodeURIComponent(group.group_id)}${runQuery}`} onClick={close} className="facility-alert-row"
            data-testid="facility-alert-row">
            <span className="alert-rank">{index + 1}</span>
            <span className="alert-row-main">
              <span className="facility-alert-name">{group.title}<small>{titleCase(group.region)}</small></span>
              <span className="alert-row-bar" aria-hidden="true"><i style={{ width: `${Math.max(3, 100 * value / most)}%` }} /></span>
              <span className="alert-row-meta"><em style={{ background: PATTERN_COLORS[top.code] }}>{FRAUD_PATTERNS[top.code]?.label ?? top.code}</em>
                {formatCount(group.lane_counts.red)} klaim risiko tinggi</span>
            </span>
            {typeof group.billed_high === "number" && <strong className="alert-row-money">{formatRupiah(group.billed_high)}</strong>}
          </Link>
        </li>;
      })}</ul>}
      <div className="facility-alert-actions">
        <Link className="button button-secondary" to={`/facilities${runQuery}`} onClick={close}><Building2 size={15} aria-hidden="true" />Lihat semua faskes</Link>
        <Link className="button alert-primary" to={`/cases${runQuery}&lane=red&sort=billed`} onClick={close}>Mulai periksa risiko tinggi <ArrowRight size={15} aria-hidden="true" /></Link>
      </div>
    </div>
  </div>, document.body);
}
