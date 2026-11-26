#!/usr/bin/env python3
"""First-pass nearest-environment analog scoring for the BTV severe-weather sample.

Scores are exploratory. Case reference environments are case means across ERA5 sites
and times; no storm-report time alignment exists. Features are normalized using
robust sample scales (IQR, with standard-deviation fallback).
"""
from pathlib import Path
import argparse, json
import numpy as np
import pandas as pd

FEATURES={
 "sbcape_jkg":("SBCAPE",1.0),
 "mlcape_100hpa_jkg":("MLCAPE",1.0),
 "mucape_300hpa_jkg":("MUCAPE",1.0),
 "sbcin_jkg":("SBCIN",0.65),
 "mlcin_100hpa_jkg":("MLCIN",0.65),
 "pwat_mm":("PWAT",0.8),
 "shear_0_1km_kt":("0-1 km shear",1.0),
 "shear_0_3km_kt":("0-3 km shear",0.8),
 "shear_0_6km_kt":("0-6 km shear",1.0),
 "lapse_0_3km_c_per_km":("0-3 km lapse rate",0.7),
 "lapse_700_500_c_per_km":("700-500 hPa lapse rate",0.7),
 "freezing_level_agl_m":("Freezing level",0.5),
 "hail_growth_layer_10_to_30c_depth_m":("-10 to -30C layer depth",0.7),
}
def main():
 p=argparse.ArgumentParser()
 p.add_argument("--diagnostics",type=Path,required=True,help="hourly environmental diagnostics CSV")
 p.add_argument("--forecast",type=Path,required=True,help="JSON file with forecast parameter values")
 p.add_argument("--output",type=Path,required=True)
 a=p.parse_args()
 d=pd.read_csv(a.diagnostics)
 forecast=json.loads(a.forecast.read_text())
 # Case reference: pooled mean across sites and valid hours for each case.
 usable=[k for k in FEATURES if k in d.columns and k in forecast and forecast[k] is not None]
 if len(usable)<4: raise SystemExit(f"Need >=4 shared numeric features; found {usable}")
 means=d.groupby("case_id")[usable].mean(numeric_only=True)
 scales={}
 for f in usable:
  q1,q3=means[f].quantile([.25,.75]); scale=float(q3-q1)
  if not np.isfinite(scale) or scale<=0: scale=float(means[f].std(ddof=1))
  if not np.isfinite(scale) or scale<=0: scale=1.0
  scales[f]=scale
 rows=[]
 for case,row in means.iterrows():
  weighted=[]; used=[]
  for f in usable:
   target=pd.to_numeric(pd.Series([forecast[f]]),errors="coerce").iloc[0]
   val=row[f]
   if pd.notna(target) and pd.notna(val):
    z=(float(val)-float(target))/scales[f]
    weighted.append(z*z*FEATURES[f][1]); used.append(f)
  if weighted:
   distance=float(np.sqrt(sum(weighted)/sum(FEATURES[f][1] for f in used)))
   # Monotonic display score only; distance is the more interpretable metric.
   score=float(100*np.exp(-distance))
   rows.append({"case_id":case,"analog_distance":distance,"similarity_score":score,"features_used":len(used),"feature_list":";".join(used)})
 out=pd.DataFrame(rows).sort_values("analog_distance")
 a.output.parent.mkdir(parents=True,exist_ok=True); out.to_csv(a.output,index=False)
 report={"input_forecast":forecast,"features_used":usable,"normalization_scales":scales,"ranked_analogs":out.to_dict(orient="records"),"method":"Weighted root-mean-square distance across standardized case-mean features; IQR scale where available, standard deviation fallback; score=100*exp(-distance).","cautions":["Case reference means pool all sites and hours, not storm-relative timing.","ERA5 is reanalysis, not observed soundings.","Score is relative/exploratory and is not a probability.","Pilot classifications and case selections require independent report verification."]}
 a.output.with_suffix(".json").write_text(json.dumps(report,indent=2,default=str))
 print(out.to_string(index=False))
if __name__=="__main__": main()
