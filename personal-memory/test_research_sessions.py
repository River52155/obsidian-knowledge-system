import unittest,threading,json
from research_sessions import ResearchSessionStore
from research_test_support import ResearchFixture,FACETS

class SessionTest(ResearchFixture,unittest.TestCase):
    def test_facets_and_frozen_scope(self):
        s=self.begin(paths=['计算机和AI/a.md']);self.assertEqual(s['scope']['document_count'],1)
        with self.assertRaises(ValueError):self.service.begin_research('q',FACETS*2,'technical','focused')
        with self.assertRaises(ValueError):self.begin(paths=['我的存在/a.md'])
        with self.assertRaises(ValueError):self.service.search_research(s['research_id'],'unknown','星光','补机制')
    def test_collection_revision_and_expiry_invalidate(self):
        s=self.begin();self.config.write_text(self.config.read_text()+' ')
        # canonical JSON hash: insignificant formatting does not invalidate.
        self.service._session(s['research_id'])
        cfg=json.loads(self.config.read_text());cfg['collections'][0]['description']='new';self.config.write_text(json.dumps(cfg))
        with self.assertRaisesRegex(ValueError,'集合'):self.service._session(s['research_id'])
        s=self.begin();self.service.sessions.rows[s['research_id']]['touched']-=901
        with self.assertRaises(ValueError):self.service._session(s['research_id'])
    def test_research_budget_does_not_reset_legacy_turn(self):
        s=self.begin();turn=self.notes.contexts.start('old');self.notes.contexts.begin_search(turn,'')
        for i in range(6):self.service.search_research(s['research_id'],'a','星光','机制缺口')
        with self.assertRaisesRegex(ValueError,'次数'):self.service.search_research(s['research_id'],'a','星光','机制缺口')
        self.assertEqual(self.notes.contexts.stats(turn)['searches'],1)
    def test_same_session_concurrency_charges_once(self):
        store=ResearchSessionStore();row=store.start(dict(strategy='focused',sections=[],facets=FACETS),'rev','scope');rid=row['research_id']
        span=dict(path='x',sha256='s',start_offset=0,end_offset=100)
        threads=[threading.Thread(target=lambda:store.admit(rid,[span])) for i in range(10)]
        for t in threads:t.start()
        for t in threads:t.join()
        self.assertEqual(store.get(rid)['text_chars'],100)
    def test_capacity_is_explicit(self):
        for _ in range(16):self.begin()
        with self.assertRaisesRegex(ValueError,'容量'):self.begin()
    def test_active_tokens_survive_legacy_eviction(self):
        s=self.begin();row=self.service._session(s['research_id']);text=(self.vault/'计算机和AI/a.md').read_text()
        import hashlib
        for i in range(300):
            hit=self.service._publish(row,'计算机和AI/a.md',text,0,len(text),section_id='1')
        for i in range(270):self.notes.search_notes('星光',mode='keyword')
        verified=self.notes.verify_evidence(s['turn_id'],[dict(hit_token=hit['hit_token'],quote='星光是足够长的合成技术说明')])
        self.assertTrue(verified['all_valid'])
        for i in range(212):self.service._publish(row,'计算机和AI/a.md',text,0,len(text),section_id='1')
        with self.assertRaisesRegex(ValueError,'容量'):self.service._publish(row,'计算机和AI/a.md',text,0,len(text),section_id='1')
