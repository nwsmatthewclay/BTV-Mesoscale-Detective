#!/usr/bin/env python3
"""Phase 5: pilot evaluation and reproducible case diagnostics. Exploratory only."""
from pathlib import Path
import argparse, json, math
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

PARAMS = {
 "sbcape_jkg":"SBCAPE (J/kg)","mlcape_100hpa_jkg":"MLCAPE (J/kg)",
 "mucape_300hpa_jkg":"MUCAPE (J/kg)","sbcin_jkg":"SBCIN (J/kg)",
 "mlcin_100hpa_jkg":"MLCIN (J/kg)","mucin_300hpa_jkg":"MUCIN (J/kg)",
 "pwat_mm":"PWAT (mm)","lcl_pressure_hpa":"LCL pressure (hPa)",
 "shear_0_1km_kt":"0-1 km shear (kt)","shear_0_3km_kt":"0-3 km shear (kt)",
 "shear_0_6km_kt":"0-6 km shear (kt)","lapse_0_3km_c_per_km":"0-3 km lapse rate (C/km)",
 "lapse_700_500_c_per_km":"700-500 hPa lapse rate (C/km)",
 "freezing_level_agl_m":"Freezing level proxy (m AGL)",
 "hail_growth_layer_10_to_30c_depth_m":"-10 to -30 C layer depth (m)"
}
CASE_TYPES={"BTV001":"Hail-dominant","BTV002":"Wind-dominant","BTV003":"Mixed",
 "BTV004":"Hail-dominant / tornado","BTV005":"Wind-dominant"}
def json_safe(v):
 if isinstance(v,dict): return {str(k):json_safe(x) for k,x in v.items()}
 if isinstance(v,list): return [json_safe(x) for x in v]
 if isinstance(v,(float,np.floating)): return float(v) if math.isfinite(float(v)) else None
 if isinstance(v,(int,np.integer)): return int(v)
 return v
def stats(df,group_cols,parameter_cols):
 rows=[]
 for keys,g in df.groupby(group_cols,dropna=False):
  if not isinstance(keys,tuple): keys=(keys,)
  base=dict(zip(group_cols,keys))
  for p in parameter_cols:
   if p not in g.columns: continue
   v=pd.to_numeric(g[p],errors="coerce").dropna()
   rows.append({**base,"parameter":p,"label":PARAMS.get(p,p),"n":int(v.size),
    "mean":float(v.mean()) if v.size else None,"median":float(v.median()) if v.size else None,
    "std":float(v.std()) if v.size>1 else None,"min":float(v.min()) if v.size else None,
    "p25":float(v.quantile(.25)) if v.size else None,"p75":float(v.quantile(.75)) if v.size else None,
    "max":float(v.max()) if v.size else None})
 return pd.DataFrame(rows)
