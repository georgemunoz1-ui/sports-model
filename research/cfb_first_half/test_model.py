import unittest
import numpy as np
from model import half_score,forecast,probabilities
class Tests(unittest.TestCase):
 def test_half_excludes_second_half_overtime(self):self.assertEqual(half_score({'score':'31','linescores':[{'value':7},{'value':3},{'value':7},{'value':7},{'value':7}]}),10)
 def test_conflicting_final(self):
  with self.assertRaises(ValueError):half_score({'score':28,'linescores':[{'value':7}]*3+[{'value':0}]})
 def test_push(self):self.assertEqual(probabilities([30,31,32],31),{'under':1/3,'over':1/3,'push':1/3})
 def test_half_line(self):self.assertEqual(probabilities([30,31],30.5)['push'],0)
 def test_seed(self):
  a,x=forecast(list(range(40)),'event','hash');b,y=forecast(list(range(40)),'event','hash');self.assertTrue(np.array_equal(x,y));self.assertEqual(a,b)
 def test_small_sample(self):
  with self.assertRaises(ValueError):forecast([10],'event','hash')
if __name__=='__main__':unittest.main()
