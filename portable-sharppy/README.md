# BTV NSHARP Portable for Windows

This package is a portable folder distribution of upstream SHARPpy 1.4.0 with a bundled relocatable Python/Qt runtime. It does not require Python, Conda, SHARPpy, or an installer to be installed on the target workstation.

## Run

1. Download the latest `BTV-NSHARP-Windows-Portable.zip` from the GitHub Actions artifact or Releases page.
2. Extract the **entire ZIP** to a folder where applications are permitted.
3. Double-click `START_SHARPpy.bat`.
4. In SHARPpy, open Data Sources and select BTV CWA RRFS (Latest), GFS (Latest), RAP (Latest), or HRRR (Latest).

Do not move `launcher.py` or `runtime` out of the extracted folder. The launcher copies the bundled BTV data-source configuration into the user's SHARPpy configuration directory.

## Package contents

- `runtime/`: relocatable Conda-pack Python runtime and scientific/Qt dependencies
- `launcher.py`: BTV startup customization
- `START_SHARPpy.bat`: simple Windows launcher
- `native-sharppy/`: BTV model and observed sounding datasource configuration

## Build and verification

GitHub Actions validates the datasource files, runs SHARPpy imports, smoke-tests the launcher, packs the environment using Conda-pack, extracts it into the portable package, runs the relocation helper, and smoke-tests the relocated runtime. It produces a SHA-256 checksum and a package manifest alongside the ZIP.

## Security and operational notes

This distribution intentionally avoids the single-file PyInstaller executable. That can reduce false-positive reputation issues but **does not guarantee** Chrome, Windows Defender, or NWS endpoint security will allow it. Do not bypass agency security controls; if blocked, request review through the appropriate IT process.

This is an alpha, unofficial distribution and is not an officially supported NWS software package.
