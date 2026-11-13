# Regional Model Viewer — Architecture and Delivery Plan

## Product goal

Evolve BTV Mesoscale Detective into a free-to-operate, browser-based regional model-analysis viewer for the Great Lakes, eastern Canada, Northeast, Mid-Atlantic, and Carolinas.

The viewer should be easy to use for routine map interrogation while supporting advanced meteorological analysis: SHARPpy-based soundings, hodographs, vertical cross-sections, omega, frontogenesis, time-height analysis, and valid-time-aligned model comparison.

## Non-negotiable constraints

- Monthly operating cost must remain $0. Do not introduce paid services, paid APIs, paid storage, or a billing-dependent fallback.
- Never exceed free-tier quotas by silently enabling paid usage. Prefer graceful degradation, cache expiry, and paused ingestion over charges.
- Never fabricate or silently substitute meteorological data.
- Every field and diagnostic must retain model, initialization time, valid time, forecast lead, level, units, source, grid metadata, and quality/provenance.
- Keep this project separate from the operational NWS_SA_Dashboard.
- Keep `index.html` and `mesoscale.html` byte-for-byte synchronized whenever either is changed.

## Proposed geographic domain

Initial rectangular acquisition/display envelope (to be tested against each model's native grid):

- West: 92°W
- East: 64°W
- South: 30°N
- North: 52°N

This is a working envelope, not a claim that every model covers every point. The UI must show native model coverage and mask areas outside each model's valid grid. A geographic display boundary/shape can be layered over the rectangular data envelope later.

## Models and current readiness

| Model | Current repository status | Intended role |
|---|---|---|
| RAP | Verified regional full-column archive for the existing BTV domain | Initial full-column analysis and cross-section development |
| HRRR | Verified regional 2-D surface archive; no full-column profile archive yet | High-resolution surface maps; later add upper-air fields |
| RRFS | Indexed range acquisition smoke-tested; no published regional archive | Future high-resolution regional model after field and multi-hour validation |
| GFS | Not integrated | Broad-domain/global comparison |
| ECMWF IFS open data | Not integrated | Broad-domain/global comparison |

Discovery of a model product is not proof that its data have been decoded, validated, and published. Each model/field/level is enabled independently only after validation.

## Architecture principles

1. **Upstream-first:** NOAA and ECMWF remain the primary model-data hosts. Retrieve only needed files/messages and geographic subsets where source services support it.
2. **Static-first deployment:** Prefer GitHub Pages and public GitHub Actions workflows for the first implementation. Avoid adding a server or storage service unless a measured requirement cannot be met for free.
3. **No full-model mirroring:** Do not retain full CONUS/global source files or duplicate equivalent source and derived fields.
4. **Small rolling working set:** Publish only a bounded set of current products needed for the active viewer. Keep previous cycles only where useful and within verified free quotas.
5. **On-demand analysis:** Generate point profiles and transects from validated model fields when requested or during bounded preprocessing. Cache only compact outputs with explicit expiry.
6. **Explicit coverage and status:** Show model availability, cycle, valid time, native grid spacing, coverage mask, field inventory, and stale/missing status.
7. **Graceful quota behavior:** Measure storage, repository growth, Pages artifact size, Actions minutes, and upstream request volume. Pause or reduce optional ingestion before any paid service could be triggered.

## Main workspaces

- **Model Explorer:** map layers, parameter search, forecast-hour slider, animation, model/cycle selection, overlays, and point interrogation.
- **Sounding Explorer:** SHARPpy sounding calculations, Skew-T, hodograph, parcel selection, thermodynamic/kinematic parameters, and observed/model comparisons.
- **Cross-Section Lab:** user-drawn transects, vertical interpolation, omega, frontogenesis, temperature, humidity, wind barbs, pressure/height axes, and forecast-hour animation.
- **Winter Weather Lab:** precipitation type, thermal profiles, dendritic growth zone, omega overlap, frontogenesis, and snow-growth diagnostics.
- **Point & Time Explorer:** point soundings, time-height sections, forecast evolution, and profile comparisons.
- **Model Comparison:** exact-valid-time comparisons with compatible variable definitions, units, and explicit missing-field handling.

## Scientific implementation notes

- SHARPpy is a Python sounding-analysis library and desktop application. Integrate its supported calculation routines in the Python processing layer; build a browser-native interface for Skew-T/hodograph interaction rather than attempting to embed its desktop GUI.
- MetPy/xarray are candidates for geospatial vertical cross-section interpolation. Preserve coordinate reference systems, vertical coordinate metadata, and interpolation method.
- Frontogenesis must be calculated from appropriate horizontal thermodynamic gradients and wind fields when not supplied by a model. Record the exact definition, units, coordinate treatment, and calculation provenance.
- Omega must retain its native units and sign convention; negative pressure vertical velocity generally indicates ascent.
- Hybrid/native model levels must be handled with their associated surface pressure and vertical-coordinate coefficients. Do not treat model levels as pressure levels.
- Cross-section samples must reflect the native model grid and report effective resolution. Do not imply that interpolation creates finer physical resolution.

## Delivery sequence

### Phase 0 — Baseline and constraints
- Preserve the existing working dashboard and its data-safety checks.
- Audit current browser smoke failures and make the existing RAP transect workflow reliable.
- Measure current repository payloads, Git history growth, Pages deployment size, and Actions usage.
- Verify the zero-cost deployment path and quota behavior before expanding ingestion.

### Phase 1 — Regional data foundation
- Implement the regional envelope as explicit configuration, not scattered constants.
- Build a model/field/level capability registry and per-model geographic coverage masks.
- Prototype one representative cycle for each source; measure actual regional payload sizes and processing time.
- Keep RAP full-column as the first verified vertical-analysis source; expand HRRR/RRFS only after validation.
- Evaluate GFS and ECMWF open-data retrieval without promising fields/hours until tested.

### Phase 2 — Analysis engine
- Define a common profile and grid data contract.
- Add SHARPpy adapter and regression fixtures for sounding calculations.
- Build and test reusable cross-section extraction, including hybrid-to-pressure handling where required.
- Add omega and frontogenesis with unit, sign, and physical sanity checks.

### Phase 3 — Viewer experience
- Introduce the unified model/time/map control system.
- Add map popups and expandable analysis panels.
- Add interactive Skew-T/hodograph and user-drawn cross-sections.
- Add model comparison, time-height, animation, and winter-weather presets.

### Phase 4 — Model expansion and hardening
- Integrate GFS and ECMWF IFS.
- Expand HRRR and RRFS vertical capabilities as source products permit.
- Add end-to-end browser tests, stale-data tests, quota alarms, and operational status reporting.


## Implementation status — 2026-11-13

- The existing RAP transect browser regression passed on the current baseline; the earlier undeclared `grid_id` reference is already corrected on `main` and has a regression guard in this feature branch.
- SHARPpy 1.4.0 installs successfully from conda-forge in an isolated Python 3.10 / NumPy 1.x environment. The adapter has passed synthetic and real archived KBTV RAP sounding tests. The latest completed validation run passed 24 tests, including new standard/compact UTC cycle parsing tests; two visible NumPy masked-value warnings from SHARPpy interpolation remain under review.
- A reusable RAP cross-section engine is implemented and validated against the committed F00 archive. The browser Cross-Section Lab now offers temperature, derived dewpoint, omega, U/V wind, specific humidity, cloud water, rain, snow, graupel, and turbulent kinetic energy. It samples distinct native grid cells, aligns hybrid fields using the profile's retained hybrid-level indices, disables vertical extrapolation, and interpolates vertically to 250 m display spacing without claiming finer horizontal resolution. The browser test exercises temperature and omega.
- The archived RAP F00 inventory confirms 50 hybrid levels for pressure, temperature, geopotential height, specific humidity, U/V wind, and vertical velocity. Cloud-water, rain, snow, and graupel mixing ratios are also available on hybrid levels.
- The GRIB processor now retains dataset-level projection/grid-spacing metadata and variable-level GRIB attributes, including U/V orientation flags. A Petterssen frontogenesis prototype derives the 2-D diagnostic from potential temperature and horizontal wind gradients on pressure surfaces. Synthetic Lambert-grid tests pass, and the function refuses missing projection/spacing or non-grid-relative/unknown U/V orientation. A read-only live RAP F00 probe then verified the actual 13,545 m Lambert grid and grid-relative U/V metadata and successfully calculated frontogenesis at 850/700/500 hPa (7 transect samples, 21 finite values). The older committed archive predates the new metadata, but the real-data engine itself is now validated on a fresh temporary source decode.
- No changes have been made to production `main`, the operational SA dashboard, or any deployment. The feature work remains isolated in draft PR #1.

## Immediate first milestone

Do not begin by adding all five models or redesigning the whole page. First:
1. Fix and validate the current RAP cross-section browser path.
2. Extract the current BTV-only assumptions into a configurable regional-domain definition.
3. Run a bounded regional data-size experiment for RAP and HRRR.
4. Prototype one SHARPpy profile calculation against an existing verified RAP profile.

This produces a stable scientific and storage foundation before large UI changes.


- The categorized variable selector now introspects each verified model grid after load and dynamically adds every unique native 2-D field to a meteorological category (thermodynamics, moisture, kinematics, forcing, surface, reflectivity, aviation, winter hydrometeors, land/soil, energy, or other). The generic native-field renderer uses source units and a 5th–95th percentile display stretch; model ownership is retained, and unavailable categories are disabled. Hybrid/vertical fields remain distinct and are exposed through the Cross-Section Lab selector. The next major work is integrating the validated frontogenesis calculation into the published model products/map layers and expanding the vertical viewer with pressure-coordinate overlays and animations. Browser CI exercises category filtering, real RAP/HRRR native-field selection, and temperature/omega cross-sections; the latest run is being rerun after updating an assertion to match the new native-cell status wording.
- PR CI now includes browser coverage for the category filtering and existing RAP/HRRR valid-time/archive switching. The new browser job is in progress; do not treat it as passed until its result is confirmed.
