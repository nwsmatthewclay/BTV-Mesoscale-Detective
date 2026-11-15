import gzip
import json
import pytest
from collections import defaultdict
from pathlib import Path

from mesoscale.cross_section import build_cross_section
from mesoscale.sharppy_adapter import calculate_sharppy_diagnostics
from mesoscale.build_rap_forecast_archive import summarize_rap_field_inventory


ROOT = Path(__file__).resolve().parents[2]
ARCHIVE = ROOT / "mesoscale/data/fields/forecast/fields/rap_f00.json.gz"


def _shape(value):
    return [len(value), *_shape(value[0])] if isinstance(value, list) and value else (
        [0] if isinstance(value, list) else []
    )


def test_print_verified_rap_field_inventory():
    assert ARCHIVE.is_file(), f"Expected committed RAP archive not found: {ARCHIVE}"
    with gzip.open(ARCHIVE, "rt", encoding="utf-8") as stream:
        payload = json.load(stream)

    assert payload["model"] == "RAP"
    catalog = defaultdict(list)
    for key, field in payload["fields"].items():
        levels = field.get("levels", {})
        catalog[field.get("short_name", "unknown")].append({
            "key": key,
            "units": field.get("units"),
            "long_name": field.get("long_name"),
            "dimensions": field.get("dimensions"),
            "level_coordinates": {
                name: {"count": len(values), "first": values[0] if values else None,
                       "last": values[-1] if values else None}
                for name, values in levels.items()
            },
            "grid_id": field.get("grid_id"),
            "shape": _shape(field.get("data", [])),
        })

    print("VERIFIED_RAP_F00_FIELD_INVENTORY=" + json.dumps(catalog, sort_keys=True))
    assert len(catalog) > 0
    assert any("hybrid" in field.get("dimensions", []) for fields in catalog.values() for field in fields)
    assert "w" in catalog
    omega = catalog["w"][0]
    assert omega["units"] == "Pa s**-1"
    assert omega["level_coordinates"]["hybrid"]["count"] == 50

    # Exercise the engine against the real committed RAP archive, not only
    # synthetic arrays. This confirms omega and temperature share pressure's
    # native hybrid coordinate and regional grid.
    section = build_cross_section(
        payload,
        (44.4719, -73.1533),
        (44.2035, -72.5623),
        {"omega": "w", "temperature": "t", "height": "gh"},
        pressure_levels_hpa=[950, 900, 850, 800, 750, 700, 650, 600, 550, 500],
        sample_count=50,
    )
    assert section["fields"]["omega"]["units"] == "Pa s**-1"
    assert section["quality"]["sample_count"] >= 2
    assert len(section["fields"]["omega"]["values"]) == section["quality"]["sample_count"]
    assert len(section["fields"]["omega"]["values"][0]) == 10



def test_sharppy_calculates_from_real_archived_kbtv_rap_profile():
    pytest.importorskip('sharppy', reason='SHARPpy is an optional sounding dependency')
    station_archive = ARCHIVE.with_name("rap_f00_stations.json")
    assert station_archive.is_file()
    payload = json.loads(station_archive.read_text(encoding="utf-8"))
    profile = payload["stations"]["KBTV"]["profile"]
    result = calculate_sharppy_diagnostics(profile)

    assert result["library"] == "SHARPpy"
    assert result["quality"]["input_levels"] == 50
    assert set(result["parcels"]) == {"surface", "most_unstable", "mixed_layer"}
    assert result["parcels"]["surface"]["cape_jkg"] is not None
    assert result["kinematics"]["bulk_shear_0_6km_kt"] is not None
    assert result["units"]["cape"] == "J/kg"

def test_rap_inventory_summary_distinguishes_records_from_unique_short_names():
    payload = {
        "fields": {
            "t_surface": {"short_name": "t"},
            "t_850": {"short_name": "t"},
            "u_850": {"short_name": "u"},
        },
        "quality": {"field_count": 3},
    }

    field_records, unique_short_names = summarize_rap_field_inventory(payload)

    assert field_records == 3
    assert unique_short_names == {"t", "u"}


def test_rap_inventory_summary_rejects_inconsistent_quality_count():
    payload = {
        "fields": {"t_surface": {"short_name": "t"}},
        "quality": {"field_count": 2},
    }

    with pytest.raises(ValueError, match="does not match decoded field records"):
        summarize_rap_field_inventory(payload)


