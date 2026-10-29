import { useEffect, useState } from "react";
import { ArrowLeft, ArrowRight, FileText, MapPinned, Printer, X } from "lucide-react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { getRunCase, type FacilityGroup, type RunCase, type RunResult } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { EmptyState } from "../components/DataStates";
import {
  LANES, LEVELS, LaneDot, ReadingGuide, formatCount, formatDateTime, indicatorLabel, mlLevel, runTitle, shortRef,
} from "../components/Display";
import { RunSelector, RunStateMessage, SourcePill } from "../components/PersistedRunWorkspace";
import { provinceName } from "../components/provinces";
import { usePersistedRunSnapshot } from "../hooks/usePersistedRunSnapshot";
import { FacilityTable } from "./OverviewPage";

type Level = FacilityGroup["level"];
const LEVEL_FILTERS: Array<[Level | "", string]> = [["", "Semua"], ["high", "Risiko tinggi"], ["medium", "Risiko sedang"], ["low", "Risiko rendah"]];

function useGroups() {
  const snapshot = usePersistedRunSnapshot();
  const result = snapshot.state.status === "success" ? snapshot.state.detail.result : null;
  const runId = snapshot.state.status === "success" ? snapshot.state.detail.run.run_id : "";
  return { ...snapshot, result, runId, runQuery: runId ? `?run_id=${encodeURIComponent(runId)}` : "" };
}

function Head({ title, text, snapshot }: { title: string; text: string; snapshot: ReturnType<typeof useGroups> }) {
  const { state, result, selectRun } = snapshot;
  return <header className="page-head no-print">
    <div><h1>{title}</h1><p>{text}</p></div>
    {state.status === "success" && <div className="page-head-actions">
      {result && <SourcePill source={result.data_source} />}
      <RunSelector runs={state.runs} detail={state.detail} onChange={selectRun} />
    </div>}
  </header>;
}

function NoGroups({ result }: { result: RunResult | null }) {
  if (!result) return <EmptyState title="Hasil analisis tidak tersedia" message="Analisis yang dipilih belum memiliki hasil tersimpan." />;
  return <EmptyState title="Kelompok faskes belum tersedia" message="Jalankan ulang analisis di menu Data & Analisis untuk melihat data per faskes." />;
}

/** All facility groups of one analysis, most urgent first. */
export default function FacilitiesPage() {
  const snapshot = useGroups();
  const { state, result, runQuery, reload } = snapshot;
  const [level, setLevel] = useState<Level | "">("");
  const [params, setParams] = useSearchParams();
  // A province chosen on the risk map (?provinsi=BPS code).
  const province = params.get("provinsi");
  const clearProvince = () => { const next = new URLSearchParams(params); next.delete("provinsi"); setParams(next, { replace: true }); };
  const groups = result?.facility_groups;
  const shown = (groups?.groups ?? []).filter(group => (!level || group.level === level) && (!province || group.province_code === province));
  return <>
    <Head title="Faskes" text="Kelompok faskes diurutkan dari yang paling layak diperiksa lebih dulu." snapshot={snapshot} />
    {state.status !== "success" && <RunStateMessage state={state} retry={reload} />}
    {state.status === "success" && (!groups ? <NoGroups result={result} /> : <>
      <ReadingGuide title="Cara membaca daftar faskes" items={[
        ["Kelompok faskes", "Gabungan wilayah, kepemilikan, jenis, dan kelas faskes. Satu kelompok dapat berisi lebih dari satu rumah sakit."],
        ["Urutan", "Kelompok dengan temuan terbanyak per rekam medis yang perlu diminta ada di atas. Nilai tagihan tidak memengaruhi urutan."],
        ["Tingkat risiko", "Prioritas pemeriksaan, bukan kesimpulan adanya kecurangan."],
        ["Pembanding wilayah", "Kelompok dibandingkan dengan faskes sekelas di provinsi yang sama, sebagai petunjuk tambahan."],
        ["Kelompok kecil", `Kelompok dengan kurang dari ${formatCount(groups.min_claims)} klaim tidak ditampilkan agar faskes tidak dapat dikenali.`],
      ]} />
      <section className="lane-cards" aria-label="Tingkat risiko faskes">
        {(["high", "medium", "low"] as const).map(key => (
          <button key={key} type="button" className={`lane-card ${key === "high" ? "red" : key === "medium" ? "yellow" : "green"}`}
            style={{ textAlign: "left", cursor: "pointer" }} onClick={() => setLevel(level === key ? "" : key)} aria-pressed={level === key}>
            <span className="lane-name">{LEVELS[key].label}</span>
            <span className="big-num">{formatCount(groups.level_counts[key])}</span>
            <span className="lane-meaning">kelompok faskes</span>
          </button>
        ))}
      </section>
      <section className="card" style={{ marginTop: 18 }}>
        <div className="card-head">
          <div><h2>{formatCount(shown.length)} kelompok faskes</h2>
            <p>Hanya kelompok dengan minimal {formatCount(groups.min_claims)} klaim{groups.hidden_group_count > 0 ? `; ${formatCount(groups.hidden_group_count)} kelompok kecil (${formatCount(groups.hidden_claim_count)} klaim) tidak ditampilkan agar faskes tidak dapat dikenali` : ""}.</p></div>
          <div className="queue-tabs" role="group" aria-label="Saring tingkat risiko">
            {LEVEL_FILTERS.map(([value, label]) => <button key={value || "all"} type="button" className="queue-tab" aria-pressed={level === value} onClick={() => setLevel(value)}>{label}</button>)}
          </div>
        </div>
        {province && <div className="filter-chip-row">
          <span className="filter-chip"><MapPinned size={14} aria-hidden="true" />Provinsi: {provinceName(province)}
            <button type="button" onClick={clearProvince} aria-label="Hapus saringan provinsi"><X size={13} /></button></span>
          <Link className="fine-link" to={`/map${runQuery}&provinsi=${encodeURIComponent(province)}`}>Kembali ke peta</Link>
        </div>}
        {shown.length === 0 ? <EmptyState title="Tidak ada kelompok faskes" message={province ? "Tidak ada kelompok faskes yang cukup besar di provinsi ini pada tingkat yang dipilih." : "Tidak ada kelompok pada tingkat ini."} />
          : <FacilityTable groups={shown} runQuery={runQuery} />}
        {groups.groups_truncated && <p className="fine-print" style={{ marginTop: 10 }}>Ditampilkan {formatCount(groups.groups.length)} kelompok teratas dari {formatCount(groups.group_count)}.</p>}
      </section>
    </>)}
  </>;
}

