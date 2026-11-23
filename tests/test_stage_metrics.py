"""Telemetry and event association failures must not look like useful delays."""
import unittest

import numpy as np

from serdes_flow import stage_metrics as sm


class StageMetricsTest(unittest.TestCase):
    def setUp(self):
        self.t=np.linspace(0,5e-9,10001)
        self.y=np.sin(2*np.pi*(self.t-20e-12)/500e-12)

    def test_causal_edges_not_modulo_wrapped(self):
        out=np.sin(2*np.pi*(self.t-100e-12)/500e-12)
        measured=sm.propagation(self.t,self.y,out,1e-9,4.8e-9,200e-12)
        for row in measured.values():
            self.assertGreaterEqual(row['events'],7)
            self.assertAlmostEqual(row['mean_s']/1e-12,80,places=6)

    def test_missing_output_cycle_fails(self):
        out=np.sin(2*np.pi*(self.t-100e-12)/500e-12)
        out[(self.t>=2.1e-9)&(self.t<=2.59e-9)]=-1
        with self.assertRaises(ValueError): sm.propagation(self.t,self.y,out,1e-9,4.8e-9,200e-12)

    def test_ambiguity_and_no_clock_fail(self):
        with self.assertRaises(ValueError): sm.propagation(self.t,self.y,self.y,1e-9,4.8e-9,600e-12)
        with self.assertRaises(ValueError): sm.propagation(self.t,self.y,np.ones_like(self.y),1e-9,4.8e-9,200e-12)

    def test_time_average_interpolated_boundaries(self):
        result=sm.telemetry(np.array([0.,1.,3.]),np.array([0.,1.,3.]),.5,2.)
        self.assertAlmostEqual(result['mean'],1.25)
        with self.assertRaises(ValueError): sm.telemetry(np.array([0.,1.]),np.array([1.,1.]),.5,2.)

    def test_headroom_is_measured_not_a_hard_gate(self):
        v=np.full_like(self.t,.1)
        result=sm.headroom(self.t,v,np.zeros_like(v),v+.02,1e-9,4e-9)
        self.assertAlmostEqual(result['minimum'],-.02)
        self.assertEqual(result['fraction_below_zero'],1.)


if __name__=='__main__': unittest.main()
