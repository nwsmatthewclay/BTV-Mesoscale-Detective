# Phase 5 — Pilot Evaluation

Run after Phase 2 diagnostics are available. This phase evaluates the five-case pilot with descriptive distribution statistics and data completeness checks.

## Run
GitHub Actions → **Phase 5 Pilot Evaluation** → Run workflow. Enter the run ID from the Phase 2 diagnostics workflow (the run that created `btv-era5-environmental-diagnostics`).

## Outputs
- `phase5_case_distribution_stats.csv`: case distributions across sampled sites/times (mean, median, standard deviation, min, quartiles, max).
- `phase5_site_distribution_stats.csv`: same statistics by case and site.
- `phase5_3hourly_distribution_stats.csv`: environmental evolution by UTC 3-hour bin (not storm-report-time aligned).
- `phase5_case_mean_zscores.csv`: descriptive standardized case means across the five cases.
- `phase5_data_completeness.csv`: per-case parameter completeness.
- `phase5_report.json`: machine-readable summary and cautions.
- `phase5_*.png`: parameter medians and IQR plots.

## Interpretation
This is descriptive pilot work only. Five cases are not sufficient for inferential statistics or operational thresholds. ERA5 gridpoint values are reanalysis estimates, not observed soundings. The UTC hourly bins are not linked to report timestamps. Report-time matching and balanced case expansion should be a later step.