function findGroup(result: RunResult | null, groupId: string) {
  return result?.facility_groups?.groups.find(group => group.group_id === groupId) ?? null;
}

const PEER_TITLES: Record<string, string> = {
  severity: "Rawat inap keparahan II/III",
  special: "Klaim dengan tambahan obat/alat/tindakan khusus",
};

/** Shares of this group against groups of the same class in the same province (a reason, not a level). */
function PeerSignals({ group }: { group: FacilityGroup }) {
  const signals = group.peer_signals ?? [];
  if (!signals.length) return null;
  const top = Math.max(...signals.map(item => Math.max(item.share, item.peer_share)), 0.0001);
  return <div className="peer-signals" data-testid="peer-signals">
    <strong>Dibanding faskes sekelas di provinsi yang sama</strong>
    {signals.map(item => <div className="peer-signal" key={item.kind}>
      <span className="peer-signal-title">{PEER_TITLES[item.kind] ?? item.kind}
        {item.ratio ? <em> · {item.ratio.toLocaleString("id-ID", { maximumFractionDigits: 1 })}× lebih tinggi</em> : null}</span>
      <div className="peer-bar"><span>Faskes ini</span><div><i style={{ width: `${(item.share / top) * 100}%` }} /></div><b>{pct(item.share)}</b></div>
      <div className="peer-bar peer"><span>{item.peer_groups} kelompok pembanding</span><div><i style={{ width: `${(item.peer_share / top) * 100}%` }} /></div><b>{pct(item.peer_share)}</b></div>
    </div>)}
    <small>Petunjuk tambahan untuk diperiksa; tidak mengubah tingkat risiko atau urutan faskes.</small>
  </div>;
}

function pct(value: number): string {
  return `${(value * 100).toLocaleString("id-ID", { maximumFractionDigits: value < 0.1 ? 1 : 0 })}%`;
}

