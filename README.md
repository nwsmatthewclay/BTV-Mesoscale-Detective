# BTV Mesoscale Detective

Interactive, map-first mesoscale analysis workspace for the NWS Burlington forecast area (Vermont and northern New York).

## Live workspace

[Open BTV Mesoscale Detective](https://nwsmatthewclay.github.io/BTV-Mesoscale-Detective/)

GitHub Pages is deployed after successful model ingestion and interface changes.

## Verified data status

**RAP full-column archive — verified and published**
- The RAP workflow downloads and decodes the 13-km CONUS hybrid-level GRIB2 family, crops it to the BTV analysis domain, and validates the resulting fields.
- The published forecast archive contains F00, F03, F06, F09, F12 and F15 from one RAP cycle. The live [RAP forecast manifest](mesoscale/data/fields/forecast/forecast_manifest.json) is the source of truth for the current cycle, valid times and grid/profile paths.
- Each forecast hour includes a regional grid and profiles for KBTV, KPBG, KMSS, KSLK, KMPV, KRUT, 1V4 and KEFK. All 48 profiles in the current six-hour archive contain 50 vertical levels, pass pressure/height monotonicity checks and have zero profile warnings.
- A separate latest RAP grid and KBTV profile are also published.

**HRRR surface archive — verified and published**
- HRRR 2-D surface subsets are downloaded from NOMADS, decoded and checked against the BTV domain before publication.
- The published [HRRR surface manifest](mesoscale/data/fields/hrrr/hrrr_forecast_manifest.json) contains six forecast points aligned to the RAP archive's six valid times. The manifest records the HRRR cycle and each selected HRRR forecast hour; do not assume matching forecast-hour numbers when cycles differ.
- Each hour contains seven BTV-intersecting grids and 20 decoded fields. Required checks pass for 2-m temperature and 10-m u/v wind; the latest archive has no validation warnings.
- The interactive map currently exposes 2-m temperature, 2-m dewpoint, 10-m wind speed, gust, composite reflectivity, visibility, CIN and boundary-layer height. CAPE and precipitation overlays are intentionally withheld until duplicate CAPE messages and precipitation accumulation metadata can be distinguished safely. HRRR is surface-only here: it does **not** provide the full-column sounding/profile support supplied by RAP.

**Automated refresh and valid-time alignment**
- The RAP workflow is configured as the hourly ingestion orchestrator (minute 47 UTC). Scheduled and manual runs refresh the RAP/HRRR/RRFS discovery manifest with retry-safe publication before checking whether a newer complete RAP cycle should be decoded.
- The separate model-discovery workflow remains available for code-change validation and manual discovery. A direct schedule-triggered RAP run succeeded (run [43339280233](https://github.com/nwsmatthewclay/BTV-Mesoscale-Detective/actions/runs/43339280233)); only two schedule-triggered runs are visible in the inspected history, so repeated hourly cadence is not yet established.
- HRRR ingestion follows successful RAP ingestion and selects one HRRR cycle that covers the RAP archive's valid times. It refuses to mix HRRR cycles or publish an incomplete alignment.

**RRFS — indexed acquisition smoke-tested; no published field archive**
- Model discovery identifies RAP, HRRR and RRFS products and records cycle, forecast-step and index metadata. RRFS subhourly F001 is represented as a 15-minute lead, not one forecast hour.
- A live read-only smoke run ([43351175252](https://github.com/nwsmatthewclay/BTV-Mesoscale-Detective/actions/runs/43351175252)) retrieved and ecCodes-decoded four bounded messages from the 00Z 3-km subhourly F001 product: 2-m temperature/dewpoint and 10-m U/V wind. It verified HTTP 206/Content-Range, complete GRIB boundaries, matching 00Z reference time and 1,905,141 finite values in each field; 7,174,900 bytes were transferred.
- The decoded Lambert grid is 1,799 × 1,059. Its coordinate mask found 12,006 grid points inside the padded BTV rectangle (-75.2 to -71.2 longitude, 42.3 to 45.3 latitude). The report explicitly records `publication: false`: this is geographic coverage validation, not a cropped BTV grid, multi-hour archive, or published RRFS field layer. The RRFS map option remains disabled.

The main map viewer enables HRRR only for its verified surface archive. Its archived soundings, hodographs, cross-sections and station Time Evolution remain RAP-only because that HRRR grid archive contains no vertical profiles. The separate Forecast Sounding Workbench can retrieve full-column BUFKIT soundings for HRRR and other models from the upstream BUFKIT feed; this is a distinct data path and is labeled with its own model cycle and source provenance. Do not interpret model discovery as proof of decoded data.

## Interface controls

- Select KBTV, KPBG, KMSS, KSLK, KMPV, KRUT, 1V4 or KEFK, or click a map point.
- Draw and clear a two-point RAP transect.
- Change model, cycle, available forecast hour and map parameter where the selected model is enabled.
- Explore Environment, Soundings, Kinematics & Forcing, Cross-Sections, Model Compare and Time Evolution.
- Plot verified RAP station diagnostics across the published forecast hours in Time Evolution; custom points are not assigned nearby-station values.
- The model manifest reader distinguishes discovered products from decoded and published fields.

## Native SHARPpy desktop application

**Forecaster-facing native SHARPpy setup:** see [native-sharppy/README.md](native-sharppy/README.md). This installs the official SHARPpy desktop GUI in an isolated Conda environment and adds BTV CWA RRFS, GFS, RAP and HRRR BUFKIT data-source entries through SHARPpy's XML/CSV configuration mechanism. It does not replace SHARPpy's interface with a browser implementation.

The native configuration now targets a cycle-aware Cloudflare Worker adapter for the versioned BTV BUFKIT archive. The Worker source and deployment instructions are in `native-sharppy/worker/` and `native-sharppy/README.md`. Deployment into the user's Cloudflare account and workstation validation remain alpha gates. The browser workbench remains separate.

## Forecast Sounding Workbench

[Open the Forecast Sounding Workbench](https://nwsmatthewclay.github.io/BTV-Mesoscale-Detective/sounding.html)

A standalone interactive Skew-T and hodograph workbench is being built around SHARPpy 1.4.0 `ConvectiveProfile`.

- Select BTV CWA locations, model, BUFKIT forecast hour and model cycle.
- Live BUFKIT acquisition is on demand from the Penn State BUFKIT Data Distribution System; the Python API uses SHARPpy's native `BufDecoder`, caches files briefly and decodes all forecast profiles in the selected station file.
- Initial model feed options: RAP, HRRR, GFS, NAM, NAM Nest, RRFS and HIRESW. Upstream availability and freshness vary by model/station; old cycles are explicitly flagged. SREF remains deferred until ensemble-member selection is supported.
- Modify low-level temperature/dewpoint, adjustment depth and boundary-layer mixing depth. The mixing experiment conservatively averages potential temperature, water-vapor mixing ratio and horizontal momentum with pressure-layer mass weights, so the wind profile and hodograph respond to mixing-depth changes.
- Original model profiles are immutable. Adjusted profiles are labeled experimental and recalculated through SHARPpy; no browser-side substitute diagnostics are used.
- Full ConvectiveProfile output includes parcel, effective inflow, kinematic, thermodynamic, severe, winter/precipitation, fire-weather, SARS and trajectory diagnostics. Optional BUFKIT omega is carried into SHARPpy's winter calculations.
- The API can run locally or in the included Cloudflare Container scaffold. Production deployment requires the Workers Paid plan and an authenticated Cloudflare account; protect the API with Access and/or rate limiting before broader use.

The static RAP archive remains available as a no-API fallback. The full ConvectiveProfile refresh and all modified-sounding calculations require the SHARPpy API service to be reachable.

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
