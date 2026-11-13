import pytest

from mesoscale.process_grib import DOMAIN, validate_grid_coverage


def regional_grid():
    return {
        "grid_0": {
            "latitude": [[32.0, 32.0], [52.0, 52.0]],
            "longitude": [[-90.0, -61.5], [-90.0, -61.5]],
        }
    }


def test_grid_coverage_accepts_full_common_rap_hrrr_domain():
    report = validate_grid_coverage(regional_grid(), DOMAIN)

    assert report["status"] == "passed"
    assert report["domain"] == DOMAIN
    assert report["grid_bounds"][0]["grid_id"] == "grid_0"
    assert report["grid_bounds"][0]["bounds"] == {
        "west": -90.0,
        "east": -61.5,
        "south": 32.0,
        "north": 52.0,
    }


def test_grid_coverage_rejects_btv_only_grid_that_cannot_support_upstream_view():
    grid = {
        "grid_0": {
            "latitude": [[44.0, 44.0], [45.0, 45.0]],
            "longitude": [[-75.0, -71.0], [-75.0, -71.0]],
        }
    }

    with pytest.raises(RuntimeError, match="does not cover required domain"):
        validate_grid_coverage(grid, DOMAIN)


def test_grid_coverage_rejects_mismatched_coordinate_shapes():
    grid = {
        "grid_0": {
            "latitude": [[32.0, 32.0], [52.0, 52.0]],
            "longitude": [[-90.0, -61.5]],
        }
    }

    with pytest.raises(RuntimeError, match="coordinate shapes do not match"):
        validate_grid_coverage(grid, DOMAIN)