/** One facility group: verdict in one sentence, traffic light, reasons and sample claims. */
export function FacilityDetailPage() {
  const { groupId = "" } = useParams();
  const snapshot = useGroups();
  const { state, result, runId, runQuery, reload } = snapshot;
  const group = findGroup(result, groupId);
  const [allSamples, setAllSamples] = useState(false);
  const samples = group ? (allSamples ? group.sample_case_ids : group.sample_case_ids.slice(0, SAMPLES_SHOWN)) : [];
  return <>
    <Head title="Rincian faskes" text="Kesimpulan singkat, alasan, dan klaim yang perlu diminta rekam medisnya." snapshot={snapshot} />
    {state.status !== "success" && <RunStateMessage state={state} retry={reload} />}
    {state.status === "success" && (!group ? <section className="card">
      <Link className="button button-secondary button-compact" to={`/facilities${runQuery}`}><ArrowLeft size={14} />Kembali ke daftar faskes</Link>
      <EmptyState title="Kelompok faskes tidak ditemukan" message="Kelompok ini tidak ada pada analisis yang dipilih." />
    </section> : <div className="stack">
      <section className="card" aria-label="Kesimpulan faskes">
        <Link className="button button-secondary button-compact" to={`/facilities${runQuery}`} style={{ marginBottom: 14 }}><ArrowLeft size={14} />Daftar faskes</Link>
        <div className="case-hero">
          <div>
            <span className="eyebrow-text">Peringkat {group.rank} · {group.facility_type}</span>
            <h2>{group.title}</h2>
            <p className="fine-print" style={{ fontSize: 14 }}>{group.region} · {formatCount(group.claim_count)} klaim dianalisis</p>
          </div>
          <Link className="button button-primary" to={`/facilities/${group.group_id}/paket${runQuery}`}><FileText size={15} />Buat paket bukti</Link>
        </div>
        <div className={`verdict-box ${group.level}`} style={{ marginTop: 16 }} data-testid="facility-verdict">
          <span className="verdict-level">{LEVELS[group.level].label.toUpperCase()}</span>
          <p>{group.verdict.replace(/^RISIKO \w+\. /, "")}</p>
        </div>
        <PeerSignals group={group} />
      </section>

      <section className="lane-cards" aria-label="Tingkat risiko klaim faskes ini">
        {(["red", "yellow", "green"] as const).map(lane => (
          <div key={lane} className={`lane-card ${lane}`}>
            <span className="lane-name"><LaneDot lane={lane} />{LANES[lane].name}</span>
            <span className="big-num">{formatCount(group.lane_counts[lane])}</span>
            <span className="lane-action">{LANES[lane].action}</span>
          </div>
        ))}
      </section>

      <div className="dash-grid">
        <section className="card span-5">
          <div className="card-head"><div><h2>Temuan per pemeriksaan</h2><p>Klaim faskes ini yang ditandai setiap pemeriksaan.</p></div></div>
          <ul className="check-rows">{Object.entries(group.indicator_counts).map(([code, count]) => (
            <li className="check-row" key={code} style={{ gridTemplateColumns: "1fr 120px 70px" }}>
              <strong>{indicatorLabel(code)}</strong>
              <div className="kpi-progress"><span style={{ width: `${(count / group.claim_count) * 100}%` }} /></div>
              <span className="num">{formatCount(count)}</span>
            </li>))}
          </ul>
          <p className="fine-print" style={{ marginTop: 10 }}>Rekam medis yang disarankan diminta: <strong>{formatCount(group.records_to_request)}</strong> klaim.</p>
        </section>
        <section className="card span-7">
          <div className="card-head"><div><h2>Klaim yang perlu diminta rekam medisnya</h2><p>Risiko tinggi lebih dulu, lalu skor AI tertinggi.</p></div>
            <span className="history-count">{formatCount(group.sample_case_ids.length)} klaim</span></div>
          {group.sample_case_ids.length === 0 ? <p className="fine-print">Tidak ada klaim berisiko tinggi atau sedang. Proses seperti biasa.</p>
            : <ul className="row-list">{samples.map(caseId => (
              <li key={caseId}>
                <Link className="row-item interactive-row" to={`/runs/${encodeURIComponent(runId)}/cases/${encodeURIComponent(caseId)}`}>
                  <LaneDot lane={group.sample_lanes[caseId] ?? "green"} />
                  <span className="row-main"><strong>Ref. klaim {shortRef(caseId)} · {LANES[(group.sample_lanes[caseId] ?? "green") as "red"].name}</strong>
                    <span>{(group.sample_findings?.[caseId] ?? []).map(indicatorLabel).join(" + ") || LANES[(group.sample_lanes[caseId] ?? "green") as "red"].action}</span></span>
                  <ArrowRight size={15} />
                </Link>
              </li>))}</ul>}
          {group.sample_case_ids.length > SAMPLES_SHOWN && <button type="button" className="button button-secondary button-compact show-more"
            onClick={() => setAllSamples(value => !value)}>{allSamples ? "Tampilkan lebih sedikit" : `Tampilkan semua (${formatCount(group.sample_case_ids.length)})`}</button>}
        </section>
      </div>
    </div>)}
  </>;
}

const SAMPLES_SHOWN = 8;

