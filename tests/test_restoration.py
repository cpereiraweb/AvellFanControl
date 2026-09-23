import copy
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'driver/profiles'))
from restoration import assess_restoration

class RestorationTests(unittest.TestCase):
    def setUp(self):
        self.before=dict(read_only=True,flags_07c5=0,flags_07c6=0,features_078e=236,
            mode_0751=160,host_0741=4,table_0f00_0f5f=[0]*96)
    def test_exact(self):
        r=assess_restoration(self.before,copy.deepcopy(self.before))
        self.assertTrue(r['controls_restored']);self.assertTrue(r['exact_match'])
    def test_only_observed_bit_is_reported_separately(self):
        after=copy.deepcopy(self.before);after['host_0741']=0
        r=assess_restoration(self.before,after)
        self.assertTrue(r['controls_restored']);self.assertFalse(r['exact_match'])
        self.assertTrue(r['observed_bit2_variation'])
    def test_manual_or_unknown_bits_fail(self):
        for value in (1,5,8,12,32,None):
            after=copy.deepcopy(self.before);after['host_0741']=value
            self.assertFalse(assess_restoration(self.before,after)['controls_restored'])
    def test_all_other_changes_fail_even_with_bit2_change(self):
        for key,value in [('flags_07c5',128),('flags_07c6',4),('mode_0751',48),('features_078e',0),('table_0f00_0f5f',[1]+[0]*95)]:
            after=copy.deepcopy(self.before);after['host_0741']=0;after[key]=value
            self.assertFalse(assess_restoration(self.before,after)['controls_restored'])
    def test_truncated_data_fails(self):
        after=copy.deepcopy(self.before);after['table_0f00_0f5f']=[]
        self.assertFalse(assess_restoration(self.before,after)['controls_restored'])
