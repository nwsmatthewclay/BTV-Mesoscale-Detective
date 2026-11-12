from mesoscale.build_rap_forecast_archive import choose_cycle_products


def product(cycle, hour, family="hybrid_levels_conus_13km"):
    token = {
        "hybrid_levels_conus_13km": "awp130bgrb",
        "pressure_levels_conus_13km": "awp130pgrb",
        "north_american_32km": "awip32",
    }[family]
    return {
        "cycle_utc": cycle,
        "forecast_hour": hour,
        "product": family,
        "filename": f"rap.t10z.{token}f{hour:02d}.grib2",
        "url": f"https://example.test/rap_f{hour:02d}.grib2",
    }


def test_archive_selects_requested_hours_from_one_hybrid_cycle():
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
        product("2026-11-12T10:00:00Z", 0),
        product("2026-11-12T10:00:00Z", 3, "pressure_levels_conus_13km"),
        product("2026-11-12T10:00:00Z", 6),
    ]}}}
    import pytest
    with pytest.raises(RuntimeError, match="hybrid-level cycle contains all requested"):
        choose_cycle_products(manifest, (0, 3, 6))


def test_archive_does_not_accept_32km_fallback_as_hybrid_soundings():
    manifest = {"models": {"RAP": {"latest_products": [
        product("2026-11-12T10:00:00Z", 0, "north_american_32km"),
        product("2026-11-12T10:00:00Z", 3, "north_american_32km"),
        product("2026-11-12T10:00:00Z", 6, "north_american_32km"),
    ]}}}
    import pytest
    with pytest.raises(RuntimeError, match="No RAP 13-km CONUS hybrid-level"):
        choose_cycle_products(manifest, (0, 3, 6))


def test_archive_requires_every_requested_hour_from_one_cycle():
    manifest = {"models": {"RAP": {"latest_products": [
        product("2026-11-12T10:00:00Z", 0),
        product("2026-11-12T10:00:00Z", 3),
        product("2026-11-12T09:00:00Z", 6),
    ]}}}
    import pytest
    with pytest.raises(RuntimeError, match="contains all requested"):
        choose_cycle_products(manifest, (0, 3, 6))
