#!/usr/bin/env python3
"""Phase 1B reproducibility/calculation audit for ERA5 severe-weather diagnostics.

Recalculates diagnostics from the archived hourly profiles using the current
MetPy-based calculation routine and compares them with the archived diagnostic
CSV. This is a reproducibility audit, not a fully independent algorithm
validation; both sides use the same calculation implementation/library.
"""
from __future__ import annotations
import argparse, json
from pathlib import Path
import numpy as np
import pandas as pd

KEY = ["case_id", "date", "site", "valid_time_utc"]
PARAMS = [
    "sbcape_jkg", "sbcin_jkg",
    "mlcape_100hpa_jkg", "mlcin_100hpa_jkg",
    "mucape_300hpa_jkg", "mucin_300hpa_jkg",
    "lcl_pressure_hpa", "lcl_temperature_c", "pwat_mm",
    "shear_0_1km_kt", "shear_0_3km_kt", "shear_0_6km_kt",
    "lapse_0_3km_c_per_km", "lapse_700_500_c_per_km",
    "freezing_level_agl_m", "hail_growth_layer_10_to_30c_depth_m",
]
# Absolute tolerances chosen to accommodate CSV float serialization and minor
# numerical differences. Larger discrepancies should be investigated, not assumed
# to be meteorologically meaningful.
TOLERANCES = {
    "sbcape_jkg": 1.0, "sbcin_jkg": 1.0,
    "mlcape_100hpa_jkg": 1.0, "mlcin_100hpa_jkg": 1.0,
    "mucape_300hpa_jkg": 1.0, "mucin_300hpa_jkg": 1.0,
    "lcl_pressure_hpa": 0.1, "lcl_temperature_c": 0.1, "pwat_mm": 0.1,
    "shear_0_1km_kt": 0.1, "shear_0_3km_kt": 0.1, "shear_0_6km_kt": 0.1,
    "lapse_0_3km_c_per_km": 0.05, "lapse_700_500_c_per_km": 0.05,
    "freezing_level_agl_m": 25.0, "hail_growth_layer_10_to_30c_depth_m": 25.0,
}

