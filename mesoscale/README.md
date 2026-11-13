# BTV Mesoscale Detective

Standalone interactive mesoscale analysis dashboard for the NWS Burlington forecast area.

## Current verified status

- RAP ingestion is configured with an hourly minute-47 UTC schedule plus model-discovery and manual triggers. A direct schedule-triggered RAP run succeeded (run [43339280233](https://github.com/nwsmatthewclay/BTV-Mesoscale-Detective/actions/runs/43339280233)); only two schedule-triggered runs are visible in the inspected history, so repeated hourly cadence remains unverified.
- The published RAP forecast archive contains six forecast points (F00, F03, F06, F09, F12 and F15) from one model cycle. Read `data/fields/forecast/forecast_manifest.json` for the actual current cycle and valid times.
- The published HRRR surface archive contains six valid times aligned to the RAP archive. Read `data/fields/hrrr/hrrr_forecast_manifest.json` for its cycle, selected forecast hours and field inventory.
- Each forecast hour includes regional gridded fields and profiles for KBTV, KPBG, KMSS, KSLK, KMPV, KRUT, 1V4 and KEFK. The latest verified profiles contain 50 levels and pass pressure/height monotonicity checks.
- The standalone latest RAP grid and KBTV profile are also published.
- RAP is the full-column source. HRRR now has a separately validated/published surface archive and is enabled in the interactive model selector for supported 2-D surface map fields. RRFS has a live indexed-range acquisition smoke test but no regional field archive or enabled map layer.
- `index.html` and `mesoscale.html` are kept byte-for-byte synchronized.
- The Time Evolution panel plots station-profile diagnostics from each verified RAP archive hour and checks cycle/hour metadata before use; custom points are not assigned nearby-station values.

This is a development/research workspace, not an operationally approved decision-support system. Do not use it as the sole basis for forecast, warning or aviation decisions.

## Architecture

1. **Acquisition:** discover RAP, HRRR and RRFS production products. The RAP ingestion workflow refreshes discovery before downloading verified hybrid-level source files; the HRRR workflow builds a six-point surface archive whose valid times align with the published RAP archive and publishes it only after validation.
2. **Subsetting:** crop decoded grids to the padded BTV analysis domain before serialization.
3. **Processing:** use xarray/cfgrib, MetPy, NumPy and SciPy for GRIB decoding, unit-aware diagnostics, vertical interpolation and profile quality checks.
4. **Products:** publish compact gzip JSON grids and station profiles with model, cycle, forecast hour, valid time, units, grid geometry and quality metadata.
5. **Frontend:** Leaflet handles map selection and overlays; Plotly renders profiles, hodographs, cross-sections and time series. The forecast-hour control is populated from the verified archive manifest.

## Model roles

- **RAP is the full-column workhorse.** The current 13-km hybrid-level workflow supplies station soundings, hodographs, vertical profiles and cross-section inputs. Its verified archive currently contains F00/F03/F06/F09/F12/F15.
- **HRRR is the high-resolution surface companion.** The live NOMADS subset workflow now downloads and decodes F00/F03/F06/F09/F12/F15 from one cycle, validates BTV coverage and required 2-m temperature/10-m wind fields, and publishes the resulting surface grids. It does not supply full-column sounding profiles.
- **RRFS is the 3-km high-resolution model.** Discovery includes pressure-level, 2-D surface and sub-hourly product families. Regional extraction remains gated on validating index offsets, partial-HTTP byte-range behavior and actual message inventories; the RRFS UI option remains disabled.
- **Comparisons must be field-aware.** Compare only fields available in both models with compatible definitions, units and valid times. Label native grid spacing and interpolation method.

## Initial BTV domain

Use a padded rectangle around Vermont and northern New York, approximately:
- west: -75.2
- east: -71.2
- south: 42.3
- north: 45.3

The map is for analysis and display; the actual CWA boundary should be supplied as a GeoJSON overlay rather than inferred from this rectangle.

## Data contract

Every generated field must include:
- `model`, `model_cycle_utc`, `forecast_hour`, `valid_time_utc`
- `field`, `level`, `units`, `description`
- `grid` (projection, dimensions, coordinates or transform)
- `source_file`, `created_utc`, `quality`

Never silently mix analysis time and forecast valid time. Never label model-derived fields as observations. Surface observations remain a separate layer with station ID, observation timestamp and age.

## Development sequence

1. Maintain RAP cycle freshness, multi-hour archive completeness and station/grid quality checks.
2. Perform browser-level validation of HRRR map parameter/hour switching, data freshness and stale-layer clearing; keep soundings and cross-sections RAP-only.
3. Validate RAP/HRRR common-valid-time comparisons for fields with compatible definitions and units.
4. Preserve GRIB level/step metadata so additional HRRR CAPE and precipitation fields can be exposed without ambiguity.
5. Extend RRFS acquisition from indexed-message smoke testing to BTV geographic coverage and validated regional extraction before publication.
6. Add stale-data checks, automated tests and clear model-by-model status reporting.

## Running locally

Open `mesoscale.html` through a local static web server. The interface uses public Leaflet/Plotly CDNs and OpenStreetMap tiles. Published RAP data are loaded from `mesoscale/data/fields/forecast/` and HRRR surface grids from `mesoscale/data/fields/hrrr/`. HRRR map parameters currently include 2-m temperature/dewpoint, 10-m wind speed, gust, composite reflectivity, visibility, CIN and boundary-layer height. Soundings, hodographs, cross-sections and Time Evolution remain RAP-only; RRFS remains discovery-only.

## Implemented ingestion components

- `discover_models.py` checks current/recent NOMADS production directories and records RAP, HRRR and RRFS cycle/forecast products with index inventories.
- `validate_rap_ingestion.py` downloads and decodes a current RAP 13-km hybrid-level file, verifies BTV grid coverage, and creates the latest regional grid plus eight station profiles.
- `validate_hrrr_ingestion.py` validates a live HRRR 2-D surface subset, while `validate_hrrr_archive.py` selects one complete HRRR cycle and verifies F00/F03/F06/F09/F12/F15 before publication.
- `build_rap_forecast_archive.py` downloads a single RAP cycle at F00/F03/F06/F09/F12/F15, validates all requested hours and station profiles, and writes the forecast manifest.
- `download_subset.py` builds bounded NOMADS filter requests from exact manifest filenames. The HRRR 2-D surface path is live-validated and published for six forecast hours. The UI intentionally withholds CAPE because two distinct CAPE messages are present, and withholds precipitation fields until the GRIB accumulation/step-range metadata are retained.
- `process_grib.py` decodes GRIB2 with cfgrib, crops 2-D and multi-level grids to the BTV analysis domain, and writes gzip-compressed JSON with grid geometry, units, level coordinates and valid-time metadata.
- `extract_profile.py` samples full-column profiles at stations or selected map points and writes strict JSON.
- `diagnostics.py` provides unit-aware MetPy profile calculations for SBCAPE/CIN, MLCAPE/CIN, MUCAPE/CIN, LCL, PWAT, 0-3 km lapse rate, 0-6 km bulk shear and 0-1 km SRH.
- `tests/` covers model discovery, profile validation, archive cycle selection and subset URL construction.

### Initial model products

The scheduled RAP workflow uses the 13-km CONUS hybrid-level GRIB2 family for full-column profiles. The optional subset utility targets the RAP 13-km pressure-level family and HRRR hourly 2-D surface family. HRRR 2-D surface data are now validated and published for F00/F03/F06/F09/F12/F15 from one cycle. They provide near-surface/column diagnostics but are not a substitute for a complete 3-D upper-air sounding. RAP remains the only source for full-column profiles, hodographs and cross-section inputs.

### Developer commands

```bash
python mesoscale/discover_models.py --days-back 2 --index-latest
pytest -q mesoscale/tests/test_model_discovery.py
python mesoscale/download_subset.py --model RAP --forecast-hour 0
python mesoscale/download_subset.py --model HRRR --forecast-hour 0
python mesoscale/process_grib.py mesoscale/data/grib/rap_YYYYMMDD_HH_f00_btv.grib2 --model RAP --cycle 2026-11-12T12:00:00Z --forecast-hour 0 --output mesoscale/data/fields/rap_f00.json.gz
pytest mesoscale/tests
```

The exact discovered filenames and initialization time must be used when running the processing commands. The example cycle and filename above are placeholders, not a claim that a specific model run is available. Run pytest -q mesoscale/hrrr_tests to test the HRRR same-cycle archive selector and surface validator.


## RRFS support (new)

The model discovery service now includes the operational RRFS deterministic CONUS 3-km products. It discovers the pressure-level, 2-D surface, and sub-hourly 2-D file families from the NCEP production directory structure and records their .idx inventories.

- Pressure levels: rrfs.tCCz.prslev.3km.fFFF.conus.grib2
- 2-D fields: rrfs.tCCz.2dfld.3km.fFFF.conus.grib2
- Sub-hourly 2-D fields: rrfs.tCCz.2dfld.3km.subh.fFFF.conus.grib2

The RRFS option remains disabled in mesoscale.html. Discovery is wired into the manifest workflow, and regression tests cover all three RRFS filename families and the two-digit cycle-directory convention. A prior scheduled discovery run succeeded, but the RAP-owned minute-47 UTC schedule has not yet produced a post-change scheduled run in the inspected history; hourly unattended refresh remains unverified. Push and workflow-run triggers are verified. A previous over-escaped regular expression was corrected. RRFS regional archive publication remains disabled. The read-only range smoke test has confirmed NOMADS HTTP 206 responses, exact Content-Range offsets, complete GRIB message boundaries, matching GRIB reference time, and ecCodes decoding. In successful run [43350740331](https://github.com/nwsmatthewclay/BTV-Mesoscale-Detective/actions/runs/43350740331), the 00Z F001 product supplied TMP, DPT, UGRD and VGRD messages; each decoded to 1,905,141 finite values. The Lambert grid is 1,799 × 1,059, and 12,006 grid points fall inside the padded BTV rectangle. The test is still read-only: it does not write a cropped grid or publish meteorological fields. The 3-km RRFS pressure-level file remains the intended future source for column diagnostics; 2-D products supply near-term fields such as composite reflectivity, CAPE/CIN, gusts, visibility and precipitation diagnostics. Sub-hourly `2dfld.3km.subh` files use 15-minute forecast steps: F001 represents 15 minutes and F003 represents 45 minutes. Discovery records these as `forecast_step`, `forecast_lead_minutes` and `forecast_interval_minutes`, not integer `forecast_hour` values.

NOMADS currently lists RRFS under HTTPS distribution without a GRIB-filter entry. Indexed HTTP range acquisition and BTV geographic coverage are now verified for a small set of messages; extracting the actual regional grid window, multi-hour consistency and a complete field inventory remain to be tested before automated RRFS publication. The RRFS/REFS transition and current product naming are documented in the NWS implementation notice and NCEP RRFS product inventory.
