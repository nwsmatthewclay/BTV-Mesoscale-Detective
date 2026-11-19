# BTV Native NSHARP Workstation (Alpha)

This installs the **official SHARPpy desktop application** in a native Windows Python environment. It is not the Pyodide/browser viewer and does not wrap the web page in Electron.

## Quick start — Windows

1. Install [Miniforge](https://github.com/conda-forge/miniforge) or Miniconda.
2. Download or clone this repository.
3. Open PowerShell in `native-sharppy`.
4. Run:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\install-windows.ps1
```

The installer creates (or reuses) a `sharppy-btv` Conda environment with Python 3.10, NumPy <2, SHARPpy 1.4.0, and PySide2. It installs four BTV CWA data sources in `%USERPROFILE%\.sharppy\datasources`.

Launch with:

```powershell
conda run -n sharppy-btv sharppy
```

The installer also creates a launcher at `%APPDATA%\BTV-NSHARP\Launch-BTV-NSHARP.cmd`.

## BTV model feeds

The native SHARPpy Data Sources menu includes:
- BTV CWA RRFS (Latest)
- BTV CWA GFS (Latest)
- BTV CWA RAP (Latest)
- BTV CWA HRRR (Latest)

These use Penn State's latest-cycle BUFKIT endpoints directly. This initial workstation build deliberately avoids a Cloudflare Worker dependency, API token, and browser Python runtime. The native SHARPpy sounding picker and BufDecoder handle BUFKIT retrieval and decoding.

**Data availability:** these entries follow the provider's latest cycle, not the project's full historical archive. Availability, station coverage, and forecast hours depend on the provider's current BUFKIT publication. The archived-cycle Worker integration remains available as a later enhancement.

## What this alpha provides

- Native CPython and official SHARPpy 1.4.0.
- SHARPpy's own Qt desktop interface, sounding picker, Skew-T, hodograph, and diagnostic panels.
- Direct BTV CWA model feeds and the station inventory in `btv_cwa.csv`.
- No Pyodide, no browser main-thread calculations, and no remote desktop session.

## Next development steps

1. Verify each live feed and station coverage on a forecaster workstation.
2. Benchmark initial BUFKIT load and forecast-hour switching.
3. Add local BUFKIT/decoded-profile caching if native picker performance warrants it.
4. Evaluate the expanded BTV diagnostic panels against the native SHARPpy profile objects.
5. Package a signed Windows installer once dependencies and workstation deployment requirements are confirmed.

This is an alpha setup for evaluation, not an officially supported NWS workstation package.
