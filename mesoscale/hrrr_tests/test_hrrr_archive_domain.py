from mesoscale.process_grib import DOMAIN
from mesoscale.validate_hrrr_archive import archive_needs_update, build_archive_manifest


CYCLE = "2026-11-13T06:00:00Z"
VALID_TIME = "2026-11-13T07:00:00Z"
REQUIRED_GROUPS = {
    "2-m temperature": {},
    "10-m u wind": {},
    "10-m v wind": {},
}


def _model_manifest():
    return {
        "models": {
            "HRRR": {
                "latest_products": [{
                    "product": "surface",
                    "url": "https://example.test/hrrr.grib2",
                    "filename": "hrrr.t06z.wrfsfcf01.grib2",
                    "cycle_utc": CYCLE,
                    "forecast_hour": 1,
                }]
            }
        }
    }


def _existing_archive(domain):
    entry = {
        "forecast_hour": 1,
        "valid_time_utc": VALID_TIME,
        "grid_file": "hrrr_f01_btv.json.gz",
        "field_count": 3,
        "grid_count": 1,
        "required_field_groups": REQUIRED_GROUPS,
    }
    archive = build_archive_manifest(CYCLE, [entry])
    archive["domain"] = domain
    archive["publishing"] = True
    return archive


def test_hrrr_manifest_uses_decoded_domain_and_records_valid_time_alignment():
    archive = build_archive_manifest(
        CYCLE, [], valid_times=(VALID_TIME,), reference_rap_cycle=CYCLE
    )
    assert archive["domain"] == DOMAIN
    assert archive["valid_time_alignment"] == {
        "reference_model": "RAP",
        "reference_cycle_utc": CYCLE,
        "valid_times_utc": [VALID_TIME],
    }


def test_stale_hrrr_manifest_domain_forces_rebuild():
    manifest = _model_manifest()
    old_domain = {"west": -75.2, "east": -71.2, "south": 42.3, "north": 45.3}
    needs_update, _ = archive_needs_update(
        manifest, _existing_archive(old_domain), (1,), archive_root=None
    )
    assert needs_update is True
    needs_update, _ = archive_needs_update(
        manifest, _existing_archive(DOMAIN), (1,), archive_root=None
    )
    assert needs_update is False
