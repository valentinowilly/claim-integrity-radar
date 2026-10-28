import provinceMap from "../assets/indonesia-provinces.json";

/** Simplified outlines of the 34 provinces (BPS codes), built by scripts/build_province_map.py. */
export interface ProvinceShape { code: string; name: string; d: string; label: [number, number] }
export const PROVINCE_MAP = provinceMap as { viewBox: string; source: string; license: string; attribution: string; provinces: ProvinceShape[] };

const NAMES = new Map(PROVINCE_MAP.provinces.map(province => [province.code, province.name]));

/** Province name for a BPS code; the code itself when it is not a province (e.g. 99, undefined in the data). */
export function provinceName(code: string): string {
  return NAMES.get(code) ?? (code === "99" ? "Tidak terdefinisi" : `Provinsi ${code}`);
}

/** Tile layout: one equal square per province, placed roughly where it lies (column, row) with a short name. */
export const TILES: Record<string, { col: number; row: number; short: string }> = {
  "11": { col: 0, row: 0, short: "ACEH" }, "12": { col: 1, row: 1, short: "SUMUT" }, "13": { col: 1, row: 2, short: "SUMBAR" },
  "14": { col: 2, row: 2, short: "RIAU" }, "21": { col: 3, row: 2, short: "KEPRI" }, "17": { col: 1, row: 3, short: "BKL" },
  "15": { col: 2, row: 3, short: "JAMBI" }, "16": { col: 2, row: 4, short: "SUMSEL" }, "19": { col: 3, row: 4, short: "BABEL" },
  "18": { col: 2, row: 5, short: "LAMPUNG" }, "31": { col: 4, row: 4, short: "DKI" }, "36": { col: 3, row: 5, short: "BANTEN" },
  "32": { col: 4, row: 5, short: "JABAR" }, "33": { col: 5, row: 5, short: "JATENG" }, "34": { col: 5, row: 6, short: "DIY" },
  "35": { col: 6, row: 5, short: "JATIM" }, "51": { col: 7, row: 5, short: "BALI" }, "52": { col: 8, row: 5, short: "NTB" },
  "53": { col: 9, row: 5, short: "NTT" }, "65": { col: 6, row: 0, short: "KALTARA" }, "61": { col: 5, row: 1, short: "KALBAR" },
  "64": { col: 6, row: 1, short: "KALTIM" }, "62": { col: 5, row: 2, short: "KALTENG" }, "63": { col: 6, row: 2, short: "KALSEL" },
  "75": { col: 8, row: 1, short: "GORONT" }, "71": { col: 9, row: 1, short: "SULUT" }, "76": { col: 7, row: 2, short: "SULBAR" },
  "72": { col: 8, row: 2, short: "SULTENG" }, "73": { col: 7, row: 3, short: "SULSEL" }, "74": { col: 8, row: 3, short: "SULTRA" },
  "82": { col: 10, row: 1, short: "MALUT" }, "81": { col: 10, row: 3, short: "MALUKU" }, "91": { col: 11, row: 2, short: "PABAR" },
  "94": { col: 12, row: 2, short: "PAPUA" },
};
export const TILE_GRID = { cols: 13, rows: 7 };
