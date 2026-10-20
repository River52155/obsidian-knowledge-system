import unittest
from research_test_support import ReadingFixture

class GainTest(ReadingFixture,unittest.TestCase):
 def test_duplicate_search_has_zero_gain_and_stops_after_two_empty_searches(self):
  rid=self.begin()['research_id'];a=self.service.search_research(rid,'a','星光','查机制');self.assertGreater(a['new_evidence_chars'],0)
  b=self.service.search_research(rid,'a','星光','尚缺机制');c=self.service.search_research(rid,'a','星光','尚缺机制')
  self.assertEqual(b['new_evidence_chars'],0);self.assertEqual(c['recommendation'],'stop_no_gain');self.assertEqual(c['consecutive_no_gain'],2)
