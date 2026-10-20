import unittest,json
from memory_search import build
from research_test_support import ReadingFixture

class MonthlyTest(ReadingFixture,unittest.TestCase):
 def start_months(self,end='2026-10-31'):
  return self.service.begin_research('回顾变化',[dict(id='a',question='变化',evidence_kind='timeline')],'personal','timeline',paths=['我的存在/月份.md'],date_from='2026-08-01',date_to=end)['research_id']
 def setUp(self):
  super().setUp();(self.vault/'我的存在/月份.md').write_text('# 2026-08-01\n'+('八月长记录。\n'*2200)+'# 2026-10-18\n十月平静但也疲惫。\n# 10月19日\n年份不明确。');build(self.vault,self.db)
 def test_monthly_coverage_counts_actual_range_unions(self):
  rid=self.start_months();listing=self.service.list_research_sections(rid);aug=next(x['section_id'] for x in listing['sections'] if x['heading_date']=='2026-08-01')
  page=self.service.read_research_sections(rid,[aug]);periods=page['coverage']['periods'];self.assertEqual([p['month'] for p in periods],['2026-08','2026-09','2026-10']);self.assertEqual(periods[1]['matched_sections'],0);self.assertEqual(periods[2]['fully_returned_sections'],0);self.assertFalse(page['coverage']['temporal_scope_complete'])
  self.assertIn(next(x['section_id'] for x in listing['sections'] if x['heading_date']=='2026-10-18'),page['coverage']['recommended_section_ids'])
 def test_recommendations_only_listed_and_unknown_not_assigned(self):
  rid=self.start_months();self.assertEqual(self.service.sessions.coverage(rid)['recommended_section_ids'],[])
  self.service.list_research_sections(rid);c=self.service.sessions.coverage(rid);self.assertEqual(sum(p['matched_sections'] for p in c['periods']),2);self.assertGreater(c['undated_sections']+c['ambiguous_sections'],0)
 def test_period_summary_bounded_and_body_still_returned(self):
  rid=self.start_months('2040-10-31');page=self.service.list_research_sections(rid);self.assertEqual(len(page['coverage']['periods']),12);self.assertTrue(page['coverage']['periods_truncated']);sid=page['sections'][0]['section_id'];out=self.service.read_research_sections(rid,[sid]);self.assertTrue(out['hits']);self.assertLessEqual(len(json.dumps(out,ensure_ascii=False)),16000)

 def test_large_directory_continues_after_reading_earlier_pages(self):
  from datetime import date,timedelta
  note=self.vault/'我的存在/全年.md';note.write_text('\n'.join('# '+(date(2026,1,1)+timedelta(days=i)).isoformat()+' '+('甲'*185)+'\n这是逐日合成材料，用于验证后续目录仍能返回。' for i in range(160)));build(self.vault,self.db)
  s=self.service.begin_research('全年回顾',[dict(id='a',question='变化',evidence_kind='timeline')],'personal','timeline',paths=['我的存在/全年.md'],date_from='2026-01-01',date_to='2026-12-31');rid=s['research_id'];page=self.service.list_research_sections(rid);items=list(page['sections'])
  for _ in range(2):page=self.service.list_research_sections(rid,cursor=page['next_cursor']);items+=page['sections']
  for i in range(0,len(items),8):
   read=self.service.read_research_sections(rid,[x['section_id'] for x in items[i:i+8]])
   while read['next_cursor']:read=self.service.read_research_sections(rid,cursor=read['next_cursor'])
  while page['next_cursor']:page=self.service.list_research_sections(rid,cursor=page['next_cursor']);items+=page['sections']
  self.assertEqual(len(items),160);self.assertTrue(page['coverage']['enumeration_complete'])
