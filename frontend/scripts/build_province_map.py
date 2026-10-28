"""Build src/assets/indonesia-provinces.json: simplified province outlines as ready-to-draw SVG paths.

Source: geoBoundaries gbOpen IDN ADM1 (34 provinces, 2017 boundaries from OpenStreetMap), simplified release
https://github.com/wmgeolab/geoBoundaries/raw/9469f09/releaseData/gbOpen/IDN/ADM1/geoBoundaries-IDN-ADM1_simplified.geojson
License: Open Data Commons Open Database License 1.0, (c) OpenStreetMap contributors. The generated file is a
derived database and stays under ODbL 1.0 with the same attribution.

The 34-province layout matches the BPJS sample data (Papua Barat = 91, Papua = 94; the 2022 Papua provinces are
not in the data). Provinces are keyed by their BPS code, the code the claim data carries.

Usage: python -I scripts/build_province_map.py <geoBoundaries-IDN-ADM1_simplified.geojson>
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

# ISO 3166-2 code in the source -> (BPS province code, name)
PROVINCES = {
    "AC": ("11", "Aceh"), "SU": ("12", "Sumatera Utara"), "SB": ("13", "Sumatera Barat"), "RI": ("14", "Riau"),
    "JA": ("15", "Jambi"), "SS": ("16", "Sumatera Selatan"), "BE": ("17", "Bengkulu"), "LA": ("18", "Lampung"),
    "BB": ("19", "Kepulauan Bangka Belitung"), "KR": ("21", "Kepulauan Riau"), "JK": ("31", "DKI Jakarta"),
    "JB": ("32", "Jawa Barat"), "JT": ("33", "Jawa Tengah"), "YO": ("34", "DI Yogyakarta"), "JI": ("35", "Jawa Timur"),
    "BT": ("36", "Banten"), "BA": ("51", "Bali"), "NB": ("52", "Nusa Tenggara Barat"), "NT": ("53", "Nusa Tenggara Timur"),
    "KB": ("61", "Kalimantan Barat"), "KT": ("62", "Kalimantan Tengah"), "KS": ("63", "Kalimantan Selatan"),
    "KI": ("64", "Kalimantan Timur"), "KU": ("65", "Kalimantan Utara"), "SA": ("71", "Sulawesi Utara"),
    "ST": ("72", "Sulawesi Tengah"), "SN": ("73", "Sulawesi Selatan"), "SG": ("74", "Sulawesi Tenggara"),
    "GO": ("75", "Gorontalo"), "SR": ("76", "Sulawesi Barat"), "MA": ("81", "Maluku"), "MU": ("82", "Maluku Utara"),
    "PB": ("91", "Papua Barat"), "PA": ("94", "Papua"),
}
WIDTH = 1000.0
TOLERANCE_DEG = 0.03       # simplification; about 3 km, below one pixel at this width
MIN_RING_AREA_DEG2 = 0.006  # islands smaller than about 70 km² are dropped (the largest ring always stays)


def _rdp(points: list[tuple[float, float]], tolerance: float) -> list[tuple[float, float]]:
    """Ramer-Douglas-Peucker on one open polyline (iterative)."""
    if len(points) < 3:
        return points
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        start, end = stack.pop()
        (x1, y1), (x2, y2) = points[start], points[end]
        dx, dy = x2 - x1, y2 - y1
        norm = math.hypot(dx, dy)
        worst, index = -1.0, -1
        for i in range(start + 1, end):
            x, y = points[i]
            # A closed ring starts and ends on the same point: measure from that point instead of a line.
            distance = abs(dy * x - dx * y + x2 * y1 - y2 * x1) / norm if norm > 1e-12 else math.hypot(x - x1, y - y1)
            if distance > worst:
                worst, index = distance, i
        if worst > tolerance:
            keep[index] = True
            stack += [(start, index), (index, end)]
    return [point for point, kept in zip(points, keep) if kept]


def _area(ring: list[tuple[float, float]]) -> float:
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]))) / 2


def _centroid(ring: list[tuple[float, float]]) -> tuple[float, float]:
    a = cx = cy = 0.0
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        cross = x1 * y2 - x2 * y1
        a += cross
        cx += (x1 + x2) * cross
        cy += (y1 + y2) * cross
    if abs(a) < 1e-12:
        return ring[0]
    return cx / (3 * a), cy / (3 * a)


def build(source: Path) -> dict:
    data = json.loads(source.read_text(encoding="utf-8"))
    provinces = []
    for feature in data["features"]:
        iso = feature["properties"]["shapeISO"].split("-")[-1]
        code, name = PROVINCES[iso]
        geometry = feature["geometry"]
        polygons = geometry["coordinates"] if geometry["type"] == "MultiPolygon" else [geometry["coordinates"]]
        rings = [[(float(x), float(y)) for x, y in polygon[0][:-1]] for polygon in polygons]  # outer rings only
        rings.sort(key=_area, reverse=True)
        kept = [rings[0]] + [ring for ring in rings[1:] if _area(ring) >= MIN_RING_AREA_DEG2]
        simplified = [ring for ring in (_rdp(ring + ring[:1], TOLERANCE_DEG)[:-1] for ring in kept) if len(ring) >= 3]
        provinces.append({"code": code, "name": name, "rings": simplified, "label": _centroid(rings[0])})
    lons = [x for p in provinces for ring in p["rings"] for x, _ in ring]
    lats = [y for p in provinces for ring in p["rings"] for _, y in ring]
    west, east, south, north = min(lons), max(lons), min(lats), max(lats)
    scale = WIDTH / (east - west)
    height = (north - south) * scale

    def project(x: float, y: float) -> str:
        return f"{(x - west) * scale:.1f} {(north - y) * scale:.1f}"

    out = []
    for p in sorted(provinces, key=lambda item: item["code"]):
        path = "".join("M" + "L".join(project(x, y) for x, y in ring) + "Z" for ring in p["rings"])
        lx, ly = p["label"]
        out.append({"code": p["code"], "name": p["name"], "d": path,
                    "label": [round((lx - west) * scale, 1), round((north - ly) * scale, 1)]})
    return {
        "viewBox": f"0 0 {WIDTH:.0f} {height:.0f}",
        "source": "geoBoundaries gbOpen IDN ADM1 (OpenStreetMap), disederhanakan",
        "license": "ODbL 1.0",
        "attribution": "© OpenStreetMap contributors, geoBoundaries",
        "provinces": out,
    }


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    result = build(Path(sys.argv[1]))
    target = Path(__file__).resolve().parent.parent / "src" / "assets" / "indonesia-provinces.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{target.name}: {len(result['provinces'])} provinces, {target.stat().st_size / 1024:.0f} KB, viewBox {result['viewBox']}")


if __name__ == "__main__":
    main()
