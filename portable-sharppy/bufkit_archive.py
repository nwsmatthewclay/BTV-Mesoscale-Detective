"""Local BUFKIT archive discovery for the BTV native NSHARP portable app.

Default office archive: T:\\data. The scanner does not modify source files and
supports plain BUFKIT and gzip-compressed BUFKIT files.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import gzip
import os
from pathlib import Path
import re
from typing import Any, Iterable

DEFAULT_ARCHIVE_ROOT = r"T:\\data"
SUPPORTED_SUFFIXES = (".buf", ".buf.gz")
MODEL_ALIASES = {
    "RAP": ("rap",),
    "HRRR": ("hrrr",),
    "GFS": ("gfs", "gfs3"),
    "NAM": ("nam",),
    "NAMNEST": ("namnest",),
    "RRFS": ("rrfs",),
    "HIRESW": ("hiresw",),
    "ECMWF": ("ecmwf", "ec"),
}


def archive_root() -> Path:
    """Return the configured archive path (environment override, then T:\\data)."""
    return Path(os.environ.get("BTV_BUFKIT_ARCHIVE", DEFAULT_ARCHIVE_ROOT))


def _read_text(path: Path) -> str:
    if path.name.lower().endswith(".gz"):
        with gzip.open(path, "rt", encoding="latin-1", errors="replace") as stream:
            return stream.read()
    return path.read_text(encoding="latin-1", errors="replace")


def parse_headers(text: str) -> list[dict[str, Any]]:
    """Parse each STID/TIME/STIM header block from a BUFKIT text file."""
    lines = text.splitlines()
    result = []
    for i, line in enumerate(lines):
        stid = re.search(r"\\bSTID\\s*=\\s*(\\S+)", line)
        time = re.search(r"\\bTIME\\s*=\\s*(\\d{6}/\\d{4})", line)
        if not stid or not time:
            continue
        stim = None
        for candidate in lines[i + 1:i + 6]:
            match = re.search(r"\\bSTIM\\s*=\\s*([-+]?\\d+(?:\\.\\d+)?)", candidate)
            if match:
                stim = float(match.group(1))
                break
        if stim is None:
            continue
        valid = datetime.strptime(time.group(1), "%y%m%d/%H%M").replace(tzinfo=timezone.utc)
        result.append({
            "station": stid.group(1).strip().upper(),
            "valid_utc": valid,
            "forecast_hour": stim,
            "cycle_utc": valid - timedelta(hours=stim),
        })
    return result


def _model_from_path(path: Path) -> str:
    pieces = [part.lower() for part in path.parts]
    stem = path.name.lower()
    for model, aliases in MODEL_ALIASES.items():
        if any(alias in stem for alias in aliases) or any(
            part == alias or part.startswith(alias + "_") for part in pieces for alias in aliases
        ):
            return model
    return "UNKNOWN"


def iter_bufkit_files(root: Path) -> Iterable[Path]:
    if not root.exists() or not root.is_dir():
        return
    for directory, _, names in os.walk(root):
        for name in names:
            lower = name.lower()
            if lower.endswith(SUPPORTED_SUFFIXES):
                yield Path(directory) / name


def scan_archive(root: str | Path | None = None, *, max_files: int | None = None) -> dict[str, Any]:
    """Index archive BUFKIT files into model/cycle/station/forecast-hour metadata."""
    root = Path(root) if root is not None else archive_root()
    files = []
    errors = []
    count = 0
    for path in iter_bufkit_files(root):
        if max_files is not None and count >= max_files:
            break
        count += 1
        try:
            records = parse_headers(_read_text(path))
            model = _model_from_path(path)
            for header in records:
                files.append({
                    "path": str(path),
                    "model": model,
                    **{key: value.isoformat().replace("+00:00", "Z") if isinstance(value, datetime) else value
               for key, value in header.items()},
                    "size_bytes": path.stat().st_size,
                    "modified_utc": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat().replace("+00:00", "Z"),
                })
        except (OSError, UnicodeError, ValueError, EOFError) as exc:
            errors.append({"path": str(path), "error": str(exc)})
    models = sorted({entry["model"] for entry in files})
    stations = sorted({entry["station"] for entry in files})
    cycles = sorted({entry["cycle_utc"] for entry in files}, reverse=True)
    forecast_hours = sorted({entry["forecast_hour"] for entry in files})
    return {
        "archive_root": str(root),
        "available": root.exists() and root.is_dir(),
        "file_count_scanned": count,
        "record_count": len(files),
        "models": models,
        "stations": stations,
        "cycles_utc": cycles,
        "forecast_hours": forecast_hours,
        "records": files,
        "errors": errors,
    }


if __name__ == "__main__":
    import json
    print(json.dumps(scan_archive(), indent=2))
