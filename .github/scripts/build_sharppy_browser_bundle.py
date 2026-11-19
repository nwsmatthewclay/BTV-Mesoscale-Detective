"""Build a compact browser-loadable archive of the pinned SHARPpy source tree."""
from __future__ import annotations

import io
import urllib.request
import zipfile
from pathlib import Path

URL = "https://codeload.github.com/sharppy/SHARPpy/zip/refs/tags/v1.4.0"
OUT = Path("mesoscale/vendor/sharppy-1.4.0-browser.zip")
OUT.parent.mkdir(parents=True, exist_ok=True)

request = urllib.request.Request(URL, headers={"User-Agent": "BTV-Mesoscale-Detective/1.0"})
with urllib.request.urlopen(request, timeout=120) as response:
    archive_bytes = response.read()

source = zipfile.ZipFile(io.BytesIO(archive_bytes))
matches = [name for name in source.namelist() if name.startswith("SHARPpy-1.4.0/sharppy/")]
if not matches:
    raise RuntimeError("Pinned SHARPpy source archive did not contain SHARPpy-1.4.0/sharppy/")

with zipfile.ZipFile(OUT, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as target:
    for name in matches:
        if name.endswith("/"):
            target.writestr(name, b"")
        else:
            target.writestr(name, source.read(name))
    license_name = next((name for name in source.namelist() if name.endswith("/LICENSE.rst")), None)
    if license_name:
        target.writestr("SHARPpy-1.4.0/LICENSE.rst", source.read(license_name))

print(f"Created {OUT} ({OUT.stat().st_size:,} bytes) from {len(matches)} package entries")
