import pytest

from mesoscale.validate_hrrr_archive import archive_needs_update, choose_cycle_products


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



def published_hrrr_archive(cycle, hours=(0, 3, 6, 9), publishing=True, quality="passed"):
    required = {
        "2-m temperature": ["2t"],
        "10-m u wind": ["10u"],
        "10-m v wind": ["10v"],
    }
    return {
        "model": "HRRR",
        "product": "surface",
        "model_cycle_utc": cycle,
        "publishing": publishing,
        "hours": [
            {
                "forecast_hour": hour,
                "grid_file": f"hrrr_f{hour:02d}_btv.json.gz",
                "required_field_groups": required,
            }
            for hour in hours
        ],
        "quality": {"status": quality, "hours_verified": len(hours)},
    }


def test_hrrr_freshness_keeps_complete_archive_when_newer_cycle_is_still_filling():
    complete = "20261112T16:00:00Z"
    manifest = {"models": {"HRRR": {"latest_products": [
        product("20261112T17:00:00Z", 0),
        product("20261112T17:00:00Z", 3),
        *[product(complete, hour) for hour in (0, 3, 6, 9)],
    ]}}}

    needs_update, target = archive_needs_update(
        manifest, published_hrrr_archive(complete), (0, 3, 6, 9)
    )

    assert target == complete
    assert needs_update is False


def test_hrrr_freshness_requests_update_for_a_newer_complete_cycle():
    current = "20261112T16:00:00Z"
    newer = "20261112T17:00:00Z"
    manifest = {"models": {"HRRR": {"latest_products": [
        *[product(newer, hour) for hour in (0, 3, 6, 9)],
    ]}}}

    needs_update, target = archive_needs_update(
        manifest, published_hrrr_archive(current), (0, 3, 6, 9)
    )

    assert target == newer
    assert needs_update is True


def test_hrrr_freshness_rebuilds_unpublished_or_failed_archives():
    cycle = "20261112T16:00:00Z"
    manifest = {"models": {"HRRR": {"latest_products": [
        *[product(cycle, hour) for hour in (0, 3, 6, 9)],
    ]}}}

    assert archive_needs_update(manifest, None, (0, 3, 6, 9))[0] is True
    assert archive_needs_update(
        manifest, published_hrrr_archive(cycle, publishing=False), (0, 3, 6, 9)
    )[0] is True
    assert archive_needs_update(
        manifest, published_hrrr_archive(cycle, quality="failed"), (0, 3, 6, 9)
    )[0] is True
