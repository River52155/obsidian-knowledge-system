import unittest,json,threading
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from memory_search import make_server
from research_test_support import ReadingFixture

class ResearchHttpTest(ReadingFixture,unittest.TestCase):
    def setUp(self):
        super().setUp();self.server=make_server(self.db,0,collections_path=self.config);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();self.base=f'http://127.0.0.1:{self.server.server_port}'
    def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join();super().tearDown()
    def post(self,path,data,origin=True):
        req=Request(self.base+path,json.dumps(data).encode(),{'Content-Type':'application/json',**({'Origin':self.base} if origin else {})})
        try:
            with urlopen(req) as r:return r.status,json.load(r)
        except HTTPError as e:return e.code,json.load(e)
    def begin_http(self):
        return self.post('/api/research/begin',dict(question='回顾10月',facets=[dict(id='a',question='变化',evidence_kind='timeline')],collection='personal',strategy='timeline',date_from='2026-10-01',date_to='2026-10-31'))
    def test_research_tools_end_to_end_on_ephemeral_port(self):
        status,s=self.begin_http();self.assertEqual(status,200);rid=s['research_id']
        status,out=self.post('/api/research/sections',dict(research_id=rid));self.assertEqual(status,200)
        ids=[x['section_id'] for x in out['sections'][:8]];status,read=self.post('/api/research/read',dict(research_id=rid,section_ids=ids));self.assertEqual(status,200);self.assertTrue(read['hits'])
        status,result=self.post('/api/research/assess',dict(research_id=rid,answers=[dict(facet_id='a',status='insufficient',claim='只做局部总结',citations=[],limitations='日期不确定')]))
        self.assertEqual(status,200);self.assertFalse(result['semantic_verified'])
    def test_wrong_vault_origin_and_structured_error(self):
        status,out=self.post('/api/research/begin',{},origin=False);self.assertEqual(status,403)
        status,out=self.post('/api/research/sections',dict(research_id='other'));self.assertEqual(status,400);self.assertEqual(out['code'],'RESEARCH_EXPIRED')
    def test_research_schema_limits(self):
        status,out=self.post('/api/research/begin',dict(question='q',facets=[],collection='personal',strategy='timeline',unknown=True));self.assertEqual(status,400)
        for facet in [dict(id='a',question='q',evidence_kind=[]),dict(id='a',question='q',evidence_kind='timeline',unknown=True)]:
            status,out=self.post('/api/research/begin',dict(question='q',facets=[facet],collection='personal',strategy='focused'));self.assertEqual(status,400)
