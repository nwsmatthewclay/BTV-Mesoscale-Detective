import pytest

from mesoscale.process_grib import (
    HRRR_MAX_GRID_DIM,
    RAP_MAX_GRID_DIM,
    grid_sampling_metadata,
    sampling_stride,
)


def test_rap_sampling_cap_preserves_the_expanded_hybrid_grid():
    assert RAP_MAX_GRID_DIM == 320
    assert sampling_stride((226, 178), RAP_MAX_GRID_DIM) == 1


def test_hrrr_sampling_cap_reports_the_bounded_surface_grid_stride():
    assert HRRR_MAX_GRID_DIM == 160
    assert sampling_stride((766, 726), HRRR_MAX_GRID_DIM) == 5


def test_effective_spacing_multiplies_source_spacing_by_stored_stride():
    rap = grid_sampling_metadata(
        {"GRIB_DxInMetres": 13545.0, "GRIB_DyInMetres": 13545.0},
        stride=2,
        max_grid_dim=320,
    )
    hrrr = grid_sampling_metadata(
        {"GRIB_DxInMetres": 3000.0, "GRIB_DyInMetres": 3000.0},
        stride=5,
        max_grid_dim=160,
    )

    assert rap["effective_spacing_m"] == {"x": 27090.0, "y": 27090.0}
    assert hrrr["effective_spacing_m"] == {"x": 15000.0, "y": 15000.0}


def test_sampling_stride_rejects_invalid_dimensions_and_caps():
    with pytest.raises(ValueError):
        sampling_stride((10, 10), 0)
    with pytest.raises(ValueError):
        sampling_stride((10,), 320)
    with pytest.raises(ValueError):
        sampling_stride((10, 0), 320)
