"""Focused checks for source fidelity, exclusions, and index replacement."""
import json
from pathlib import Path
import tempfile
import unittest
from memory_search import build, chunks, metadata, search


class RetrievalTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.vault = self.base / 'vault'
        self.db = self.base / 'index/db.sqlite3'
        self.vault.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def put(self, relative, text):
        p = self.vault / relative
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding='utf-8')
        return p

    def test_exact_source_lines_and_heading_date(self):
        text = '---\ntype: note\n---\n# 日记\n## 2026 年 9 月 8 日\n练习观察星空。\n\n一小段原文。\n## 下一天\n散步。\n'
        for part in chunks(text, limit=20):
            self.assertEqual(part['text'], '\n'.join(text.splitlines()[part['start_line']-1:part['end_line']]))
        self.put('我的存在/感受.md', text)
        build(self.vault, self.db)
        results = search(self.db, '练习观察星空')['results']
        self.assertTrue(results)
        self.assertEqual(results[0]['date_label'], '2026 年 9 月 8 日')
        self.assertEqual(results[0]['source_status'], 'current')

    def test_protected_raw_symlink_and_secret_exclusion(self):
        self.put('我的存在/普通.md', '# 安全\n普通文字')
        for relative in ['重要信息/a.md', 'raw/a.md', '我的存在/重要信息/a.md', '我的存在/.hidden/a.md']:
            self.put(relative, '不可索引机密')
        secret = 'sk-' + 'a' * 32
        self.put('wiki/暴露.md', '# 注释\n' + secret)
        self.put('我的存在/密码.md', '不可索引机密')
        outside = self.base / 'outside.md'
        outside.write_text('不可索引机密')
        (self.vault / '我的存在/link.md').symlink_to(outside)
        build(self.vault, self.db)
        self.assertFalse(search(self.db, '不可索引机密')['results'])
        self.assertNotIn(secret.encode(), self.db.read_bytes())
        inv = metadata(self.db, 'inventory')
        self.assertEqual(sum(r['status']=='excluded_suspected_secret' for r in inv), 1)
        self.assertFalse(any('重要信息' in r['path'] or r['path'].startswith('raw/') for r in inv))

    def test_rebuild_removes_deleted_and_renamed_paths(self):
        p = self.put('我的存在/旧.md', '和解提醒')
        build(self.vault, self.db)
        p.rename(p.with_name('新.md'))
        self.assertEqual(search(self.db, '和解')['results'][0]['source_status'], 'missing_or_moved')
        build(self.vault, self.db)
        self.assertEqual(search(self.db, '和解')['results'][0]['path'], '我的存在/新.md')
        p.with_name('新.md').unlink()
        build(self.vault, self.db)
        self.assertFalse(search(self.db, '和解')['results'])

    def test_changed_source_flag_and_read_only_build(self):
        p = self.put('wiki/a.md', '# Embedding\n语义向量搜索。')
        original = p.read_bytes()
        build(self.vault, self.db)
        self.assertEqual(p.read_bytes(), original)
        p.write_text('# 修改过的内容')
        self.assertEqual(search(self.db, 'Embedding')['results'][0]['source_status'], 'changed')

    def test_filters_and_fts_query_punctuation(self):
        self.put('wiki/a.md', 'Embedding 向量')
        self.put('我的存在/b.md', 'Embedding 学习笔记')
        build(self.vault, self.db)
        self.assertEqual(search(self.db, 'Embedding " OR *', 'wiki')['results'][0]['kind'], 'wiki')
        self.assertEqual(search(self.db, 'Embedding', 'source')['results'][0]['kind'], 'source')
        self.assertFalse(search(self.db, '???')['results'])

    def test_heading_only_fragments_are_not_search_results(self):
        self.put('wiki/a.md', '# Embedding\n\n## 一句话解释\n文字转成向量。\n\n## 核心\n相近的意思。\n')
        build(self.vault, self.db)
        results = search(self.db, 'Embedding')['results']
        self.assertTrue(results)
        self.assertTrue(all('文字转成向量' in r['text'] or '相近的意思' in r['text'] for r in results))

    def test_cannot_write_index_inside_vault(self):
        with self.assertRaises(ValueError):
            build(self.vault, self.vault / 'new.db')

    def test_explicit_topic_survives_question_boilerplate(self):
        self.put('wiki/Embedding.md', '# Embedding\n## 一句话解释\n把文字转换成可以比较的数字表示，用来寻找相关资料。\n## 关联\n[[别的页面]] 与其他概念的关系。')
        self.put('wiki/水果.md', '# 有什么区别\n苹果与梨有什么区别？这两者的区别是什么？')
        build(self.vault, self.db)
        before = self.db.read_bytes()
        value = search(self.db, 'Embedding 是什么？它和负责回答的大模型有什么区别？', mode='keyword')
        self.assertEqual(value['results'][0]['path'], 'wiki/Embedding.md')
        self.assertIn('一句话解释', value['results'][0]['heading'])
        self.assertEqual(value['query_focus'], ['embedding'])
        self.assertEqual(before, self.db.read_bytes())

    def test_topic_word_boundaries_and_scope(self):
        self.put('wiki/Embedding.md', '# 一句话解释\n这是一段有关文字转换成向量的技术说明。')
        self.put('我的存在/普通.md', '# 学习\nEmbedding 是我最近接触的一个技术术语。')
        build(self.vault, self.db)
        for q in ('myembeddingtest', '123embedding', '_embedding'):
            self.assertEqual(search(self.db, q)['query_focus'], [])
        self.assertEqual(search(self.db, 'Embedding', 'source')['query_focus'], [])

    def test_multiple_topics_and_chinese_title(self):
        for name in ('Embedding', 'Transformer', '个人记录与未来自我对话'):
            self.put('wiki/'+name+'.md', '# '+name+'\n## 一句话解释\n这里有一段足够完整的正文，用于说明这个页面的主要内容。')
        build(self.vault, self.db)
        value = search(self.db, 'Embedding 和 Transformer 的区别是什么？')
        self.assertEqual([r['path'] for r in value['results'][:2]], ['wiki/Embedding.md','wiki/Transformer.md'])
        value = search(self.db, '我之前的“个人记录与未来自我对话”讲了什么？')
        self.assertEqual(value['results'][0]['path'], 'wiki/个人记录与未来自我对话.md')
        self.assertEqual(value['query_focus'], ['个人记录与未来自我对话'])

    def test_reference_only_page_does_not_get_reserved_slot(self):
        self.put('wiki/Embedding.md', '# Embedding\n## 关联\n[[参考资料链接]] 这里只列出相关条目的导航入口。')
        build(self.vault, self.db)
        self.assertEqual(search(self.db, 'Embedding')['query_focus'], [])


if __name__ == '__main__':
    unittest.main()
