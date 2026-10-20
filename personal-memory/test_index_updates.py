import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from answering import DeepSeek
from index_updates import IndexUpdates, snapshot
from memory_search import build, make_server, search
from semantic_search import read_corpus


class UpdateTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.vault = self.root / 'vault'
        (self.vault / 'wiki').mkdir(parents=True)
        self.note = self.vault / 'wiki/测试.md'
        self.note.write_text('# 测试\n过去保留的旧内容，用来测试变化。\n')
        self.base = self.root / 'data/baseline.sqlite3'
        build(self.vault, self.base)
        self.embeds = 0
        def embed(db, dest):
            self.embeds += 1
            dest.write_text(read_corpus(db)[1])
        def validate(db):
            if (db.parent / 'embedding-index.npz').read_text() != read_corpus(db)[1]:
                raise ValueError('mismatch')
        self.update = IndexUpdates(self.base, embed=embed, validate=validate)

    def tearDown(self):
        self.temp.cleanup()

    def test_success_clears_active_error_preserves_failure_history(self):
        self.update.refresh();self.note.write_text('内容更新后模拟一次失败。')
        with patch.object(self.update,'embed',side_effect=ValueError('synthetic')):self.update.refresh()
        self.assertIsNotNone(self.update.status()['active_error'])
        self.update.refresh();state=self.update.status()
        self.assertIsNone(state['active_error']);self.assertIsNone(state.get('error_type'));self.assertIsNotNone(state['last_failure'])
        self.assertEqual(state['pending_changes'],dict(added=0,removed=0,modified=0))

    def test_unchanged_text_rebuilds_invalid_artifact_or_contract(self):
        self.update.refresh();old=self.update.current_db()
        (old.parent/'embedding-index.npz').write_text('corrupted')
        self.update.refresh();self.assertNotEqual(self.update.current_db(),old)

    def test_invalid_utf8_reports_safe_path_and_keeps_old_generation(self):
        self.update.refresh();old=self.update.current_db();self.note.write_bytes(b'\xff\xfe')
        self.update.refresh();state=self.update.status()
        self.assertEqual(self.update.current_db(),old)
        self.assertEqual(state['active_error']['paths'],['wiki/测试.md'])
        self.assertEqual(state['active_error']['code'],'READ_FAILED')

    def test_missing_active_sqlite_rebuilds_from_sources(self):
        self.update.refresh();old=self.update.current_db();old.unlink()
        self.update.refresh();self.assertNotEqual(self.update.current_db(),old)
        self.assertEqual(self.update.status()['state'],'current')

    def test_reverted_change_clears_pending_and_progress(self):
        original=self.note.read_text();self.update.refresh();self.note.write_text('后来又撤销的修改。')
        with patch.object(self.update,'embed',side_effect=ValueError('fail')):self.update.refresh()
        self.note.write_text(original);self.update.refresh();state=self.update.status()
        self.assertEqual(state['pending_changes'],dict(added=0,removed=0,modified=0));self.assertIsNone(state['progress'])

    def test_restore_pair_reopens_expected_source(self):
        from index_updates import atomic_json
        source=self.note.read_text();self.update.refresh();old=self.update.current_db()
        self.note.write_text('新内容作为第二代合成资料。');self.update.refresh()
        self.note.write_text(source);atomic_json(self.update.pointer,dict(generation=old.parent.name,updated_at='2026-10-20T00:00:00+08:00'))
        restored=IndexUpdates(self.base,embed=self.update.embed,validate=self.update.validate);count=self.embeds;restored.refresh()
        self.assertEqual(restored.current_db(),old);self.assertEqual(self.embeds,count)
        self.assertTrue(search(restored.current_db(),'过去',current_only=True)['results'])

    def test_parser_upgrade_without_vault_change_builds_new_generation(self):
        import sqlite3
        self.update.refresh();old=self.update.current_db()
        with sqlite3.connect(old) as con:con.execute("DELETE FROM meta WHERE key='research_parser_version'")
        self.update.refresh();self.assertNotEqual(self.update.current_db(),old)
        from research_catalog import catalog_schema_version
        from memory_search import connect
        with connect(self.update.current_db()) as con:self.assertEqual(catalog_schema_version(con),1)

    def test_add_modify_rename_delete_and_empty_publish(self):
        self.update.refresh()
        initial = self.update.current_db()
        added = self.vault / 'wiki/新增.md'
        added.write_text('# 新增\n这里记录银河旅行的新计划。\n')
        self.note.write_text('# 测试\n修改后描述海洋探索的新内容。\n')
        self.update.refresh()
        current = self.update.current_db()
        self.assertNotEqual(current, initial)
        self.assertTrue(search(current, '银河')['results'])
        self.assertTrue(all('过去保留的旧内容' not in r['text'] for r in read_corpus(current)[0]))
        renamed = added.with_name('改名.md')
        added.rename(renamed)
        self.note.unlink()
        self.update.refresh()
        result = search(self.update.current_db(), '银河')['results']
        self.assertEqual(result[0]['path'], 'wiki/改名.md')
        renamed.unlink()
        self.update.refresh()
        self.assertEqual(search(self.update.current_db(), '银河')['results'], [])
        self.assertTrue(initial.is_file())  # Older generation remains recoverable.

    def test_no_change_skips_encoding_and_restart_reuses_generation(self):
        self.update.refresh()
        active = self.update.current_db()
        self.update.refresh()
        self.assertEqual(self.embeds, 1)
        restored = IndexUpdates(self.base, embed=self.update.embed, validate=self.update.validate)
        restored.refresh()
        self.assertEqual(restored.current_db(), active)
        self.assertEqual(self.embeds, 1)

    def test_failure_keeps_active_pair_and_cleans_unpublished_files(self):
        self.update.refresh()
        active = self.update.current_db()
        pointer = self.update.pointer.read_bytes()
        self.note.write_text('修改后的内容。')
        with patch.object(self.update, 'embed', side_effect=ValueError('failure')):
            self.update.refresh()
        self.assertEqual(self.update.current_db(), active)
        self.assertEqual(self.update.pointer.read_bytes(), pointer)
        self.assertEqual(len(list(self.update.directory.iterdir())), 1)
        self.assertEqual(self.update.status()['state'], 'error')

    def test_source_changes_during_encoding_do_not_publish(self):
        self.update.refresh()
        active = self.update.current_db()
        original = self.update.embed
        self.note.write_text('正在修改的内容。')
        def changing(db, dest):
            original(db, dest)
            self.note.write_text('编码结束之前又一次修改的内容。')
        with patch.object(self.update, 'embed', side_effect=changing):
            self.update.refresh()
        self.assertEqual(self.update.current_db(), active)
        self.assertEqual(self.update.status()['state'], 'error')

    def test_mismatched_vectors_and_read_failure_cannot_publish(self):
        self.update.refresh()
        active = self.update.current_db()
        self.note.write_text('这次内容发生修改。')
        with patch.object(self.update, 'embed', side_effect=lambda db, dest: dest.write_text('wrong')):
            self.update.refresh()
        self.assertEqual(self.update.current_db(), active)
        self.note.write_bytes(b'\xff\xfe')
        self.update.refresh()
        self.assertEqual(self.update.current_db(), active)

    def test_snapshot_scope_does_not_open_blocked_or_attachment_files(self):
        for relative in ('raw/no.md','重要信息/no.md','wiki/.hidden/no.md','wiki/archive/no.md'):
            p = self.vault / relative
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text('不进入快照')
        attachment = self.vault / 'wiki/picture.png'
        attachment.write_bytes(b'fake')
        sensitive = self.vault / 'wiki/密码.md'
        sensitive.write_text('not-a-real-secret')
        (self.vault / 'wiki/link.md').symlink_to(self.note)
        original = Path.read_bytes
        def checked(path):
            self.assertNotEqual(path, attachment)
            self.assertNotEqual(path, sensitive)
            self.assertNotIn('raw', path.parts)
            self.assertNotIn('重要信息', path.parts)
            return original(path)
        with patch.object(Path, 'read_bytes', checked):
            value = snapshot(self.vault)
        self.assertEqual(set(value), {'wiki/测试.md','wiki/picture.png','wiki/密码.md'})

    def test_http_rejects_old_selection_and_provider_survives_switch(self):
        self.update.refresh()
        provider = DeepSeek()
        with patch.object(provider, '_request', return_value={'data':[{'id':'test-model'}]}):
            provider.configure('test-key-not-a-real-credential')
        server = make_server(self.base, 0, provider, updates=self.update)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        try:
            with urlopen(base+'/api/search?q=test&mode=keyword') as r:
                revision = json.load(r)['index_revision']
            self.note.write_text('# 测试\n未来新的内容，原来的编号可能被重新使用。')
            self.update.refresh()
            data = dict(query='test', mode='keyword', selected_ids=[1], index_revision=revision)
            req = Request(base+'/api/prepare',json.dumps(data).encode(),{'Origin':base,'Content-Type':'application/json'})
            with self.assertRaises(HTTPError) as caught:
                urlopen(req)
            self.assertEqual(caught.exception.code, 400)
            self.assertIn('索引已更新', json.load(caught.exception)['error'])
            self.assertTrue(provider.status()['connected'])
            with urlopen(base+'/api/index/status') as r:
                self.assertEqual(json.load(r)['state'], 'current')
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_background_timer_and_manual_trigger_publish_without_restart(self):
        def wait_for(predicate):
            deadline = time.monotonic() + 3
            while not predicate() and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertTrue(predicate())
        self.update.interval = .03
        self.update.start()
        try:
            wait_for(lambda: self.update.current_db() != self.base.resolve())
            first = self.update.current_db()
            self.note.write_text('后台定期检查应当找到这次修改。')
            wait_for(lambda: self.update.current_db() != first)
            self.update.stop()
            self.update.thread.join(3)
            self.assertFalse(self.update.thread.is_alive())
            self.update.stopped.clear()
            self.update.interval = 3600
            self.update.start()
            wait_for(lambda: not self.update.status()['running'])
            second = self.update.current_db()
            self.note.write_text('手动检查应当马上找到这次修改。')
            self.update.trigger()
            wait_for(lambda: self.update.current_db() != second)
        finally:
            self.update.stop()
            self.update.thread.join(3)


if __name__ == '__main__':
    unittest.main()
