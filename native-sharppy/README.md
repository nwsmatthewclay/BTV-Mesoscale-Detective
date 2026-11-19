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

## Archive adapter deployment (one-time)

The native data sources now point to a small Cloudflare Worker that serves the exact archived BUFKIT cycle requested by SHARPpy. The Worker reads the repository's catalog, retrieves the matching `.buf.gz` object, decompresses it, and returns plain BUFKIT text. A missing cycle or station returns HTTP 404; it never substitutes a newer run.

The Worker is designed for Cloudflare's free Workers tier. To deploy it:

1. Install Node.js and run `npx wrangler login` in a terminal.
2. From this folder, run:

```bash
cd worker
npx wrangler deploy
```

3. Copy the hostname from the deployment output (for example `btv-sharppy-bufkit.YOUR-SUBDOMAIN.workers.dev`).
4. Run the workstation installer. It asks for that hostname and writes the correct URL into `~/.sharppy/datasources/btv_cwa.xml`.

The Worker source is in [worker/src/index.js](worker/src/index.js). Its configuration is in [worker/wrangler.toml](worker/wrangler.toml). The repository also includes an optional GitHub Actions deployment workflow. Add a Cloudflare API token as the repository Actions secret `CLOUDFLARE_API_TOKEN`, then run **Deploy Native SHARPpy BUFKIT Worker** from the Actions tab. This avoids needing Wrangler installed locally. The deployment still needs your Cloudflare authorization.

## Alpha scope

The alpha is intended to cover the four archived model feeds and the 25-station inventory. The live repository catalog controls which cycle/station combinations are actually available. Sounding-picker availability is constrained by each model's configured archive retention and forecast range.

`BTV CWA RRFS`, `GFS`, `RAP`, and `HRRR` use the native SHARPpy BUFKIT decoder. This is not a fork of SHARPpy and does not replace its native plotting or diagnostic tools.
## Data source configuration

SHARPpy's own documentation specifies a separate XML file plus station CSV under `~/.sharppy/datasources`. The installer writes these files without modifying SHARPpy's `standard.xml`, and substitutes the Worker hostname you provide.

Official documentation:
- https://sharppy.github.io/SHARPpy/install.html
- https://sharppy.github.io/SHARPpy/datasource_guide.html
- https://sharppy.github.io/SHARPpy/picker.html
