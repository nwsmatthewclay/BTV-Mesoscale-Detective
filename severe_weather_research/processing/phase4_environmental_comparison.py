#!/usr/bin/env python3
"""Phase 4 exploratory comparisons for the five ERA5 severe-weather pilot cases."""
from pathlib import Path
import argparse, json, math
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

PARAMS = {
 "sbcape_jkg": ("Surface-based CAPE", "J/kg"),
 "mlcape_100hpa_jkg": ("100-hPa Mixed-layer CAPE", "J/kg"),
 "mucape_300hpa_jkg": ("300-hPa Most-unstable CAPE", "J/kg"),
 "sbcin_jkg": ("Surface-based CIN", "J/kg"),
 "mlcin_100hpa_jkg": ("100-hPa Mixed-layer CIN", "J/kg"),
 "mucin_300hpa_jkg": ("300-hPa Most-unstable CIN", "J/kg"),
 "pwat_mm": ("Precipitable Water", "mm"),
 "lcl_pressure_hpa": ("LCL Pressure", "hPa"),
 "shear_0_1km_kt": ("0–1 km Shear", "kt"),
 "shear_0_3km_kt": ("0–3 km Shear", "kt"),
 "shear_0_6km_kt": ("0–6 km Shear", "kt"),
 "lapse_0_3km_c_per_km": ("0–3 km Lapse Rate", "°C/km"),
 "lapse_700_500_c_per_km": ("700–500 hPa Lapse Rate", "°C/km"),
 "freezing_level_agl_m": ("Freezing Level (proxy)", "m AGL"),
 "hail_growth_layer_10_to_30c_depth_m": ("−10 to −30°C Layer Depth", "m"),
}
CASE_INFO = {
 "BTV001": "Hail-dominant",
 "BTV002": "Wind-dominant",
 "BTV003": "Mixed",
 "BTV004": "Hail-dominant / tornado",
 "BTV005": "Wind-dominant",
}
def safe_json(v):
 if isinstance(v,dict): return {k:safe_json(x) for k,x in v.items()}
 if isinstance(v,list): return [safe_json(x) for x in v]
 if isinstance(v,(float,np.floating)): return float(v) if math.isfinite(float(v)) else None
 if isinstance(v,(int,np.integer)): return int(v)
 return v
def main():
 ap=argparse.ArgumentParser()
 ap.add_argument("--input",type=Path,required=True)
 ap.add_argument("--out-dir",type=Path,required=True)
 args=ap.parse_args(); args.out_dir.mkdir(parents=True,exist_ok=True)
 df=pd.read_csv(args.input)
 required=["case_id","site","valid_time_utc"]
 miss=[c for c in required if c not in df.columns]
 if miss: raise SystemExit(f"Missing required columns: {miss}")
 df["valid_time_utc"]=pd.to_datetime(df.valid_time_utc,utc=True,errors="coerce")
 df["hour_utc"]=df.valid_time_utc.dt.hour
 case_summary=[]
 site_summary=[]
 hourly=[]
 for case,g in df.groupby("case_id"):
  for col,(label,unit) in PARAMS.items():
   if col not in g: continue
   vals=pd.to_numeric(g[col],errors="coerce")
   case_summary.append({"case_id":case,"case_characterization":CASE_INFO.get(case,"Unclassified"),"parameter":col,"label":label,"unit":unit,"n":int(vals.notna().sum()),"mean":float(vals.mean()) if vals.notna().any() else None,"median":float(vals.median()) if vals.notna().any() else None})
   for site,sg in g.groupby("site"):
    sv=pd.to_numeric(sg[col],errors="coerce")
    site_summary.append({"case_id":case,"site":site,"parameter":col,"n":int(sv.notna().sum()),"mean":float(sv.mean()) if sv.notna().any() else None,"median":float(sv.median()) if sv.notna().any() else None})
   for hour,hg in g.groupby("hour_utc"):
    hv=pd.to_numeric(hg[col],errors="coerce")
    hourly.append({"case_id":case,"hour_utc":int(hour),"parameter":col,"n":int(hv.notna().sum()),"mean":float(hv.mean()) if hv.notna().any() else None})
 pd.DataFrame(case_summary).to_csv(args.out_dir/"phase4_case_comparison.csv",index=False)
 pd.DataFrame(site_summary).to_csv(args.out_dir/"phase4_site_comparison.csv",index=False)
 pd.DataFrame(hourly).to_csv(args.out_dir/"phase4_hourly_evolution.csv",index=False)
 # Mean case comparison panels: independent plots with readable axes.
 plot_params=["sbcape_jkg","mlcape_100hpa_jkg","mucape_300hpa_jkg","pwat_mm","shear_0_6km_kt","lapse_0_3km_c_per_km","lapse_700_500_c_per_km"]
 for col in plot_params:
  if col not in df: continue
  means=df.groupby("case_id")[col].mean().dropna()
  if means.empty: continue
  label,unit=PARAMS[col]
  fig,ax=plt.subplots(figsize=(9,5))
  means.plot(kind="bar",ax=ax)
  ax.set_title(f"Pilot-case mean: {label}")
  ax.set_ylabel(unit); ax.set_xlabel("Case")
  ax.grid(axis="y",alpha=.25); fig.tight_layout()
  fig.savefig(args.out_dir/f"case_mean_{col}.png",dpi=160); plt.close(fig)
 # Hourly environmental evolution at KBTV for a selected suite.
 if "KBTV" in df.site.unique():
  for col in ["sbcape_jkg","mucape_300hpa_jkg","pwat_mm","shear_0_6km_kt"]:
   if col not in df: continue
   fig,ax=plt.subplots(figsize=(10,5))
   for case,g in df[df.site=="KBTV"].groupby("case_id"):
    series=g.groupby("hour_utc")[col].mean()
    ax.plot(series.index,series.values,marker="o",label=case)
   ax.set_title(f"KBTV hourly evolution: {PARAMS[col][0]}")
   ax.set_xlabel("Hour UTC"); ax.set_ylabel(PARAMS[col][1]); ax.grid(alpha=.25); ax.legend()
   fig.tight_layout(); fig.savefig(args.out_dir/f"kb tv_hourly_{col}.png".replace(" ",""),dpi=160); plt.close(fig)
 report={"rows":int(len(df)),"case_count":int(df.case_id.nunique()),"site_count":int(df.site.nunique()),"times_per_case_site_median":int(df.groupby(["case_id","site"]).valid_time_utc.nunique().median()),"case_characterizations":CASE_INFO,"generated_csv":["phase4_case_comparison.csv","phase4_site_comparison.csv","phase4_hourly_evolution.csv"],"plots":int(len(list(args.out_dir.glob("*.png"))))}
 (args.out_dir/"phase4_report.json").write_text(json.dumps(safe_json(report),indent=2,allow_nan=False))
 print(json.dumps(report,indent=2))
if __name__=="__main__": main()
