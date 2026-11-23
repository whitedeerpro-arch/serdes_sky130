import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

from serdes_flow import project

FILE = project.ROOT / 'analog/tx/output_driver/tb/coupling_state/run.py'
spec = importlib.util.spec_from_file_location('test_coupling_card', FILE)
card = importlib.util.module_from_spec(spec); spec.loader.exec_module(card)


class CouplingStateTest(unittest.TestCase):
    def test_paired_fixtures_have_distinct_coupling_and_enable_states(self):
        source = card.ddj.TEMPLATE.read_text()
        with patch.object(card.ddj, 'deck', return_value=source):
            text = card.build(Path('/tmp/paired_fixture'), 'fs_v1650_t85', 92e-9)
        self.assertIn('Ven1 tx_en1 0 PWL(0 0 4n 0 4.1n 1.65)', text)
        self.assertIn('Ven2 tx_en2 0 1.65', text)
        for i in (1, 2):
            self.assertIn(f'Clacp{i} lap{i} ltp{i} 10n', text)
            self.assertIn(f'Clacn{i} lan{i} ltn{i} 10n', text)
            self.assertIn(f'Vlcm{i} lcm{i} 0 .9', text)
            self.assertIn(f'Xdriver{i} qp qn tx_en{i} lqp{i} lqn{i} vbias vd{i} vd{i} 0', text)
            self.assertIn(f'let irp{i}=@r.xdriver{i}.xrp.rbody[i]', text)
        self.assertEqual(text.count('.control'), 1)
        self.assertEqual(text.count('Cqp qp 0 2f'), 1)

    def test_changed_driver_pin_order_is_rejected(self):
        source = card.ddj.TEMPLATE.read_text().replace('qp qn tx_en lqp lqn vbias', 'qn qp tx_en lqp lqn vbias')
        with patch.object(card.ddj, 'deck', return_value=source):
            with self.assertRaises(ValueError): card.build(Path('/tmp/paired_fixture'), 'fs_v1650_t85', 92e-9)


if __name__ == '__main__': unittest.main()
