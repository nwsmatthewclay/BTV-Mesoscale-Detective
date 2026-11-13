#!/usr/bin/env python3
"""Render GRIB-derived model grids as zoomable XYZ raster tiles and GeoJSON contours.

The source grid remains authoritative. Raster tiles are a display product; contours
are calculated independently from the native grid and exported as geographic vectors.
"""
from __future__ import annotations

import argparse
import gzip
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image
from pyproj import Transformer
from scipy.interpolate import LinearNDInterpolator
from scipy.spatial import Delaunay, QhullError

WEB_MERCATOR_LIMIT = 20037508.342789244
TILE_SIZE = 256
WEB = "EPSG:3857"
GEO = "EPSG:4326"


def load_payload(path: Path) -> dict[str, Any]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as stream:
        payload = json.load(stream)
    if not isinstance(payload.get("grids"), dict) or not isinstance(payload.get("fields"), dict):
        raise ValueError(f"{path} is not a decoded model-grid payload")
    return payload


def squeeze_2d(values: Any) -> np.ndarray | None:
    arr = np.asarray(values, dtype=float)
    arr = np.squeeze(arr)
    return arr if arr.ndim == 2 else None


def choose_field(payload: dict[str, Any], selector: str) -> tuple[str, dict[str, Any], np.ndarray, dict[str, Any]]:
    matches = []
    for key, field in payload["fields"].items():
        if selector not in (key, field.get("short_name")):
            continue
        data = squeeze_2d(field.get("data"))
        grid = payload["grids"].get(field.get("grid_id"))
        if data is not None and isinstance(grid, dict):
            matches.append((key, field, data, grid))
    if len(matches) != 1:
        details = [item[0] for item in matches]
        raise ValueError(f"Field selector {selector!r} matched {len(matches)} 2-D fields: {details}")
    return matches[0]


def nice_interval(span: float, target_count: int = 12) -> float:
    rough = max(span / max(target_count, 1), 1e-9)
    power = 10 ** math.floor(math.log10(rough))
    scaled = rough / power
    return (1 if scaled <= 1 else 2 if scaled <= 2 else 5 if scaled <= 5 else 10) * power


def tile_x(lon: float, z: int) -> int:
    return int(math.floor((lon + 180.0) / 360.0 * (2 ** z)))


def tile_y(lat: float, z: int) -> int:
    lat = max(min(lat, 85.05112878), -85.05112878)
    rad = math.radians(lat)
    return int(math.floor((1 - math.asinh(math.tan(rad)) / math.pi) / 2 * (2 ** z)))


def tile_bounds_mercator(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    n = 2 ** z
    span = 2 * WEB_MERCATOR_LIMIT / n
    xmin = -WEB_MERCATOR_LIMIT + x * span
    xmax = xmin + span
    ymax = WEB_MERCATOR_LIMIT - y * span
    ymin = ymax - span
    return xmin, ymin, xmax, ymax


def rgba_for_values(values: np.ndarray, vmin: float, vmax: float, cmap_name: str) -> np.ndarray:
    import matplotlib
    cmap = matplotlib.colormaps[cmap_name]
    normalized = np.clip((values - vmin) / max(vmax - vmin, 1e-12), 0, 1)
    rgba = (cmap(normalized) * 255).astype(np.uint8)
    rgba[~np.isfinite(values), 3] = 0
    return rgba


def build_contours(data: np.ndarray, lat: np.ndarray, lon: np.ndarray,
                   levels: np.ndarray, output: Path) -> int:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots()
    contour = ax.contour(lon, lat, np.ma.masked_invalid(data), levels=levels)
    features = []
    for level, collection in zip(contour.levels, contour.collections):
        for path in collection.get_paths():
            vertices = path.vertices
            if len(vertices) < 2:
                continue
            coords = [[float(x), float(y)] for x, y in vertices if np.isfinite(x) and np.isfinite(y)]
            if len(coords) >= 2:
                features.append({
                    "type": "Feature",
                    "properties": {"value": float(level)},
                    "geometry": {"type": "LineString", "coordinates": coords},
                })
    plt.close(fig)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({
        "type": "FeatureCollection",
        "name": output.parent.name,
        "features": features,
    }, separators=(",", ":"), allow_nan=False) + "\n", encoding="utf-8")
    return len(features)


