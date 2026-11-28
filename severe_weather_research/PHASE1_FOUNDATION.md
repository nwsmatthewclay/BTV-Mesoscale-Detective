# Phase 1 — Foundation and Data Integrity

Phase 1 establishes an auditable baseline before further meteorological discovery.

## Checks
- Case manifest structure, unique IDs, valid date strings, duplicate-date review flags.
- Raw ERA5 file existence, size and GRIB signature for pressure-level and single-level files.
- Optional profile coverage by case/site, duplicate profile keys and expected row coverage.
- Optional diagnostics inventory, case/site coverage and duplicate diagnostic keys.
- A machine-readable JSON report plus CSV tables for review.

## Interpretation
This is a structural and completeness audit, not meteorological validation. ERA5 is reanalysis; nearest-grid profiles are not observed soundings. Event labels, report timing and event locations remain provisional pending report-level verification.

## Run
Use GitHub Actions workflow **Phase 1 Foundation Audit**. Supply the run ID containing the 30-case raw ERA5 artifact. Optionally supply a run ID containing the processed profile/diagnostic artifact. Outputs are retained as a 30-day Actions artifact.
