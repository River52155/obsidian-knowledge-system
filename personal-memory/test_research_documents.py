import unittest
from memory_search import build
from research_test_support import ReadingFixture

class DocumentsTest(ReadingFixture,unittest.TestCase):
 def test_document_lookup_stays_in_collection_and_disambiguates(self):
  for p in ['计算机和AI/甲/同名.md','计算机和AI/乙/同名.md','我的存在/同名.md']:
   path=self.vault/p;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('# 标题\n这是合成来源说明，主体和范围应当保留。')
  build(self.vault,self.db);s=self.begin();out=self.service.list_research_documents(s['research_id'],'同名')
  self.assertEqual(len(out['documents']),2);self.assertTrue(all(x['path'].startswith('计算机和AI/') for x in out['documents']))
  self.assertEqual(self.service.list_research_documents(s['research_id'],'不存在')['documents'],[])
 def test_narrow_only_before_evidence_and_never_expands(self):
  s=self.begin();rid=s['research_id'];self.service.list_research_documents(rid)
  out=self.service.narrow_research(rid,['计算机和AI/a.md']);self.assertEqual(out['scope']['document_count'],1)
  with self.assertRaises(ValueError):self.service.narrow_research(rid,['我的存在/同名.md'])
  sections=self.service.list_research_sections(rid)['sections'];self.service.read_research_sections(rid,[sections[0]['section_id']])
  with self.assertRaisesRegex(ValueError,'正文'):self.service.narrow_research(rid,['计算机和AI/a.md'])
 def test_document_cursor_binding_and_shared_page_budget(self):
  for i in range(22):(self.vault/f'计算机和AI/p{i}.md').write_text('# 标题\n合成技术说明。')
  build(self.vault,self.db);rid=self.begin()['research_id'];page=self.service.list_research_documents(rid)
  self.assertEqual(len(page['documents']),20);self.assertTrue(page['next_cursor'])
  a=self.service.list_research_documents(rid,cursor=page['next_cursor']);used=self.service._session(rid)['list_pages'];b=self.service.list_research_documents(rid,cursor=page['next_cursor']);self.assertEqual(a['documents'],b['documents']);self.assertEqual(self.service._session(rid)['list_pages'],used)
  with self.assertRaises(ValueError):self.service.list_research_documents(rid,'p',page['next_cursor'])
  with self.assertRaises(ValueError):self.service.list_research_documents(rid,cursor=[])
