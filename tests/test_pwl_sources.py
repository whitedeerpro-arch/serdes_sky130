import unittest

import numpy as np

from serdes_flow import pwl_sources


class PwlSourcesTest(unittest.TestCase):
    def test_nonuniform_dense_reconstruction_and_plateaus(self):
        t=np.array([0.,.1,.15,.7,1.]);y=np.array([1.2,1.3,-.8,.2,.5]);dense=np.linspace(0,1,1001)
        segments,error=pwl_sources.parts(t,y,3)
        actual=sum((np.interp(dense,a,b) for a,b in segments),np.zeros_like(dense))
        np.testing.assert_allclose(actual,np.interp(dense,t,y),atol=1e-14)
        self.assertLess(error,1e-14)
        self.assertLess(segments[0][0][-1],t[-1])

    def test_extra_sources_are_zero(self):
        segments,error=pwl_sources.parts([0,1],[1.2,1.3],4)
        self.assertEqual(len(segments),4)
        for _,v in segments[1:]:np.testing.assert_array_equal(v,[0,0])

    def test_invalid_and_nonfinite_data_rejected(self):
        for t,y,c in [([1,2],[0,1],2),([0,0],[0,1],2),([0,1],[0,np.nan],2),([0,1],[0,1],0)]:
            with self.assertRaises(ValueError):pwl_sources.parts(t,y,c)


if __name__=='__main__':unittest.main()
