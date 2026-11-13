import gzip
import json
from pathlib import Path

import numpy as np
from PIL import Image

from mesoscale.render_model_tiles import render_tiles


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
