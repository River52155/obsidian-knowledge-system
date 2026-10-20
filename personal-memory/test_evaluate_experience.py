import tempfile
import unittest
from pathlib import Path
from memory_search import build
import evaluate_experience as evaluation


class ExperienceTest(unittest.TestCase):
    def test_rank_and_missing_are_reported_per_target(self):
        rows=[dict(path='wiki/a.md',start_line=3,end_line=7)]
        self.assertEqual(evaluation.ranks(rows,[dict(path='wiki/a.md',line=5),dict(path='wiki/a.md',line=8),dict(path='wiki/b.md')]),[1,None,None])

    def test_only_explicit_snapshot_is_used_even_with_live_pointer(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); vault=root/'vault'; (vault/'wiki').mkdir(parents=True)
            (vault/'wiki/a.md').write_text('# 星光\n星光照亮夜晚，这是一条测试记录。')
            fixed=root/'fixed';fixed.mkdir();build(vault,fixed/'baseline.sqlite3')
            (fixed/'active-index.json').write_text('{"generation":"does-not-exist"}')
            out=evaluation.evaluate([dict(label='原词',query='星光',mode='keyword',targets=[dict(path='wiki/a.md'),dict(path='wiki/missing.md')])],fixed)
            self.assertEqual(out['rows'][0]['ranks'],[1,None])
            self.assertEqual(out['rows'][0]['missing_targets'],['wiki/missing.md'])
            self.assertEqual(out['snapshot_db'],str((fixed/'baseline.sqlite3').resolve()))
            self.assertTrue(out['unchanged'])
            with self.assertRaises(ValueError):evaluation.evaluate([],root/'absent')
