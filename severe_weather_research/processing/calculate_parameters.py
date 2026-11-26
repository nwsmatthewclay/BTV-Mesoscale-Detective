#!/usr/bin/env python3
"""Phase 2: calculate hourly ERA5 environmental diagnostics from pilot profiles.
All diagnostics are research-derived from nearest-grid ERA5 pressure profiles.
Surface-based values use the lowest available pressure level, not station observations.
"""
from __future__ import annotations
import argparse, json
from pathlib import Path
import numpy as np
import pandas as pd

def hypsometric_heights(p_hpa, t_c, td_c):
    """Approximate relative heights from hypsometric layer thicknesses (lowest level=0)."""
    p=np.asarray(p_hpa,float); t=np.asarray(t_c,float); td=np.asarray(td_c,float)
    order=np.argsort(p)[::-1]; p=p[order]; t=t[order]; td=td[order]
    from metpy.calc import mixing_ratio_from_dewpoint, virtual_temperature
    from metpy.units import units
    mixing_ratio=mixing_ratio_from_dewpoint(p*units.hPa,td*units.degC)
    tv=virtual_temperature(t*units.degC,mixing_ratio).to('kelvin').magnitude
    z=np.zeros_like(p); Rd=287.05; g=9.80665
    for i in range(1,len(p)):
        z[i]=z[i-1]+Rd*((tv[i]+tv[i-1])/2)/g*np.log(p[i-1]/p[i])
    return p,t,td,z,order

def interp_at_height(z, values, target):
    z=np.asarray(z,float); values=np.asarray(values,float)
    mask=np.isfinite(z)&np.isfinite(values); z=z[mask]; values=values[mask]
    if len(z)<2 or not np.isfinite(target) or target<z.min() or target>z.max(): return np.nan
    return float(np.interp(target,z,values))

def safe_float(value):
    try:
        x=float(np.asarray(value).squeeze())
        return x if np.isfinite(x) else np.nan
    except Exception: return np.nan

