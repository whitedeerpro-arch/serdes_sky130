import numpy as np
from serdes_flow.feedback import middlebrook, unity_crossings


def test_dual_injection_recovers_loaded_unilateral_loop():
    # Voltage injection alone includes the impedance ratio r; current injection
    # supplies the correction. This is independent of any LDO netlist.
    f=np.logspace(0,10,501);s=2j*np.pi*f
    loop=3000/(1+s/(2*np.pi*1000))/(1+s/(2*np.pi*20e6))
    r=(1+s/(2*np.pi*1e6))*.02
    tv=loop+r;ti=(1+loop)/r
    np.testing.assert_allclose(middlebrook(tv,ti),loop/(1+r),rtol=1e-12,atol=1e-12)


def test_all_unity_crossings_are_retained():
    rows=unity_crossings([1,10,100,1000],np.array([10,.1,.2,2])*np.exp(-1j*np.pi/2))
    assert [x['direction'] for x in rows]==['down','up']
    np.testing.assert_allclose([x['pm_deg'] for x in rows],[90,90])
