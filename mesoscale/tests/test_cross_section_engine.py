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
        "grids": {"grid_0": {"latitude": lat, "longitude": lon, "shape": [3, 3], "stride": 1}},
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
    assert result["quality"]["sampling_count"] if "sampling_count" in result["quality"] else result["quality"]["sample_count"] == 5
    assert result["vertical_coordinate"]["levels_hpa"] == [900.0, 700.0, 500.0]
    assert result["fields"]["omega"]["units"] == "Pa s**-1"
    assert result["fields"]["omega"]["values"][0][0] == pytest.approx(-0.1)
    assert result["fields"]["omega"]["values"][0][-1] == pytest.approx(-0.4)


def test_cross_section_refuses_fields_on_different_hybrid_coordinates():
    payload = sample_payload()
    payload["fields"]["omega"]["levels"] = {"hybrid": [1, 2, 3, 5]}
    with pytest.raises(ValueError, match="identical hybrid coordinates"):
        build_cross_section(payload, (44.0, -73.2), (44.2, -73.0), {"omega": "w"}, sample_count=3)


def test_cross_section_refuses_ambiguous_short_name():
    payload = sample_payload()
    payload["fields"]["omega_duplicate"] = dict(payload["fields"]["omega"])
    with pytest.raises(ValueError, match="exactly one hybrid"):
        build_cross_section(payload, (44.0, -73.2), (44.2, -73.0), {"omega": "w"}, sample_count=3)
