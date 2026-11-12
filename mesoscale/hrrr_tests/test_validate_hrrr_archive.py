import pytest

from mesoscale.validate_hrrr_archive import choose_cycle_products


def product(cycle, hour, family="surface"):
    token = "wrfsfc" if family == "surface" else "wrfprs"
    return {
        "cycle_utc": cycle,
        "forecast_hour": hour,
        "product": family,
        "filename": f"hrrr.t15z.{token}f{hour:02d}.grib2",
        "url": f"https://example.test/{token}/f{hour:02d}.grib2",
    }


def test_hrrr_archive_selects_latest_cycle_with_all_requested_hours():
    manifest = {"models": {"HRRR": {"latest_products": [
        product("20261112T14:00:00Z", 0),
        product("20261112T14:00:00Z", 3),
        product("20261112T14:00:00Z", 6),
        product("20261112T14:00:00Z", 9),
        product("20261112T15:00:00Z", 0),
        product("20261112T15:00:00Z", 3),
    ]}}}

    cycle, selected = choose_cycle_products(manifest, (0, 3, 6, 9))

    assert cycle == "20261112T14:00:00Z"
    assert [item["forecast_hour"] for item in selected] == [0, 3, 6, 9]


def test_hrrr_archive_never_mixes_cycles_to_fill_missing_hours():
    manifest = {"models": {"HRRR": {"latest_products": [
        product("20261112T15:00:00Z", 0),
        product("20261112T15:00:00Z", 3),
        product("20261112T14:00:00Z", 6),
        product("20261112T14:00:00Z", 9),
    ]}}}

    with pytest.raises(RuntimeError, match="refusing to mix model cycles"):
        choose_cycle_products(manifest, (0, 3, 6, 9))


def test_hrrr_archive_ignores_pressure_level_products():
    manifest = {"models": {"HRRR": {"latest_products": [
        product("20261112T15:00:00Z", 0, "pressure_levels"),
        product("20261112T15:00:00Z", 3, "pressure_levels"),
    ]}}}

    with pytest.raises(RuntimeError, match="No HRRR surface GRIB2 products"):
        choose_cycle_products(manifest, (0, 3))
