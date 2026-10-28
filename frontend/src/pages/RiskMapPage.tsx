import { useMemo, useState } from "react";
import { ArrowRight, ArrowUpRight, Building2, LayoutGrid, Map as MapIcon, MapPinned, Scale, X } from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";
import type { FacilityGroup, Fairness } from "../api/client";
import { EmptyState } from "../components/DataStates";
import { Callout, LEVELS, LaneDot, formatCount, formatRupiah } from "../components/Display";
import { RunSelector, RunStateMessage, SourcePill } from "../components/PersistedRunWorkspace";
import { METRICS, RiskMap, formatPercent, type MapMetric, type MapView, type ProvinceValue } from "../components/RiskMap";
import { PROVINCE_MAP, provinceName } from "../components/provinces";
import { usePersistedRunSnapshot } from "../hooks/usePersistedRunSnapshot";

/** Per-province rows of the stored analysis (aggregates only); null when the analysis predates province codes. */
function provinceRows(fairness: Fairness | undefined): Map<string, ProvinceValue> | null {
  const dimension = fairness?.dimensions.find(item => item.field === "province_code");
  if (!dimension || dimension.rows.some(row => row.code === undefined)) return null;
  return new Map(dimension.rows.map(row => [row.code!, {
    code: row.code!, name: provinceName(row.code!), claims: row.claims, high: row.high, medium: row.medium, share: row.share,
    ratio: row.ratio_to_overall, facilityGroups: row.facility_groups ?? null, billed: row.billed_high_or_medium ?? null,
  }]));
}

/** Where high and medium-risk claims concentrate, per province; a province opens its facility groups. */
export default function RiskMapPage() {
  const { state, selectRun, reload } = usePersistedRunSnapshot();
  const [params, setParams] = useSearchParams();
  const [metric, setMetric] = useState<MapMetric>("share");
  const result = state.status === "success" ? state.detail.result : null;
  const runId = state.status === "success" ? state.detail.run.run_id : "";
  const groups = result?.facility_groups;
  const rows = useMemo(() => provinceRows(groups?.fairness), [groups]);
  const selected = params.get("provinsi");
  const select = (code: string | null) => {
    const next = new URLSearchParams(params);
    if (code) next.set("provinsi", code); else next.delete("provinsi");
    setParams(next, { replace: true });
  };
  const hasBilled = rows ? [...rows.values()].some(row => row.billed !== null) : false;

  return <>
    <header className="page-head">
      <div>
        <h1>Peta Risiko</h1>
        <p>Sebaran klaim risiko tinggi dan sedang per provinsi. Pilih provinsi untuk melihat kelompok faskesnya.</p>
      </div>
      {state.status === "success" && <div className="page-head-actions">
        {result && <SourcePill source={result.data_source} />}
        <RunSelector runs={state.runs} detail={state.detail} onChange={selectRun} />
      </div>}
    </header>
    {state.status !== "success" ? <RunStateMessage state={state} retry={reload} />
      : !groups?.fairness ? <div className="card"><EmptyState title="Data wilayah belum tersedia"
        message="Analisis ini belum memiliki ringkasan per provinsi. Jalankan ulang analisis di menu Data & Analisis." /></div>
      : !rows ? <div className="card"><EmptyState title="Peta tersedia untuk analisis berikutnya"
        message="Analisis ini disimpan sebelum kode provinsi dicatat. Jalankan ulang analisis di menu Data & Analisis untuk menampilkan peta." /></div>
      : <MapWorkspace rows={rows} fairness={groups.fairness} groups={groups.groups} runId={runId}
          metric={hasBilled || metric !== "billed" ? metric : "share"} setMetric={setMetric} hasBilled={hasBilled}
          selected={selected && rows.has(selected) ? selected : null} select={select} />}
  </>;
}

