import numpy as np
import pytest

from mesoscale.cross_section import build_cross_section, great_circle_points


def sample_payload():
    lat = [[44.0, 44.0, 44.0], [44.1, 44.1, 44.1], [44.2, 44.2, 44.2]]
    lon = [[-73.2, -73.1, -73.0], [-73.2, -73.1, -73.0], [-73.2, -73.1, -73.0]]
    levels = {"hybrid": [1, 2, 3, 4]}
    dims = ["hybrid"]
    shape = (4, 3, 3)
    pressure_column = np.array([100000.0, 80000.0, 60000.0, 40000.0])
    pressure = np.broadcast_to(pressure_column[:, None, None], shape).tolist()
    temperature = np.broadcast_to(np.array([290.0, 280.0, 270.0, 260.0])[:, None, None], shape).tolist()
    omega = np.broadcast_to(np.array([-0.1, -0.2, -0.3, -0.4])[:, None, None], shape).tolist()
    return {
        "model": "RAP",
        "model_cycle_utc": "2026-11-13T00:00:00Z",
        "forecast_hour": 3,
        "valid_time_utc": "2026-11-13T03:00:00Z",
        "source_file": "synthetic.grib2",
        "grids": {"grid_0": {
            "latitude": lat, "longitude": lon, "shape": [3, 3], "stride": 1,
            "sampling": {"stride": 1, "effective_spacing_m": {"x": 13545.0, "y": 13545.0}},
        }},
        "fields": {
            "pres": {"short_name": "pres", "units": "Pa", "dimensions": dims, "levels": levels,
                     "grid_id": "grid_0", "data": pressure},
            "temp": {"short_name": "t", "units": "K", "dimensions": dims, "levels": levels,
                     "grid_id": "grid_0", "data": temperature},
            "omega": {"short_name": "w", "units": "Pa s**-1", "dimensions": dims, "levels": levels,
                      "grid_id": "grid_0", "data": omega},
        },
    }


def test_great_circle_points_are_evenly_spaced():
    points, distances = great_circle_points((44.0, -73.2), (44.2, -73.0), 5)
    assert len(points) == 5
    assert distances[0] == 0
    assert distances[-1] > 20
    assert np.allclose(np.diff(distances), np.diff(distances)[0])


def test_cross_section_samples_hybrid_field_on_common_log_pressure_levels():
    result = build_cross_section(
        sample_payload(), (44.0, -73.2), (44.2, -73.0),
        {"omega": "w"}, pressure_levels_hpa=[900, 700, 500], sample_count=5,
    )
    assert result["model"] == "RAP"
    assert 2 <= result["quality"]["sample_count"] <= 5
    assert result["quality"]["requested_sample_count"] == 5
    assert len({(p["grid_y"], p["grid_x"]) for p in result["transect"]["points"]}) == result["quality"]["sample_count"]
    assert result["vertical_coordinate"]["levels_hpa"] == [900.0, 700.0, 500.0]
    assert result["fields"]["omega"]["units"] == "Pa s**-1"
    assert result["fields"]["omega"]["values"][0][0] == pytest.approx(-0.1472164734)
    assert result["fields"]["omega"]["values"][0][-1] == pytest.approx(-0.3449660287)


def test_cross_section_disables_vertical_extrapolation():
    result = build_cross_section(
        sample_payload(), (44.0, -73.2), (44.2, -73.0),
        {"omega": "w"}, pressure_levels_hpa=[1100, 900, 700, 500, 300], sample_count=3,
    )
    values = result["fields"]["omega"]["values"][0]
    assert values[0] is None
    assert values[-1] is None
    assert values[1] is not None


def test_cross_section_rejects_transects_outside_native_grid_coverage():
    with pytest.raises(ValueError, match="within the native-grid distance limit"):
        build_cross_section(
            sample_payload(), (46.0, -73.2), (46.2, -73.0),
            {"omega": "w"}, pressure_levels_hpa=[900, 700, 500], sample_count=5,
        )


def test_cross_section_skips_outside_samples_and_reports_distance_quality():
    result = build_cross_section(
        sample_payload(), (44.0, -73.2), (44.4, -73.0),
        {"omega": "w"}, pressure_levels_hpa=[900, 700, 500], sample_count=9,
    )
    quality = result["quality"]
    assert quality["rejected_outside_native_grid_samples"] > 0
    assert quality["max_sample_offset_km"] <= quality["native_grid_sample_offset_limit_km"]
    assert quality["sample_count"] + quality["duplicate_native_grid_samples_removed"] + quality[
        "rejected_outside_native_grid_samples"
    ] == quality["requested_sample_count"]
    _, requested_distances = great_circle_points((44.0, -73.2), (44.4, -73.0), 9)
    assert result["transect"]["total_distance_km"] == pytest.approx(requested_distances[-1])
    assert result["transect"]["sampled_distance_range_km"][1] < result["transect"]["total_distance_km"]


def test_cross_section_derives_effective_spacing_from_projection_and_stride():
    payload = sample_payload()
    grid = payload["grids"]["grid_0"]
    grid.pop("sampling")
    grid["projection"] = {"GRIB_DxInMetres": 13545.0, "GRIB_DyInMetres": 13545.0}
    grid["stride"] = 2

    result = build_cross_section(
        payload, (44.0, -73.2), (44.2, -73.0),
        {"omega": "w"}, pressure_levels_hpa=[900, 700, 500], sample_count=5,
    )
    expected_limit_km = np.hypot(27090.0, 27090.0) * 0.75 / 1000.0
    assert result["quality"]["native_grid_sample_offset_limit_km"] == pytest.approx(expected_limit_km)


def test_cross_section_requires_effective_or_native_grid_spacing_metadata():
    payload = sample_payload()
    payload["grids"]["grid_0"].pop("sampling")
    with pytest.raises(ValueError, match="effective grid spacing metadata unavailable"):
        build_cross_section(
            payload, (44.0, -73.2), (44.2, -73.0),
            {"omega": "w"}, pressure_levels_hpa=[900, 700, 500], sample_count=5,
        )


def test_cross_section_refuses_fields_on_different_hybrid_coordinates():
    payload = sample_payload()
    payload["fields"]["omega"]["levels"] = {"hybrid": [1, 2, 3, 5]}
    with pytest.raises(ValueError, match="share reference hybrid coordinates"):
        build_cross_section(payload, (44.0, -73.2), (44.2, -73.0), {"omega": "w"}, sample_count=3)


def test_cross_section_refuses_ambiguous_short_name():
    payload = sample_payload()
    payload["fields"]["omega_duplicate"] = dict(payload["fields"]["omega"])
    with pytest.raises(ValueError, match="exactly one hybrid"):
        build_cross_section(payload, (44.0, -73.2), (44.2, -73.0), {"omega": "w"}, sample_count=3)
