# BTV Mesoscale Detective

Standalone interactive mesoscale analysis dashboard for the NWS Burlington forecast area.

## Current verified status

- RAP ingestion is configured with an hourly minute-47 UTC schedule plus model-discovery and manual triggers. A direct schedule-triggered RAP run succeeded (run [43339280233](https://github.com/nwsmatthewclay/BTV-Mesoscale-Detective/actions/runs/43339280233)); only two schedule-triggered runs are visible in the inspected history, so repeated hourly cadence remains unverified.
- The published RAP forecast archive contains six forecast points (F00, F03, F06, F09, F12 and F15) from one model cycle. Grid payloads carry their geographic crop bounds; archive freshness checks rebuild grids when the domain definition changes. Read `data/fields/forecast/forecast_manifest.json` for the actual current cycle and valid times.
- The published HRRR surface archive contains six valid times aligned to the RAP archive. HRRR archive freshness checks also verify the geographic crop bounds before reusing an existing grid. Read `data/fields/hrrr/hrrr_forecast_manifest.json` for its cycle, selected forecast hours and field inventory.
- Each forecast hour includes regional gridded fields and profiles for KBTV, KPBG, KMSS, KSLK, KMPV, KRUT, 1V4 and KEFK. The latest verified profiles contain 50 levels and pass pressure/height monotonicity checks.
- The standalone latest RAP grid and KBTV profile are also published.
- RAP is the full-column source. The committed F00 archive inventory confirms 50-level hybrid fields for pressure, temperature, geopotential height, specific humidity, U/V wind, and vertical velocity (`w`, Pa s**-1). Cloud water, rain, snow, and graupel mixing ratios are also present on hybrid levels. HRRR has a separately validated/published surface archive and is enabled in the interactive model selector for supported 2-D surface map fields. RRFS has a live indexed-range acquisition smoke test but no regional field archive or enabled map layer.
- `index.html` and `mesoscale.html` are kept byte-for-byte synchronized.
- The standalone hybrid-level cross-section engine samples a great-circle transect on distinct native grid cells, interpolates to a common log-pressure coordinate, disables vertical extrapolation, and preserves model/cycle/valid-time provenance. Its CI test successfully builds a real archived RAP omega (`w`), temperature and height cross-section.
- The GRIB processor now retains dataset-level projection/grid-spacing metadata and variable-level GRIB metadata, including wind orientation flags. A read-only live RAP F00 probe decoded a fresh 2026-11-13 04Z source file, verified Lambert geometry (13,545 m native spacing) and grid-relative U/V, then successfully calculated Petterssen frontogenesis at 850/700/500 hPa: 7 distinct transect samples and 21 finite values in K (100 km)-1 (3 h)-1. The older committed archive still predates those metadata fields; the real-data calculation was validated on a freshly downloaded temporary payload and is not yet exposed as a browser map layer.
- SHARPpy 1.4.0 has passed isolated Conda validation on both a synthetic sounding and the archived KBTV RAP F00 sounding. The latest completed dedicated run passed all 24 tests, including compact NOMADS timestamp parsing; two NumPy masked-value warnings from SHARPpy interpolation remain visible and under review.
- The Time Evolution panel plots station-profile diagnostics from each verified RAP archive hour and checks cycle/hour metadata before use; custom points are not assigned nearby-station values.

This is a development/research workspace, not an operationally approved decision-support system. Do not use it as the sole basis for forecast, warning or aviation decisions.

## Architecture

1. **Acquisition:** discover RAP, HRRR and RRFS production products. The RAP ingestion workflow refreshes discovery before downloading verified hybrid-level source files; the HRRR workflow builds a six-point surface archive whose valid times align with the published RAP archive and publishes it only after validation.
2. **Subsetting:** crop decoded grids to the expanded Great Lakes–Northeast upstream analysis domain before serialization.
3. **Processing:** use xarray/cfgrib, MetPy, NumPy and SciPy for GRIB decoding, unit-aware diagnostics, vertical interpolation and profile quality checks.
4. **Products:** publish compact gzip JSON grids and station profiles with model, cycle, forecast hour, valid time, units, grid geometry and quality metadata.
5. **Frontend:** Leaflet handles map selection and overlays; Plotly renders profiles, hodographs, cross-sections and time series. The model selector currently offers RAP and HRRR according to verified archive availability. The categorized variable selector groups thermodynamics, moisture, kinematics, forcing, surface/boundary-layer, reflectivity, aviation/visibility, winter hydrometeors, land/soil, surface energy and other fields. After a verified model grid loads, the browser inspects its decoded field inventory and adds each unique native 2-D field to the appropriate category. These dynamically added layers use the source units and a per-grid 5th–95th percentile display stretch; they are explicitly labeled as native fields. Model-specific options are filtered so a RAP field cannot appear as an HRRR field. Hybrid/vertical fields are kept separate for the cross-section and profile workstream.

## Model roles

- **RAP is the full-column workhorse.** The current 13-km hybrid-level workflow supplies station soundings, hodographs, vertical profiles and cross-section inputs. Its verified archive currently contains F00/F03/F06/F09/F12/F15.
- **HRRR is the high-resolution surface companion.** The live NOMADS subset workflow now downloads and decodes F00/F03/F06/F09/F12/F15 from one cycle, validates BTV coverage and required 2-m temperature/10-m wind fields, and publishes the resulting surface grids. It does not supply full-column sounding profiles.
- **RRFS is the 3-km high-resolution model.** Discovery includes pressure-level, 2-D surface and sub-hourly product families. A read-only live smoke test has verified indexed 2-m temperature/dewpoint and 10-m U/V wind messages, exact HTTP 206 byte ranges, complete GRIB message boundaries, matching model reference time and 12,006 grid points inside the padded BTV rectangle. This remains a whole-grid decode plus coverage mask: a cropped regional payload, multi-hour archive and full field inventory are not yet published, so the RRFS UI option remains disabled.
- **Comparisons must be field-aware.** Compare only fields available in both models with compatible definitions, units and valid times. Label native grid spacing and interpolation method.

## Initial BTV domain

Use a broad upstream regional rectangle around the Great Lakes, southern Ontario/Quebec, New England and the Mid-Atlantic, approximately:
- west: -84.0
- east: -65.0
- south: 36.5
- north: 51.5

This expanded grid preserves the BTV CWA while adding upstream context from the Great Lakes and Ohio Valley. The published raster remains bounded by the model grid crop; map reset fits this full regional rectangle.

The map is for analysis and display; the actual CWA boundary should be supplied as a GeoJSON overlay rather than inferred from this rectangle.

## Data contract

Every generated field must include:
- `model`, `model_cycle_utc`, `forecast_hour`, `valid_time_utc`
- `field`, `level`, `units`, `description`
- `grid` (projection, dimensions, coordinates or transform)
- `source_file`, `created_utc`, `quality`

Never silently mix analysis time and forecast valid time. Never label model-derived fields as observations. Surface observations remain a separate layer with station ID, observation timestamp and age.

## Interactive Forecast Sounding Workbench

Open the [Browser SHARPpy Lab](../sounding-browser.html) from GitHub Pages. It reads the rolling BUFKIT archive catalog at `data/bufkit/catalog.json`, lets the forecaster select RRFS, GFS, RAP or HRRR, then choose an initialization cycle, station and forecast hour. The archived `.buf.gz` file is downloaded by the browser, decompressed with the Web Streams API, and decoded with SHARPpy's native `BufDecoder` inside Pyodide. No API server, paid container, or local Python installation is required.

- The browser loads pinned SHARPpy 1.4.0 source and the repository's `sharppy_adapter.py`, `bufkit_browser.py` and `browser_adjustments.py` modules into its Python/WebAssembly runtime.
- Every selected BUFKIT forecast time is converted to the shared SI profile contract and recalculated through SHARPpy `ConvectiveProfile`. The Skew-T and hodograph use the decoded model profile.
- The diagnostic suite includes surface, mixed-layer, most-unstable, forecast and effective parcels; effective inflow layers; Bunkers storm motion; SRH and bulk shear; PWAT; lapse rates; PBL height and winds; SCP/STP/SHIP/SHERBE; DCAPE and downburst indices; precipitation phase/type and DGZ diagnostics; fire-weather indices; SARS matches; and vertical wet-bulb, theta, theta-e, mixing-ratio and RH profiles.
- Temperature/dewpoint adjustment depth and mixing depth are separate controls in metres AGL. Mixing potential temperature, moisture and horizontal momentum can transport stronger winds downward. This is an idealized sensitivity experiment, not a replacement for the forecast model's PBL scheme.
- Original profile arrays are immutable. Adjusted diagnostics are shown only after a successful SHARPpy calculation; no substitute JavaScript indices are produced when SHARPpy fails.
- `sharppy_service.py` remains available as an optional local FastAPI interface for external workflows, but the public browser lab runs SHARPpy locally in the tab.

### Legacy optional hosted API (not required for the browser lab)

The following container scaffold is retained for optional future server-side workflows only. **Do not deploy it for the current Browser SHARPpy Lab.** The current browser workflow is fully local to the tab and has no paid hosting dependency:

- `Dockerfile.sharppy` builds the Python 3.10 + SHARPpy API image.
- `workers/sounding-api/src/index.js` exposes the API through a Cloudflare Worker and enables outbound internet access for PSU BUFKIT downloads.
- `wrangler.sharppy.toml` defines the Durable Object-backed Container.
- `package.json` provides `npm run deploy:sharppy`.

From the repository root, with Docker and Wrangler authenticated to the intended Cloudflare account:

```bash
npm install
npm run deploy:sharppy
```

Cloudflare Containers are a paid option and are not part of the current architecture. No public Pages setting should point to a Workers URL. The UI's API endpoint field is editable; set it to the deployed Worker URL once Cloudflare returns the exact hostname. Do not publish a guessed hostname.

For Workers Builds, connect the repository with the root directory set to the repository root and use `npm run deploy:sharppy` as the production deploy command. The container requires outbound internet access to fetch BUFKIT files from PSU. Local BUFKIT cache storage is ephemeral and short-lived; a persistent R2 cache can be added after the first end-to-end validation. Before making the API broadly reachable, protect it with Cloudflare Access and/or rate-limiting rules; CORS is a browser policy, not authentication, and SHARPpy calculations consume container resources.

Start the local SHARPpy calculation API:

```bash
conda env create -f mesoscale/environment-sharppy.yml
conda activate btv-sharppy
uvicorn mesoscale.sharppy_service:app --host 0.0.0.0 --port 8000
```

Then open the Workbench and leave the calculation-service field at `http://127.0.0.1:8000`. Click **Check** to verify SHARPpy is reachable. Modified profiles are not calculated in browser JavaScript: if the API is unavailable, the original profile remains visible and the page clearly reports that no modified SHARPpy output was produced.

Run focused tests with:

```bash
pytest -q mesoscale/tests/test_sharppy_adapter.py mesoscale/tests/test_sharppy_service.py
```

The UI retains the verified RAP archive as a static fallback and the SHARPpy API now exposes on-demand BUFKIT ingestion through SHARPpy's own `BufDecoder`. The source is the Penn State BUFKIT Data Distribution System; supported model keys include RAP, HRRR, GFS, NAM, NAMNEST, RRFS, and HIRESW. SREF is deferred until ensemble-member selection is implemented. Files are downloaded only when requested and cached locally for a short TTL. The model cycle is derived from the BUFKIT valid time and STIM lead. A model can be missing or stale at the upstream provider; the endpoint reports that condition instead of substituting another model. BUFKIT height is referenced to its lowest valid model level for AGL adjustments.

## Development sequence

1. Maintain RAP cycle freshness, multi-hour archive completeness and station/grid quality checks.
2. Perform browser-level validation of HRRR map parameter/hour switching, data freshness and stale-layer clearing; keep soundings and cross-sections RAP-only.
3. Validate RAP/HRRR common-valid-time comparisons for fields with compatible definitions and units.
4. Preserve GRIB level/step metadata so additional HRRR CAPE and precipitation fields can be exposed without ambiguity.
5. Build and validate a compact BTV-cropped RRFS surface payload from the verified Lambert grid, then extend it to multi-hour consistency before publication.
6. Add stale-data checks, automated tests and clear model-by-model status reporting.

## Running locally

Open `mesoscale.html` through a local static web server. The interface uses public Leaflet/Plotly CDNs and OpenStreetMap tiles. Published RAP data are loaded from `mesoscale/data/fields/forecast/` and HRRR surface grids from `mesoscale/data/fields/hrrr/`. HRRR map parameters currently include 2-m temperature/dewpoint, 10-m wind speed, gust, composite reflectivity, visibility, CIN and boundary-layer height. Soundings, hodographs, cross-sections and Time Evolution remain RAP-only; RRFS remains discovery/smoke-test-only with no published field archive.

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

The model discovery service now includes the operational RRFS deterministic CONUS 3-km products. It discovers the pressure-level, 2-D surface, and sub-hourly 2-D file families from the NCEP production directory structure and records their .idx inventories. Index probes retry transient empty/HTML responses up to three times with a short bounded backoff; permanent HTTP errors remain visible and the older indexed cycle is retained as a fallback.

- Pressure levels: rrfs.tCCz.prslev.3km.fFFF.conus.grib2
- 2-D fields: rrfs.tCCz.2dfld.3km.fFFF.conus.grib2
- Sub-hourly 2-D fields: rrfs.tCCz.2dfld.3km.subh.fFFF.conus.grib2

The RRFS option remains disabled in mesoscale.html. Discovery is wired into the manifest workflow, and regression tests cover all three RRFS filename families and the two-digit cycle-directory convention. A prior scheduled discovery run succeeded, but the RAP-owned minute-47 UTC schedule has not yet produced a post-change scheduled run in the inspected history; hourly unattended refresh remains unverified. Push and workflow-run triggers are verified. A previous over-escaped regular expression was corrected. RRFS regional archive publication remains disabled. The read-only range smoke test has confirmed NOMADS HTTP 206 responses, exact Content-Range offsets, complete GRIB message boundaries, matching GRIB reference time, and ecCodes decoding. In successful run [43351175252](https://github.com/nwsmatthewclay/BTV-Mesoscale-Detective/actions/runs/43351175252), the 00Z F001 product supplied TMP, DPT, UGRD and VGRD messages; each decoded to 1,905,141 finite values. The Lambert grid is 1,799 × 1,059, and 12,006 grid points fall inside the padded BTV rectangle. The test is still read-only: it does not write a cropped grid or publish meteorological fields. The 3-km RRFS pressure-level file remains the intended future source for column diagnostics; 2-D products supply near-term fields such as composite reflectivity, CAPE/CIN, gusts, visibility and precipitation diagnostics. Sub-hourly `2dfld.3km.subh` files use 15-minute forecast steps: F001 represents 15 minutes and F003 represents 45 minutes. Discovery records these as `forecast_step`, `forecast_lead_minutes` and `forecast_interval_minutes`, not integer `forecast_hour` values.

NOMADS currently lists RRFS under HTTPS distribution without a GRIB-filter entry. Indexed HTTP range acquisition and BTV geographic coverage are now verified for a small set of messages; extracting the actual regional grid window, multi-hour consistency and a complete field inventory remain to be tested before automated RRFS publication. The RRFS/REFS transition and current product naming are documented in the NWS implementation notice and NCEP RRFS product inventory.

## SHARPpy sounding diagnostics (optional integration)

The RAP profile extractor now includes a separate `sharppy` result block for each extracted profile. It reports `passed`, `not_installed`, or `failed` independently of the existing MetPy diagnostics; a SHARPpy failure does not invalidate or replace the verified source profile.

Install the optional dependency in an isolated environment with:

```bash
conda env create -f mesoscale/environment-sharppy.yml
conda activate btv-sharppy
pytest -q mesoscale/tests/test_sharppy_adapter.py
```

The adapter converts the repository's profile contract explicitly (K to °C, m/s to kt) before calling SHARPpy. It returns surface, most-unstable and mixed-layer parcel diagnostics, Bunkers storm motion, 0–1 km SRH and 0–6 km bulk shear. SHARPpy outputs are kept separate from the existing MetPy calculations so forecasters can compare methods and provenance. The dedicated Conda CI run now exercises both a synthetic sounding and the actual archived KBTV RAP profile; the latest completed scientific validation run passed 24 tests.

SHARPpy remains an optional dependency, but its installation and adapter calculations have passed the dedicated Python 3.10 / NumPy 1.x Conda workflow using SHARPpy 1.4.0. Two NumPy warnings remain when SHARPpy interpolation converts masked values to NaN; these are visible in CI and are not suppressed. The browser remains responsible for rendering the Skew-T and hodograph; the SHARPpy desktop GUI is not embedded in the web page. The model explorer now groups native 2-D fields into meteorological categories and exposes each model's own decoded fields through a generic renderer; hybrid-level 3-D fields remain reserved for vertical analysis rather than being misrepresented as surface maps.

## Hybrid-level cross-section engine (prototype)

`cross_section.py` accepts exact GRIB short names supplied by a verified inventory, samples a great-circle transect using nearest native-grid points, and interpolates each column to a common pressure coordinate in log-pressure space. Repeated hits on the same native grid cell are removed, out-of-column levels are returned as null, and the result includes model/cycle/valid-time metadata and native grid indices. A real-data regression test successfully samples RAP `w` (vertical velocity, Pa s**-1), `t` (temperature), and `gh` (geopotential height) from the committed F00 archive. Negative pressure vertical velocity indicates ascent under the model convention.

The browser Cross-Section Lab now has a vertical-variable selector for temperature, derived dewpoint, omega, U/V wind, specific humidity, cloud water, rain, snow, graupel, and turbulent kinetic energy. It samples the corresponding hybrid-level field at the same nearest native grid cells as the quality-controlled RAP profile, uses no vertical extrapolation, and interpolates only vertically to 250 m display spacing. Consecutive duplicate native cells are removed; the status line reports distinct native columns, skipped probes, nearest-cell offset, and the nominal ~13-km RAP horizontal resolution. The browser test exercises temperature and omega selection.

Frontogenesis is not supplied as a direct field in the current RAP archive. `frontogenesis.py` derives 2-D Petterssen frontogenesis from potential temperature and horizontal wind gradients on pressure surfaces, then samples the transect. It requires a verified Lambert projection, native grid spacing, and U/V explicitly marked grid-relative by GRIB metadata. Synthetic-grid tests pass, and the live read-only RAP F00 probe has now passed on an actual freshly downloaded RAP file (850/700/500 hPa, 7 transect samples, 21 finite values). The calculation is validated but is not yet exposed as a browser map layer. No proxy field is substituted.


## Viewer interface — model workstation redesign

The browser interface has been redesigned as a map-first model workstation. Model, cycle, forecast hour, variable category, and map variable now live in a single horizontal control deck above the map. The regional map is the dominant workspace, with overlays, station selection, and transect tools in a compact toolbar beneath it. Point diagnostics and Skew-T/hodograph panels sit in a right-side analysis rail; cross-section, time-evolution, and provenance panels are arranged below. The visual system uses a restrained navy/blue/cyan palette, consistent panel surfaces, compact metadata labels, responsive spacing, and a mobile single-column reflow.

The desktop and mobile layout are covered by Playwright regression assertions. The redesigned `index.html` and `mesoscale.html` are maintained byte-for-byte identically. This is a presentation/layout change only; it does not change model ingestion, data products, or the production SA dashboard.


## Zoomable model map tiles

The model viewer now has a pre-rendered map-tile path alongside the legacy in-browser renderer.

- `render_model_tiles.py` reads the published, cropped GRIB-derived JSON grid and produces transparent 256-pixel XYZ raster tiles.
- Raster interpolation is performed in Web Mercator from the source grid; invalid/out-of-domain cells remain transparent.
- Contours are calculated separately from the native two-dimensional source grid and exported as GeoJSON, not inferred from the display raster.
- Each product records model, cycle, forecast hour, valid time, source field, source/display units, display transform, color range, contour interval, and tile URL template.
- `.github/workflows/model_tile_render.yml` validates the renderer, generates available supported 2-D products for verified RAP and HRRR archives, writes a catalog, and publishes the tile archive.
- The Leaflet viewer reads the catalog, loads the matching XYZ raster layer, and independently toggles the GeoJSON contour overlay. CARTO's light/no-label basemap plus a separate label layer provides a cleaner synoptic-style geographic context than the previous street map.

The renderer intentionally refuses ambiguous short-name matches and non-2-D fields. Three-dimensional pressure/hybrid-level products must first be selected or vertically interpolated to a defined pressure surface; they must not be silently treated as surface fields. The first automated product set is limited to verified 2-D surface fields. Temperature, visibility, and gust products are converted to display-friendly units while the original units and transform are retained in product metadata.

This is an initial tile-rendering implementation. Validate the published products against native grid values and independent plotting before operational use. Tile zoom levels currently target regional viewing (z3-z7); higher zoom levels upscale the highest-resolution tiles until a finer native-grid tiling strategy is added.


## Browser-based SHARPpy experiment (new)

Open the dark-only [Browser SHARPpy Lab](../sounding-browser.html) from the Sounding Workbench. This is a technical proof of concept for running the actual SHARPpy calculation routines inside the user's browser with Pyodide/WebAssembly; it does not require a local Python installation, API server, or GitHub Action for interactive profile changes.

- The lab loads a verified RAP station profile from the published forecast archive.
- On user request, it initializes Pyodide 0.26.4, loads NumPy, loads the same-origin, repository-vendored SHARPpy v1.4.0 source bundle (built from the pinned upstream tag by GitHub Actions), and imports the repository's existing `sharppy_adapter.py`.
- The adapter calls SHARPpy's actual `create_profile(profile="convective")` path. The lab only labels a calculation successful after the `ConvectiveProfile` suite returns.
- `browser_adjustments.py` is a NumPy-only module (no MetPy or server dependency) for low-level temperature/dewpoint offsets and pressure-mass-weighted mixing of potential temperature, water-vapor mixing ratio, and horizontal momentum.
- Slider changes are debounced briefly and recalculate in the already initialized browser Python runtime. GitHub Actions is not invoked for these interactive changes.
- The original profile remains immutable. If the browser cannot load SHARPpy or a diagnostic fails, the page reports the error and retains the archived original diagnostics; it does not substitute JavaScript or MetPy values.
- The initial prototype is limited to the verified RAP station archive. BUFKIT ingestion, arbitrary map-click profiles, and Web Worker isolation remain follow-on work.
- A Playwright Chromium smoke test now loads the real archived KBTV RAP profile, initializes Pyodide, imports SHARPpy, verifies the full `ConvectiveProfile` baseline, changes low-level temperature, and verifies a second SHARPpy calculation. The successful GitHub Actions run measured approximately 899 ms for the baseline and 677 ms for the modified profile on its hosted runner; actual workstation timing will vary.

The first initialization downloads the Python/WebAssembly runtime and the vendored SHARPpy source bundle, so it is expected to take longer than subsequent recalculations. This remains a research prototype until the browser diagnostics have been numerically compared against the native Python/SHARPpy environment and the additional data sources are integrated.


## Regional BUFKIT sounding archive

A separate hourly BUFKIT acquisition pipeline is now in place for the exact 32 station identifiers transcribed from the user's BUFKIT selector screenshot. The model set is RRFS, GFS, RAP and HRRR. The first live provider acquisition confirmed all 32 requested station files were available for each of the four models after correctly reading the final site code as `LO1` (not `LOI`).

Retention is six model cycles for RAP and HRRR, and eight cycles for GFS and RRFS. Original provider BUFKIT text is gzip-compressed for repository storage; per-file JSON metadata preserves source URL, initialization cycle, valid times, forecast hours, byte counts and SHA-256. The archive job runs hourly and can also be manually dispatched. It avoids rewriting unchanged files and prunes older cycles according to the configured retention.

- Station/model inventory: `bufkit_sites.json`
- Hourly archive downloader: `archive_bufkit.py`
- GitHub Actions workflow: `.github/workflows/bufkit_archive.yml`
- Published archive catalog: `data/bufkit/catalog.json`
- Dark-mode archive browser: `../bufkit-archive.html`

The archive browser lists model cycles, stations, forecast periods and direct compressed BUFKIT downloads. The archive-to-browser-SHARPpy decoding integration is the next step; at this stage the archive pipeline and catalog are being validated independently from the interactive SHARPpy calculations.
