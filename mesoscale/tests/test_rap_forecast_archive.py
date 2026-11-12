from mesoscale.build_rap_forecast_archive import choose_cycle_products


def product(cycle, hour, family="north_american_32km"):
    return {
        "cycle_utc": cycle,
        "forecast_hour": hour,
        "product": family,
        "url": f"https://example.test/rap_f{hour:02d}.grib2",
    }


def test_archive_selects_requested_hours_from_one_cycle_and_family():
    manifest = {"models": {"RAP": {"latest_products": [
        product("2026-11-12T10:00:00Z", 9),
        product("2026-11-12T10:00:00Z", 6),
        product("2026-11-12T10:00:00Z", 3),
        product("2026-11-12T09:00:00Z", 0),
    ]}}}
    cycle, chosen = choose_cycle_products(manifest, (3, 6, 9))
    assert cycle == "2026-11-12T10:00:00Z"
    assert [p["forecast_hour"] for p in chosen] == [3, 6, 9]


def test_archive_does_not_mix_product_families():
    manifest = {"models": {"RAP": {"latest_products": [
        product("2026-11-12T10:00:00Z", 0, "north_american_32km"),
        product("2026-11-12T10:00:00Z", 3, "pressure_levels_conus"),
        product("2026-11-12T10:00:00Z", 6, "north_american_32km"),
    ]}}}
    import pytest
    with pytest.raises(RuntimeError, match="North American 32-km"):
        choose_cycle_products(manifest, (0, 3, 6))
