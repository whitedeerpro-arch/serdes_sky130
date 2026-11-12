import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

from serdes_flow import poly_geometry, project

FILE = project.ROOT / 'analog/common/devices/tb/passive_card/wide_load_card.py'
spec = importlib.util.spec_from_file_location('test_wide_card', FILE)
card = importlib.util.module_from_spec(spec); spec.loader.exec_module(card)


class WideCardTest(unittest.TestCase):
    def test_reference_string_is_connected_and_uses_distinct_series_devices(self):
        values = {}
        coefficients = {'1p41': [256., 230., 10.], '2p85': [130., 113., 19.], '5p73': [68., 56., -.06]}
        for width, coeff in coefficients.items():
            lengths = card.LENGTHS['reference' if width == '1p41' else 'short']
            for i, length in enumerate(lengths): values[f'r_cal_{width}_{i}'] = poly_geometry.value(length, coeff)
        values.update({'r_generic' + str(r): float(r) for r in card.TARGETS})
        values.update(r_ref112=112000., r_ref16=12480.)
        plan = dict(minimum_lengths_um={w: .5 for w in coefficients}, current_boundary=dict(peak_a=.006619))
        with patch.object(card.scalar_raw, 'read', return_value=values):
            model = card.make_networks(plan, Path('/tmp/calibration_fixture'))
        reference = next(p for p in model['parts'] if p['id'] == 'reference_fixed_s8')
        devices = [line.split() for line in reference['instance'].splitlines()]
        self.assertEqual(len(devices), 9)
        self.assertEqual(devices[0][1], 'rail')
        self.assertEqual(devices[-1][2], 'out_reference_fixed_s8')
        self.assertTrue(all(a[2] == b[1] for a, b in zip(devices[:-1], devices[1:])))
        self.assertTrue(all(d[3] == '0' and d[4] == 'sky130_fd_pr__res_high_po_1p41' for d in devices))
        self.assertEqual(len({d[0] for d in devices}), 9)
        self.assertLess(model['curves']['5p73']['coefficients_ohm'][2], 0)

    def test_reference_drop_and_LF_RF_measurements_are_separate(self):
        parts = [dict(id='load', kind='fixed_load', instance='Xload rail out_load 0 Rmodel'),
                 dict(id='ref', kind='reference_string_surrogate', instance='Xref rail out_ref 0 Rmodel')]
        text = card.deck(parts, 'tt', '/tmp/explicit_library.spice')
        self.assertIn('alter Vport_ref dc=0.57\nop', text)
        self.assertIn('alter Vport_load dc=1.79', text)
        self.assertEqual(text.count('ac lin 1 1 1'), 12)
        self.assertEqual(text.count('ac lin 1 2000000000 2000000000'), 12)
        self.assertIn('t-40_d10_lo.raw', text)
        self.assertIn('t85_d500_hi.raw', text)


if __name__ == '__main__': unittest.main()
