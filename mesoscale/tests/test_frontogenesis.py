import numpy as np
import pytest

from mesoscale.frontogenesis import build_frontogenesis_cross_section


def frontogenesis_payload():
    lat = [[44.0, 44.0, 44.0], [44.1, 44.1, 44.1], [44.2, 44.2, 44.2]]
    lon = [[-73.2, -73.1, -73.0], [-73.2, -73.1, -73.0], [-73.2, -73.1, -73.0]]
    levels = {"hybrid": [1, 2, 3, 4]}
    dims = ["hybrid"]
    shape = (4, 3, 3)
    pressure = np.broadcast_to(np.array([100000, 80000, 60000, 40000])[:, None, None], shape).tolist()
    x = np.broadcast_to(np.arange(3)[None, None, :], shape)
    temperature = (
        np.broadcast_to(np.array([290, 280, 270, 260])[:, None, None], shape) + x * 2
    ).tolist()
    u = np.broadcast_to((10 - np.arange(3)[None, None, :] * 2), shape).tolist()
    v = np.zeros(shape).tolist()
    return {
        "model": "RAP",
        "model_cycle_utc": "2026-11-13T00:00:00Z",
        "forecast_hour": 3,
        "valid_time_utc": "2026-11-13T03:00:00Z",
        "source_file": "synthetic_lambert.grib2",
        "grids": {
            "grid_0": {
                "latitude": lat, "longitude": lon, "shape": [3, 3], "stride": 1,
                "projection": {
                    "GRIB_gridType": "lambert",
                    "GRIB_DxInMetres": 10000,
                    "GRIB_DyInMetres": 10000,
                },
            }
        },
        "fields": {
            "pres": {"short_name": "pres", "units": "Pa", "dimensions": dims,
                     "levels": levels, "grid_id": "grid_0", "data": pressure},
            "temp": {"short_name": "t", "units": "K", "dimensions": dims,
                     "levels": levels, "grid_id": "grid_0", "data": temperature},
            "u": {"short_name": "u", "units": "m s**-1", "dimensions": dims,
                  "levels": levels, "grid_id": "grid_0", "data": u,
                  "grib_metadata": {"GRIB_uvRelativeToGrid": 1}},
            "v": {"short_name": "v", "units": "m s**-1", "dimensions": dims,
                  "levels": levels, "grid_id": "grid_0", "data": v,
                  "grib_metadata": {"GRIB_uvRelativeToGrid": 1}},
        },
    }


def test_frontogenesis_calculates_from_verified_grid_relative_winds():
    result = build_frontogenesis_cross_section(
        frontogenesis_payload(),
        (44.1, -73.2),
        (44.1, -73.0),
        pressure_levels_hpa=[800, 700],
        sample_count=5,
    )
    field = result["fields"]["frontogenesis"]
    assert field["units"] == "K (100 km)-1 (3 h)-1"
    assert result["provenance"]["grid_type"] == "lambert"
    assert result["provenance"]["grid_spacing_m"] == {"dx": 10000, "dy": 10000}
    finite_values = [value for row in field["values"] for value in row if value is not None]
    assert finite_values
    assert max(finite_values) > 0


def test_frontogenesis_refuses_unknown_wind_orientation():
    payload = frontogenesis_payload()
    payload["fields"]["u"]["grib_metadata"] = {}
    with pytest.raises(ValueError, match="grid-relative"):
        build_frontogenesis_cross_section(
            payload, (44.1, -73.2), (44.1, -73.0),
            pressure_levels_hpa=[800, 700], sample_count=5,
        )


def test_frontogenesis_refuses_missing_projection_metadata():
    payload = frontogenesis_payload()
    payload["grids"]["grid_0"].pop("projection")
    with pytest.raises(ValueError, match="projection"):
        build_frontogenesis_cross_section(
            payload, (44.1, -73.2), (44.1, -73.0),
            pressure_levels_hpa=[800, 700], sample_count=5,
        )
