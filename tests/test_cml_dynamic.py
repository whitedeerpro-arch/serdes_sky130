import unittest

import numpy as np

from serdes_flow import cml_dynamic


class DynamicCMLTest(unittest.TestCase):
    def setUp(self):
        self.t = np.arange(0, 2.001e-9, 1e-12)
        self.cm = np.full_like(self.t, 1.55)
        self.vdd = np.full_like(self.t, 1.8)
        self.p = [.25, 2., 10., 20., 0., 0., 0.]

    def evaluate(self, d, p=None, cm=None):
        return cml_dynamic.drive(self.t, d, self.cm if cm is None else cm, self.vdd,
                                 self.p if p is None else p, cm_ref=1.55, d2_ref=0.)

    def test_constant_input_has_expected_polarity_and_common_mode(self):
        d, cm = self.evaluate(np.full_like(self.t, .1))
        np.testing.assert_allclose(d, .25 * np.tanh(.8), atol=1e-14)
        np.testing.assert_allclose(cm, 1.675, atol=1e-14)

    def test_step_cannot_move_before_explicit_delay(self):
        x = np.where(self.t < 1e-9, -.1, .1)
        d, _ = self.evaluate(x)
        np.testing.assert_allclose(d[self.t < 1.018e-9], d[0], atol=1e-13)
        self.assertGreater(d[-1], 0.)

    def test_common_mode_changes_tail_saturation_and_is_not_clamped(self):
        p = self.p.copy(); p[4] = 4.
        _, high = self.evaluate(np.full_like(self.t, .1), p)
        _, low = self.evaluate(np.full_like(self.t, .1), p, self.cm - .025)
        self.assertGreater(low[-1], high[-1])
        # An unphysical prediction must remain visible to the caller.
        p[4] = 20.
        d, cm = self.evaluate(np.full_like(self.t, .5), p, self.cm + .3)
        self.assertTrue(np.any(cm + abs(d) / 2 > self.vdd) or np.any(cm - abs(d) / 2 < 0))

    def test_invalid_grid_and_parameters_fail(self):
        t = self.t.copy(); t[20] += .1e-12
        with self.assertRaises(ValueError):
            cml_dynamic.drive(t, t * 0, self.cm, self.vdd, self.p, cm_ref=1.55, d2_ref=0.)
        p = self.p.copy(); p[2] = 0.
        with self.assertRaises(ValueError): self.evaluate(self.t * 0, p)


if __name__ == '__main__': unittest.main()
