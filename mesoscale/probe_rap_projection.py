#!/usr/bin/env python3
"""Read-only probe of real RAP projection, cross-section, and wind metadata.

Downloads one RAP F00 hybrid-level product into a temporary directory,
decodes the bounded BTV subset, exercises the generic vertical cross-section
sampler and (when wind orientation is verified) frontogenesis. It never
publishes or commits data.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mesoscale.build_rap_forecast_archive import choose_cycle_products, download
from mesoscale.cross_section import build_cross_section
from mesoscale.frontogenesis import build_frontogenesis_cross_section
from mesoscale.process_grib import RAP_MAX_GRID_DIM, process_file


TRANSECT_START = (44.4719, -73.1533)
TRANSECT_END = (44.2035, -72.5623)
PRESSURE_LEVELS_HPA = [850, 700, 500]


def decode_probe_product(grib_path: Path, cycle: str, output_path: Path) -> dict:
    """Decode the probe with the same RAP sampling policy used by production archives."""
    return process_file(
        grib_path, "RAP", cycle, 0, output_path, max_grid_dim=RAP_MAX_GRID_DIM
    )


def main() -> None:
    manifest_path = Path("mesoscale/data/model_manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    cycle, products = choose_cycle_products(manifest, (0,))
    product = products[0]
    session = requests.Session()
    session.headers.update({"User-Agent": "BTV-Mesoscale-Detective/0.1 read-only metadata probe"})

    with tempfile.TemporaryDirectory(prefix="btv-rap-projection-") as tmp:
        root = Path(tmp)
        grib_path = root / product["filename"]
        output_path = root / "rap_f00.json.gz"
        size = download(product["url"], grib_path, session)
        payload = decode_probe_product(grib_path, cycle, output_path)

        temperature = [
            field for field in payload["fields"].values()
            if field.get("short_name") == "t" and "hybrid" in field.get("dimensions", [])
        ]
        if len(temperature) != 1:
            raise RuntimeError(f"Expected one hybrid temperature field, found {len(temperature)}")
        grid_id = temperature[0]["grid_id"]
        grid = payload["grids"][grid_id]
        projection = grid.get("projection") or {}
        u_fields = [
            field for field in payload["fields"].values()
            if field.get("short_name") == "u" and field.get("grid_id") == grid_id
            and "hybrid" in field.get("dimensions", [])
        ]
        v_fields = [
            field for field in payload["fields"].values()
            if field.get("short_name") == "v" and field.get("grid_id") == grid_id
            and "hybrid" in field.get("dimensions", [])
        ]
        if len(u_fields) != 1 or len(v_fields) != 1:
            raise RuntimeError("Could not identify unique collocated hybrid U/V fields")
        u_relative = (u_fields[0].get("grib_metadata") or {}).get("GRIB_uvRelativeToGrid")
        v_relative = (v_fields[0].get("grib_metadata") or {}).get("GRIB_uvRelativeToGrid")

        report = {
            "status": "metadata_inspected",
            "model": "RAP",
            "cycle_utc": cycle,
            "forecast_hour": 0,
            "valid_time_utc": payload["valid_time_utc"],
            "source_file": product["filename"],
            "download_bytes": size,
            "grid_id": grid_id,
            "grid_shape": grid["shape"],
            "sampling": grid.get("sampling"),
            "processing": payload.get("processing"),
            "projection": projection,
            "u_grib_metadata": u_fields[0].get("grib_metadata"),
            "v_grib_metadata": v_fields[0].get("grib_metadata"),
            "u_relative_to_grid": u_relative,
            "v_relative_to_grid": v_relative,
        }
        print("RAP_PROJECTION_PROBE=" + json.dumps(report, sort_keys=True))

        required_projection = (
            projection.get("GRIB_gridType")
            and projection.get("GRIB_DxInMetres")
            and projection.get("GRIB_DyInMetres")
        )
        if not required_projection:
            raise RuntimeError("RAP source did not expose grid type and native Dx/Dy metadata")

        # Exercise the generic pressure-coordinate cross-section engine against
        # the actual decoded RAP temperature and specific-humidity columns.
        # This is intentionally separate from frontogenesis: it validates the
        # general transect sampler, native-grid distance guard, hybrid pressure
        # selection, and missing-level reporting without requiring wind rotation.
        section = build_cross_section(
            payload,
            TRANSECT_START,
            TRANSECT_END,
            {"temperature": "t", "specific_humidity": "q"},
            pressure_levels_hpa=PRESSURE_LEVELS_HPA,
            sample_count=50,
        )
        finite_by_field = {
            name: sum(
                value is not None
                for column in field["values"]
                for value in column
            )
            for name, field in section["fields"].items()
        }
        if section["quality"]["status"] != "passed" or section["quality"]["sample_count"] < 2:
            raise RuntimeError("Real RAP generic cross-section did not pass native-grid sampling quality")
        if any(count < 1 for count in finite_by_field.values()):
            raise RuntimeError(
                "Real RAP generic cross-section produced no finite values for one or more selected fields: "
                f"{finite_by_field}"
            )
        if section["quality"]["max_sample_offset_km"] > section["quality"]["native_grid_sample_offset_limit_km"]:
            raise RuntimeError("Real RAP generic cross-section exceeded the native-grid distance limit")

        cross_section_report = {
            "status": "real_rap_generic_cross_section_passed",
            "model_cycle_utc": cycle,
            "valid_time_utc": payload["valid_time_utc"],
            "source_file": product["filename"],
            "grid_id": section["grid_id"],
            "sample_count": section["quality"]["sample_count"],
            "requested_sample_count": section["quality"]["requested_sample_count"],
            "pressure_levels_hpa": section["vertical_coordinate"]["levels_hpa"],
            "field_short_names": {
                name: field["short_name"] for name, field in section["fields"].items()
            },
            "field_units": {
                name: field["units"] for name, field in section["fields"].items()
            },
            "finite_values_by_field": finite_by_field,
            "unavailable_values_by_field": section["quality"]["unavailable_values_by_field"],
            "total_distance_km": section["transect"]["total_distance_km"],
            "sampled_distance_range_km": section["transect"]["sampled_distance_range_km"],
            "native_grid_sample_offset_limit_km": section["quality"]["native_grid_sample_offset_limit_km"],
            "max_sample_offset_km": section["quality"]["max_sample_offset_km"],
            "missing_level_policy": section["quality"]["missing_level_policy"],
        }
        print("RAP_CROSS_SECTION_PROBE=" + json.dumps(cross_section_report, sort_keys=True))

        if u_relative in (1, True, "1") and v_relative in (1, True, "1"):
            frontogenesis = build_frontogenesis_cross_section(
                payload,
                TRANSECT_START,
                TRANSECT_END,
                pressure_levels_hpa=PRESSURE_LEVELS_HPA,
                sample_count=50,
            )
            values = [
                value
                for row in frontogenesis["fields"]["frontogenesis"]["values"]
                for value in row
                if value is not None
            ]
            report = {
                "status": "real_rap_frontogenesis_passed",
                "model_cycle_utc": cycle,
                "valid_time_utc": payload["valid_time_utc"],
                "sample_count": frontogenesis["quality"]["sample_count"],
                "pressure_levels_hpa": frontogenesis["quality"]["pressure_levels_hpa"],
                "finite_frontogenesis_values": len(values),
                "units": frontogenesis["fields"]["frontogenesis"]["units"],
            }
            print("RAP_FRONTGENESIS_PROBE=" + json.dumps(report, sort_keys=True))
            if not values:
                raise RuntimeError("Real RAP frontogenesis returned no finite transect values")
        else:
            print("RAP_FRONTGENESIS_PROBE=" + json.dumps({
                "status": "blocked_wind_rotation_required",
                "u_relative_to_grid": u_relative,
                "v_relative_to_grid": v_relative,
                "note": "No wind rotation is guessed; implement and validate projection rotation first.",
            }, sort_keys=True))


if __name__ == "__main__":
    main()
