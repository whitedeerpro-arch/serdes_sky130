import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np

from serdes_flow import project

FILE=project.ROOT/'analog/tx/input_register/tb/loaded_clock_card/run.py'
spec=importlib.util.spec_from_file_location('loaded_clock_test',FILE)
card=importlib.util.module_from_spec(spec);spec.loader.exec_module(card)


class LoadedClockCardTest(unittest.TestCase):
    def test_independent_amplitude_and_common_mode_and_rail_guard(self):
        d={n:np.array([1.,1.]) for n in card.NODES}
        d.update(ip=np.array([1.6,1.4]),inn=np.array([1.4,1.6]),vdd=np.array([1.65,1.65]))
        out=card.inputs(d,dict(id='test',scale=.8,cm_shift_v=-.025))
        np.testing.assert_allclose((out['ip']+out['inn'])/2,[1.475,1.475])
        np.testing.assert_allclose(out['ip']-out['inn'],[.16,-.16])
        with self.assertRaises(ValueError):card.inputs(d,dict(id='test',scale=2.,cm_shift_v=0.))
        original=card.inputs(d,dict(id='baseline',scale=1.,cm_shift_v=0.))
        np.testing.assert_array_equal(original['ip'],d['ip'])

    def test_three_load_copies_do_not_duplicate_control_or_temperature(self):
        source=card.helper.TEMPLATE.read_text().replace('serdes_tx_cml_line_driver_lowvt_enable wgatep=32',
             'serdes_tx_cml_line_driver_lowvt_enable wgatep=32 rpre=120 wout=192 wtpre=60')
        old=Path.read_text
        def read(path,*args,**kwargs):
            if str(path).endswith('execution/physical_tb.cir'):return source
            return old(path,*args,**kwargs)
        with patch.object(Path,'read_text',read):
            text,_=card.template(Path('/tmp/loaded_clock_fixture'),'fs_v1650_t85',dict(source='fake',library='/tmp/model.lib'))
        self.assertEqual(text.count('.control'),1)
        self.assertEqual(text.count('.temp '),1)
        for i in (1,2,3):
            self.assertIn(f'Xslice{i} ap an bp bn sp{i} sn{i} qp{i} qn{i}',text)
            self.assertIn(f'Clacp{i} lap{i} ltp{i} 10n',text)
            self.assertIn(f'Vlcm{i} lcm{i} 0 .9',text)


if __name__=='__main__':unittest.main()
