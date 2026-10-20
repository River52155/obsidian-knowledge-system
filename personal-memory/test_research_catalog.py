import unittest,tempfile,sqlite3
from pathlib import Path
from memory_search import build,connect,search
from research_catalog import parse_sections,enumerate_sections,catalog_schema_version

class CatalogTest(unittest.TestCase):
    def test_october_sections_ignore_filename_month(self):
        text='\n'.join(f'# 2026 年 10 月 {d} 日\n观察{d}。' for d in (4,5,8,12))
        rows=parse_sections(text)
        self.assertEqual([s['heading_date'] for s in rows],['2026-10-04','2026-10-05','2026-10-08','2026-10-12'])
    def test_parent_year_and_ambiguous_dates(self):
        rows=parse_sections('# 2026年\n## 10月4日\n真实记录。\n## 2026年2月30日\n非法。\n# 10月5日\n不猜年份。')
        self.assertEqual([r['date_status'] for r in rows],['dated','ambiguous','ambiguous'])
    def test_fenced_heading_and_same_day_sections(self):
        rows=parse_sections('# 2026-10-04\n上午\n```md\n# 2026-10-05\n```\n# 2026-10-04\n晚上')
        self.assertEqual(len(rows),2);self.assertEqual(rows[1]['heading_date'],'2026-10-04')
    def test_date_parent_children_partition_without_overlap(self):
        text='# 2026年10月4日\n## 上午\n期待。\n## 晚上\n疲惫。\n# 2026年10月5日\n另一天。'
        rows=parse_sections(text)
        self.assertEqual([r['heading_date'] for r in rows],['2026-10-04','2026-10-04','2026-10-05'])
        for a,b in zip(rows,rows[1:]):self.assertLessEqual(a['end_offset'],b['start_offset'])
        self.assertIn('期待。',''.join(r['text'] for r in rows));self.assertIn('疲惫。',''.join(r['text'] for r in rows))
    def test_child_date_overrides_and_ambiguous_blocks(self):
        rows=parse_sections('# 2026-10-04\n## 2026-10-05\n五号\n## 2026-02-30\n### 子节\n不应沿用4号')
        self.assertEqual([r['heading_date'] for r in rows],['2026-10-05',None])
        self.assertEqual(rows[-1]['date_status'],'ambiguous')
    def test_empty_parent_preamble_and_undated_sibling(self):
        rows=parse_sections('---\na: b\n---\n前言\n# 2026年\n## 10月4日\n记录\n# 无日期\n未知')
        self.assertEqual([r['date_status'] for r in rows],['undated','dated','undated'])
        self.assertNotIn('a: b',''.join(r['text'] for r in rows))
    def test_multichunk_section_preserves_source_ranges(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'v/wiki').mkdir(parents=True);text='# 2026-10-04\n'+'正文。\n'*1000
            (p/'v/wiki/a.md').write_text(text);db=p/'db';build(p/'v',db)
            with connect(db) as con:
                self.assertEqual(catalog_schema_version(con),1)
                rows=enumerate_sections(con,{'wiki/a.md'},'2026-10-01','2026-10-31')
                spans=con.execute('select * from research_spans order by start_offset').fetchall()
            self.assertEqual(len(rows),1);self.assertGreater(len(spans),1)
            self.assertEqual(''.join(s['text'] for s in spans),text.rstrip('\n'))
    def test_old_schema_requests_reindex_without_breaking_search(self):
        con=sqlite3.connect(':memory:');self.assertEqual(catalog_schema_version(con),0)
    def test_mixed_full_and_partial_dates_are_ambiguous(self):
        row=parse_sections('# 2026-10-04、10月5日\n两天合并观察。')[0]
        self.assertEqual(row['date_status'],'ambiguous');self.assertIsNone(row['heading_date'])
    def test_shorter_fence_does_not_expose_code_heading(self):
        rows=parse_sections('# 2026-10-04\n正文\n````md\n```\n# 2026-10-05\n示例\n````\n正文结束')
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['heading_date'],'2026-10-04')