function MapWorkspace({ rows, fairness, groups, runId, metric, setMetric, hasBilled, selected, select }: {
  rows: Map<string, ProvinceValue>; fairness: Fairness; groups: FacilityGroup[]; runId: string; metric: MapMetric;
  setMetric: (metric: MapMetric) => void; hasBilled: boolean; selected: string | null; select: (code: string | null) => void;
}) {
  const runQuery = `?run_id=${encodeURIComponent(runId)}`;
  const spec = METRICS[metric];
  const ordered = [...rows.values()].sort((a, b) => (spec.value(b) ?? -1) - (spec.value(a) ?? -1) || a.name.localeCompare(b.name));
  const above = ordered.filter(row => (row.ratio ?? 0) >= 2).length;
  const mapped = ordered.filter(row => PROVINCE_MAP.provinces.some(item => item.code === row.code)).length;
  const metrics = (Object.keys(METRICS) as MapMetric[]).filter(key => key !== "billed" || hasBilled);
  const [view, setView] = useState<MapView>("map");

  return <>
    <section className="map-stats" aria-label="Ringkasan wilayah">
      <div className="map-stat card"><span className="map-stat-icon"><MapPinned size={18} aria-hidden="true" /></span>
        <div><span>Provinsi dinilai</span><strong>{formatCount(mapped)}<small> dari 34</small></strong></div></div>
      <div className="map-stat card"><span className="map-stat-icon"><Scale size={18} aria-hidden="true" /></span>
        <div><span>Porsi berisiko nasional</span><strong>{formatPercent(fairness.overall_share)}</strong></div></div>
      <div className="map-stat card"><span className="map-stat-icon tone-warn"><ArrowUpRight size={18} aria-hidden="true" /></span>
        <div><span>Provinsi ≥ 2× rata-rata nasional</span><strong>{formatCount(above)}</strong></div></div>
    </section>

    <section className="dash-grid">
      <article className="card span-8 map-card">
        <div className="card-head">
          <div><h2><MapPinned size={16} className="head-icon" aria-hidden="true" />Sebaran per provinsi</h2>
            <p>{view === "map" ? "Warna makin pekat berarti nilai makin tinggi." : "Setiap provinsi satu petak berukuran sama, agar provinsi kecil tetap terlihat."}</p></div>
          <div className="map-controls">
            <div className="segmented-pill" role="group" aria-label="Pilih ukuran peta">
              {metrics.map(key => <button key={key} type="button" aria-pressed={metric === key} onClick={() => setMetric(key)}>{METRICS[key].label}</button>)}
            </div>
            <div className="segmented-pill view-switch" role="group" aria-label="Pilih tampilan">
              <button type="button" aria-pressed={view === "map"} onClick={() => setView("map")} title="Bentuk wilayah sebenarnya"><MapIcon size={14} aria-hidden="true" />Peta</button>
              <button type="button" aria-pressed={view === "tile"} onClick={() => setView("tile")} title="Satu petak sama besar per provinsi"><LayoutGrid size={14} aria-hidden="true" />Petak</button>
            </div>
          </div>
        </div>
        <RiskMap rows={rows} metric={metric} view={view} selected={selected} onSelect={select} />
      </article>
      <aside className="card span-4 map-side" aria-live="polite">
        {selected ? <ProvincePanel row={rows.get(selected)!} groups={groups} runQuery={runQuery} overall={fairness.overall_share}
          onClose={() => select(null)} />
          : <>
            <div className="card-head"><div><h2>Tertinggi menurut {spec.label.toLowerCase()}</h2><p>Pilih provinsi di peta atau di daftar ini.</p></div></div>
            <ol className="map-top">
              {ordered.slice(0, 6).map((row, index) => {
                const value = spec.value(row);
                const top = spec.value(ordered[0]) || 1;
                return <li key={row.code}><button type="button" onClick={() => select(row.code)}>
                  <span className="map-top-rank">{index + 1}</span>
                  <span className="map-top-main"><strong>{row.name}</strong>
                    <span className="map-top-bar" aria-hidden="true"><i style={{ width: `${Math.max(3, (value ?? 0) / top * 100)}%` }} /></span></span>
                  <span className="map-top-value">{value === null ? "—" : spec.format(value)}</span>
                </button></li>;
              })}
            </ol>
          </>}
      </aside>
    </section>

    <section className="card">
      <div className="card-head"><div><h2>Semua provinsi</h2><p>Diurutkan menurut {spec.label.toLowerCase()}.</p></div></div>
      <div className="table-scroll">
        <table className="data-table map-table">
          <thead><tr><th>Provinsi</th><th>Klaim</th><th>Risiko tinggi</th><th>Risiko sedang</th><th>Porsi berisiko</th>
            <th>Dibanding nasional</th><th>Kelompok faskes</th>{hasBilled && <th>Nilai tagihan berisiko</th>}</tr></thead>
          <tbody>{ordered.map(row => <tr key={row.code} className={selected === row.code ? "is-selected" : undefined}>
            <td><button type="button" className="link-button" onClick={() => select(row.code)}>{row.name}</button></td>
            <td>{formatCount(row.claims)}</td>
            <td><span className="status-dot-text"><LaneDot lane="red" />{formatCount(row.high)}</span></td>
            <td><span className="status-dot-text"><LaneDot lane="yellow" />{formatCount(row.medium)}</span></td>
            <td>{formatPercent(row.share)}</td>
            <td><RatioPill ratio={row.ratio} /></td>
            <td>{row.facilityGroups === null ? "—" : formatCount(row.facilityGroups)}</td>
            {hasBilled && <td>{row.billed === null ? "—" : formatRupiah(row.billed)}</td>}
          </tr>)}</tbody>
        </table>
      </div>
      <Callout tone="info" title="Cara membaca">
        {fairness.note} Provinsi dengan kurang dari {formatCount(fairness.min_claims)} klaim tidak dinilai. Warna peta menunjukkan prioritas
        pemeriksaan, bukan bukti kecurangan.
      </Callout>
      <p className="map-attribution">Batas wilayah: {PROVINCE_MAP.attribution} ({PROVINCE_MAP.license}).</p>
    </section>
  </>;
}

