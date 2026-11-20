"""Portable launcher for the official SHARPpy desktop application."""
from __future__ import annotations
import os, shutil, sys
from pathlib import Path

def bundle_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent.parent

def install_btv_data_sources() -> None:
    source = bundle_root() / "native-sharppy"
    destination = Path(os.environ.get("APPDATA", Path.home())) / ".sharppy" / "datasources"
    destination.mkdir(parents=True, exist_ok=True)
    for name in ("btv_cwa_latest.xml", "btv_cwa.csv"):
        src = source / name
        if not src.is_file():
            raise FileNotFoundError(f"Bundled BTV data-source file is missing: {src}")
        shutil.copy2(src, destination / name)

def main() -> int:
    install_btv_data_sources()
    from runsharp.full_gui import main as sharppy_main
    sharppy_main()
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
