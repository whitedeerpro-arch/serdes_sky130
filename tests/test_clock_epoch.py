"""Startup diagnostics must change only their declared boundary conditions."""
import importlib.util
import re

import pytest
from serdes_flow.project import ROOT

spec=importlib.util.spec_from_file_location('epoch_test',ROOT/'analog/tx/input_register/tb/full_serializer/clock_epoch.py')
epoch=importlib.util.module_from_spec(spec);spec.loader.exec_module(epoch)

BASE='''fixture
Vdd vdd 0 1.65
Vd15 d15 0 0
Xout2g e3p e3n c2gp c2gn vbias vdd 0 cell wn=32 wt=16 rload=240
.ic v(xclocks.q0p)=1.3 v(xclocks.q0n)=1.6
.save v(c2gp)
.control
tran 2p 120n 8n 2p
write waveforms.raw v(c2gp)
quit
.endc
.end
'''


def test_complete_seed_preserves_circuit_and_original_state():
    result=epoch.render(BASE,masters=True)
    assert epoch.circuit_key(BASE)==epoch.circuit_key(result)
    strip=lambda text:re.sub(r'^\.ic .*$', '',text.split('.control')[0],flags=re.M)
    assert strip(BASE)==strip(result)
    assert 'v(xclocks.q0p)=1.3 v(xclocks.q0n)=1.6' in result
    for bit in range(3):
        assert f'v(xclocks.xcnt.m{bit}p)=1.3' in result
        assert f'v(xclocks.xcnt.m{bit}n)=1.6' in result
    assert 'tran 2p 18n 0 2p' in result


def test_metadata_adds_only_independent_sources():
    result=epoch.render(BASE,metadata=True)
    assert epoch.circuit_key(BASE)==epoch.circuit_key(result)
    added=[line for line in result.splitlines() if line.startswith('Vguard_')]
    assert len(added)==4
    assert all(line.endswith(' 0 0') for line in added)
    assert next(line for line in BASE.splitlines() if line.startswith('Xout2g ')) in result


def test_diagnostic_refuses_ambiguous_source_layout():
    with pytest.raises(ValueError,match='already contains metadata'):
        epoch.render(BASE.replace('Vd15','Vguard_a guard_a 0 0\nVd15'),metadata=True)
    with pytest.raises(ValueError,match='initial-condition'):
        epoch.render(BASE.replace('.save','.ic v(other)=0\n.save'),masters=True)
