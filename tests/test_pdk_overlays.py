import unittest

from serdes_flow.pdk_overlays import fixed_poly_cube


class PolyOverlayTest(unittest.TestCase):
    def example(self,card='2p85'):
        return (f'.subckt sky130_fd_pr__res_high_po_{card} r0 r1 b\n'
                '.param k=pow(2,3)\n'
                'rend r0 ra r = {130*(1+pow(min(abs(v(r0,r1))-1.6,0.4),2)*a+pow(min(abs(v(r0,r1))-1.6,0.4),3)*b)}\n'
                '.ends\n')

    def test_only_dynamic_cube_changes(self):
        text=self.example();after,change=fixed_poly_cube(text)
        self.assertEqual(after.replace(change['replacement'],change['original']),text)
        self.assertIn('pow(2,3)',after)
        self.assertIn('pow(min(abs(v(r0,r1))-1.6,0.4),2)',after)
        self.assertEqual(change['replacement'].count('min(abs(v(r0,r1))-1.6,0.4)'),3)

    def test_model_and_already_patched_inputs_rejected(self):
        with self.assertRaises(ValueError):fixed_poly_cube(self.example('other'))
        patched,_=fixed_poly_cube(self.example())
        with self.assertRaises(ValueError):fixed_poly_cube(patched)

    def test_unexpected_or_missing_expression_rejected(self):
        with self.assertRaises(ValueError):fixed_poly_cube(self.example().replace('pow(min(abs(v(r0,r1))-1.6,0.4),3)','pow(v(r0),3)'))
        with self.assertRaises(ValueError):fixed_poly_cube(self.example().replace(',3)*b',',4)*b'))


if __name__=='__main__':unittest.main()
