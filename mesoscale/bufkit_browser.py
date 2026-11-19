"""Small SHARPpy BUFKIT decoder bridge for Pyodide and browser-side use.

The browser downloads an archived .buf.gz file, decompresses it with the
Web Streams API, writes the BUFKIT text into Pyodide's virtual filesystem,
and calls decode_bufkit_file(). No server or paid service is required.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
from typing import Any

import numpy as np

_HEADER = re.compile(r"\bSTID\s*=\s*(\S+).*?\bTIME\s*=\s*(\d{6}/\d{4})")


def _headers(text: str) -> list[dict[str, Any]]:
    lines = text.splitlines()
    result = []
    for index, line in enumerate(lines):
        match = _HEADER.search(line)
        if not match:
            continue
        stim = None
        for candidate in lines[index + 1:index + 5]:
            found = re.search(r"\bSTIM\s*=\s*([-+]?\d+(?:\.\d+)?)", candidate)
            if found:
                stim = float(found.group(1))
                break
        if stim is None:
            raise ValueError(f"BUFKIT record at line {index + 1} has no STIM")
        valid = datetime.strptime(match.group(2), "%y%m%d/%H%M").replace(tzinfo=timezone.utc)
        result.append({
            "station": match.group(1).strip().upper(),
            "valid_time_utc": valid.isoformat().replace("+00:00", "Z"),
            "forecast_hour": stim,
            "model_cycle_utc": (valid - timedelta(hours=stim)).isoformat().replace("+00:00", "Z"),
        })
    if not result:
        raise ValueError("No BUFKIT STID/TIME/STIM records found")
    return result


def _values(value, name):
    array = np.ma.asarray(value, dtype=float)
    data = np.asarray(np.ma.getdata(array), dtype=float)
    mask = np.ma.getmaskarray(array) | ~np.isfinite(data)
    if data.ndim != 1:
        raise ValueError(f"SHARPpy BUFKIT field {name} is not one-dimensional")
    return np.ma.array(data, mask=mask)


def _to_contract(profile):
    fields = {
        "pressure": _values(profile.pres, "PRES"),
        "temperature": _values(profile.tmpc, "TMPC"),
        "dewpoint": _values(profile.dwpc, "DWPC"),
        "height": _values(profile.hght, "HGHT"),
        "u": _values(profile.u, "U"),
        "v": _values(profile.v, "V"),
    }
    if len({x.size for x in fields.values()}) != 1:
        raise ValueError("BUFKIT profile fields have inconsistent level counts")
    mask = np.ones(fields["pressure"].shape, dtype=bool)
    for value in fields.values():
        mask &= ~np.ma.getmaskarray(value)
    arrays = {key: np.asarray(value.data[mask], dtype=float) for key, value in fields.items()}
    if arrays["pressure"].size < 10:
        raise ValueError("BUFKIT profile has fewer than 10 complete levels")
    order = np.argsort(arrays["pressure"])[::-1]
    arrays = {key: value[order] for key, value in arrays.items()}
    if np.any(arrays["pressure"] <= 0) or not np.all(np.diff(arrays["pressure"]) < 0):
        raise ValueError("BUFKIT pressure does not strictly decrease upward")
    if not np.all(np.diff(arrays["height"]) > 0):
        raise ValueError("BUFKIT height does not strictly increase upward")
    result = {
        "pressure_hpa": arrays["pressure"].tolist(),
        "temperature_k": (arrays["temperature"] + 273.15).tolist(),
        "dewpoint_k": (arrays["dewpoint"] + 273.15).tolist(),
        "height_agl_m": (arrays["height"] - arrays["height"][0]).tolist(),
        "u_ms": (arrays["u"] / 1.9438444924406).tolist(),
        "v_ms": (arrays["v"] / 1.9438444924406).tolist(),
    }
    omega = getattr(profile, "omeg", None)
    if omega is not None:
        omega_array = np.ma.asarray(omega, dtype=float)
        if omega_array.size == len(mask):
            omega_data = np.asarray(np.ma.getdata(omega_array), dtype=float)[mask][order]
            omega_mask = np.ma.getmaskarray(omega_array)[mask][order] | ~np.isfinite(omega_data)
            result["omega_pa_s"] = [None if omega_mask[i] else float(omega_data[i]) for i in range(len(omega_data))]
    return result


def decode_bufkit_file(path: str, expected_station: str, expected_cycle: str, model: str) -> dict:
    """Decode every forecast time in a BUFKIT file with SHARPpy's BufDecoder."""
    from sharppy.io.buf_decoder import BufDecoder
    from sharppy.io.decoder import Decoder
    # SHARPpy passes a removed cafile keyword to urllib.request.urlopen.
    # Browser mode only reads a local Pyodide file, so use a local reader.
    Decoder._downloadFile = lambda self: open(self._file_name, "rb").read().decode("utf-8")

    with open(path, "r", encoding="ascii", errors="replace") as stream:
        headers = _headers(stream.read())
    expected_station = expected_station.upper()
    expected_cycle = expected_cycle.replace("+00:00", "Z")
    if any(h["station"] != expected_station for h in headers):
        raise ValueError("BUFKIT station identifier does not match selected station")
    if any(h["model_cycle_utc"] != expected_cycle for h in headers):
        raise ValueError("BUFKIT initialization cycle does not match selected cycle")

    collection = BufDecoder(path).getProfiles()
    profiles = []
    for index, header in enumerate(headers):
        if index:
            collection.advanceTime(1)
        current = collection.getCurrentProfs()
        member = collection.getHighlightedMemberName()
        if member not in current and len(current) == 1:
            member = next(iter(current))
        if member not in current:
            raise ValueError(f"No selectable SHARPpy profile at forecast record {index}")
        converted = _to_contract(current[member])
        profiles.append({
            **header,
            "profile": converted,
            "quality": {
                "status": "passed",
                "levels": len(converted["pressure_hpa"]),
                "height_reference": "lowest valid BUFKIT model level (relative AGL)",
                "decoder": "SHARPpy BufDecoder",
            },
        })
    if len(profiles) != len(headers):
        raise ValueError("SHARPpy decoder count does not match BUFKIT time blocks")
    return {"model": model.upper(), "station": expected_station, "model_cycle_utc": expected_cycle, "profiles": profiles}
