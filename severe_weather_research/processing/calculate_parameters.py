#!/usr/bin/env python3
"""Phase 2: hourly ERA5 environmental diagnostics from pilot profiles.

Diagnostics are research-derived from nearest-grid ERA5 pressure profiles.
Surface-based values use the lowest available pressure level, not station observations.
"""
from __future__ import annotations
import argparse, json
from pathlib import Path
import numpy as np
import pandas as pd

def hypsometric_heights(p_hpa, t_c, td_c):
    """Approximate relative heights (AGL proxy), using virtual temperature."""
    p=np.asarray(p_hpa,float); t=np.asarray(t_c,float); td=np.asarray(td_c,float)
    order=np.argsort(p)[::-1]
    p,t,td=p[order],t[order],td[order]
    from metpy.calc import mixing_ratio, saturation_vapor_pressure, virtual_temperature
    from metpy.units import units
    vapor_pressure=saturation_vapor_pressure(td*units.degC)
    mixing_ratio_value=mixing_ratio(vapor_pressure,p*units.hPa)
    tv=virtual_temperature(t*units.degC,mixing_ratio_value).to('kelvin').magnitude
    z=np.zeros_like(p); Rd=287.05; g=9.80665
    for i in range(1,len(p)):
        z[i]=z[i-1]+Rd*((tv[i]+tv[i-1])/2)/g*np.log(p[i-1]/p[i])
    return p,t,td,z,order

def interp_at_height(z, values, target):
    z=np.asarray(z,float); values=np.asarray(values,float)
    mask=np.isfinite(z)&np.isfinite(values); z=z[mask]; values=values[mask]
    if len(z)<2 or not np.isfinite(target) or target<z.min() or target>z.max(): return np.nan
    order=np.argsort(z)
    return float(np.interp(target,z[order],values[order]))

def safe_float(value):
    try:
        x=float(np.asarray(value).squeeze())
        return x if np.isfinite(x) else np.nan
    except Exception: return np.nan

