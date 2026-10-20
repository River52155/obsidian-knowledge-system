import json,tempfile,unittest
from pathlib import Path

class ReliabilityEvaluationTest(unittest.TestCase):
    def test_six_distinct_cases_are_executed_and_missing_target_fails(self):
        from evaluate_reliability import run_program
        report=run_program()
        self.assertEqual(len(report['executed_cases']),6)
        self.assertEqual(len({r['corpus_hash'] for r in report['executed_cases']}),6)
        self.assertTrue(all(r['passed'] for r in report['executed_cases']))
        bad=run_program(extra_target='计算机和AI/不存在.md')
        self.assertFalse(bad['passed'])

    def test_named_diary_scope_excludes_other_personal_files(self):
        from evaluate_reliability import run_program
        report=run_program();month=next(x for x in report['executed_cases'] if x['case_id']=='months')
        self.assertEqual(month['found'],['我的存在/截至9月的日记.md'])
