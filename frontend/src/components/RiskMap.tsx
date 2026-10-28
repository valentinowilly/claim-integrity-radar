import { useMemo, useRef, useState, type KeyboardEvent, type MouseEvent } from "react";
import { formatCount, formatRupiah } from "./Display";
import { PROVINCE_MAP, TILES, TILE_GRID } from "./provinces";

export type MapMetric = "share" | "count" | "billed";
/** "map": the provinces' real shapes; "tile": one equal square per province, so small provinces weigh the same. */
export type MapView = "map" | "tile";
export interface ProvinceValue {
  code: string; name: string; claims: number; high: number; medium: number; share: number;
  ratio: number | null; facilityGroups: number | null; billed: number | null;
}

export const METRICS: Record<MapMetric, { label: string; legend: string; value: (row: ProvinceValue) => number | null; format: (value: number) => string }> = {
  share: { label: "Porsi berisiko", legend: "Porsi klaim risiko tinggi dan sedang", value: row => row.share, format: value => formatPercent(value) },
  count: { label: "Jumlah klaim berisiko", legend: "Klaim risiko tinggi dan sedang", value: row => row.high + row.medium, format: formatCount },
  billed: { label: "Nilai tagihan", legend: "Nilai tagihan klaim risiko tinggi dan sedang", value: row => row.billed, format: formatRupiah },
};

const STEPS = 5;
const LABELLED = 4; // the map names its darkest provinces; the tiles name every province
const TILE = 74, GAP = 6;

export function formatPercent(value: number): string {
  return `${(value * 100).toLocaleString("id-ID", { maximumFractionDigits: value < 0.1 ? 1 : 0 })}%`;
}

/** Class breaks from zero to the largest value. */
function breaks(max: number): number[] {
  if (max <= 0) return [];
  const step = max / STEPS;
  return Array.from({ length: STEPS - 1 }, (_, index) => step * (index + 1));
}

function stepOf(value: number, edges: number[]): number {
  let step = 0;
  while (step < edges.length && value > edges[step]) step += 1;
  return step;
}

/** Compact value for a tile (fits under the short name). */
function tileValue(metric: MapMetric, value: number): string {
  if (metric === "billed") {
    if (value >= 1e9) return `${(value / 1e9).toLocaleString("id-ID", { maximumFractionDigits: 1 })} M`;
    if (value >= 1e6) return `${(value / 1e6).toLocaleString("id-ID", { maximumFractionDigits: 0 })} jt`;
    return formatCount(Math.round(value / 1e3)) + " rb";
  }
  return METRICS[metric].format(value);
}