/** One-page evidence pack for a facility group (print / save as PDF). */
export function EvidencePackPage() {
  const { groupId = "" } = useParams();
  const snapshot = useGroups();
  const { state, result, runId, runQuery, reload } = snapshot;
  const { state: auth } = useAuth();
  const username = "session" in auth ? auth.session?.user.username ?? "" : "";
  const group = findGroup(result, groupId);
  const [claims, setClaims] = useState<{ key: string; items: Array<RunCase | null> } | null>(null);
  const key = `${runId}/${groupId}`;
  useEffect(() => {
    if (!group || !runId) return;
    const controller = new AbortController();
    // A few requests at a time (and one retry), so a busy local database never leaves gaps in the pack.
    const fetchOne = (caseId: string) => getRunCase(runId, caseId, controller.signal).then(detail => detail.result?.cases[caseId] ?? null);
    void (async () => {
      const items: Array<RunCase | null> = [];
      for (let start = 0; start < group.sample_case_ids.length; start += 3) {
        const batch = group.sample_case_ids.slice(start, start + 3);
        items.push(...await Promise.all(batch.map(caseId => fetchOne(caseId).catch(() => fetchOne(caseId)).catch(() => null))));
        if (controller.signal.aborted) return;
      }
      setClaims({ key, items });
    })();
    return () => controller.abort();
  }, [group, runId, key]);
  const loaded = claims && claims.key === key ? claims.items : null;

  if (state.status !== "success") return <RunStateMessage state={state} retry={reload} />;
  if (!group) return <NoGroups result={result} />;
  return <article className="pack-sheet stack">
    <div className="inline-actions no-print">
      <Link className="button button-secondary" to={`/facilities/${group.group_id}${runQuery}`}><ArrowLeft size={14} />Kembali</Link>
      <button className="button button-primary" type="button" onClick={() => window.print()}><Printer size={15} />Cetak / simpan PDF</button>
    </div>
    <section className="card">
      <span className="eyebrow-text">Paket bukti · Claim Integrity Radar</span>
      <h1>{group.title}</h1>
      <p className="fine-print" style={{ fontSize: 14 }}>{group.facility_type} · {group.region} · {runTitle(state.detail.run)}</p>
      <div className={`verdict-box ${group.level}`} style={{ marginTop: 14 }}>
        <span className="verdict-level">{LEVELS[group.level].label.toUpperCase()}</span>
        <p>{group.verdict.replace(/^RISIKO \w+\. /, "")}</p>
        <PeerSignals group={group} />
      </div>
      <div className="lane-counts" style={{ marginTop: 12 }}>
        <span><LaneDot lane="red" />Risiko tinggi {group.lane_counts.red}</span>
        <span><LaneDot lane="yellow" />Risiko sedang {group.lane_counts.yellow}</span>
        <span><LaneDot lane="green" />Risiko rendah {group.lane_counts.green}</span>
        <span>dari {formatCount(group.claim_count)} klaim</span>
      </div>
    </section>
    <section className="card">
      <div className="card-head"><div><h2>Rekam medis yang perlu diminta ({formatCount(group.records_to_request)} klaim)</h2>
        <p>Nomor referensi adalah nomor samaran; cocokkan dengan nomor kunjungan asli di sistem internal BPJS.</p></div></div>
      <div className="table-scroll"><table className="data-table" aria-label="Daftar klaim sampel">
        <thead><tr><th>No</th><th>Ref. klaim</th><th>Risiko</th><th>Alasan</th><th>AI</th></tr></thead>
        <tbody>{group.sample_case_ids.map((caseId, index) => {
          const item = loaded?.[index];
          const percentile = item?.ml_anomaly ? item.ml_anomaly.reference_percentile ?? item.ml_anomaly.anomaly_percentile : null;
          const lane = (group.sample_lanes[caseId] ?? "green") as "red";
          return <tr key={caseId}>
            <td>{index + 1}</td>
            <td><code>{shortRef(caseId)}</code></td>
            <td><LaneDot lane={lane} /> {LANES[lane].name}</td>
            <td>{item ? item.indicators.map(indicatorLabel).join(", ") : loaded ? "—" : "Memuat…"}</td>
            <td>{percentile !== null ? mlLevel(percentile).label : "—"}</td>
          </tr>;
        })}</tbody>
      </table></div>
    </section>
    <p className="fine-print">Dibuat {formatDateTime(new Date().toISOString())} oleh {username}. Paket ini adalah prioritas tinjauan, bukan temuan kecurangan; keputusan tetap pada verifikator dan tim anti-kecurangan.</p>
  </article>;
}
