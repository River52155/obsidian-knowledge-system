import unittest
from research_test_support import ReadingFixture

class AssessmentTest(ReadingFixture,unittest.TestCase):
    def answer(self,s,status='supported'):
        rid=s['research_id'];items=self.service.list_research_sections(rid)['sections'];sid=next(x['section_id'] for x in items if x['path']=='计算机和AI/a.md');h=self.service.read_research_sections(rid,[sid])['hits'][0]
        return dict(facet_id='a',status=status,claim='合成说明',citations=[dict(hit_token=h['hit_token'],quote='星光是足够长的合成技术说明')],limitations='不能证明经历')
    def test_every_facet_once(self):
        s=self.begin();a=self.answer(s)
        self.assertTrue(self.service.assess_research(s['research_id'],[a])['structural_valid'])
        self.assertFalse(self.service.assess_research(s['research_id'],[])['structural_valid'])
        self.assertFalse(self.service.assess_research(s['research_id'],[a,a])['structural_valid'])
    def test_supported_requires_valid_current_quote(self):
        s=self.begin();a=self.answer(s);a['citations'][0]['quote']='完全不存在的原文不能通过核对'
        self.assertFalse(self.service.assess_research(s['research_id'],[a])['structural_valid'])
    def test_insufficient_requires_reason(self):
        s=self.begin();a=dict(facet_id='a',status='insufficient',claim='不足',citations=[],limitations='')
        self.assertFalse(self.service.assess_research(s['research_id'],[a])['structural_valid'])
        a['limitations']='只找到教程，没有实践记录';self.assertTrue(self.service.assess_research(s['research_id'],[a])['structural_valid'])
    def test_scope_and_token_owner_checked(self):
        s=self.begin();other=self.begin();a=self.answer(other)
        self.assertFalse(self.service.assess_research(s['research_id'],[a])['structural_valid'])
    def test_partial_rejection_preserved(self):
        s=self.begin();a=self.answer(s);a['citations'].append(dict(hit_token='fake',quote='足够长但并不存在的错误原文片段'))
        out=self.service.assess_research(s['research_id'],[a]);self.assertFalse(out['structural_valid']);self.assertEqual(len(out['sources']),1)
    def test_timeline_claim_reports_incomplete_coverage(self):
        s=self.timeline([self.expected['diary']]);a=dict(facet_id='a',status='insufficient',claim='目前只读局部',citations=[],limitations='没有完整读完')
        out=self.service.assess_research(s['research_id'],[a]);self.assertTrue(any(i['code']=='INCOMPLETE_COVERAGE' for i in out['issues']))
    def test_earliest_record_is_not_machine_verified_first_use(self):
        s=self.begin();a=self.answer(s);a['claim']='这是人生第一次'
        out=self.service.assess_research(s['research_id'],[a]);self.assertFalse(out['semantic_verified'])
    def test_assess_rechecks_all_covered_sources_without_citations(self):
        s=self.timeline([self.expected['diary']]);rid=s['research_id'];items=self.service.list_research_sections(rid)['sections'];self.service.read_research_sections(rid,[x['section_id'] for x in items]);(self.vault/self.expected['diary']).write_text('新原文')
        with self.assertRaisesRegex(ValueError,'原文'):
            self.service.assess_research(rid,[dict(facet_id='a',status='insufficient',claim='只读局部',citations=[],limitations='不足')])
