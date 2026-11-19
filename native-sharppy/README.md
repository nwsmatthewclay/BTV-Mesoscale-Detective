# Native SHARPpy — BTV CWA setup

This folder installs the **official SHARPpy desktop application** and adds BTV CWA model feeds through SHARPpy's supported custom-data-source mechanism. It does not use the browser Skew-T interface.

## Install (Windows)

1. Install Miniforge or Miniconda (if not already installed).
2. Extract this folder or clone the repository.
3. Open PowerShell in this folder.
4. Run:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\install-windows.ps1
```

Launch SHARPpy:

```powershell
conda run -n sharppy-btv sharppy
```

## Install (macOS/Linux)

Install Miniforge/Miniconda, then run `bash install-unix.sh` from this folder. Launch with:

```bash
conda run -n sharppy-btv sharppy
```

## What is configured

The SHARPpy Data Sources menu receives four BTV-specific entries:
- BTV CWA RRFS
- BTV CWA GFS
- BTV CWA RAP
- BTV CWA HRRR

Each source uses SHARPpy's native BUFKIT decoder and native sounding picker, Skew-T, hodograph, and diagnostic windows. The CSV currently includes 25 nearby stations with coordinates drawn from SHARPpy's published RAP station inventory and the project's BTV station inventory.

## Important limitation in this first integration pass

The PSU BUFKIT endpoint used here exposes a `latest` file path. SHARPpy's standard data-source calendar models cycle availability using a URL/time schedule, so this first pass is intended to verify native installation, station selection, file retrieval, and native plotting—not to claim that the BTV local multi-cycle archive is already browsable inside SHARPpy. The next integration step is a small free HTTPS BUFKIT archive adapter that maps SHARPpy's cycle/station URL template to the versioned BTV archive and returns uncompressed BUFKIT text.

The local archive currently retains multiple cycles and compressed files. The adapter must preserve exact model cycle and valid-time provenance and return 404 for missing combinations; it must never silently substitute the latest cycle.

## Data source configuration

SHARPpy's own documentation specifies a separate XML file plus station CSV under `~/.sharppy/datasources`. This installer copies those files without modifying SHARPpy's `standard.xml`.

Official documentation:
- https://sharppy.github.io/SHARPpy/install.html
- https://sharppy.github.io/SHARPpy/datasource_guide.html
- https://sharppy.github.io/SHARPpy/picker.html
