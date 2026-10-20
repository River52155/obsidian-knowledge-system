import unittest,tempfile,json
from pathlib import Path
from unittest.mock import patch
from memory_search import build,search,connect
from research_scope import load_collections,resolve_collection
from semantic_search import SemanticIndex

class ScopeTest(unittest.TestCase):
    def test_technical_excludes_diary_and_unreviewed_wiki(self):
        cfg={'schema_version':1,'collections':[dict(id='technical',description='技术',include_prefixes=['计算机和AI'],include_paths=['wiki/a.md'],exclude_prefixes=[])]}
        out=resolve_collection(cfg,'technical',{'计算机和AI/a.md','wiki/a.md','wiki/b.md','我的存在/a.md'},None)
        self.assertEqual(out['allowed_paths'],{'计算机和AI/a.md','wiki/a.md'})
        with self.assertRaises(ValueError):resolve_collection(cfg,'technical',{'wiki/b.md'},['wiki/b.md'])
    def test_prefix_boundary_and_traversal(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'c.json'
            for prefix in ['../wiki','/etc','wiki/*','我的存在']:
                p.write_text(json.dumps({'schema_version':1,'collections':[dict(id='technical',description='x',include_prefixes=[prefix],include_paths=[],exclude_prefixes=[])]}))
                with self.subTest(prefix=prefix),self.assertRaises(ValueError):load_collections(p)
    def test_collection_hash_changes(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'c.json';v={'schema_version':1,'collections':[dict(id='technical',description='x',include_prefixes=['计算机和AI'],include_paths=[],exclude_prefixes=[])]}
            p.write_text(json.dumps(v));a=load_collections(p)[1];v['collections'][0]['description']='y';p.write_text(json.dumps(v));self.assertNotEqual(a,load_collections(p)[1])
    def test_scope_and_date_filter_before_candidate_caps(self):
        import numpy as np
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'v/wiki').mkdir(parents=True)
            for n in range(162):(p/f'v/wiki/{n:03}.md').write_text('# 星光\n星光技术 '+('星光 '*4 if n<161 else '目标')+'\n')
            db=p/'db';build(p/'v',db)
            with connect(db) as con:rows=[dict(r) for r in con.execute('select c.*,d.kind,d.sha256 from chunks c join documents d on d.path=c.path')]
            engine=object.__new__(SemanticIndex);engine.rows={r['id']:r for r in rows};engine.ids=np.array([r['id'] for r in rows]);engine.vectors=np.arange(162,0,-1).reshape(-1,1);engine.encoder=type('E',(),{'query':lambda s,q:np.array([1.0])})();engine.stat=1;engine.file_state=lambda:1;engine.meta={'model_id':'fake','revision':'fake'}
            for mode in ['keyword','semantic','hybrid']:
                with self.subTest(mode=mode),patch('semantic_search.get_index',return_value=engine):
                    out=search(db,'星光',mode=mode,allowed_paths={'wiki/161.md'})
                    self.assertEqual([r['path'] for r in out['results']],['wiki/161.md'])
                    out=search(db,'星光',mode=mode,allowed_chunk_ids={rows[-1]['id']})
                    self.assertEqual([r['path'] for r in out['results']],['wiki/161.md'])
                    self.assertEqual(search(db,'星光',mode=mode,allowed_paths=set())['results'],[])
    def test_filter_precedes_ranking_limit_and_title_focus(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'v/wiki').mkdir(parents=True)
            for name in ['alpha','beta','gamma','delta']:(p/f'v/wiki/{name}.md').write_text('# 一句话解释\n星光是一条足够长的测试技术资料，用于标题优先检索。')
            db=p/'db';build(p/'v',db)
            out=search(db,'alpha beta gamma delta',mode='keyword',allowed_paths={'wiki/delta.md'})
            self.assertEqual([r['path'] for r in out['results']],['wiki/delta.md'])
    def test_empty_scope_never_means_all(self):
        self.assertEqual(resolve_collection({'schema_version':1,'collections':[dict(id='allowed',description='x',include_prefixes=['wiki'],include_paths=[],exclude_prefixes=[])]},'allowed',set(),None)['allowed_paths'],set())
