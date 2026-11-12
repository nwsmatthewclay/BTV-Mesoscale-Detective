# BTV Mesoscale Detective

Standalone interactive mesoscale analysis dashboard for the NWS Burlington forecast area.

## Current verified status

- RAP ingestion is running automatically: 13-km CONUS hybrid-level GRIB2 files are decoded and cropped to the BTV domain.
- The published RAP forecast archive currently exposes F00, F03, F06 and F09 from a single model cycle. Read `data/fields/forecast/forecast_manifest.json` for the actual current cycle and valid times.
- Each forecast hour includes regional gridded fields and profiles for KBTV, KPBG, KMSS, KSLK, KMPV, KRUT, 1V4 and KEFK. The latest verified profiles contain 50 levels and pass pressure/height monotonicity checks.
- The standalone latest RAP grid and KBTV profile are also published.
- RAP is the full-column source. HRRR now has a separately validated/published surface archive and is enabled in the interactive model selector for supported 2-D surface map fields. RRFS remains discovery-only.
- `index.html` and `mesoscale.html` are kept byte-for-byte synchronized.
- The Time Evolution panel plots station-profile diagnostics from each verified RAP archive hour and checks cycle/hour metadata before use; custom points are not assigned nearby-station values.

This is a development/research workspace, not an operationally approved decision-support system. Do not use it as the sole basis for forecast, warning or aviation decisions.

## Architecture

1. **Acquisition:** discover RAP, HRRR and RRFS production products. The RAP ingestion workflow refreshes discovery before downloading verified hybrid-level source files; the HRRR workflow builds a same-cycle F00/F03/F06/F09 surface archive and publishes it only after validation.
2. **Subsetting:** crop decoded grids to the padded BTV analysis domain before serialization.
3. **Processing:** use xarray/cfgrib, MetPy, NumPy and SciPy for GRIB decoding, unit-aware diagnostics, vertical interpolation and profile quality checks.
4. **Products:** publish compact gzip JSON grids and station profiles with model, cycle, forecast hour, valid time, units, grid geometry and quality metadata.
5. **Frontend:** Leaflet handles map selection and overlays; Plotly renders profiles, hodographs, cross-sections and time series. The forecast-hour control is populated from the verified archive manifest.

## Model roles

- **RAP is the full-column workhorse.** The current 13-km hybrid-level workflow supplies station soundings, hodographs, vertical profiles and cross-section inputs. Its verified archive currently contains F00/F03/F06/F09.
- **HRRR is the high-resolution surface companion.** The live NOMADS subset workflow now downloads and decodes F00/F03/F06/F09 from one cycle, validates BTV coverage and required 2-m temperature/10-m wind fields, and publishes the resulting surface grids. It does not supply full-column sounding profiles.
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
5. Add RRFS regional acquisition only after its product inventory and byte-range behavior are verified.
6. Add stale-data checks, automated tests and clear model-by-model status reporting.

## Running locally

Open `mesoscale.html` through a local static web server. The interface uses public Leaflet/Plotly CDNs and OpenStreetMap tiles. Published RAP data are loaded from `mesoscale/data/fields/forecast/` and HRRR surface grids from `mesoscale/data/fields/hrrr/`. HRRR map parameters currently include 2-m temperature/dewpoint, 10-m wind speed, gust, composite reflectivity, visibility, CIN and boundary-layer height. Soundings, hodographs, cross-sections and Time Evolution remain RAP-only; RRFS remains discovery-only.

## Implemented ingestion components

- `discover_models.py` checks current/recent NOMADS production directories and records RAP, HRRR and RRFS cycle/forecast products with index inventories.
- `validate_rap_ingestion.py` downloads and decodes a current RAP 13-km hybrid-level file, verifies BTV grid coverage, and creates the latest regional grid plus eight station profiles.
- `validate_hrrr_ingestion.py` validates a live HRRR 2-D surface subset, while `validate_hrrr_archive.py` selects one complete HRRR cycle and verifies F00/F03/F06/F09 before publication.
- `build_rap_forecast_archive.py` downloads a single RAP cycle at F00/F03/F06/F09, validates all requested hours and station profiles, and writes the forecast manifest.
- `download_subset.py` builds bounded NOMADS filter requests from exact manifest filenames. The HRRR 2-D surface path is live-validated and published for four forecast hours. The UI intentionally withholds CAPE because two distinct CAPE messages are present, and withholds precipitation fields until the GRIB accumulation/step-range metadata are retained.
- `process_grib.py` decodes GRIB2 with cfgrib, crops 2-D and multi-level grids to the BTV analysis domain, and writes gzip-compressed JSON with grid geometry, units, level coordinates and valid-time metadata.
- `extract_profile.py` samples full-column profiles at stations or selected map points and writes strict JSON.
- `diagnostics.py` provides unit-aware MetPy profile calculations for SBCAPE/CIN, MLCAPE/CIN, MUCAPE/CIN, LCL, PWAT, 0-3 km lapse rate, 0-6 km bulk shear and 0-1 km SRH.
- `tests/` covers model discovery, profile validation, archive cycle selection and subset URL construction.

### Initial model products

The scheduled RAP workflow uses the 13-km CONUS hybrid-level GRIB2 family for full-column profiles. The optional subset utility targets the RAP 13-km pressure-level family and HRRR hourly 2-D surface family. HRRR 2-D surface data are now validated and published for F00/F03/F06/F09 from one cycle. They provide near-surface/column diagnostics but are not a substitute for a complete 3-D upper-air sounding. RAP remains the only source for full-column profiles, hodographs and cross-section inputs.

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

The RRFS option remains disabled in mesoscale.html. Discovery is wired into the manifest workflow, and regression tests cover all three RRFS filename families and the two-digit cycle-directory convention. Cron definitions are present, but no schedule-triggered Actions runs have appeared in the recent run history; push and workflow-run triggers are verified. A previous over-escaped regular expression was corrected. RRFS regional download/decoding is intentionally not enabled yet: its operational product families and NOMADS subsetting method need to be validated against current inventories before an automated downloader is allowed to fetch large CONUS files. The 3-km RRFS pressure-level file is the intended source for column diagnostics; the 2-D file supplies near-term fields such as composite reflectivity, CAPE/CIN, gusts, visibility and precipitation diagnostics.

NOMADS currently lists RRFS under HTTPS distribution without a GRIB-filter entry. NOMADS documentation recommends partial-HTTP transfers for selecting fields; the specific range-request behavior and byte-offset handling must be tested before implementing automated extraction. The RRFS/REFS transition and current product naming are documented in the NWS implementation notice and NCEP RRFS product inventory.
