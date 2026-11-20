"""Local BUFKIT archive discovery for the BTV native NSHARP portable app.
Default office archive: T:\data. Read-only scanner for plain and gzip BUFKIT files.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
import gzip, os, re
from pathlib import Path
from typing import Any, Iterable

DEFAULT_ARCHIVE_ROOT = r"T:\data"
SUPPORTED_SUFFIXES = (".buf", ".buf.gz")
MODEL_ALIASES = {
    "RAP": ("rap",), "HRRR": ("hrrr",), "GFS": ("gfs", "gfs3"),
    "NAMNEST": ("namnest",), "NAM": ("nam",), "RRFS": ("rrfs",),
    "HIRESW": ("hiresw",), "ECMWF": ("ecmwf", "ec"),
}

def archive_root() -> Path:
    return Path(os.environ.get("BTV_BUFKIT_ARCHIVE", DEFAULT_ARCHIVE_ROOT))

def _read_text(path: Path) -> str:
    if path.name.lower().endswith(".gz"):
        with gzip.open(path, "rt", encoding="latin-1", errors="replace") as stream:
            return stream.read()
    return path.read_text(encoding="latin-1", errors="replace")

def parse_headers(text: str) -> list[dict[str, Any]]:
    lines, result = text.splitlines(), []
    for i, line in enumerate(lines):
        station = re.search(r"\bSTID\s*=\s*(\S+)", line)
        valid_match = re.search(r"\bTIME\s*=\s*(\d{6}/\d{4})", line)
        if not station or not valid_match:
            continue
        lead = None
        for candidate in lines[i + 1:i + 6]:
            match = re.search(r"\bSTIM\s*=\s*([-+]?\d+(?:\.\d+)?)", candidate)
            if match:
                lead = float(match.group(1))
                break
        if lead is None:
            continue
        valid = datetime.strptime(valid_match.group(1), "%y%m%d/%H%M").replace(tzinfo=timezone.utc)
        result.append({"station": station.group(1).strip().upper(),
                      "valid_utc": valid, "forecast_hour": lead,
                      "cycle_utc": valid - timedelta(hours=lead)})
    return result

def _model_from_path(path: Path) -> str:
    parts = [p.lower() for p in path.parts]
    filename = path.name.lower()
    # Prefer the filename's model identifier over a parent folder: archives
    # commonly group files by cycle while storing several model feeds together.
    for model, aliases in MODEL_ALIASES.items():
        for alias in aliases:
            if filename.startswith(alias + "_") or filename.startswith(alias + "."):
                return model
    for model, aliases in MODEL_ALIASES.items():
        if any(alias in parts for alias in aliases):
            return model
    return "UNKNOWN"

def iter_bufkit_files(root: Path) -> Iterable[Path]:
    if not root.exists() or not root.is_dir():
        return
    for directory, _, names in os.walk(root):
        for name in names:
            if name.lower().endswith(SUPPORTED_SUFFIXES):
                yield Path(directory) / name

def scan_archive(root: str | Path | None = None, *, max_files: int | None = None) -> dict[str, Any]:
    root = Path(root) if root is not None else archive_root()
    records, errors, scanned = [], [], 0
    for path in iter_bufkit_files(root):
        if max_files is not None and scanned >= max_files:
            break
        scanned += 1
        try:
            model = _model_from_path(path)
            for header in parse_headers(_read_text(path)):
                records.append({"path": str(path), "model": model,
                    **{k: (v.isoformat().replace("+00:00", "Z") if isinstance(v, datetime) else v)
                       for k, v in header.items()},
                    "size_bytes": path.stat().st_size,
                    "modified_utc": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat().replace("+00:00", "Z")})
        except (OSError, UnicodeError, ValueError, EOFError) as exc:
            errors.append({"path": str(path), "error": str(exc)})
    return {"archive_root": str(root), "available": root.is_dir(),
            "file_count_scanned": scanned, "record_count": len(records),
            "models": sorted({r["model"] for r in records}),
            "stations": sorted({r["station"] for r in records}),
            "cycles_utc": sorted({r["cycle_utc"] for r in records}, reverse=True),
            "forecast_hours": sorted({r["forecast_hour"] for r in records}),
            "records": records, "errors": errors}

if __name__ == "__main__":
    import json
    print(json.dumps(scan_archive(), indent=2))
