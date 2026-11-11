import unittest

import numpy as np

from serdes_flow import clock_transfer


class ClockTransferTest(unittest.TestCase):
    def setUp(self):
        self.t=np.linspace(0,5e-9,20001)
        self.x=np.sin(2*np.pi*(self.t-20e-12)/500e-12)
        self.y=np.sin(2*np.pi*(self.t-100e-12)/500e-12)

    def test_full_core_window_and_latency(self):
        result=clock_transfer.analyze(self.t,self.x,self.y,1e-9,4.2e-9,200e-12,minimum_pp_v=.15)
        self.assertTrue(result['edges_complete']);self.assertTrue(result['clock_qualified'])
        for row in result['propagation'].values():self.assertAlmostEqual(row['mean_s']/1e-12,80.,places=6)

    def test_missing_first_or_last_required_cycle_fails(self):
        for a,b in ((1.09e-9,1.59e-9),(4.09e-9,4.59e-9)):
            y=self.y.copy();y[(self.t>=a)&(self.t<=b)]=-1
            with self.assertRaises(ValueError):clock_transfer.analyze(self.t,self.x,y,1e-9,4.2e-9,200e-12)

    def test_small_periodic_noise_is_not_qualified_clock(self):
        result=clock_transfer.analyze(self.t,self.x,self.y*1e-6,1e-9,4.2e-9,200e-12,minimum_pp_v=.15)
        self.assertTrue(result['edges_complete']);self.assertFalse(result['amplitude_pass']);self.assertFalse(result['clock_qualified'])

    def test_truncated_response_window_fails(self):
        with self.assertRaises(ValueError):clock_transfer.analyze(self.t,self.x,self.y,1e-9,4.9e-9,200e-12)


if __name__=='__main__':unittest.main()
