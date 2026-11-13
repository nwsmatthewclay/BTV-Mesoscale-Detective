#!/usr/bin/env python3
"""Render published model grids as zoomable XYZ raster tiles and GeoJSON contours.

The complete archived grid remains authoritative for cursor and point sampling. Raster
and contour products use a bounded display resample to keep tile rendering predictable.
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
TILE_MAX_GRID_DIM = 320
WEB = "EPSG:3857"
GEO = "EPSG:4326"


def display_sampling_stride(shape: tuple[int, int], max_grid_dim: int = TILE_MAX_GRID_DIM) -> int:
    """Bound the display grid without changing the source archive payload."""
    if max_grid_dim < 1 or len(shape) != 2 or any(int(value) < 1 for value in shape):
        raise ValueError("display sampling requires a positive 2-D shape and positive cap")
    return max(1, (max(int(value) for value in shape) + max_grid_dim - 1) // max_grid_dim)


def summarize_forecast_hour_coverage(
    archive_hours: list[dict[str, Any]], rendered_forecast_hours: list[int]
) -> dict[str, Any]:
    """Describe exactly which verified archive hours have tile products."""
    declared = [int(item["forecast_hour"]) for item in archive_hours]
    if len(set(declared)) != len(declared):
        raise ValueError("Archive contains duplicate forecast hours")
    rendered_set = {int(hour) for hour in rendered_forecast_hours}
    unknown = rendered_set.difference(declared)
    if unknown:
        raise ValueError(f"Rendered forecast hours are absent from the archive: {sorted(unknown)}")
    rendered = [hour for hour in declared if hour in rendered_set]
    return {
        "archive_hours": declared,
        "rendered_hours": rendered,
        "not_rendered_hours": [hour for hour in declared if hour not in rendered_set],
    }


def build_tile_catalog(
    products: list[dict[str, Any]],
    existing_catalog: dict[str, Any] | None = None,
    generated_utc: str | None = None,
) -> dict[str, Any]:
    """Build a deterministic catalog, preserving its timestamp when inventory is unchanged."""
    previous = existing_catalog if isinstance(existing_catalog, dict) else {}
    previous_products = previous.get("products")
    previous_timestamp = previous.get("generated_utc")
    if previous_products == products and isinstance(previous_timestamp, str) and previous_timestamp:
        timestamp = previous_timestamp
    else:
        timestamp = generated_utc
    if not isinstance(timestamp, str) or not timestamp:
        raise ValueError("generated_utc is required when the tile product inventory changes")
    return {
        "schema_version": 1,
        "generated_utc": timestamp,
        "tile_scheme": "XYZ",
        "products": products,
    }


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
    for level, path in zip(contour.levels, contour.get_paths()):
        vertices = path.vertices
        codes = path.codes
        if codes is None:
            segments = [vertices]
        else:
            starts = np.flatnonzero(codes == 1)  # matplotlib.path.Path.MOVETO
            segments = [
                vertices[start:(starts[i + 1] if i + 1 < len(starts) else len(vertices))]
                for i, start in enumerate(starts)
            ]
        for segment in segments:
            if len(segment) < 2:
                continue
            coords = [[float(x), float(y)] for x, y in segment if np.isfinite(x) and np.isfinite(y)]
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
                 contour_interval: float | None = None, scale: float = 1.0,
                 offset: float = 0.0, display_units: str | None = None,
                 display_label: str | None = None) -> dict[str, Any]:
    field_key, field, data, grid = choose_field(payload, selector)
    source_units = field.get("units")
    data = data * float(scale) + float(offset)
    source_grid_shape = list(data.shape)
    source_grid_stride = int(grid.get("stride", 1))
    sampling = grid.get("sampling") or {}
    source_effective_spacing = sampling.get("effective_spacing_m")
    if not isinstance(source_effective_spacing, dict):
        projection = grid.get("projection") or {}
        dx, dy = projection.get("GRIB_DxInMetres"), projection.get("GRIB_DyInMetres")
        try:
            dx, dy = abs(float(dx)) * source_grid_stride, abs(float(dy)) * source_grid_stride
            source_effective_spacing = {"x": dx, "y": dy} if dx > 0 and dy > 0 else None
        except (TypeError, ValueError):
            source_effective_spacing = None
    lat = np.asarray(grid["latitude"], dtype=float)
    lon = ((np.asarray(grid["longitude"], dtype=float) + 180) % 360) - 180
    if data.shape != lat.shape or data.shape != lon.shape:
        raise ValueError(f"Field/grid shape mismatch: data={data.shape}, lat={lat.shape}, lon={lon.shape}")
    render_stride = display_sampling_stride(data.shape)
    if render_stride > 1:
        data = data[::render_stride, ::render_stride]
        lat = lat[::render_stride, ::render_stride]
        lon = lon[::render_stride, ::render_stride]
    render_effective_spacing = (
        {axis: float(source_effective_spacing[axis]) * render_stride
         for axis in ("x", "y") if source_effective_spacing.get(axis) is not None}
        if isinstance(source_effective_spacing, dict) else None
    )
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
        "long_name": display_label or field.get("long_name"), "units": display_units or source_units,
        "source_units": source_units, "display_transform": {"scale": float(scale), "offset": float(offset)},
        "source_grid_shape": source_grid_shape, "render_grid_shape": list(data.shape),
        "source_grid_id": field.get("grid_id"), "source_grid_stride": source_grid_stride,
        "render_stride": render_stride, "source_effective_spacing_m": source_effective_spacing,
        "render_effective_spacing_m": render_effective_spacing,
        "display_range": [low, high], "contour_interval": interval,
        "contour_levels": [float(v) for v in levels], "tile_size": TILE_SIZE,
        "zoom_min": zoom_min, "zoom_max": zoom_max, "tile_count": tile_count,
        "contour_feature_count": contour_count,
        "tile_url": f"{relative.as_posix()}/tiles/{{z}}/{{x}}/{{y}}.png",
        "contour_url": f"{relative.as_posix()}/contours.geojson",
        "rendering": "raster and contours use a bounded display resample; the full published grid remains available for cursor and point sampling",
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
    parser.add_argument("--scale", type=float, default=1.0)
    parser.add_argument("--offset", type=float, default=0.0)
    parser.add_argument("--display-units")
    parser.add_argument("--display-label")
    args = parser.parse_args()
    if args.zoom_min < 0 or args.zoom_max > 12 or args.zoom_min > args.zoom_max:
        parser.error("zoom range must satisfy 0 <= zoom-min <= zoom-max <= 12")
    result = render_tiles(load_payload(args.input), args.field, args.output,
                          args.zoom_min, args.zoom_max, args.cmap,
                          args.vmin, args.vmax, args.contour_interval,
                          args.scale, args.offset, args.display_units, args.display_label)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