def locate(root: Path, filename: str) -> Path:
    matches = list(root.rglob(filename))
    if not matches:
        raise FileNotFoundError(f"Could not find {filename} under {root}")
    return matches[0]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profiles", type=Path, required=True)
    ap.add_argument("--diagnostics", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    profiles = pd.read_csv(args.profiles)
    archived = pd.read_csv(args.diagnostics)
    from calculate_parameters import diagnostics as calc_diagnostics

    # Recalculate each profile-time/site independently from the source profile CSV.
    rows = []
    for key, group in profiles.groupby(KEY, sort=True):
        row = dict(zip(KEY, key))
        row.update(calc_diagnostics(group))
        rows.append(row)
    fresh = pd.DataFrame(rows)

    merged = archived.merge(fresh, on=KEY, how="outer", suffixes=("_archived", "_recalc"), indicator=True)
    comparison_rows = []
    for _, row in merged.iterrows():
        base = {k: row[k] for k in KEY}
        base["record_match"] = row["_merge"] == "both"
        for param in PARAMS:
            old_col, new_col = f"{param}_archived", f"{param}_recalc"
            old = row.get(old_col, np.nan); new = row.get(new_col, np.nan)
            old_num = pd.to_numeric(pd.Series([old]), errors="coerce").iloc[0]
            new_num = pd.to_numeric(pd.Series([new]), errors="coerce").iloc[0]
            both_missing = pd.isna(old_num) and pd.isna(new_num)
            valid_pair = np.isfinite(old_num) and np.isfinite(new_num)
            delta = float(new_num-old_num) if valid_pair else np.nan
            tol = TOLERANCES.get(param, 1.0)
            status = "both_missing" if both_missing else ("match" if valid_pair and abs(delta)<=tol else ("missing_value" if not valid_pair else "mismatch"))
            comparison_rows.append({**base, "parameter":param,"archived_value":old_num,"recalculated_value":new_num,"difference_recalc_minus_archived":delta,"absolute_tolerance":tol,"status":status})
    comparisons = pd.DataFrame(comparison_rows)
    comparisons.to_csv(args.out_dir/"phase1b_parameter_comparison.csv", index=False)

    record_counts = {
        "profiles_rows": int(len(profiles)),
        "archived_diagnostic_rows": int(len(archived)),
        "recalculated_diagnostic_rows": int(len(fresh)),
        "profile_keys_unique": bool(not profiles.duplicated(KEY+["pressure_hpa"]).any()),
        "archived_diagnostic_keys_unique": bool(not archived.duplicated(KEY).any()),
        "recalculated_diagnostic_keys_unique": bool(not fresh.duplicated(KEY).any()),
    }
    summary = comparisons.groupby(["parameter","status"]).size().unstack(fill_value=0).reset_index()
    summary.to_csv(args.out_dir/"phase1b_parameter_summary.csv", index=False)
    total = len(comparisons)
    matches = int((comparisons.status=="match").sum())
    both_missing = int((comparisons.status=="both_missing").sum())
    missing = int((comparisons.status=="missing_value").sum())
    mismatches = int((comparisons.status=="mismatch").sum())
    unmatched = int((comparisons.record_match==False).sum())
    overall = "PASS" if mismatches==0 and missing==0 and unmatched==0 and all(record_counts.values()) else ("WARN" if mismatches or missing or unmatched else "FAIL")
    report = {
        "phase":"phase1b_met_calculation_reproducibility_audit",
        "audit_scope":"Recalculation from archived profile CSV using the same MetPy-based calculation routine; not fully independent method validation.",
        "overall_status":overall,
        "comparison_rows":total,"matches_within_tolerance":matches,
        "both_missing":both_missing,"missing_values":missing,"mismatches":mismatches,
        "unmatched_records":unmatched,"record_integrity":record_counts,
        "tolerances":TOLERANCES,
        "parameter_summary":summary.to_dict(orient="records"),
        "notes":[
            "CAPE/CIN, LCL, PWAT, shear, lapse rates, freezing level, and hail-growth-layer diagnostics are recalculated and compared.",
            "DCAPE is not currently produced by the Phase 2 diagnostics routine and is therefore explicitly noted as not audited.",
            "Surface-based diagnostics use the lowest available ERA5 pressure level, not station observations.",
            "Height-based diagnostics use the existing hypsometric height method, which is an AGL proxy and should receive separate scientific scrutiny.",
            "Because the archived and recalculated values use the same implementation, exact agreement establishes reproducibility, not independent correctness."
        ]
    }
    (args.out_dir/"phase1b_met_audit.json").write_text(json.dumps(report,indent=2,default=str))
    lines = [
        "# Phase 1B — Meteorological Calculation Audit",
        "",
        f"**Overall status: {overall}**",
        "",
        f"- Comparison rows: {total}",
        f"- Within tolerance: {matches}",
        f"- Both missing: {both_missing}",
        f"- Missing value pairs: {missing}",
        f"- Mismatches: {mismatches}",
        f"- Unmatched records: {unmatched}",
        "",
        "## Parameter summary",
        "",
        summary.to_markdown(index=False),
        "",
        "## Scope and limitations",
        "",
        report["audit_scope"],
        "",
        "- DCAPE is not currently produced by the Phase 2 diagnostics routine and is not audited here.",
        "- Surface-based values use the lowest available ERA5 pressure level, not station observations.",
        "- Height-based diagnostics use the existing hypsometric height method; these heights are AGL proxies.",
        "- This audit verifies reproducibility and record integrity, not independent scientific correctness.",
    ]
    (args.out_dir/"phase1b_met_audit.md").write_text("\n".join(lines),encoding="utf-8")
    print(json.dumps({"status":overall,"comparison_rows":total,"matches":matches,"both_missing":both_missing,"missing":missing,"mismatches":mismatches,"unmatched_records":unmatched},indent=2))
    if overall == "FAIL":
        raise SystemExit("Phase 1B audit failed record integrity checks.")

if __name__=="__main__":
    main()