def test_all_published_rap_station_profiles_have_consistent_arrays_and_provenance():
    import numpy as np

    manifest_path = ARCHIVE.parent.parent / "forecast_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_stations = {"KBTV", "KPBG", "KMSS", "KSLK", "KMPV", "KRUT", "1V4", "KEFK"}

    assert manifest["model"] == "RAP"
    assert manifest["quality"]["status"] == "passed"
    assert len(manifest["hours"]) == 6

    for hour in manifest["hours"]:
        station_path = manifest_path.parent / hour["station_file"]
        collection = json.loads(station_path.read_text(encoding="utf-8"))

        assert collection["model"] == "RAP"
        assert collection["model_cycle_utc"] == manifest["model_cycle_utc"]
        assert collection["forecast_hour"] == hour["forecast_hour"]
        assert collection["valid_time_utc"] == hour["valid_time_utc"]
        assert set(collection["stations"]) == expected_stations
        assert len(collection["stations"]) == hour["station_count"] == 8

        for station, entry in collection["stations"].items():
            assert entry["model"] == "RAP"
            assert entry["model_cycle_utc"] == manifest["model_cycle_utc"]
            assert entry["forecast_hour"] == hour["forecast_hour"]
            assert entry["valid_time_utc"] == hour["valid_time_utc"]

            profile = entry["profile"]
            arrays = {
                name: profile[name]
                for name in (
                    "pressure_hpa",
                    "temperature_k",
                    "dewpoint_k",
                    "height_agl_m",
                    "u_ms",
                    "v_ms",
                )
            }
            lengths = {name: len(values) for name, values in arrays.items()}
            assert len(set(lengths.values())) == 1, f"{station} F{hour['forecast_hour']:02d}: {lengths}"
            level_count = next(iter(lengths.values()))
            assert level_count > 0
            assert entry["quality"]["levels"] == level_count

            pressure = np.asarray(arrays["pressure_hpa"], dtype=float)
            height = np.asarray(arrays["height_agl_m"], dtype=float)
            assert np.all(np.isfinite(pressure))
            assert np.all(np.isfinite(height))
            assert np.all(np.diff(pressure) < 0), f"{station} F{hour['forecast_hour']:02d}: pressure order"
            assert np.all(np.diff(height) > 0), f"{station} F{hour['forecast_hour']:02d}: height order"
            assert entry["quality"]["pressure_decreases_upward"] is True
            assert entry["quality"]["height_increases_upward"] is True
            assert entry["quality"]["profile_warnings"] == []


def test_generic_cross_section_validates_all_published_forecast_hours():
    """Exercise geographic/vertical sampling for every committed RAP hour."""
    import numpy as np

    manifest_path = ARCHIVE.parent.parent / "forecast_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_hours = [0, 3, 6, 9, 12, 15]

    assert manifest["model"] == "RAP"
    assert manifest["quality"]["status"] == "passed"
    assert [item["forecast_hour"] for item in manifest["hours"]] == expected_hours

    reports = []
    for hour in manifest["hours"]:
        grid_path = manifest_path.parent / hour["grid_file"]
        assert grid_path.is_file(), f"Missing published RAP grid: {grid_path}"
        with gzip.open(grid_path, "rt", encoding="utf-8") as stream:
            payload = json.load(stream)

        assert payload["model"] == "RAP"
        assert payload["model_cycle_utc"] == manifest["model_cycle_utc"]
        assert payload["forecast_hour"] == hour["forecast_hour"]
        assert payload["valid_time_utc"] == hour["valid_time_utc"]

        section = build_cross_section(
            payload,
            (44.4719, -73.1533),
            (44.2035, -72.5623),
            {"temperature": "t", "specific_humidity": "q"},
            pressure_levels_hpa=[850, 700, 500],
            sample_count=50,
        )
        quality = section["quality"]
        assert section["model_cycle_utc"] == manifest["model_cycle_utc"]
        assert section["forecast_hour"] == hour["forecast_hour"]
        assert section["valid_time_utc"] == hour["valid_time_utc"]
        assert quality["status"] == "passed"
        assert quality["sample_count"] >= 2
        assert quality["max_sample_offset_km"] <= quality["native_grid_sample_offset_limit_km"]
        assert section["transect"]["total_distance_km"] > 0
        assert section["transect"]["sampled_distance_range_km"][1] <= section["transect"]["total_distance_km"]

        finite_by_field = {}
        for name, field in section["fields"].items():
            values = [value for column in field["values"] for value in column if value is not None]
            assert values, f"No finite {name} values for RAP F{hour['forecast_hour']:02d}"
            assert np.all(np.isfinite(np.asarray(values, dtype=float)))
            finite_by_field[name] = len(values)

        reports.append({
            "forecast_hour": hour["forecast_hour"],
            "valid_time_utc": hour["valid_time_utc"],
            "sample_count": quality["sample_count"],
            "finite_values_by_field": finite_by_field,
            "unavailable_values_by_field": quality["unavailable_values_by_field"],
            "max_sample_offset_km": quality["max_sample_offset_km"],
            "native_grid_sample_offset_limit_km": quality["native_grid_sample_offset_limit_km"],
        })

    print("RAP_ALL_HOUR_CROSS_SECTION_VALIDATION=" + json.dumps({
        "model_cycle_utc": manifest["model_cycle_utc"],
        "forecast_hours": reports,
    }, sort_keys=True))
