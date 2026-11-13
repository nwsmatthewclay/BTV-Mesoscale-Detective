import gzip
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from mesoscale.render_model_tiles import (
    TILE_MAX_GRID_DIM,
    render_tiles,
    summarize_forecast_hour_coverage,
)


def test_tile_coverage_reports_only_forecast_hours_actually_rendered():
    hours = [{"forecast_hour": value} for value in (0, 3, 6, 9, 12, 15)]

    coverage = summarize_forecast_hour_coverage(hours, [0])

    assert coverage == {
        "archive_hours": [0, 3, 6, 9, 12, 15],
        "rendered_hours": [0],
        "not_rendered_hours": [3, 6, 9, 12, 15],
    }


def test_tile_coverage_rejects_unknown_or_duplicate_forecast_hours():
    import pytest

    with pytest.raises(ValueError, match="absent from the archive"):
        summarize_forecast_hour_coverage([{"forecast_hour": 0}], [3])
    with pytest.raises(ValueError, match="duplicate forecast hours"):
        summarize_forecast_hour_coverage([{"forecast_hour": 0}, {"forecast_hour": 0}], [0])


def test_render_native_grid_to_xyz_raster_and_independent_contours(tmp_path: Path):
    lat = np.linspace(40, 48, 30)
    lon = np.linspace(-80, -68, 40)
    lon2, lat2 = np.meshgrid(lon, lat)
    values = 1000 + 8 * np.sin((lon2 + 74) / 2) + 5 * np.cos((lat2 - 44) / 2)
    payload = {
        "model": "RAP", "model_cycle_utc": "2026-11-13T00:00:00Z",
        "forecast_hour": 0, "valid_time_utc": "2026-11-13T00:00:00Z",
        "domain": {"west": -80, "east": -68, "south": 40, "north": 48},
        "grids": {"g": {"latitude": lat2.tolist(), "longitude": lon2.tolist()}},
        "fields": {"gh_2d": {
            "short_name": "gh", "long_name": "Geopotential height",
            "units": "gpm", "grid_id": "g", "data": values.tolist(),
        }},
    }
    result = render_tiles(payload, "gh", tmp_path, 3, 4, "viridis", contour_interval=2)
    assert result["tile_count"] > 0
    assert result["contour_feature_count"] > 0
    assert result["source_grid_shape"] == [30, 40]
    assert result["render_grid_shape"] == [30, 40]
    assert result["render_stride"] == 1
    product_path = tmp_path / "rap" / "20261113T000000Z" / "f00" / "gh_2d" / "product.json"
    assert product_path.is_file()
    tile_paths = list(product_path.parent.glob("tiles/*/*/*.png"))
    assert tile_paths
    with Image.open(tile_paths[0]) as image:
        assert image.mode == "RGBA"
        assert image.size == (256, 256)
    geojson = json.loads((product_path.parent / "contours.geojson").read_text())
    assert geojson["type"] == "FeatureCollection"
    assert all(feature["geometry"]["type"] == "LineString" for feature in geojson["features"])


def test_tile_renderer_rejects_ambiguous_short_names(tmp_path: Path):
    lat = np.linspace(40, 42, 5)
    lon = np.linspace(-75, -73, 6)
    lon2, lat2 = np.meshgrid(lon, lat)
    base = {
        "model": "RAP", "model_cycle_utc": "2026-11-13T00:00:00Z",
        "forecast_hour": 0, "valid_time_utc": "2026-11-13T00:00:00Z",
        "grids": {"g": {"latitude": lat2.tolist(), "longitude": lon2.tolist()}},
        "fields": {},
    }
    for suffix in ("surface", "column"):
        base["fields"][f"t_{suffix}"] = {
            "short_name": "t", "grid_id": "g",
            "data": (np.ones_like(lat2) * (270 if suffix == "surface" else 260)).tolist(),
        }
    import pytest
    with pytest.raises(ValueError, match="matched 2"):
        render_tiles(base, "t", tmp_path, 3, 3)


def test_model_tile_frontend_uses_catalog_and_keeps_pages_sources_synchronized():
    root = Path(__file__).resolve().parents[2]
    html = (root / "index.html").read_text(encoding="utf-8")
    mirror = (root / "mesoscale.html").read_text(encoding="utf-8")
    assert html == mirror
    assert "async function loadModelTileCatalog()" in html
    assert "L.tileLayer(tileUrl" in html
    assert "L.geoJSON(geojson" in html
    assert "await renderPublishedModelTiles(payload,'RAP',param)" in html
    assert "await renderPublishedModelTiles(payload,'HRRR',param)" in html
    assert "tile.openstreetmap.org" in html
    assert "function selectedTileFieldKey(model,param,payload)" in html
    assert "item.field_key===fieldKey" in html
    assert "option.dataset.fieldKey=fieldKey" in html
    assert "for(const [fieldKey,field] of Object.entries(payload.fields||{}))" in html
    assert "staticNames.has(shortName)" not in html
    assert "map.on('mousemove'" in html
    assert "stateBoundaryPane" in html
    assert "countyBoundaryPane" in html



def test_tile_renderer_bounds_display_resample_and_preserves_source_resolution(tmp_path: Path):
    lat = np.linspace(40, 48, 400)
    lon = np.linspace(-80, -68, 350)
    lon2, lat2 = np.meshgrid(lon, lat)
    values = 1000 + 8 * np.sin((lon2 + 74) / 2) + 5 * np.cos((lat2 - 44) / 2)
    payload = {
        "model": "HRRR", "model_cycle_utc": "2026-11-13T14:00:00Z",
        "forecast_hour": 0, "valid_time_utc": "2026-11-13T14:00:00Z",
        "domain": {"west": -80, "east": -68, "south": 40, "north": 48},
        "grids": {"g": {
            "latitude": lat2.tolist(), "longitude": lon2.tolist(),
            "stride": 1,
            "sampling": {"effective_spacing_m": {"x": 3000.0, "y": 3000.0}},
        }},
        "fields": {"t_2d": {
            "short_name": "t", "long_name": "Temperature",
            "units": "K", "grid_id": "g", "data": values.tolist(),
        }},
    }

    result = render_tiles(payload, "t", tmp_path, 3, 3, "viridis", contour_interval=2)

    assert TILE_MAX_GRID_DIM == 320
    assert result["source_grid_shape"] == [400, 350]
    assert result["render_grid_shape"] == [200, 175]
    assert result["render_stride"] == 2
    assert result["source_grid_stride"] == 1
    assert result["source_effective_spacing_m"] == {"x": 3000.0, "y": 3000.0}
    assert result["render_effective_spacing_m"] == {"x": 6000.0, "y": 6000.0}
    assert len(payload["grids"]["g"]["latitude"]) == 400
