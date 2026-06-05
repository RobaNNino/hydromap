"""
Cut Acquedotto del Fiora service polygons out of Acque S.p.A. polygons.

Acque RIS geometries are municipal polygons. Around the Siena/Grosseto border
some of those polygons cover more precise Fiora KML zones. This post-process
keeps both datasets clickable by subtracting Fiora geometries from Acque
features, creating real polygon holes where they overlap.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from shapely.geometry import GeometryCollection, MultiPolygon, Polygon, mapping, shape
from shapely.ops import unary_union
from shapely.validation import make_valid

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
ACQUE_GEOJSON = DATA_DIR / "mappa-qualita-acque.json"
FIORA_GEOJSON = DATA_DIR / "mappa-qualita-fiora.json"
MIN_OVERLAP_AREA = 1e-12


def _valid_polygonal(geom):
    if geom.is_empty:
        return geom
    geom = make_valid(geom)
    if not geom.is_valid:
        geom = geom.buffer(0)
    if isinstance(geom, (Polygon, MultiPolygon)):
        return geom
    if isinstance(geom, GeometryCollection):
        parts = [
            g for g in geom.geoms
            if isinstance(g, (Polygon, MultiPolygon)) and not g.is_empty
        ]
        if parts:
            return unary_union(parts)
        return GeometryCollection()
    return GeometryCollection()


def _load_geojson(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def clip_acque_by_fiora(
    acque_path: Path = ACQUE_GEOJSON,
    fiora_path: Path = FIORA_GEOJSON,
    *,
    verbose: bool = True,
) -> dict:
    if not acque_path.exists() or not fiora_path.exists():
        if verbose:
            print("[clip] skip: Acque or Fiora GeoJSON missing")
        return {"changed": 0, "dropped": 0, "features": 0, "overlap_area": 0.0}

    acque = _load_geojson(acque_path)
    fiora = _load_geojson(fiora_path)

    fiora_geoms = [
        _valid_polygonal(shape(feat["geometry"]))
        for feat in fiora.get("features", [])
        if feat.get("geometry")
    ]
    fiora_geoms = [g for g in fiora_geoms if not g.is_empty]
    if not fiora_geoms:
        if verbose:
            print("[clip] skip: no Fiora polygon geometry")
        return {"changed": 0, "dropped": 0, "features": len(acque.get("features", [])), "overlap_area": 0.0}

    fiora_union = _valid_polygonal(unary_union(fiora_geoms))
    changed = 0
    dropped = 0
    overlap_area = 0.0
    out_features = []

    for feat in acque.get("features", []):
        if not feat.get("geometry"):
            out_features.append(feat)
            continue
        geom = _valid_polygonal(shape(feat["geometry"]))
        if geom.is_empty:
            dropped += 1
            continue
        overlap = geom.intersection(fiora_union)
        if overlap.is_empty or overlap.area <= MIN_OVERLAP_AREA:
            out_features.append(feat)
            continue

        clipped = _valid_polygonal(geom.difference(fiora_union))
        changed += 1
        overlap_area += overlap.area
        if clipped.is_empty or clipped.area <= MIN_OVERLAP_AREA:
            dropped += 1
            continue

        props = feat.setdefault("properties", {})
        props["clipped_by"] = "toscana_fiora"
        props["clipped_overlap_area"] = round(overlap.area, 12)
        feat["geometry"] = mapping(clipped)
        out_features.append(feat)

    acque["features"] = out_features
    acque["_clipped_by"] = "toscana_fiora"
    acque["_clipped_at"] = datetime.now(timezone.utc).isoformat()
    acque["_clipped_features"] = changed
    acque["_clipped_overlap_area"] = overlap_area
    acque_path.write_text(json.dumps(acque, ensure_ascii=False), encoding="utf-8")

    stats = {
        "changed": changed,
        "dropped": dropped,
        "features": len(out_features),
        "overlap_area": overlap_area,
    }
    if verbose:
        print(
            "[clip] Acque x Fiora: "
            f"{changed} clipped, {dropped} dropped, {len(out_features)} kept"
        )
    return stats


def main() -> int:
    clip_acque_by_fiora(verbose=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
