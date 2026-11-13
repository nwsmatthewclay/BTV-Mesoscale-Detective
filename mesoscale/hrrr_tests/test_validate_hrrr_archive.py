import gzip
import json

import pytest

from datetime import datetime, timedelta, timezone

from mesoscale.process_grib import DOMAIN
from mesoscale.validate_hrrr_archive import (
    archive_needs_update,
    choose_cycle_products,
    choose_cycle_products_for_valid_times,
)


def product(cycle, hour, family="surface"):
    token = "wrfsfc" if family == "surface" else "wrfprs"
    return {
        "cycle_utc": cycle,
        "forecast_hour": hour,
        "product": family,
        "filename": f"hrrr.t15z.{token}f{hour:02d}.grib2",
        "url": f"https://example.test/{token}/f{hour:02d}.grib2",
    }


def write_hrrr_archive_files(archive_root, archive):
    for entry in archive["hours"]:
        path = archive_root / entry["grid_file"]
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "model": "HRRR",
            "model_cycle_utc": archive["model_cycle_utc"],
            "forecast_hour": entry["forecast_hour"],
            "valid_time_utc": entry["valid_time_utc"],
            "domain": DOMAIN,
            "grids": {
                "regional": {
                    "latitude": [[32.0, 32.0], [52.0, 52.0]],
                    "longitude": [[-90.0, -61.5], [-90.0, -61.5]],
                }
            },
            "fields": {
                "temperature": {"short_name": "2t", "grid_id": "regional", "data": [[280.0, 281.0], [282.0, 283.0]]},
                "u_wind": {"short_name": "10u", "grid_id": "regional", "data": [[1.0, 1.1], [1.2, 1.3]]},
                "v_wind": {"short_name": "10v", "grid_id": "regional", "data": [[-1.0, -1.1], [-1.2, -1.3]]},
            },
            "quality": {"field_count": 3, "grid_count": 1, "warnings": []},
        }
        with gzip.open(path, "wt", encoding="utf-8") as stream:
            json.dump(payload, stream)


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