def main():
 ap=argparse.ArgumentParser()
 ap.add_argument("--input",type=Path,required=True); ap.add_argument("--out-dir",type=Path,required=True)
 a=ap.parse_args(); a.out_dir.mkdir(parents=True,exist_ok=True)
 d=pd.read_csv(a.input)
 required=["case_id","site","valid_time_utc"]
 missing=[x for x in required if x not in d]
 if missing: raise SystemExit("Missing required input columns: "+", ".join(missing))
 d["valid_time_utc"]=pd.to_datetime(d.valid_time_utc,utc=True,errors="coerce")
 d=d[d.valid_time_utc.notna()].copy()
 d["hour_utc"]=d.valid_time_utc.dt.hour
 d["hour_bin_utc"]=(d.hour_utc//3)*3
 params=[p for p in PARAMS if p in d.columns]
 if not params: raise SystemExit("No recognized environmental parameter columns found.")
 # Case-level distributions across all sites/times; site stats reveal spatial variability.
 case=stats(d,["case_id"],params); case["case_type"]=case.case_id.map(CASE_TYPES)
 site=stats(d,["case_id","site"],params); site["case_type"]=site.case_id.map(CASE_TYPES)
 hourly=stats(d,["case_id","hour_bin_utc"],params); hourly["case_type"]=hourly.case_id.map(CASE_TYPES)
 # Case means standardized across the five cases (descriptive only; n=5).
 means=d.groupby("case_id")[params].mean()
 z=means.copy()
 for p in params:
  sd=means[p].std(ddof=1)
  z[p]=(means[p]-means[p].mean())/sd if pd.notna(sd) and sd>0 else np.nan
 z.reset_index().to_csv(a.out_dir/"phase5_case_mean_zscores.csv",index=False)
 case.to_csv(a.out_dir/"phase5_case_distribution_stats.csv",index=False)
 site.to_csv(a.out_dir/"phase5_site_distribution_stats.csv",index=False)
 hourly.to_csv(a.out_dir/"phase5_3hourly_distribution_stats.csv",index=False)
 # Completeness by case and parameter
 comp=[]
 for c,g in d.groupby("case_id"):
  for p in params:
   total=len(g); valid=pd.to_numeric(g[p],errors="coerce").notna().sum()
   comp.append({"case_id":c,"case_type":CASE_TYPES.get(c,"Unclassified"),"parameter":p,
    "label":PARAMS[p],"rows_expected":int(total),"valid":int(valid),
    "missing":int(total-valid),"completeness_pct":float(100*valid/total) if total else None})
 pd.DataFrame(comp).to_csv(a.out_dir/"phase5_data_completeness.csv",index=False)
 # Individual parameter plots: case medians with interquartile ranges.
 for p in params:
  sub=case[case.parameter==p].sort_values("case_id")
  if sub.empty: continue
  fig,ax=plt.subplots(figsize=(9,5))
  x=np.arange(len(sub)); med=sub["median"].to_numpy(float)
  lo=sub["p25"].to_numpy(float); hi=sub["p75"].to_numpy(float)
  ax.bar(x,med)
  ax.errorbar(x,med,yerr=np.vstack([med-lo,hi-med]),fmt="none",capsize=4)
  ax.set_xticks(x,sub.case_id); ax.set_ylabel(PARAMS[p]); ax.set_title("Pilot case medians and IQR: "+PARAMS[p])
  ax.grid(axis="y",alpha=.25); fig.tight_layout()
  fig.savefig(a.out_dir/f"phase5_{p}.png",dpi=150); plt.close(fig)
 # Completeness summary + diagnostic report; no event-specific report-time linkage exists.
 completeness=pd.DataFrame(comp)
 report={"phase":"5 pilot evaluation","input_rows":int(len(d)),"cases":sorted(d.case_id.unique().tolist()),
  "sites":sorted(d.site.unique().tolist()),"recognized_parameters":params,
  "case_types":CASE_TYPES,"output_csvs":["phase5_case_distribution_stats.csv","phase5_site_distribution_stats.csv",
  "phase5_3hourly_distribution_stats.csv","phase5_case_mean_zscores.csv","phase5_data_completeness.csv"],
  "plots_created":int(len(list(a.out_dir.glob("*.png")))),
  "completeness_overall_pct":float(completeness.completeness_pct.mean()) if not completeness.empty else None,
  "scientific_cautions":["Pilot has only five cases; case-type comparisons are descriptive, not inferential.",
  "Case labels are report-based pilot labels and are not independent event classifications.",
  "ERA5 gridpoint diagnostics are reanalysis estimates, not observed soundings.",
  "Hourly bins are UTC and are not report-time-aligned; no report timestamp linkage is used.",
  "Z-scores are calculated across five case means and should not be treated as thresholds or significance tests."]}
 (a.out_dir/"phase5_report.json").write_text(json.dumps(json_safe(report),indent=2,allow_nan=False))
 print(json.dumps(report,indent=2))
if __name__=="__main__": main()
