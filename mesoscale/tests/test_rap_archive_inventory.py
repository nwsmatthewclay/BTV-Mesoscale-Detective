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

