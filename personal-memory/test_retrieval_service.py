import tempfile
import unittest
import json
import threading
from urllib.request import Request, urlopen
from pathlib import Path

from memory_search import build, make_server
try:
    from retrieval_service import RetrievalService
except ImportError:
    RetrievalService = None


class RetrievalServiceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.vault = self.root / 'vault'
        (self.vault / 'wiki/a').mkdir(parents=True)
        (self.vault / 'wiki/b').mkdir()
        self.note = self.vault / 'wiki/a/相同.md'
        self.note.write_text('# 天空\n\n星光照亮夜晚，这是原来保存的一条观察记录。\n')
        (self.vault / 'wiki/b/相同.md').write_text('# 天空\n\n这是另一篇关于星光的笔记，请避免混淆文件。\n')
        self.db = self.root / 'baseline.sqlite3'
        build(self.vault, self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def service(self):
        self.assertIsNotNone(RetrievalService, 'RetrievalService is not implemented')
        return RetrievalService(lambda: self.db)

    def test_folder_filter_and_exact_source_resolution(self):
        s = self.service()
        out = s.search_notes('星光', folder='wiki/a', mode='keyword')
        self.assertEqual([h['path'] for h in out['hits']], ['wiki/a/相同.md'])
        h = out['hits'][0]
        self.assertNotIn(str(self.vault), str(out))
        self.assertTrue(h['open_url'].startswith('obsidian://memory-source?'))
        excerpt = s.get_excerpt(h['hit_token'], context_lines=0)
        self.assertEqual(excerpt['text'], '# 天空\n\n星光照亮夜晚，这是原来保存的一条观察记录。')
        self.assertEqual(excerpt['start_line'], 1)

    def test_changed_file_before_index_refresh_rejects_old_line(self):
        s = self.service()
        h = s.search_notes('星光', folder='wiki/a', mode='keyword')['hits'][0]
        self.note.write_text('# 改过了\n\n原文已经改变，旧行号不能再使用。\n')
        with self.assertRaisesRegex(ValueError, '原文'):
            s.get_excerpt(h['hit_token'])

    def test_changed_first_candidate_does_not_hide_current_next_result(self):
        s=self.service()
        original=s.search_notes('星光',limit=1,mode='keyword')['hits'][0]
        (self.vault/original['path']).write_text('# 新内容\n这篇笔记刚刚修改。\n')
        result=s.search_notes('星光',limit=1,mode='keyword')
        self.assertEqual(len(result['hits']),1)
        self.assertNotEqual(result['hits'][0]['path'],original['path'])
        self.assertEqual(result['hits'][0]['source_status'],'current')

    def test_index_switch_and_expired_token_are_rejected(self):
        s = self.service()
        h = s.search_notes('星光', mode='keyword')['hits'][0]
        second = self.root / 'second.sqlite3'
        build(self.vault, second)
        self.db = second
        with self.assertRaisesRegex(ValueError, '索引'):
            s.get_excerpt(h['hit_token'])
        h = s.search_notes('星光', mode='keyword')['hits'][0]
        s.hits[h['hit_token']]['created'] -= 1000
        with self.assertRaisesRegex(ValueError, '过期'):
            s.get_excerpt(h['hit_token'])

    def test_unindexed_and_escaping_paths_never_read(self):
        s = self.service()
        for folder in ['../重要信息','raw','wiki/../../重要信息','wiki/.hidden','/etc']:
            with self.subTest(folder=folder), self.assertRaises(ValueError):
                s.search_notes('星光', folder=folder, mode='keyword')
        with self.assertRaises(ValueError):
            s.get_excerpt('/etc/passwd')

    def test_scope_limit_and_context_budget(self):
        s = self.service()
        with self.assertRaises(ValueError):
            s.search_notes('星光', limit=100, mode='keyword')
        out = s.search_notes('星光', mode='keyword')
        self.assertLessEqual(len(__import__('json').dumps(out, ensure_ascii=False)), 16000)
        with self.assertRaises(ValueError):
            s.get_excerpt(out['hits'][0]['hit_token'], context_lines=100000)

    def test_http_health_and_native_search_share_validated_sources(self):
        server = make_server(self.db, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        def post(path, value):
            req = Request(base+path,json.dumps(value).encode(),{'Content-Type':'application/json','Origin':base})
            with urlopen(req) as response:
                return json.load(response)
        try:
            with urlopen(base+'/api/health') as response:
                self.assertEqual(json.load(response)['service_id'], 'river.personal-memory')
            h = post('/api/notes/search',{'query':'星光','folder':'wiki/a','mode':'keyword'})['hits'][0]
            out = post('/api/notes/excerpt',{'hit_token':h['hit_token'],'context_lines':0})
            self.assertEqual(out['path'], 'wiki/a/相同.md')
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_v2_and_current_note_resolution_without_body_reads(self):
        from unittest.mock import patch
        from urllib.parse import parse_qs,urlparse
        spaced=self.vault/'wiki/a/含 空格.md'; spaced.write_text('星光 空格路由测试。')
        build(self.vault,self.db)
        s=self.service(); h=next(h for h in s.search_notes('星光',mode='keyword')['hits'] if h['path'].endswith('含 空格.md'))
        self.assertIn('%20',h['open_url']); self.assertNotIn('+',h['open_url'])
        fields=parse_qs(urlparse(h['open_url']).query)
        self.assertNotIn('path',fields); self.assertEqual(fields['note'],[h['path']])
        self.assertEqual(fields['v'],['2']); self.assertEqual(fields['vault'],['vault']); self.assertEqual(fields['vault_id'],[s.health()['vault_id']])
        with patch.object(Path,'read_bytes',side_effect=AssertionError('resolve must not read text')):
            resolved=s.resolve_note('wiki/a/相同.md',h['vault_id'])
        self.assertEqual(resolved,dict(path='wiki/a/相同.md',vault_id=h['vault_id'],title='相同'))
        h2=s.search_notes('星光',folder='wiki/b',mode='keyword')['hits'][0]
        self.assertNotEqual(s.resolve_note(h2['path'],h2['vault_id'])['path'],resolved['path'])

    def test_resolve_denies_foreign_protected_unindexed_and_symlink_paths(self):
        s=self.service(); identity=s.health()['vault_id']
        (self.vault/'wiki/not indexed.md').write_text('not indexed')
        (self.vault/'wiki/link').symlink_to(self.vault/'wiki/a',target_is_directory=True)
        for path,code in [('wiki/not indexed.md','SOURCE_FORBIDDEN'),('wiki/link/相同.md','SOURCE_FORBIDDEN'),('../wiki/a/相同.md','SOURCE_FORBIDDEN'),('重要信息/a.md','SOURCE_FORBIDDEN'),('wiki//a/相同.md','SOURCE_FORBIDDEN')]:
            with self.subTest(path=path),self.assertRaises(ValueError) as caught:s.resolve_note(path,identity)
            self.assertEqual(caught.exception.code,code)
        with self.assertRaises(ValueError) as caught:s.resolve_note('wiki/a/相同.md','0'*64)
        self.assertEqual(caught.exception.code,'VAULT_MISMATCH')
        self.note.unlink()
        with self.assertRaises(ValueError) as caught:s.resolve_note('wiki/a/相同.md',identity)
        self.assertEqual(caught.exception.code,'SOURCE_MISSING')

    def test_source_error_codes_are_stable(self):
        s=self.service(); h=s.search_notes('星光',folder='wiki/a',mode='keyword')['hits'][0]
        self.note.write_text('changed')
        with self.assertRaises(ValueError) as caught:s.get_excerpt(h['hit_token'])
        self.assertEqual(caught.exception.code,'SOURCE_CHANGED')
        s.hits[h['hit_token']]['created']-=1000
        with self.assertRaises(ValueError) as caught:s.get_excerpt(h['hit_token'])
        self.assertEqual(caught.exception.code,'SOURCE_EXPIRED')

    def test_turn_continuations_dedup_before_limit_and_stop_without_search(self):
        from unittest.mock import patch
        for i in range(12):(self.vault/f'wiki/extra{i}.md').write_text(f'# 星光{i}\n星光记录编号{i}，夜晚可以观察不同的星光轨迹。')
        build(self.vault,self.db);s=self.service()
        first=s.search_notes('星光',mode='keyword');turn=first['turn_id']
        second=s.search_notes('星光',mode='keyword',turn_id=turn,purpose='找尚未返回的观察记录')
        self.assertTrue(second['hits']);self.assertTrue(second['already_seen'])
        self.assertFalse({h['text'] for h in first['hits']}&{h['text'] for h in second['hits']})
        self.assertEqual(second['turn_stats']['original_query'],'星光')
        s.search_notes('星光',mode='keyword',turn_id=turn,purpose='补足缺口')
        with patch('retrieval_service.search',side_effect=AssertionError('must not search a fourth time')):
            stopped=s.search_notes('星光',mode='keyword',turn_id=turn,purpose='another gap')
        self.assertEqual(stopped['stop_reason'],'SEARCH_LIMIT');self.assertFalse(stopped['hits'])
        self.assertTrue(s.search_notes('星光',mode='keyword')['hits'])

    def test_excerpt_charges_expansion_but_omitting_turn_cannot_bypass_budget(self):
        self.note.write_text('before context line\n# 星光\n星光照亮夜晚，这是原来保存的一条观察记录。\n# next\nextra context after the heading\nline six\nline seven\nline eight\nline nine')
        build(self.vault,self.db);s=self.service();first=s.search_notes('星光',folder='wiki/a',mode='keyword');h=first['hits'][0];turn=first['turn_id']
        chars=first['turn_stats']['text_chars'];out=s.get_excerpt(h['hit_token'],2,turn)
        self.assertEqual(s.contexts.stats(turn)['text_chars'],chars+len(out['text']))
        with self.assertRaises(ValueError):s.get_excerpt(h['hit_token'],0,s.search_notes('星光',mode='keyword')['turn_id'])
        s.contexts.admit_text(turn,'x'*(24000-s.contexts.stats(turn)['text_chars']))
        with self.assertRaises(ValueError) as caught:s.get_excerpt(h['hit_token'],24)
        self.assertEqual(caught.exception.code,'TURN_BUDGET')

    def test_json_discard_is_not_charged_or_marked_seen(self):
        self.note.write_text('# 星光\n'+'星光'*9000)
        build(self.vault,self.db);s=self.service();out=s.search_notes('星光',folder='wiki/a',mode='keyword')
        self.assertLessEqual(len(json.dumps(out,ensure_ascii=False)),16000)
        self.assertEqual(out['turn_stats']['text_chars'],0);self.assertFalse(out['hits'])
        self.assertEqual(s.contexts.stats(out['turn_id'])['unique_texts'],0)

    def test_verify_only_returned_text_dedup_and_partial_failures_without_charge(self):
        self.note.write_text('# 星光\n星光照亮夜晚，这是原来保存的一条观察记录。\n# 其他\n这段隐藏的上下文尚未发送，不能用来核对任何引用。')
        build(self.vault,self.db);s=self.service();out=s.search_notes('星光',folder='wiki/a',mode='keyword',limit=1);h=out['hits'][0];turn=out['turn_id']
        item=dict(hit_token=h['hit_token'],quote='星光照亮夜晚，这是原来保存的一条观察记录。')
        stats=s.contexts.stats(turn)
        result=s.verify_evidence(turn,[item,item]);self.assertTrue(result['all_valid']);self.assertEqual(len(result['verified']),1)
        self.assertEqual(result['verified'][0]['quote_start_line'],2);self.assertNotIn('quote',result['verified'][0]);self.assertEqual(s.contexts.stats(turn),stats)
        hidden=dict(hit_token=h['hit_token'],quote='这段隐藏的上下文尚未发送，不能用来核对任何引用。')
        failed=s.verify_evidence(turn,[item,hidden]);self.assertFalse(failed['all_valid']);self.assertEqual(failed['rejected'][0]['index'],1)
        s.get_excerpt(h['hit_token'],8,turn)
        self.assertTrue(s.verify_evidence(turn,[hidden])['all_valid'])

    def test_verify_rejects_wrong_turn_expired_changed_generation_and_bad_items(self):
        s=self.service();out=s.search_notes('星光',folder='wiki/a',mode='keyword');h=out['hits'][0];turn=out['turn_id']
        item=dict(hit_token=h['hit_token'],quote='星光照亮夜晚，这是原来保存的一条观察记录。')
        other=s.search_notes('星光',mode='keyword')['turn_id']
        self.assertEqual(s.verify_evidence(other,[item])['rejected'][0]['code'],'TURN_MISMATCH')
        for bad in [None,{},[],[item]*9,'bad']:
            with self.subTest(bad=bad),self.assertRaises(ValueError):s.verify_evidence(turn,bad)
        for bad in [None,{},dict(hit_token=[],quote='secret should not appear'),dict(hit_token=h['hit_token'],quote='short')]:
            rejected=s.verify_evidence(turn,[bad]);self.assertFalse(rejected['all_valid']);self.assertNotIn('secret should not appear',str(rejected))
        self.note.write_text('changed')
        self.assertEqual(s.verify_evidence(turn,[item])['rejected'][0]['code'],'SOURCE_CHANGED')
        second=self.root/'second.sqlite3';build(self.vault,second);self.db=second
        self.assertEqual(s.verify_evidence(turn,[item])['rejected'][0]['code'],'INDEX_CHANGED')
        s.hits[h['hit_token']]['created']-=1000
        self.assertEqual(s.verify_evidence(turn,[item])['rejected'][0]['code'],'SOURCE_EXPIRED')

    def test_same_name_markdown_and_text_labels_terminate_and_differ(self):
        import signal
        for name in ['wiki/同名.md','wiki/同名.txt']:(self.vault/name).write_text('# 星光\n星光照亮夜晚，这是测试用的原始观察。'+name[-3:])
        build(self.vault,self.db);s=self.service();out=s.search_notes('星光',folder='wiki',mode='keyword')
        hits=[h for h in out['hits'] if h['path'] in {'wiki/同名.md','wiki/同名.txt'}]
        self.assertEqual(len(hits),2)
        previous=signal.signal(signal.SIGALRM,lambda *_:(_ for _ in ()).throw(TimeoutError('label disambiguation never terminated')))
        try:
            signal.setitimer(signal.ITIMER_REAL,1)
            result=s.verify_evidence(out['turn_id'],[dict(hit_token=h['hit_token'],quote='星光照亮夜晚，这是测试用的原始观察。') for h in hits])
        finally:signal.setitimer(signal.ITIMER_REAL,0);signal.signal(signal.SIGALRM,previous)
        self.assertTrue(result['all_valid']);self.assertEqual(len({h['label'] for h in result['verified']}),2)

    def test_budget_admission_backfills_after_arbitrarily_many_large_candidates(self):
        # A fixed candidate multiplier is insufficient; all 35 earlier candidates are too large.
        for i in range(35):(self.vault/f'wiki/星光{i:02}.md').write_text('# 星光\n'+'星光'*9000+str(i))
        (self.vault/'wiki/星光99.md').write_text('# 星光\n星光照亮夜晚，这是可以放入预算的简短材料。')
        build(self.vault,self.db);s=self.service();out=s.search_notes('星光',mode='keyword',limit=1)
        self.assertEqual(len(out['hits']),1)
        self.assertLess(len(out['hits'][0]['text']),100)
        # Existing turn budget must also allow a smaller later candidate to fill the slot.
        s=self.service();turn=s.contexts.start('星光');s.contexts.admit_text(turn,'x'*23950)
        out=s.search_notes('星光',mode='keyword',limit=1,turn_id=turn)
        self.assertEqual(len(out['hits']),1);self.assertLessEqual(out['turn_stats']['text_chars'],24000)

    def test_index_change_invalidates_turn_instead_of_returning_stale_seen_tokens(self):
        s=self.service();first=s.search_notes('星光',mode='keyword')
        second=self.root/'new.sqlite3';build(self.vault,second);self.db=second
        with self.assertRaises(ValueError) as caught:s.search_notes('星光',mode='keyword',turn_id=first['turn_id'],purpose='补上下文')
        self.assertEqual(caught.exception.code,'INDEX_CHANGED')
        current=s.search_notes('星光',mode='keyword');self.assertTrue(current['hits'])
        self.assertTrue(s.verify_evidence(current['turn_id'],[dict(hit_token=current['hits'][0]['hit_token'],quote='星光照亮夜晚，这是原来保存的一条观察记录。')])['all_valid'])

    def test_excerpt_serialized_json_is_bounded_without_double_highlight_body(self):
        self.note.write_text('# 星光\n'+('星光观察'*2250))
        build(self.vault,self.db);s=self.service();out=s.search_notes('星光',folder='wiki/a',mode='keyword');hit=out['hits'][0]
        excerpt=s.get_excerpt(hit['hit_token'],0)
        self.assertLessEqual(len(json.dumps(excerpt,ensure_ascii=False)),16000)
        self.assertEqual(excerpt['text'],hit['text'])
        self.assertTrue(s.verify_evidence(out['turn_id'],[dict(hit_token=hit['hit_token'],quote='星光观察'*4)])['all_valid'])


if __name__ == '__main__':
    unittest.main()
