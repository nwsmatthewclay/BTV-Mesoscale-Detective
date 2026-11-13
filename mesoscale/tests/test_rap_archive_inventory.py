import gzip
import json
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ARCHIVE = ROOT / "mesoscale/data/fields/forecast/fields/rap_f00.json.gz"


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
            "shape": [
                len(field["data"]),
                len(field["data"][0]) if field["data"] else 0,
                len(field["data"][0][0]) if field["data"] and field["data"][0] else 0,
            ],
        })

    print("VERIFIED_RAP_F00_FIELD_INVENTORY=" + json.dumps(catalog, sort_keys=True))
    assert len(catalog) > 0
    assert any("hybrid" in field.get("dimensions", []) for fields in catalog.values() for field in fields)
