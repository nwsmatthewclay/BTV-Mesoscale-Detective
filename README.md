# BTV Mesoscale Detective

Interactive, map-first mesoscale analysis workspace for the NWS Burlington forecast area (Vermont and northern New York).

## Live workspace

[Open BTV Mesoscale Detective](https://nwsmatthewclay.github.io/BTV-Mesoscale-Detective/)

GitHub Pages is deployed after successful model ingestion and interface changes.

## Verified data status

**RAP full-column archive — verified and published**
- The RAP workflow downloads and decodes the 13-km CONUS hybrid-level GRIB2 family, crops it to the BTV analysis domain, and validates the resulting fields.
- The published forecast archive contains F00, F03, F06 and F09 from one RAP cycle. The live [RAP forecast manifest](mesoscale/data/fields/forecast/forecast_manifest.json) is the source of truth for the cycle, valid times and grid/profile paths.
- Each forecast hour includes a regional grid and profiles for KBTV, KPBG, KMSS, KSLK, KMPV, KRUT, 1V4 and KEFK. The latest verified profiles contain 50 vertical levels and pass pressure/height monotonicity checks.
- A separate latest RAP grid and KBTV profile are also published.

**HRRR surface archive — verified and published**
- HRRR 2-D surface subsets are downloaded from NOMADS, decoded and checked against the BTV domain before publication.
- The published [HRRR surface manifest](mesoscale/data/fields/hrrr/hrrr_forecast_manifest.json) currently contains F00, F03, F06 and F09 from one 15Z cycle.
- Each hour contains seven BTV-intersecting grids and 20 decoded fields. Required checks pass for 2-m temperature and 10-m u/v wind; the latest archive has no validation warnings.
- The subset also contains available surface/column fields such as CAPE, CIN, dewpoint, gust, visibility, reflectivity and precipitation fields. HRRR is surface-only here: it does **not** provide the full-column sounding/profile support supplied by RAP.

**RRFS — discovery only**
- Model discovery identifies RAP, HRRR and RRFS products and records their cycle/forecast-hour metadata.
- RRFS regional decoding and publication are not enabled yet.

The dashboard's RAP forecast-hour control reads the verified RAP manifest. HRRR data are published, but HRRR is not yet enabled in the interactive model selector; the current soundings, hodographs and cross-sections remain RAP-only. Do not interpret model discovery as proof of decoded data.

## Interface controls

- Select KBTV, KPBG, KMSS, KSLK, KMPV, KRUT, 1V4 or KEFK, or click a map point.
- Draw and clear a two-point RAP transect.
- Change model, cycle, available forecast hour and map parameter where the selected model is enabled.
- Explore Environment, Soundings, Kinematics & Forcing, Cross-Sections, Model Compare and Time Evolution.
- Plot verified RAP station diagnostics across the published forecast hours in Time Evolution; custom points are not assigned nearby-station values.
- The model manifest reader distinguishes discovered products from decoded and published fields.

## Data safety

This remains a development and research workspace, not an operationally approved decision-support system. Do not use it as the sole basis for warning, forecast or aviation decisions.

- Never display fabricated meteorological values.
- Keep observations distinct from model output.
- Carry source, initialization time, valid time, units and provenance with every diagnostic.
- Do not compare models unless fields have compatible definitions, units and valid times.
- Keep this project independent of the operational NWS_SA_Dashboard until separately validated.

## Local setup

Run the static interface locally with: python -m http.server 8000, then open http://localhost:8000.

Python pipeline setup:

~~~bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r mesoscale/requirements.txt
pytest -q mesoscale/tests
pytest -q mesoscale/hrrr_tests
~~~

See [mesoscale/README.md](mesoscale/README.md) for pipeline details.

## Structure

- index.html: GitHub Pages entry point.
- mesoscale.html: synchronized source copy of the interface.
- mesoscale/: model discovery, GRIB acquisition/processing, diagnostics, tests and configuration.
- .github/workflows/: model discovery, RAP ingestion/archive, HRRR surface ingestion/archive and Pages deployment.

## Development principles

- Never fabricate meteorological values.
- Preserve source model, cycle, forecast hour, valid time, units and quality metadata.
- Validate every field and vertical profile before publishing.
- Keep this project separate from the operational SA Dashboard until it has completed its own validation.