def valid_time(cycle, hour):
    cycle_time = datetime.strptime(cycle, "%Y%m%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return (cycle_time + timedelta(hours=hour)).strftime("%Y-%m-%dT%H:%M:%SZ")


def published_hrrr_archive(cycle, hours=(0, 3, 6, 9), publishing=True, quality="passed"):
    required = {
        "2-m temperature": ["2t"],
        "10-m u wind": ["10u"],
        "10-m v wind": ["10v"],
    }
    return {
        "model": "HRRR",
        "product": "surface",
        "domain": DOMAIN,
        "model_cycle_utc": cycle,
        "publishing": publishing,
        "hours": [
            {
                "forecast_hour": hour,
                "valid_time_utc": valid_time(cycle, hour),
                "grid_file": f"hrrr_f{hour:02d}_btv.json.gz",
                "field_count": 3,
                "grid_count": 1,
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


def test_hrrr_freshness_rebuilds_archive_with_stale_domain_metadata():
    cycle = "20261112T16:00:00Z"
    manifest = {"models": {"HRRR": {"latest_products": [
        *[product(cycle, hour) for hour in (0, 3, 6, 9)],
    ]}}}
    archive = published_hrrr_archive(cycle)
    archive["domain"] = {"west": -75.2, "east": -71.2, "south": 42.3, "north": 45.3}

    assert archive_needs_update(manifest, archive, (0, 3, 6, 9))[0] is True


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



def test_hrrr_archive_aligns_forecast_hours_to_rap_valid_times():
    targets = (
        "2026-11-12T17:00:00Z",
        "2026-11-12T20:00:00Z",
        "2026-11-12T23:00:00Z",
        "2026-11-13T02:00:00Z",
    )
    manifest = {"models": {"HRRR": {"latest_products": [
        *[product("20261112T16:00:00Z", hour) for hour in (1, 4, 7, 10)],
        *[product("20261112T17:00:00Z", hour) for hour in (0, 1, 2)],
    ]}}}

    cycle, selected = choose_cycle_products_for_valid_times(manifest, targets)

    assert cycle == "20261112T16:00:00Z"
    assert [item["forecast_hour"] for item in selected] == [1, 4, 7, 10]


def test_hrrr_valid_time_alignment_refuses_to_mix_cycles():
    targets = (
        "2026-11-12T17:00:00Z",
        "2026-11-12T20:00:00Z",
        "2026-11-12T23:00:00Z",
        "2026-11-13T02:00:00Z",
    )
    manifest = {"models": {"HRRR": {"latest_products": [
        *[product("20261112T16:00:00Z", hour) for hour in (1, 4, 7)],
        *[product("20261112T17:00:00Z", hour) for hour in (0, 3, 6)],
    ]}}}

    with pytest.raises(RuntimeError, match="refusing to mix model cycles"):
        choose_cycle_products_for_valid_times(manifest, targets)


def test_hrrr_freshness_rebuilds_archive_when_valid_times_do_not_match_rap():
    targets = (
        "2026-11-12T17:00:00Z",
        "2026-11-12T20:00:00Z",
        "2026-11-12T23:00:00Z",
        "2026-11-13T02:00:00Z",
    )
    cycle = "20261112T16:00:00Z"
    manifest = {"models": {"HRRR": {"latest_products": [
        *[product(cycle, hour) for hour in (1, 4, 7, 10)],
        *[product("20261112T17:00:00Z", hour) for hour in (0, 1, 2)],
    ]}}}

    needs_update, target_cycle = archive_needs_update(
        manifest,
        published_hrrr_archive(cycle, hours=(0, 3, 6, 9)),
        (0, 3, 6, 9),
        valid_times=targets,
    )

    assert target_cycle == cycle
    assert needs_update is True


def test_hrrr_freshness_accepts_archive_aligned_to_rap_valid_times():
    targets = (
        "2026-11-12T17:00:00Z",
        "2026-11-12T20:00:00Z",
        "2026-11-12T23:00:00Z",
        "2026-11-13T02:00:00Z",
    )
    cycle = "20261112T16:00:00Z"
    manifest = {"models": {"HRRR": {"latest_products": [
        *[product(cycle, hour) for hour in (1, 4, 7, 10)],
        *[product("20261112T17:00:00Z", hour) for hour in (0, 1, 2)],
    ]}}}

    needs_update, target_cycle = archive_needs_update(
        manifest,
        published_hrrr_archive(cycle, hours=(1, 4, 7, 10)),
        (0, 3, 6, 9),
        valid_times=targets,
    )

    assert target_cycle == cycle
    assert needs_update is False



def test_hrrr_archive_aligns_six_forecast_points_to_rap_valid_times():
    targets = (
        "2026-11-12T17:00:00Z",
        "2026-11-12T20:00:00Z",
        "2026-11-12T23:00:00Z",
        "2026-11-13T02:00:00Z",
        "2026-11-13T05:00:00Z",
        "2026-11-13T08:00:00Z",
    )
    hours = (0, 3, 6, 9, 12, 15)
    cycle = "20261112T17:00:00Z"
    manifest = {"models": {"HRRR": {"latest_products": [
        *[product(cycle, hour) for hour in hours],
        *[product("20261112T18:00:00Z", hour) for hour in (0, 1, 2)],
    ]}}}

    selected_cycle, selected = choose_cycle_products_for_valid_times(manifest, targets)

    assert selected_cycle == cycle
    assert [item["forecast_hour"] for item in selected] == list(hours)



def test_hrrr_freshness_rebuilds_when_a_referenced_grid_is_missing(tmp_path):
    cycle = "20261112T16:00:00Z"
    manifest = {"models": {"HRRR": {"latest_products": [
        *[product(cycle, hour) for hour in (0, 3, 6, 9)],
    ]}}}
    archive = published_hrrr_archive(cycle)
    archive_root = tmp_path / "hrrr"

    write_hrrr_archive_files(archive_root, archive)

    assert archive_needs_update(
        manifest, archive, (0, 3, 6, 9), archive_root=archive_root
    )[0] is False

    (archive_root / archive["hours"][0]["grid_file"]).unlink()
    assert archive_needs_update(
        manifest, archive, (0, 3, 6, 9), archive_root=archive_root
    )[0] is True


def test_hrrr_freshness_rebuilds_when_published_grid_is_corrupt(tmp_path):
    cycle = "20261112T16:00:00Z"
    manifest = {"models": {"HRRR": {"latest_products": [
        *[product(cycle, hour) for hour in (0, 3, 6, 9)],
    ]}}}
    archive = published_hrrr_archive(cycle)
    archive_root = tmp_path / "hrrr"
    write_hrrr_archive_files(archive_root, archive)

    grid_path = archive_root / archive["hours"][0]["grid_file"]
    grid_path.write_bytes(b"truncated gzip data")

    assert archive_needs_update(
        manifest, archive, (0, 3, 6, 9), archive_root=archive_root
    )[0] is True


def test_hrrr_freshness_rebuilds_archive_with_inconsistent_valid_times():
    cycle = "20261112T16:00:00Z"
    manifest = {"models": {"HRRR": {"latest_products": [
        *[product(cycle, hour) for hour in (0, 3, 6, 9)],
    ]}}}
    archive = published_hrrr_archive(cycle)
    archive["hours"][1]["valid_time_utc"] = "2026-11-12T18:59:00Z"

    assert archive_needs_update(manifest, archive, (0, 3, 6, 9))[0] is True


def test_hrrr_freshness_treats_malformed_quality_metadata_as_stale():
    cycle = "20261112T16:00:00Z"
    manifest = {"models": {"HRRR": {"latest_products": [
        *[product(cycle, hour) for hour in (0, 3, 6, 9)],
    ]}}}
    archive = published_hrrr_archive(cycle)
    archive["quality"] = "passed"

    assert archive_needs_update(manifest, archive, (0, 3, 6, 9))[0] is True