def diagnostics(group):
    from metpy.calc import parcel_profile, cape_cin, mixed_layer, most_unstable, lcl, precipitable_water
    from metpy.units import units
    g=group.sort_values('pressure_hpa',ascending=False)
    p=g.pressure_hpa.to_numpy(float); t=g.temperature_c.to_numpy(float); td=g.dewpoint_c.to_numpy(float)
    u=g.u_ms.to_numpy(float); v=g.v_ms.to_numpy(float)
    valid=np.isfinite(p)&np.isfinite(t)&np.isfinite(td)&np.isfinite(u)&np.isfinite(v)
    p,t,td,u,v=p[valid],t[valid],td[valid],u[valid],v[valid]
    out={}
    if len(p)<8: return out
    try:
        prof=parcel_profile(p*units.hPa,t[0]*units.degC,td[0]*units.degC)
        cape,cin=cape_cin(p*units.hPa,t*units.degC,td*units.degC,prof)
        out['sbcape_jkg']=safe_float(cape.to('J/kg').magnitude); out['sbcin_jkg']=safe_float(cin.to('J/kg').magnitude)
    except Exception as e: out['sbcape_jkg']=np.nan; out['sbcin_jkg']=np.nan; out['sbcape_error']=str(e)[:200]
    try:
        ml_t,ml_td=mixed_layer(p*units.hPa,t*units.degC,td*units.degC,depth=100*units.hPa)
        ml_prof=parcel_profile(p*units.hPa,ml_t,ml_td)
        cape,cin=cape_cin(p*units.hPa,t*units.degC,td*units.degC,ml_prof)
        out['mlcape_100hpa_jkg']=safe_float(cape.to('J/kg').magnitude); out['mlcin_100hpa_jkg']=safe_float(cin.to('J/kg').magnitude)
    except Exception as e: out['mlcape_100hpa_jkg']=np.nan; out['mlcin_100hpa_jkg']=np.nan; out['mlcape_error']=str(e)[:200]
    try:
        mu_p,mu_t,mu_td=most_unstable(p*units.hPa,t*units.degC,td*units.degC,depth=300*units.hPa)
        mu_prof=parcel_profile(p*units.hPa,mu_t,mu_td)
        cape,cin=cape_cin(p*units.hPa,t*units.degC,td*units.degC,mu_prof)
        out['mucape_300hpa_jkg']=safe_float(cape.to('J/kg').magnitude); out['mucin_300hpa_jkg']=safe_float(cin.to('J/kg').magnitude)
    except Exception as e: out['mucape_300hpa_jkg']=np.nan; out['mucin_300hpa_jkg']=np.nan; out['mucape_error']=str(e)[:200]
    try:
        lcl_p,lcl_t=lcl(p[0]*units.hPa,t[0]*units.degC,td[0]*units.degC)
        out['lcl_pressure_hpa']=safe_float(lcl_p.to('hPa').magnitude); out['lcl_temperature_c']=safe_float(lcl_t.to('degC').magnitude)
    except Exception as e: out['lcl_pressure_hpa']=np.nan; out['lcl_error']=str(e)[:200]
    try:
        pw=precipitable_water(p*units.hPa,td*units.degC)
        out['pwat_mm']=safe_float(pw.to('mm').magnitude)
    except Exception as e: out['pwat_mm']=np.nan; out['pwat_error']=str(e)[:200]
    try:
        p,t,td,z,order=hypsometric_heights(p,t,td); u=u[order]; v=v[order]
        out['profile_top_agl_m']=float(np.nanmax(z))
        for km in (1,3,6):
            ut=interp_at_height(z,u,km*1000); vt=interp_at_height(z,v,km*1000)
            if np.isfinite(ut) and np.isfinite(vt):
                out[f'shear_0_{km}km_kt']=float(np.hypot(ut-u[0],vt-v[0])*1.94384)
            else: out[f'shear_0_{km}km_kt']=np.nan
        t3=interp_at_height(z,t,3000)
        out['lapse_0_3km_c_per_km']=float((t[0]-t3)/3) if np.isfinite(t3) else np.nan
        z500=interp_at_height(z,p,500); z700=interp_at_height(z,p,700)
        temp500=interp_at_height(z,t,z500) if np.isfinite(z500) else np.nan
        temp700=interp_at_height(z,t,z700) if np.isfinite(z700) else np.nan
        out['lapse_700_500_c_per_km']=float((temp700-temp500)/((z500-z700)/1000)) if np.isfinite(temp500) and np.isfinite(temp700) and z500>z700 else np.nan
        def crossing_height(temp_target):
            for i in range(len(t)-1):
                if (t[i]-temp_target)*(t[i+1]-temp_target)<=0:
                    if t[i+1]==t[i]: return float((z[i]+z[i+1])/2)
                    return float(z[i]+(temp_target-t[i])*(z[i+1]-z[i])/(t[i+1]-t[i]))
            return np.nan
        out['freezing_level_agl_m']=crossing_height(0)
        z10=crossing_height(-10); z30=crossing_height(-30)
        out['hail_growth_layer_10_to_30c_depth_m']=float(abs(z30-z10)) if np.isfinite(z10) and np.isfinite(z30) else np.nan
    except Exception as e: out['height_based_error']=str(e)[:200]
    return out

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--profiles',type=Path,required=True); ap.add_argument('--out-dir',type=Path,required=True); args=ap.parse_args()
    args.out_dir.mkdir(parents=True,exist_ok=True); df=pd.read_csv(args.profiles)
    key=['case_id','date','site','valid_time_utc','grid_lat','grid_lon']; rows=[]; errors=[]
    for k,g in df.groupby(key,sort=True):
        rec=dict(zip(key,k)); rec.update(diagnostics(g)); rows.append(rec)
        for col in [c for c in rec if c.endswith('_error')]: errors.append({'key':dict(zip(key,k)),'field':col,'error':rec[col]})
    out=pd.DataFrame(rows); out.to_csv(args.out_dir/'hourly_environmental_parameters.csv',index=False)
    report={'profile_rows':len(df),'diagnostic_rows':len(out),'cases':sorted(df.case_id.unique().tolist()),'sites':sorted(df.site.unique().tolist()),'time_count_per_case_site':int(df.groupby(['case_id','site']).valid_time_utc.nunique().median()),'pressure_levels_count':int(df.pressure_hpa.nunique()),'diagnostic_errors':errors,'parameter_columns':list(out.columns)}
    (args.out_dir/'parameter_report.json').write_text(json.dumps(report,indent=2,default=str))
    print(json.dumps({'diagnostic_rows':len(out),'errors':len(errors),'columns':list(out.columns)},indent=2))
if __name__=='__main__': main()
