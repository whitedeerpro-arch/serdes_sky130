import tempfile
import unittest
from pathlib import Path

import numpy as np

from serdes_flow import scalar_raw


class ScalarRawTest(unittest.TestCase):
    def write(self,path,values,*,complex_plot=True,points=1):
        header=f'Flags: {"complex" if complex_plot else "real"}\nNo. Variables: 2\nNo. Points: {points}\nVariables:\n0 frequency frequency\n1 v(r) voltage\nBinary:\n'.encode()
        path.write_bytes(header+np.array(values,dtype='<c16' if complex_plot else '<f8').tobytes())

    def test_real_observables_in_complex_ac_plot(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'ac.raw';self.write(p,[2e9,124.5])
            self.assertEqual(scalar_raw.read(p,frequency_hz=2e9)['r'],124.5)
            with self.assertRaises(ValueError):scalar_raw.read(p,frequency_hz=1e9)

    def test_complex_observable_is_not_silently_truncated(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'ac.raw';self.write(p,[2e9,1+1j])
            with self.assertRaises(ValueError):scalar_raw.read(p)

    def test_truncation_and_wrong_point_count_fail(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'ac.raw';self.write(p,[2e9])
            with self.assertRaises(ValueError):scalar_raw.read(p)
            self.write(p,[2e9,1],points=2)
            with self.assertRaises(ValueError):scalar_raw.read(p)

    def test_real_dc_plot(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'dc.raw';self.write(p,[1.8,225.],complex_plot=False)
            self.assertEqual(scalar_raw.read(p)['r'],225.)


if __name__=='__main__':unittest.main()
