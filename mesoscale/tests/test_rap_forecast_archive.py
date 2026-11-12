from mesoscale.build_rap_forecast_archive import archive_needs_update, choose_cycle_products


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



def published_rap_archive(cycle, hours=(0, 3, 6, 9, 12, 15), quality="passed"):
    return {
        "model": "RAP",
        "model_cycle_utc": cycle,
        "hours": [
            {
                "forecast_hour": hour,
                "grid_file": f"fields/rap_f{hour:02d}.json.gz",
                "station_file": f"fields/rap_f{hour:02d}_stations.json",
            }
            for hour in hours
        ],
        "quality": {"status": quality, "hours_verified": len(hours)},
    }


def test_rap_freshness_keeps_complete_archive_when_newer_cycle_is_still_filling():
    complete = "2026-11-12T16:00:00Z"
    manifest = {"models": {"RAP": {"latest_products": [
        product("2026-11-12T17:00:00Z", 0),
        product("2026-11-12T17:00:00Z", 3),
        product("2026-11-12T17:00:00Z", 6),
        *[product(complete, hour) for hour in (0, 3, 6, 9, 12, 15)],
    ]}}}

    needs_update, target = archive_needs_update(
        manifest, published_rap_archive(complete), (0, 3, 6, 9, 12, 15)
    )

    assert target == complete
    assert needs_update is False


def test_rap_freshness_requests_update_for_a_newer_complete_cycle():
    current = "2026-11-12T16:00:00Z"
    newer = "2026-11-12T17:00:00Z"
    manifest = {"models": {"RAP": {"latest_products": [
        *[product(newer, hour) for hour in (0, 3, 6, 9, 12, 15)],
    ]}}}

    needs_update, target = archive_needs_update(
        manifest, published_rap_archive(current), (0, 3, 6, 9, 12, 15)
    )

    assert target == newer
    assert needs_update is True


def test_rap_freshness_rebuilds_missing_or_failed_archives():
    cycle = "2026-11-12T16:00:00Z"
    manifest = {"models": {"RAP": {"latest_products": [
        *[product(cycle, hour) for hour in (0, 3, 6, 9, 12, 15)],
    ]}}}

    assert archive_needs_update(manifest, None, (0, 3, 6, 9, 12, 15))[0] is True
    assert archive_needs_update(
        manifest, published_rap_archive(cycle, quality="failed"), (0, 3, 6, 9, 12, 15)
    )[0] is True
    assert archive_needs_update(
        manifest, published_rap_archive(cycle, hours=(0, 3, 6, 9, 12)), (0, 3, 6, 9, 12, 15)
    )[0] is True



def test_archive_selects_six_three_hourly_forecast_points_from_one_cycle():
    hours = (0, 3, 6, 9, 12, 15)
    cycle = "2026-11-12T17:00:00Z"
    manifest = {"models": {"RAP": {"latest_products": [
        *[product(cycle, hour) for hour in hours],
        product("2026-11-12T16:00:00Z", 0),
        product("2026-11-12T16:00:00Z", 3),
    ]}}}

    selected_cycle, selected = choose_cycle_products(manifest, hours)

    assert selected_cycle == cycle
    assert [item["forecast_hour"] for item in selected] == list(hours)


def test_archive_rebuilds_four_hour_archive_to_add_f12_and_f15():
    hours = (0, 3, 6, 9, 12, 15)
    cycle = "2026-11-12T17:00:00Z"
    manifest = {"models": {"RAP": {"latest_products": [
        *[product(cycle, hour) for hour in hours],
    ]}}}

    needs_update, target = archive_needs_update(
        manifest, published_rap_archive(cycle, hours=(0, 3, 6, 9)), hours
    )

    assert target == cycle
    assert needs_update is True
