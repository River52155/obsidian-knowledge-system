import tempfile,json
from pathlib import Path
from unittest.mock import patch
from memory_search import build,search
from retrieval_service import RetrievalService
from research_service import ResearchService
from acceptance.research_fixtures import build_fixture
FACETS=[dict(id='a',question='机制是什么',evidence_kind='explanation')]

class ResearchFixture:
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.vault=self.root/'v';(self.vault/'计算机和AI').mkdir(parents=True);(self.vault/'计算机和AI/a.md').write_text('# 星光\n星光是足够长的合成技术说明，不能作为个人经历证明。');self.db=self.root/'db';build(self.vault,self.db)
        self.config=self.root/'c';self.config.write_text(json.dumps({'schema_version':1,'collections':[dict(id='technical',description='x',include_prefixes=['计算机和AI'],include_paths=[],exclude_prefixes=[])]}))
        self.notes=RetrievalService(lambda:self.db);self.service=ResearchService(self.notes,self.config)
        self.mock_search=patch('research_service.search',side_effect=lambda db,q,**kw:search(db,q,**dict(kw,mode='keyword')));self.mock_search.start();self.addCleanup(self.mock_search.stop)
    def tearDown(self):self.temp.cleanup()
    def begin(self,**kwargs):return self.service.begin_research('技术问题',FACETS,'technical','focused',**kwargs)

class ReadingFixture(ResearchFixture):
    def setUp(self):
        super().setUp();self.expected=build_fixture(self.vault);build(self.vault,self.db)
        cfg=json.loads(self.config.read_text());cfg['collections'].append(dict(id='personal',description='x',include_prefixes=['我的存在'],include_paths=[],exclude_prefixes=[]));self.config.write_text(json.dumps(cfg))
    def timeline(self,paths=None):return self.service.begin_research('回顾10月',[dict(id='a',question='变化',evidence_kind='timeline')],'personal','timeline',paths,date_from='2026-10-01',date_to='2026-10-31')
