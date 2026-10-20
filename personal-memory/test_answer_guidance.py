import json
import unittest
from research_test_support import ReadingFixture


class GuidanceTest(ReadingFixture, unittest.TestCase):
    def start(self, kinds):
        facets=[dict(id=f'f{i}',question='合成问题'*20,evidence_kind=kind) for i,kind in enumerate(kinds)]
        return self.service.begin_research('合成资料问题',facets,'technical','focused')

    def proposal(self, fid='f0', status='insufficient', claim='资料证明我已经学过并搭建用好'):
        return dict(facet_id=fid,status=status,claim=claim,citations=[],limitations='只有方法，没有足够的经历或效果证据')

    def test_insufficient_fallback_does_not_echo_unproved_experience(self):
        s=self.start(['practice','outcome'])
        out=self.service.assess_research(s['research_id'],[self.proposal('f0'),self.proposal('f1')])
        guidance=out['answer_guidance']
        self.assertTrue(guidance['statuses_are_model_proposals'])
        for review in guidance['facets']:
            self.assertIn('本轮已读材料',review['fallback_if_insufficient'])
            self.assertNotIn('已经学过',review['fallback_if_insufficient'])
        self.assertIn('本人',guidance['facets'][0]['evidence_check'])
        self.assertIn('实测',guidance['facets'][1]['evidence_check'])

    def test_first_date_guidance_preserves_unknown_date_role(self):
        s=self.start(['first_use']);out=self.service.assess_research(s['research_id'],[self.proposal(claim='2026-05-30就是保存日期和首次使用日期')])
        review=out['answer_guidance']['facets'][0]
        self.assertIn('来源标注',review['evidence_check'])
        self.assertIn('含义不明',review['evidence_check'])
        self.assertNotIn('2026-05-30',review['fallback_if_insufficient'])
        self.assertFalse(out['semantic_verified'])

    def test_reading_summary_uses_actual_returned_ranges(self):
        s=self.start(['explanation']);rid=s['research_id']
        out=self.service.assess_research(rid,[self.proposal(claim='我已读完全部107个小节')])
        reading=out['answer_guidance']['reading']
        self.assertEqual(reading['returned_sections'],0)
        self.assertEqual(reading['fully_returned_sections'],0)
        self.assertEqual(reading['matched_sections'],out['coverage']['matched_sections'])
        self.assertGreater(reading['matched_sections'],0)
        self.assertIn('目录',out['answer_guidance']['scope_check'])
        self.assertIn('实践记录',out['answer_guidance']['scope_check'])

    def test_valid_quote_never_becomes_verified_meaning(self):
        s=self.start(['first_use']);rid=s['research_id']
        sections=self.service.list_research_sections(rid)['sections']
        sid=next(x['section_id'] for x in sections if x['path']=='计算机和AI/a.md')
        hit=self.service.read_research_sections(rid,[sid])['hits'][0]
        a=self.proposal(status='supported',claim='这能证明人生首次')
        a['citations']=[dict(hit_token=hit['hit_token'],quote='星光是足够长的合成技术说明')]
        out=self.service.assess_research(rid,[a]);review=out['answer_guidance']['facets'][0]
        self.assertTrue(out['structural_valid'])
        self.assertTrue(review['structure_and_quotes_valid'])
        self.assertTrue(review['requires_semantic_review'])
        self.assertIsNone(review['fallback_if_insufficient'])
        self.assertFalse(out['semantic_verified'])

    def test_partial_long_section_cannot_be_described_as_all_read(self):
        s=self.service.begin_research('查技术记录',[
            dict(id='f0',question='有何记录',evidence_kind='practice')
        ],'technical','focused',paths=self.expected['technical_targets']+['计算机和AI/长行.md'])
        rid=s['research_id']
        sections=self.service.list_research_sections(rid)['sections']
        self.service.read_research_sections(rid,[x['section_id'] for x in sections])
        reading=self.service.assess_research(rid,[self.proposal()])['answer_guidance']['reading']
        self.assertEqual((reading['matched_sections'],reading['returned_sections'],reading['fully_returned_sections']),(5,5,4))
        self.assertFalse(reading['all_matched_sections_fully_returned'])
        self.assertIn('4/5',reading['scope_statement'])
        self.assertIn('1个小节未完整返回',reading['scope_statement'])
        self.assertIn('不能声称全部读完',reading['scope_statement'])

    def test_missing_and_rejected_items_cannot_receive_fallback(self):
        s=self.start(['practice','outcome']);a=self.proposal();a['citations']=[dict(hit_token='fake',quote='足够长但没有被实际读取的引文')]
        out=self.service.assess_research(s['research_id'],[a])
        bad,missing=out['answer_guidance']['facets']
        self.assertFalse(bad['structure_and_quotes_valid'])
        self.assertIsNone(bad['fallback_if_insufficient'])
        self.assertEqual(missing['proposed_status'],'missing')
        self.assertIsNone(missing['fallback_if_insufficient'])

    def test_all_six_facets_guidance_is_bounded(self):
        s=self.start(['explanation','explanation','practice','outcome','first_use','timeline'])
        answers=[self.proposal(f'f{i}') for i in range(6)]
        out=self.service.assess_research(s['research_id'],answers)
        self.assertEqual(len(out['answer_guidance']['facets']),6)
        self.assertLess(len(json.dumps(out['answer_guidance'],ensure_ascii=False)),3200)
