import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

from serdes_flow import project

FILE = project.ROOT / 'analog/tx/input_register/tb/loaded_stage_cm/run.py'
spec = importlib.util.spec_from_file_location('test_stage_cm_card', FILE)
card = importlib.util.module_from_spec(spec)
spec.loader.exec_module(card)


class DirectCMTest(unittest.TestCase):
    def setUp(self):
        self.chains = '\n'.join(card.parent.chain(mode, i) for i, mode in enumerate(card.parent.MODES, 1))

    def test_equal_series_sources_retain_both_adjacent_stages(self):
        text = card.inject_chain(self.chains, dict(e4_cm_v=-.025, out_cm_v=0.))
        for expected in ('Xe3 ip inn ', 'Xe4 e4ip e4in ', 'Xout outip outin '):
            self.assertEqual(text.count(expected), 3)
        self.assertEqual(text.count('Vcm_e4p e4ip e3p -0.025'), 3)
        self.assertEqual(text.count('Vcm_e4n e4in e3n -0.025'), 3)
        self.assertEqual(text.count('Vcm_outp outip e4p 0'), 3)
        self.assertEqual(text.count('Vcm_outn outin e4n 0'), 3)
        self.assertEqual(text.count('wn=24 wt=15.6'), 6)
        self.assertEqual(text.count('wn=32 wt=16'), 3)

    def test_missing_connection_is_rejected(self):
        with self.assertRaises(ValueError):
            card.inject_chain(self.chains.replace('Xe4 e3p e3n ', 'Xe4 wrong nodes ', 1), dict(e4_cm_v=0., out_cm_v=0.))

    def test_added_nodes_are_saved_and_written(self):
        source = '.include "' + str(card.PARENT / 'snap' / 'fs' / 'clock_variants.spice') + '"\n.save v(ip)\nwrite baseline.raw v(ip)\n'
        with patch.object(card.parent, 'render', return_value=source):
            rendered = card.render(Path('/tmp/explicit_cm_test'), 'fs', 'e4_m25')
        self.assertIn('.save v(xclock1.e4ip)', rendered)
        self.assertIn('write e4_m25.raw v(xclock1.e4ip)', rendered)
        self.assertEqual(rendered.count('v(xclock3.outin)'), 2)
        self.assertIn('/tmp/explicit_cm_test/variants/fs/e4_m25.spice', rendered)


if __name__ == '__main__': unittest.main()
