# BTV Severe Weather Research

Research workspace for severe convective events in the Burlington (BTV) forecast area, March–September.

## First acquisition run
The initial manifest contains five report-driven candidate cases. These are screening dates—not an environmental classification.

Run the **ERA5 First Five Cases** workflow from GitHub Actions (or it runs on pushes to this acquisition folder). It downloads ERA5 pressure-level and single-level GRIB files for each case day to an Actions artifact. Raw GRIB files are intentionally not committed.

### Secret
Set repository Actions secret `CDS_API_KEY` to your Copernicus Climate Data Store personal access token. The token is passed to the downloader as an environment variable; never place it in a file or commit.

### Files
- `acquisition/case_manifest.csv`: first five cases
- `acquisition/download_era5_cases.py`: downloader, retry-safe skip behavior, manifest logging
- `.github/workflows/acquire_era5_first_five.yml`: manual + path-push workflow
- `data/raw/`: downloads in the workflow workspace (artifact only)
- `data/metadata/acquisition_log.csv`: per-file result log

The downloader requests hourly ERA5 for each case date (00–23 UTC), pressure levels 1000/925/850/700/500/300/250 hPa and a set of surface fields. Dataset terms must be accepted in CDS before requests can succeed.
