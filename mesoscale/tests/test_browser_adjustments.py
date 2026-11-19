import numpy as np
from mesoscale.browser_adjustments import adjust_profile

def sample_profile():
    p=np.array([1000,950,900,850,800,750,700,650,600,550,500,450],dtype=float)
    z=np.array([0,400,800,1200,1600,2050,2500,3000,3550,4150,4800,5500],dtype=float)
    t=np.array([20,17,14,11,8,5,2,-2,-7,-13,-20,-28],dtype=float)
    td=t-4
    return {"pressure_hpa":p.tolist(),"temperature_k":(t+273.15).tolist(),"dewpoint_k":(td+273.15).tolist(),"height_agl_m":z.tolist(),"u_ms":np.linspace(2,20,p.size).tolist(),"v_ms":np.linspace(1,10,p.size).tolist(),"location":"KBTV"}

def test_adjustment_preserves_original_profile():
    source=sample_profile()
    before={k:(v.copy() if isinstance(v,list) else v) for k,v in source.items()}
    adjusted,_=adjust_profile(source,{"temperature_offset_c":2,"mixing_depth_m":1200})
    assert source==before
    assert adjusted["temperature_k"]!=source["temperature_k"]

def test_mixing_changes_thermal_and_momentum_profiles():
    source=sample_profile()
    adjusted,warnings=adjust_profile(source,{"mixing_depth_m":1600})
    for key in ("temperature_k","dewpoint_k","u_ms","v_ms"):
        assert adjusted[key]!=source[key]
    assert not warnings

def test_zero_adjustment_is_identity():
    source=sample_profile()
    adjusted,warnings=adjust_profile(source,{})
    for key in ("pressure_hpa","temperature_k","dewpoint_k","height_agl_m","u_ms","v_ms"):
        np.testing.assert_allclose(adjusted[key],source[key])
    assert not warnings
