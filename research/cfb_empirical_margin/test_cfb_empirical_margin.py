import unittest
import numpy as np
from cfb_empirical_margin import cover, simulate, distribution
class Tests(unittest.TestCase):
 def test_orientation_and_push(self):
  r=cover(np.array([3,7,10]),-7); self.assertAlmostEqual(r['home_cover'],1/3);self.assertAlmostEqual(r['push'],1/3)
 def test_half(self):
  self.assertEqual(cover(np.array([3,7,10]),-7.5)['push'],0)
 def test_all_push(self):
  self.assertIsNone(cover(np.array([7,7]),-7)['home_conditional_no_push'])
 def test_seed(self):
  a,s=simulate(np.array([-7,3]),np.array([.4,.6]),'1','abc'); b,t=simulate(np.array([-7,3]),np.array([.4,.6]),'1','abc');self.assertTrue(np.array_equal(a,b));self.assertEqual(s,t)
 def test_sample_block(self):
  with self.assertRaises(ValueError): distribution([],1500,1500,False)
 def test_quarter_line(self):
  with self.assertRaises(ValueError):cover(np.array([7]),-7.25)
if __name__=='__main__':unittest.main()
