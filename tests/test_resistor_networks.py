import unittest

import numpy as np

from serdes_flow import resistor_networks as rn


class ResistorNetworksTest(unittest.TestCase):
    def test_inverse_length_term_is_not_a_constant_head(self):
        lengths=np.array([.5,1,2,4,8]);coeff=[130.,112.,20.]
        result,error=rn.fit(lengths,np.array([rn.resistance(l,coeff) for l in lengths]))
        np.testing.assert_allclose(result,coeff,atol=1e-10)
        self.assertLess(error,1e-10)

    def test_impossible_network_is_rejected(self):
        self.assertIsNone(rn.parallel(50.,4,[130.,112.,20.]))
        self.assertIsNone(rn.parallel(120.,1,[130.,112.,20.]))

    def test_legal_root_and_grid(self):
        plan=rn.parallel(50.,6,[130.,112.,20.])
        self.assertGreaterEqual(plan['length_um'],.5)
        self.assertAlmostEqual(plan['length_um']/.01,round(plan['length_um']/.01),places=9)
        self.assertLess(abs(plan['relative_error']),.002)

    def test_distinct_parallel_devices(self):
        plan=rn.parallel(50.,6,[130.,112.,20.])
        text=rn.instances('term','vdd','out','vss',plan)
        self.assertEqual(len(text.splitlines()),6)
        self.assertEqual(len(set(line.split()[0] for line in text.splitlines())),6)
        self.assertTrue(all('vdd out vss' in line for line in text.splitlines()))

    def test_bad_calibration_and_counts_fail(self):
        with self.assertRaises(ValueError):rn.fit([1,1,1],[1,1,1])
        with self.assertRaises(ValueError):rn.parallel(50,0,[130,112,20])
        with self.assertRaises(ValueError):rn.parallel(50,2,[130,112,-20])


if __name__=='__main__':unittest.main()
