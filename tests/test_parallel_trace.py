import importlib.util

from serdes_flow.project import ROOT

spec = importlib.util.spec_from_file_location('parallel_trace', ROOT/'analog/tx/input_register/tb/full_serializer/trace.py')
trace = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trace)


def test_internal_observation_keeps_data_and_clock_in_circuit_identity():
    original = '\n'.join(['same circuit', '.lib "pdk" fs', '.include "cell.spice"',
                          'Vd0 d0 0 PWL(0 0 1n 1.65)', 'Vclock ck 0 PULSE(0 1.65 1n 20p 20p 1n 2n)',
                          'Cload out 0 2f', '.save v(out)', '.control', 'tran 2p 120n 8n 2p',
                          'write waveforms.raw v(out)', 'quit', '.endc', '.end'])
    observed = trace.instrument(original)
    assert trace.circuit_signature(observed) == trace.circuit_signature(original)
    for old, new in [('1n 1.65)', '1n 1.8)'), ('Cload out 0 2f', 'Cload out 0 5f'),
                     ('PULSE(0 1.65', 'PULSE(0 1.8')]:
        assert trace.circuit_signature(observed.replace(old,new)) != trace.circuit_signature(original)
