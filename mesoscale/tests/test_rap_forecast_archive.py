import gzip
import json
from datetime import datetime, timedelta

from mesoscale.build_rap_forecast_archive import archive_needs_update, choose_cycle_products
from mesoscale.process_grib import DOMAIN


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
    cycle_time = datetime.fromisoformat(cycle.replace("Z", "+00:00"))
    return {
        "model": "RAP",
        "domain": DOMAIN,
        "model_cycle_utc": cycle,
        "hours": [
            {
                "forecast_hour": hour,
                "valid_time_utc": (
                    cycle_time + timedelta(hours=hour)
                ).isoformat(timespec="seconds").replace("+00:00", "Z"),
                "grid_file": f"fields/rap_f{hour:02d}.json.gz",
                "station_file": f"fields/rap_f{hour:02d}_stations.json",
                "field_count": 1,
                "grid_count": 1,
                "station_count": 1,
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


def test_rap_freshness_rebuilds_archive_with_stale_domain_metadata():
    cycle = "2026-11-12T16:00:00Z"
    manifest = {"models": {"RAP": {"latest_products": [
        *[product(cycle, hour) for hour in (0, 3, 6, 9, 12, 15)],
    ]}}}
    archive = published_rap_archive(cycle)
    archive["domain"] = {"west": -75.2, "east": -71.2, "south": 42.3, "north": 45.3}

    assert archive_needs_update(manifest, archive, (0, 3, 6, 9, 12, 15))[0] is True


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



def write_rap_archive_files(archive_root, archive):
    for entry in archive["hours"]:
        grid_path = archive_root / entry["grid_file"]
        grid_path.parent.mkdir(parents=True, exist_ok=True)
        grid_payload = {
            "model": "RAP",
            "model_cycle_utc": archive["model_cycle_utc"],
            "forecast_hour": entry["forecast_hour"],
            "valid_time_utc": entry["valid_time_utc"],
            "domain": DOMAIN,
            "fields": {"temperature": {"short_name": "t", "grid_id": "hybrid"}},
            "grids": {"hybrid": {
                "latitude": [[32.0, 32.0], [52.0, 52.0]],
                "longitude": [[-90.0, -61.5], [-90.0, -61.5]],
                "shape": [2, 2],
            }},
            "quality": {"field_count": 1, "grid_count": 1},
        }
        with gzip.open(grid_path, "wt", encoding="utf-8") as stream:
            json.dump(grid_payload, stream)

        station_path = archive_root / entry["station_file"]
        station_path.parent.mkdir(parents=True, exist_ok=True)
        station_payload = {
            "model": "RAP",
            "model_cycle_utc": archive["model_cycle_utc"],
            "forecast_hour": entry["forecast_hour"],
            "valid_time_utc": entry["valid_time_utc"],
            "stations": {
                "KBTV": {
                    "model": "RAP",
                    "model_cycle_utc": archive["model_cycle_utc"],
                    "forecast_hour": entry["forecast_hour"],
                    "valid_time_utc": entry["valid_time_utc"],
                    "quality": {
                        "levels": 50,
                        "pressure_decreases_upward": True,
                        "height_increases_upward": True,
                    },
                }
            },
        }
        station_path.write_text(json.dumps(station_payload), encoding="utf-8")


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



def test_rap_freshness_rebuilds_when_referenced_archive_files_are_missing(tmp_path):
    cycle = "2026-11-12T16:00:00Z"
    manifest = {"models": {"RAP": {"latest_products": [
        *[product(cycle, hour) for hour in (0, 3, 6, 9, 12, 15)],
    ]}}}
    archive = published_rap_archive(cycle)
    archive_root = tmp_path / "forecast"

    write_rap_archive_files(archive_root, archive)

    assert archive_needs_update(
        manifest, archive, (0, 3, 6, 9, 12, 15), archive_root=archive_root
    )[0] is False

    (archive_root / archive["hours"][0]["grid_file"]).unlink()
    assert archive_needs_update(
        manifest, archive, (0, 3, 6, 9, 12, 15), archive_root=archive_root
    )[0] is True


def test_rap_freshness_rebuilds_when_published_json_is_corrupt(tmp_path):
    cycle = "2026-11-12T16:00:00Z"
    manifest = {"models": {"RAP": {"latest_products": [
        *[product(cycle, hour) for hour in (0, 3, 6, 9, 12, 15)],
    ]}}}
    archive = published_rap_archive(cycle)
    archive_root = tmp_path / "forecast"
    write_rap_archive_files(archive_root, archive)

    grid_path = archive_root / archive["hours"][0]["grid_file"]
    grid_path.write_bytes(b"not a gzip JSON file")

    assert archive_needs_update(
        manifest, archive, (0, 3, 6, 9, 12, 15), archive_root=archive_root
    )[0] is True


def test_rap_freshness_rebuilds_archive_with_inconsistent_valid_times():
    cycle = "2026-11-12T16:00:00Z"
    manifest = {"models": {"RAP": {"latest_products": [
        *[product(cycle, hour) for hour in (0, 3, 6, 9, 12, 15)],
    ]}}}
    archive = published_rap_archive(cycle)
    archive["hours"][2]["valid_time_utc"] = "2026-11-12T22:59:00Z"

    assert archive_needs_update(
        manifest, archive, (0, 3, 6, 9, 12, 15)
    )[0] is True
