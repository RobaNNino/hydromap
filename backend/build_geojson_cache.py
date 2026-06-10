"""
Precompute the enriched /api/geojson payload.

Render free tier has a 512 MB memory ceiling. Building the merged map response
at runtime can briefly hold all provider GeoJSON, results.json and the final
serialized response in memory. This script does that work offline and stores
streamable files for Flask:

  - backend/data/geojson-cache.json
  - backend/data/geojson-cache.json.gz
"""
from __future__ import annotations

import gc
import gzip
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from app import (  # noqa: E402
    GEOJSON_CACHE_FILE,
    GEOJSON_CACHE_GZ_FILE,
    _build_enriched_geojson,
    _freshness,
)


def main() -> int:
    data = _build_enriched_geojson()
    for feat in data.get("features", []):
        p = feat.get("properties") or {}
        p["freshness"] = _freshness(p.get("periodo"))

    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    GEOJSON_CACHE_FILE.write_bytes(raw)
    GEOJSON_CACHE_GZ_FILE.write_bytes(gzip.compress(raw, compresslevel=6))

    raw_mb = GEOJSON_CACHE_FILE.stat().st_size / 1024 / 1024
    gz_mb = GEOJSON_CACHE_GZ_FILE.stat().st_size / 1024 / 1024
    print(
        f"[geojson-cache] wrote {GEOJSON_CACHE_FILE.name} ({raw_mb:.2f} MB) "
        f"and {GEOJSON_CACHE_GZ_FILE.name} ({gz_mb:.2f} MB)"
    )
    data = None
    raw = None
    gc.collect()
    return 0


if __name__ == "__main__":
    sys.exit(main())
