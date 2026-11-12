import unittest

import numpy as np

from serdes_flow import poly_geometry as poly


class SignedPolyGeometryTest(unittest.TestCase):
    def test_negative_contact_coefficient_and_grid_solution(self):
        lengths = np.array([.5, 1., 2., 4., 8., 16.])
        curve = poly.calibrate(lengths, poly.value(lengths, [68., 56., -.06]))
        self.assertLess(curve['coefficients_ohm'][2], 0)
        planned = poly.parallel(52., 12, curve)
        self.assertIsNotNone(planned)
        self.assertLess(abs(planned['relative_error']), .001)
        self.assertAlmostEqual(planned['length_um'] / .01, round(planned['length_um'] / .01))

    def test_geometry_does_not_extrapolate_past_calibration(self):
        curve = dict(coefficients_ohm=[130., 113., 19.], domain_um=[.5, 8.])
        self.assertIsNone(poly.parallel(52., 24, curve))
        self.assertIsNone(poly.parallel(52., 4, curve))
        self.assertIsNotNone(poly.parallel(52., 8, curve))

    def test_positive_contact_uses_increasing_root(self):
        curve = dict(coefficients_ohm=[1., 1., 4.], domain_um=[.5, 20.])
        planned = poly.parallel(6., 1, curve)
        self.assertAlmostEqual(planned['length_um'], 4.)

    def test_distinct_physical_instances_and_body(self):
        curve = dict(coefficients_ohm=[68., 56., -.06], domain_um=[.5, 32.])
        planned = poly.parallel(52., 12, curve)
        lines = poly.instances('term', 'vdd', 'out', 'vss', planned, '5p73').splitlines()
        self.assertEqual(len(lines), 12)
        self.assertEqual(len({line.split()[0] for line in lines}), 12)
        self.assertTrue(all('vdd out vss sky130_fd_pr__res_high_po_5p73' in line for line in lines))


if __name__ == '__main__': unittest.main()