/** Choropleth of the 34 provinces: one warm hue, light to dark, for the chosen magnitude. */
export function RiskMap({ rows, metric, view, selected, onSelect }: {
  rows: Map<string, ProvinceValue>; metric: MapMetric; view: MapView; selected: string | null; onSelect: (code: string | null) => void;
}) {
  const box = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<{ code: string; x: number; y: number } | null>(null);
  const spec = METRICS[metric];
  const max = useMemo(() => Math.max(0, ...[...rows.values()].map(row => spec.value(row) ?? 0)), [rows, spec]);
  const edges = useMemo(() => breaks(max), [max]);
  // The darkest provinces get their name on the map, so the reader does not need to hover to find them.
  const labelled = useMemo(() => new Set([...rows.values()]
    .filter(row => (spec.value(row) ?? 0) > 0)
    .sort((a, b) => (spec.value(b) ?? 0) - (spec.value(a) ?? 0)).slice(0, LABELLED).map(row => row.code)), [rows, spec]);

  const place = (event: MouseEvent, code: string) => {
    const rect = box.current?.getBoundingClientRect();
    if (rect) setHover({ code, x: event.clientX - rect.left, y: event.clientY - rect.top });
  };
  const keyed = (event: KeyboardEvent, code: string) => {
    if (event.key === "Enter" || event.key === " ") { event.preventDefault(); onSelect(selected === code ? null : code); }
  };
  const describe = (code: string) => {
    const row = rows.get(code);
    const value = row ? spec.value(row) : null;
    const step = value === null || value === undefined ? null : stepOf(value, edges);
    return { row, value, step };
  };
  const shared = (code: string, name: string, step: number | null, value: number | null | undefined) => ({
    "data-code": code,
    className: `risk-map-province${step === null ? " no-data" : ` step-${step}`}${selected === code ? " selected" : ""}`,
    tabIndex: 0, role: "button",
    "aria-label": value !== null && value !== undefined ? `${name}: ${spec.format(value)}` : `${name}: data terlalu sedikit`,
    "aria-pressed": selected === code,
    onMouseMove: (event: MouseEvent) => place(event, code), onFocus: () => setHover(null),
    onClick: () => onSelect(selected === code ? null : code), onKeyDown: (event: KeyboardEvent) => keyed(event, code),
  });
  const tip = hover ? rows.get(hover.code) ?? null : null;
  const tipName = hover ? PROVINCE_MAP.provinces.find(item => item.code === hover.code)?.name ?? hover.code : "";
  const tileBox = `0 0 ${TILE_GRID.cols * (TILE + GAP) - GAP} ${TILE_GRID.rows * (TILE + GAP) - GAP}`;

  return <div className="risk-map">
    <div className={`risk-map-canvas view-${view}`} ref={box} onMouseLeave={() => setHover(null)}>
      {view === "map" ? <svg viewBox={PROVINCE_MAP.viewBox} role="group" aria-label={`Peta Indonesia per provinsi: ${spec.label.toLowerCase()}`}>
        {PROVINCE_MAP.provinces.map(province => {
          const { step, value } = describe(province.code);
          return <path key={province.code} d={province.d} {...shared(province.code, province.name, step, value)} />;
        })}
        <g className="risk-map-labels" aria-hidden="true">
          {PROVINCE_MAP.provinces.filter(province => labelled.has(province.code)).map(province =>
            <text key={province.code} x={province.label[0]} y={province.label[1]} textAnchor="middle">{province.name}</text>)}
        </g>
      </svg>
        : <svg viewBox={tileBox} role="group" aria-label={`Petak provinsi Indonesia: ${spec.label.toLowerCase()}`}>
          {PROVINCE_MAP.provinces.filter(province => TILES[province.code]).map(province => {
            const tile = TILES[province.code];
            const { step, value } = describe(province.code);
            const x = tile.col * (TILE + GAP), y = tile.row * (TILE + GAP);
            return <g key={province.code} className={`risk-map-tile tile-step-${step ?? "none"}`}>
              <rect x={x} y={y} width={TILE} height={TILE} rx={10} {...shared(province.code, province.name, step, value)} />
              <text x={x + TILE / 2} y={y + TILE / 2 + (value === null || value === undefined ? 6 : -4)} textAnchor="middle" aria-hidden="true"
                className="risk-map-tile-name">{tile.short}</text>
              {value !== null && value !== undefined && <text x={x + TILE / 2} y={y + TILE / 2 + 18} textAnchor="middle" aria-hidden="true"
                className="risk-map-tile-value">{tileValue(metric, value)}</text>}
            </g>;
          })}
        </svg>}
      {hover && <div className="risk-map-tip" role="tooltip"
        style={{ left: hover.x, top: hover.y, transform: `translate(${hover.x > (box.current?.clientWidth ?? 0) * 0.6 ? "calc(-100% - 14px)" : "14px"}, -50%)` }}>
        <strong>{tipName}</strong>
        {tip ? <>
          <span className="risk-map-tip-value">{spec.format(spec.value(tip) ?? 0)}<small>{spec.label.toLowerCase()}</small></span>
          <dl>
            <div><dt>Klaim dianalisis</dt><dd>{formatCount(tip.claims)}</dd></div>
            <div><dt>Risiko tinggi · sedang</dt><dd>{formatCount(tip.high)} · {formatCount(tip.medium)}</dd></div>
            {tip.ratio !== null && <div><dt>Dibanding nasional</dt><dd>{tip.ratio.toLocaleString("id-ID")}×</dd></div>}
          </dl>
          <small className="risk-map-tip-hint">Klik untuk rincian</small>
        </> : <span className="risk-map-tip-empty">Data terlalu sedikit untuk dinilai</span>}
      </div>}
    </div>
    <div className="risk-map-legend" aria-label="Keterangan warna">
      <span className="risk-map-legend-title">{spec.legend}</span>
      <div className="risk-map-legend-scale">
        {edges.length ? Array.from({ length: STEPS }, (_, step) => <span key={step} className="risk-map-legend-step">
          <i className={`step-${step}`} />
          <small>{step === 0 ? `≤ ${spec.format(edges[0])}` : step === STEPS - 1 ? `> ${spec.format(edges[STEPS - 2])}` : `≤ ${spec.format(edges[step])}`}</small>
        </span>) : <small>Belum ada nilai untuk ditampilkan</small>}
        <span className="risk-map-legend-step"><i className="no-data" /><small>Data terlalu sedikit</small></span>
      </div>
    </div>
  </div>;
}