function RatioPill({ ratio }: { ratio: number | null }) {
  if (ratio === null) return <>—</>;
  const tone = ratio >= 2 ? "danger" : ratio >= 1.25 ? "warn" : "neutral";
  return <span className={`status-pill tone-${tone}`}>{ratio.toLocaleString("id-ID")}×</span>;
}

function ProvincePanel({ row, groups, runQuery, overall, onClose }: {
  row: ProvinceValue; groups: FacilityGroup[]; runQuery: string; overall: number; onClose: () => void;
}) {
  const inProvince = groups.filter(group => group.province_code === row.code).sort((a, b) => a.rank - b.rank);
  return <div className="map-province">
    <div className="map-province-head">
      <div><span className="eyebrow-text">Provinsi</span><h2>{row.name}</h2></div>
      <button type="button" className="icon-close" onClick={onClose} aria-label="Tutup rincian provinsi"><X size={16} /></button>
    </div>
    <div className="map-province-share">
      <strong>{formatPercent(row.share)}</strong>
      <span>klaim berisiko · nasional {formatPercent(overall)}</span>
      <RatioPill ratio={row.ratio} />
    </div>
    <dl className="map-province-facts">
      <div><dt>Klaim dianalisis</dt><dd>{formatCount(row.claims)}</dd></div>
      <div><dt>Risiko tinggi</dt><dd><LaneDot lane="red" />{formatCount(row.high)}</dd></div>
      <div><dt>Risiko sedang</dt><dd><LaneDot lane="yellow" />{formatCount(row.medium)}</dd></div>
      <div><dt>Kelompok faskes</dt><dd>{row.facilityGroups === null ? "—" : formatCount(row.facilityGroups)}</dd></div>
      {row.billed !== null && <div className="wide"><dt>Nilai tagihan berisiko</dt><dd>{formatRupiah(row.billed)}</dd></div>}
    </dl>
    <h3 className="map-province-sub"><Building2 size={15} className="head-icon" aria-hidden="true" />Kelompok faskes paling mendesak</h3>
    {inProvince.length === 0 ? <p className="fine-print">Tidak ada kelompok faskes yang cukup besar untuk dinilai di provinsi ini.</p>
      : <ul className="map-province-groups">{inProvince.slice(0, 3).map(group => <li key={group.group_id}>
        <Link to={`/facilities/${group.group_id}${runQuery}`}>
          <span><strong>{group.title}</strong><small>{group.region} · {formatCount(group.claim_count)} klaim</small></span>
          <span className={`status-pill tone-${LEVELS[group.level].tone}`}>{LEVELS[group.level].label}</span>
        </Link>
      </li>)}</ul>}
    <Link className="button button-primary map-province-cta" to={`/facilities${runQuery}&provinsi=${encodeURIComponent(row.code)}`}>
      Lihat kelompok faskes di provinsi ini <ArrowRight size={14} aria-hidden="true" />
    </Link>
  </div>;
}