def diagnostics(group):
    from metpy.calc import surface_based_cape_cin, mixed_layer_cape_cin, most_unstable_cape_cin, lcl, precipitable_water
    from metpy.units import units
    g=group.sort_values('pressure_hpa',ascending=False)
    p=g.pressure_hpa.to_numpy(float); t=g.temperature_c.to_numpy(float); td=g.dewpoint_c.to_numpy(float)
    u=g.u_ms.to_numpy(float); v=g.v_ms.to_numpy(float)
    valid=np.isfinite(p)&np.isfinite(t)&np.isfinite(td)&np.isfinite(u)&np.isfinite(v)
    p,t,td,u,v=p[valid],t[valid],td[valid],u[valid],v[valid]
    out={}
    if len(p)<8: out['profile_error']='fewer than 8 complete levels'; return out
    # CAPE/CIN convenience functions perform parcel selection and parcel-profile integration.
    try:
        cape,cin=surface_based_cape_cin(p*units.hPa,t*units.degC,td*units.degC)
        out['sbcape_jkg']=safe_float(cape.to('J/kg').magnitude); out['sbcin_jkg']=safe_float(cin.to('J/kg').magnitude)
    except Exception as e: out['sbcape_jkg']=np.nan; out['sbcin_jkg']=np.nan; out['sbcape_error']=str(e)[:200]
    try:
        cape,cin=mixed_layer_cape_cin(p*units.hPa,t*units.degC,td*units.degC,depth=100*units.hPa)
        out['mlcape_100hpa_jkg']=safe_float(cape.to('J/kg').magnitude); out['mlcin_100hpa_jkg']=safe_float(cin.to('J/kg').magnitude)
    except Exception as e: out['mlcape_100hpa_jkg']=np.nan; out['mlcin_100hpa_jkg']=np.nan; out['mlcape_error']=str(e)[:200]
    try:
        cape,cin=most_unstable_cape_cin(p*units.hPa,t*units.degC,td*units.degC,depth=300*units.hPa)
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
        p_sorted,t_sorted,td_sorted,z,order=hypsometric_heights(p,t,td)
        u_sorted=u[order]; v_sorted=v[order]
        out['profile_top_agl_m']=float(np.nanmax(z))
        for km in (1,3,6):
            ut=interp_at_height(z,u_sorted,km*1000); vt=interp_at_height(z,v_sorted,km*1000)
            if np.isfinite(ut) and np.isfinite(vt):
                out[f'shear_0_{km}km_kt']=float(np.hypot(ut-u_sorted[0],vt-v_sorted[0])*1.94384)
            else: out[f'shear_0_{km}km_kt']=np.nan
        t3=interp_at_height(z,t_sorted,3000)
        out['lapse_0_3km_c_per_km']=float((t_sorted[0]-t3)/3) if np.isfinite(t3) else np.nan
        z500=interp_at_height(z,p_sorted,500); z700=interp_at_height(z,p_sorted,700)
        temp500=interp_at_height(z,t_sorted,z500) if np.isfinite(z500) else np.nan
        temp700=interp_at_height(z,t_sorted,z700) if np.isfinite(z700) else np.nan
        out['lapse_700_500_c_per_km']=float((temp700-temp500)/((z500-z700)/1000)) if np.isfinite(temp500) and np.isfinite(temp700) and z500>z700 else np.nan
        def crossing_height(temp_target):
            for i in range(len(t_sorted)-1):
                if (t_sorted[i]-temp_target)*(t_sorted[i+1]-temp_target)<=0:
                    if t_sorted[i+1]==t_sorted[i]: return float((z[i]+z[i+1])/2)
                    return float(z[i]+(temp_target-t_sorted[i])*(z[i+1]-z[i])/(t_sorted[i+1]-t_sorted[i]))
            return np.nan
        out['freezing_level_agl_m']=crossing_height(0)
        z10=crossing_height(-10); z30=crossing_height(-30)
        out['hail_growth_layer_10_to_30c_depth_m']=float(abs(z30-z10)) if np.isfinite(z10) and np.isfinite(z30) else np.nan
    except Exception as e: out['height_based_error']=str(e)[:200]
    return out

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--profiles',type=Path,required=True)
    ap.add_argument('--out-dir',type=Path,required=True)
    ap.add_argument('--fail-on-errors',action='store_true',help='Exit nonzero when core diagnostics have widespread failures.')
    args=ap.parse_args()
    args.out_dir.mkdir(parents=True,exist_ok=True); df=pd.read_csv(args.profiles)
    key=['case_id','date','site','valid_time_utc','grid_lat','grid_lon']; rows=[]; errors=[]
    for k,g in df.groupby(key,sort=True):
        rec=dict(zip(key,k)); rec.update(diagnostics(g)); rows.append(rec)
        for col in [c for c in rec if c.endswith('_error')]:
            errors.append({'key':dict(zip(key,k)),'field':col,'error':rec[col]})
    out=pd.DataFrame(rows); out.to_csv(args.out_dir/'hourly_environmental_parameters.csv',index=False)
    core=['sbcape_jkg','mlcape_100hpa_jkg','mucape_300hpa_jkg','pwat_mm','lcl_pressure_hpa']
    valid_rates={c:float(out[c].notna().mean()) if c in out else 0.0 for c in core}
    report={'profile_rows':len(df),'diagnostic_rows':len(out),'cases':sorted(df.case_id.unique().tolist()),'sites':sorted(df.site.unique().tolist()),'time_count_per_case_site':int(df.groupby(['case_id','site']).valid_time_utc.nunique().median()),'pressure_levels_count':int(df.pressure_hpa.nunique()),'diagnostic_errors':errors,'valid_rates':valid_rates,'parameter_columns':list(out.columns)}
    (args.out_dir/'parameter_report.json').write_text(json.dumps(report,indent=2,default=str))
    print(json.dumps({'diagnostic_rows':len(out),'errors':len(errors),'valid_rates':valid_rates,'columns':list(out.columns)},indent=2))
    if args.fail_on_errors and any(rate < 0.90 for rate in valid_rates.values()):
        raise SystemExit('Diagnostic QC failed: one or more core parameters have <90% valid coverage.')
if __name__=='__main__': main()
