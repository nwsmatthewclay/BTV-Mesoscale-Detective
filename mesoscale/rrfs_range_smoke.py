#!/usr/bin/env python3
"""Safely smoke-test RRFS indexed HTTP byte-range retrieval without publishing data."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import requests

HEADERS = {
    "User-Agent": "BTV-Mesoscale-Detective/0.1 (NWS forecast office research)",
    "Accept-Encoding": "identity",
}
MAX_MESSAGE_BYTES = 20_000_000
CONTENT_RANGE_RE = re.compile(r"bytes\s+(\d+)-(\d+)/(\d+)$", re.IGNORECASE)
BTV_DOMAIN = {"west": -75.2, "east": -71.2, "south": 42.3, "north": 45.3}


def select_rrfs_product(manifest: dict) -> dict:
    """Select the newest indexed 3-km RRFS subhourly surface product."""
    products = (manifest.get("models") or {}).get("RRFS", {}).get("latest_products") or []
    candidates = [
        item for item in products
        if item.get("product") == "surface_subhourly_3km"
        and item.get("url")
        and isinstance(item.get("index"), dict)
        and item["index"].get("messages")
    ]
    if not candidates:
        index_errors = [
            item.get("index_error") for item in products
            if item.get("product") == "surface_subhourly_3km" and item.get("index_error")
        ]
        detail = f"; latest index error: {index_errors[0]}" if index_errors else ""
        raise ValueError(
            "No RRFS 3-km subhourly surface product with indexed message metadata is available"
            + detail
        )
    return max(
        candidates,
        key=lambda item: (
            str(item.get("cycle_utc") or ""),
            -int(item.get("forecast_lead_minutes") or 0),
        ),
    )


def plan_index_ranges(
    messages: list[dict],
    limit: int = 3,
    max_message_bytes: int = MAX_MESSAGE_BYTES,
    preferred_short_names: tuple[str, ...] | None = None,
) -> list[dict]:
    """Use each next GRIB-index offset to bound the preceding message."""
    if limit < 1:
        raise ValueError("message limit must be at least one")
    if max_message_bytes < 1:
        raise ValueError("maximum message size must be positive")
    if not isinstance(messages, list) or len(messages) < 2:
        raise ValueError("at least two index records are required to bound a message")

    offsets = []
    for index, record in enumerate(messages):
        try:
            offset = int(record["byte_offset"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"index record {index + 1} has an invalid byte offset") from exc
        if offset < 0 or (offsets and offset <= offsets[-1]):
            raise ValueError("GRIB index byte offsets must be non-negative and strictly increasing")
        offsets.append(offset)

    if preferred_short_names:
        if limit < len(preferred_short_names):
            raise ValueError(
                f"message limit {limit} cannot include all {len(preferred_short_names)} required fields"
            )
        selected_positions = []
        missing = []
        for short_name in preferred_short_names:
            target = str(short_name).upper()
            position = next(
                (
                    index for index, record in enumerate(messages[:-1])
                    if str(record.get("short_name") or record.get("level") or "").upper() == target
                ),
                None,
            )
            if position is None:
                missing.append(target)
            else:
                selected_positions.append(position)
        if missing:
            raise ValueError(
                "RRFS index is missing required smoke-test fields: " + ", ".join(missing)
            )
        selected_positions = selected_positions[:limit]
    else:
        selected_positions = list(range(min(limit, len(messages) - 1)))

    planned = []
    for index in selected_positions:
        start = offsets[index]
        end = offsets[index + 1] - 1
        size = end - start + 1
        if size <= 0:
            raise ValueError(f"index record {index + 1} has an empty byte range")
        if size > max_message_bytes:
            raise ValueError(
                f"indexed message {messages[index].get('message', index + 1)} "
                f"exceeds the {max_message_bytes}-byte safety cap ({size} bytes)"
            )
        record = messages[index]
        planned.append({
            "message": str(record.get("message", index + 1)),
            "short_name": record.get("short_name") or record.get("level"),
            "level": record.get("level"),
            "description": record.get("description", ""),
            "start": start,
            "end": end,
            "bytes": size,
        })
    if not planned:
        raise ValueError("no bounded GRIB messages could be planned")
    return planned


def verify_content_range(value: str | None, start: int, end: int) -> int:
    """Require an exact HTTP 206 Content-Range response for the requested bytes."""
    match = CONTENT_RANGE_RE.fullmatch((value or "").strip())
    if not match:
        raise RuntimeError(f"Missing or invalid Content-Range header: {value!r}")
    actual_start, actual_end, total = map(int, match.groups())
    if actual_start != start or actual_end != end or total <= end:
        raise RuntimeError(
            f"Content-Range mismatch: expected bytes {start}-{end}/N, "
            f"received bytes {actual_start}-{actual_end}/{total}"
        )
    return total


def fetch_indexed_message(
    session: requests.Session,
    url: str,
    record: dict,
) -> bytes:
    """Fetch one indexed message and reject servers that ignore byte ranges."""
    start, end = int(record["start"]), int(record["end"])
    headers = {**HEADERS, "Range": f"bytes={start}-{end}"}
    with session.get(url, headers=headers, timeout=(20, 90)) as response:
        if response.status_code != 206:
            raise RuntimeError(
                f"NOMADS did not honor the requested byte range "
                f"(HTTP {response.status_code}; expected 206)"
            )
        response.raise_for_status()
        verify_content_range(response.headers.get("Content-Range"), start, end)
        payload = response.content

    if len(payload) != end - start + 1:
        raise RuntimeError(
            f"Range body length mismatch: expected {end - start + 1}, received {len(payload)}"
        )
    if not payload.startswith(b"GRIB") or payload[-4:] != b"7777":
        raise RuntimeError("Indexed byte range is not one complete GRIB message")
    return payload


def validate_decoded_cycle(decoded: dict, cycle_utc: str) -> None:
    """Reject decoded GRIB messages whose reference date/time differs from the selected cycle."""
    match = re.match(r"^(\d{4})-?(\d{2})-?(\d{2})T(\d{2})", cycle_utc)
    if not match:
        raise ValueError(f"Invalid model cycle timestamp: {cycle_utc!r}")
    expected_date = int("".join(match.group(index) for index in (1, 2, 3)))
    expected_time = int(match.group(4)) * 100
    if decoded.get("data_date") is not None and int(decoded["data_date"]) != expected_date:
        raise RuntimeError(
            f"GRIB reference date mismatch: expected {expected_date}, got {decoded['data_date']}"
        )
    if decoded.get("data_time") is not None and int(decoded["data_time"]) != expected_time:
        raise RuntimeError(
            f"GRIB reference time mismatch: expected {expected_time:04d}, got {decoded['data_time']}"
        )


def summarize_btv_coverage(latitudes, longitudes, domain: dict = BTV_DOMAIN) -> dict:
    """Summarize finite RRFS grid points inside the padded BTV analysis domain."""
    try:
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("BTV coverage validation requires numpy") from exc

    lat = np.asarray(latitudes, dtype=float).reshape(-1)
    lon = np.asarray(longitudes, dtype=float).reshape(-1)
    if lat.size == 0 or lon.size != lat.size:
        raise ValueError("RRFS latitude/longitude arrays must be non-empty and have equal lengths")

    # ecCodes may expose longitudes in either -180..180 or 0..360 convention.
    normalized_lon = ((lon + 180.0) % 360.0) - 180.0
    finite = np.isfinite(lat) & np.isfinite(normalized_lon)
    inside = (
        finite
        & (normalized_lon >= float(domain["west"]))
        & (normalized_lon <= float(domain["east"]))
        & (lat >= float(domain["south"]))
        & (lat <= float(domain["north"]))
    )
    count = int(inside.sum())
    if count == 0:
        raise RuntimeError("RRFS grid does not intersect the BTV analysis domain")

    return {
        "domain": dict(domain),
        "grid_points": int(lat.size),
        "points_inside_domain": count,
        "fraction_inside_domain": round(count / int(lat.size), 8),
        "bounds": {
            "south": float(lat[inside].min()),
            "north": float(lat[inside].max()),
            "west": float(normalized_lon[inside].min()),
            "east": float(normalized_lon[inside].max()),
        },
    }


def decode_grib_message(payload: bytes, include_btv_coverage: bool = False) -> dict:
    """Decode GRIB metadata, finite values, and optionally BTV geographic coverage."""
    try:
        import numpy as np
        from eccodes import (
            codes_get,
            codes_get_array,
            codes_new_from_message,
            codes_release,
        )
    except ImportError as exc:
        raise RuntimeError("The RRFS smoke test requires numpy and eccodes") from exc

    handle = codes_new_from_message(payload)
    if handle is None:
        raise RuntimeError("ecCodes could not create a handle for the indexed GRIB message")
    try:
        values = np.asarray(codes_get_array(handle, "values"), dtype=float)
        finite_count = int(np.isfinite(values).sum())
        if finite_count < 1:
            raise RuntimeError("Decoded GRIB message contains no finite grid values")

        def optional(key):
            try:
                return codes_get(handle, key)
            except Exception:
                return None

        decoded = {
            "short_name": optional("shortName"),
            "type_of_level": optional("typeOfLevel"),
            "level": optional("level"),
            "data_date": optional("dataDate"),
            "data_time": optional("dataTime"),
            "step_range": optional("stepRange"),
            "grid_type": optional("gridType"),
            "ni": optional("Ni"),
            "nj": optional("Nj"),
            "number_of_points": int(values.size),
            "finite_value_count": finite_count,
        }
        if include_btv_coverage:
            try:
                latitudes = codes_get_array(handle, "latitudes")
                longitudes = codes_get_array(handle, "longitudes")
            except Exception as exc:
                raise RuntimeError(
                    "ecCodes could not derive RRFS latitude/longitude coordinates for BTV coverage"
                ) from exc
            decoded["btv_coverage"] = summarize_btv_coverage(latitudes, longitudes)
        return decoded
    finally:
        codes_release(handle)


def run_smoke(
    manifest: dict,
    session: requests.Session,
    message_limit: int = 4,
    decoder=decode_grib_message,
) -> dict:
    """Download and decode a small set of indexed messages entirely in memory."""
    product = select_rrfs_product(manifest)
    index = product["index"]
    index_url = index.get("url")
    if index_url != product["url"] + ".idx":
        raise ValueError("RRFS index URL does not match the selected GRIB product URL")

    ranges = plan_index_ranges(
        index.get("messages") or [],
        limit=message_limit,
        preferred_short_names=("TMP", "DPT", "UGRD", "VGRD"),
    )
    decoded_messages = []
    total_bytes = 0
    for message_index, record in enumerate(ranges):
        payload = fetch_indexed_message(session, product["url"], record)
        decoded = decoder(payload, include_btv_coverage=(message_index == 0))
        if message_index == 0:
            coverage = decoded.get("btv_coverage")
            if not isinstance(coverage, dict) or int(coverage.get("points_inside_domain") or 0) < 1:
                raise RuntimeError("First RRFS field did not verify any grid points inside the BTV domain")
        # NOMADS index mnemonics and ecCodes shortName aliases are not guaranteed
        # to be identical (some local-table fields decode as "unknown"). Keep
        # both labels in the report; validate the decoded reference date/time
        # and non-empty values instead of rejecting an alias difference.
        validate_decoded_cycle(decoded, product["cycle_utc"])
        total_bytes += len(payload)
        decoded_messages.append({
            **record,
            "decoded": decoded,
        })

    return {
        "status": "passed",
        "model": "RRFS",
        "product": product["product"],
        "filename": product["filename"],
        "model_cycle_utc": product["cycle_utc"],
        "forecast_step": product.get("forecast_step"),
        "forecast_lead_minutes": product.get("forecast_lead_minutes"),
        "index_url": index_url,
        "index_message_count": index.get("message_count", len(index.get("messages") or [])),
        "messages_verified": len(decoded_messages),
        "bytes_downloaded": total_bytes,
        "btv_coverage": decoded_messages[0]["decoded"]["btv_coverage"],
        "publication": False,
        "messages": decoded_messages,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default="mesoscale/data/model_manifest.json")
    parser.add_argument("--messages", type=int, default=4)
    parser.add_argument("--output", help="Optional JSON report path")
    args = parser.parse_args()

    try:
        manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
        session = requests.Session()
        session.headers.update(HEADERS)
        report = run_smoke(manifest, session, message_limit=args.messages)
    except Exception as exc:
        report = {"status": "failed", "error": f"{type(exc).__name__}: {exc}", "publication": False}
        print(json.dumps(report, indent=2), file=sys.stderr)
        if args.output:
            output = Path(args.output)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        return 1

    print(json.dumps(report, indent=2))
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
