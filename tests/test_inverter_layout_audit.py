"""Regression for unused exported ports and source/drain-reversed folded fingers."""
import importlib.util

from serdes_flow.project import ROOT

spec = importlib.util.spec_from_file_location('inverter_layout_audit', ROOT / 'verification/layout_training/inverter_audit.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def measure(tmp_path, body):
    p = tmp_path / 'cell.spice'
    p.write_text('.subckt inv_std d g vdd vss\n' + body + '\n.ends\n')
    return module.audit(p, 'inv_std')


def test_normal_inverter_ports_and_total_widths(tmp_path):
    r = measure(tmp_path, 'Xn d g vss vss sky130_fd_pr__nfet_01v8 w=4 l=.15\n'
                'Xp d g vdd vdd sky130_fd_pr__pfet_01v8 w=8 l=.15')
    assert r['status'] == 'pass' and r['total_w_um'] == {'n': 4, 'p': 8}
    assert len(r['port_usage']['d']) == 2


def test_folded_fingers_keep_total_width_and_count_actual_output_terminal(tmp_path):
    r = measure(tmp_path,
        'Xn0 d g vss vss sky130_fd_pr__nfet_01v8 w=2 l=.15 ad=.85 pd=2.85\n'
        'Xn1 vss g d vss sky130_fd_pr__nfet_01v8 w=2 l=.15 as=.85 ps=2.85\n'
        'Xp0 d g vdd vdd sky130_fd_pr__pfet_01v8 w=4 l=.15 ad=1.7 pd=4.85\n'
        'Xp1 vdd g d vdd sky130_fd_pr__pfet_01v8 w=4 l=.15 as=1.7 ps=4.85')
    assert r['status'] == 'pass'
    assert r['output_junction']['p']['output_diffusion_area_um2'] == 3.4
    assert r['output_junction']['n']['output_diffusion_perimeter_um'] == 5.7


def test_unused_external_pin_fails_even_when_internal_inverter_exists(tmp_path):
    r = measure(tmp_path, 'Xn internal g vss vss sky130_fd_pr__nfet_01v8 w=4 l=.15\n'
                'Xp internal g vdd vdd sky130_fd_pr__pfet_01v8 w=8 l=.15')
    assert r['status'] == 'fail' and 'unused exported port: d' in r['errors']
    assert r['output_junction']['n']['output_diffusion_area_um2'] is None


def test_alias_views_remain_ungraded_instead_of_inventing_connectivity(tmp_path):
    r = measure(tmp_path, '.connect d internal\n'
                'Xn internal g vss vss sky130_fd_pr__nfet_01v8 w=4 l=.15')
    assert r['status'] == 'ungraded'
