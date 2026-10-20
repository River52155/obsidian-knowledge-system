import unittest
from research_test_support import ReadingFixture

class RoleTest(ReadingFixture,unittest.TestCase):
 def run_role(self,kind,role,date='unknown',first='unknown',bad=False):
  s=self.service.begin_research('判断经历',[dict(id='a',question='判断',evidence_kind=kind)],'technical','focused');rid=s['research_id'];sid=next(x['section_id'] for x in self.service.list_research_sections(rid)['sections'] if x['path']=='计算机和AI/a.md');h=self.service.read_research_sections(rid,[sid])['hits'][0]
  c=dict(hit_token=h['hit_token'],quote='不存在的引文不能支撑个人经历' if bad else '星光是足够长的合成技术说明',evidence_role=role,date_basis=date,first_basis=first)
  return self.service.assess_research(rid,[dict(facet_id='a',status='supported',claim='本人完成',citations=[c],limitations='')])
 def test_reference_plan_other_and_fiction_cannot_support_self_action(self):
  for role in ['reference','plan','other_person','fiction']:
   with self.subTest(role=role):self.assertIn('EVIDENCE_ROLE_CONFLICT',[i['code'] for i in self.run_role('practice',role)['issues']])
 def test_action_not_outcome_and_heading_not_first_event(self):
  self.assertFalse(self.run_role('outcome','self_action')['structural_valid']);self.assertFalse(self.run_role('first_use','self_first_use','heading_only','earliest_found')['structural_valid'])
 def test_self_label_does_not_certify_semantics_and_rejected_quote_not_support(self):
  out=self.run_role('outcome','self_outcome');self.assertTrue(out['structural_valid']);self.assertFalse(out['semantic_verified']);self.assertTrue(out['evidence_role_checks']['classifications_are_model_proposals'])
  self.assertFalse(self.run_role('outcome','self_outcome',bad=True)['structural_valid'])
 def test_unknown_is_legacy_warning_not_semantic_success(self):
  out=self.run_role('practice','unknown');self.assertTrue(out['structural_valid']);self.assertTrue(out['evidence_role_checks']['warnings'])

 def test_malformed_classification_returns_controlled_error(self):
  out=self.run_role('practice',[]);self.assertFalse(out['structural_valid'])