def render_tiles(payload: dict[str, Any], selector: str, output_root: Path,
                 zoom_min: int = 3, zoom_max: int = 7, cmap: str = "turbo",
                 vmin: float | None = None, vmax: float | None = None,
                 contour_interval: float | None = None) -> dict[str, Any]:
    field_key, field, data, grid = choose_field(payload, selector)
    lat = np.asarray(grid["latitude"], dtype=float)
    lon = ((np.asarray(grid["longitude"], dtype=float) + 180) % 360) - 180
    if data.shape != lat.shape or data.shape != lon.shape:
        raise ValueError(f"Field/grid shape mismatch: data={data.shape}, lat={lat.shape}, lon={lon.shape}")
    valid = np.isfinite(data) & np.isfinite(lat) & np.isfinite(lon)
    if int(valid.sum()) < 12:
        raise ValueError("Fewer than 12 valid grid cells; refusing to publish a misleading map")
    values = data[valid]
    low = float(np.nanpercentile(values, 2)) if vmin is None else float(vmin)
    high = float(np.nanpercentile(values, 98)) if vmax is None else float(vmax)
    if not np.isfinite(low + high) or high <= low:
        raise ValueError("Invalid color range")
    transform = Transformer.from_crs(GEO, WEB, always_xy=True)
    sx, sy = transform.transform(lon[valid], lat[valid])
    points = np.column_stack((sx, sy))
    try:
        triangulation = Delaunay(points)
    except QhullError as exc:
        raise ValueError(f"Could not triangulate source grid: {exc}") from exc
    interpolator = LinearNDInterpolator(triangulation, values, fill_value=np.nan)

    bounds = payload.get("domain") or {
        "west": float(np.nanmin(lon[valid])), "east": float(np.nanmax(lon[valid])),
        "south": float(np.nanmin(lat[valid])), "north": float(np.nanmax(lat[valid])),
    }
    product_id = field_key.replace("/", "_").replace(" ", "_")
    product_root = output_root / str(payload["model"]).lower() / str(payload["model_cycle_utc"]).replace(":", "").replace("-", "") / f"f{int(payload['forecast_hour']):02d}" / product_id
    tile_count = 0
    for z in range(zoom_min, zoom_max + 1):
        n = 2 ** z
        x0, x1 = max(0, tile_x(bounds["west"], z)), min(n - 1, tile_x(bounds["east"], z))
        y0, y1 = max(0, tile_y(bounds["north"], z)), min(n - 1, tile_y(bounds["south"], z))
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                xmin, ymin, xmax, ymax = tile_bounds_mercator(z, x, y)
                px = xmin + (np.arange(TILE_SIZE) + 0.5) / TILE_SIZE * (xmax - xmin)
                py = ymax - (np.arange(TILE_SIZE) + 0.5) / TILE_SIZE * (ymax - ymin)
                xx, yy = np.meshgrid(px, py)
                sampled = np.asarray(interpolator(xx, yy), dtype=float)
                rgba = rgba_for_values(sampled, low, high, cmap)
                tile_path = product_root / "tiles" / str(z) / str(x) / f"{y}.png"
                tile_path.parent.mkdir(parents=True, exist_ok=True)
                Image.fromarray(rgba, mode="RGBA").save(tile_path, optimize=True)
                tile_count += 1

    interval = float(contour_interval) if contour_interval else nice_interval(high - low)
    levels = np.arange(math.ceil(low / interval) * interval, high + interval * 0.5, interval)
    contour_path = product_root / "contours.geojson"
    contour_count = build_contours(data, lat, lon, levels, contour_path) if len(levels) else 0
    relative = product_root.relative_to(output_root)
    product = {
        "model": payload["model"], "cycle_utc": payload["model_cycle_utc"],
        "forecast_hour": int(payload["forecast_hour"]), "valid_time_utc": payload["valid_time_utc"],
        "field_key": field_key, "short_name": field.get("short_name"),
        "long_name": field.get("long_name"), "units": field.get("units"),
        "source_grid_shape": list(data.shape), "source_grid_id": field.get("grid_id"),
        "display_range": [low, high], "contour_interval": interval,
        "contour_levels": [float(v) for v in levels], "tile_size": TILE_SIZE,
        "zoom_min": zoom_min, "zoom_max": zoom_max, "tile_count": tile_count,
        "contour_feature_count": contour_count,
        "tile_url": f"{relative.as_posix()}/tiles/{{z}}/{{x}}/{{y}}.png",
        "contour_url": f"{relative.as_posix()}/contours.geojson",
        "rendering": "linear interpolation from native model grid; contours calculated independently on native geographic grid",
    }
    product_root.mkdir(parents=True, exist_ok=True)
    (product_root / "product.json").write_text(json.dumps(product, indent=2) + "\n", encoding="utf-8")
    return product


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", default=Path("mesoscale/data/model_tiles"), type=Path)
    parser.add_argument("--field", required=True, help="Exact field key or unique GRIB short name (2-D fields only)")
    parser.add_argument("--zoom-min", type=int, default=3)
    parser.add_argument("--zoom-max", type=int, default=7)
    parser.add_argument("--cmap", default="turbo")
    parser.add_argument("--vmin", type=float)
    parser.add_argument("--vmax", type=float)
    parser.add_argument("--contour-interval", type=float)
    args = parser.parse_args()
    if args.zoom_min < 0 or args.zoom_max > 12 or args.zoom_min > args.zoom_max:
        parser.error("zoom range must satisfy 0 <= zoom-min <= zoom-max <= 12")
    result = render_tiles(load_payload(args.input), args.field, args.output,
                          args.zoom_min, args.zoom_max, args.cmap,
                          args.vmin, args.vmax, args.contour_interval)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
