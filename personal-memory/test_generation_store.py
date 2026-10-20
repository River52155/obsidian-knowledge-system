import json,tempfile,unittest
from pathlib import Path

class GenerationTest(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);(self.root/'generations').mkdir();(self.root/'baseline.sqlite3').touch()
  for i in range(5):
   d=self.root/'generations'/f'generation-{i}';d.mkdir()
   for n in ['baseline.sqlite3','embedding-index.npz','snapshot.json']:(d/n).write_text('synthetic')
  (self.root/'active-index.json').write_text(json.dumps(dict(generation='generation-0')));(self.root/'pinned-generations.json').write_text(json.dumps(dict(schema_version=1,generations=['generation-1'])))
 def tearDown(self):self.tmp.cleanup()
 def test_dry_run_keeps_active_two_recent_and_pins(self):
  from generation_store import plan_prune,apply_prune
  plan=plan_prune(self.root);self.assertEqual(set(plan['keep']),{'generation-0','generation-1','generation-3','generation-4'});self.assertTrue((self.root/'generations/generation-2').exists())
  report=apply_prune(self.root);self.assertEqual(report['removed'],['generation-2']);self.assertTrue((self.root/'baseline.sqlite3').exists())
 def test_service_lock_blocks_apply(self):
  from generation_store import service_lock,apply_prune
  with service_lock(self.root):
   with self.assertRaises(ValueError):apply_prune(self.root)
 def test_bad_pointer_pins_symlink_and_incomplete_not_deleted(self):
  from generation_store import plan_prune,apply_prune
  (self.root/'generations/generation-link').symlink_to(self.root/'generations/generation-2');(self.root/'generations/generation-incomplete').mkdir();p=plan_prune(self.root);self.assertIn('generation-link',p['skipped']);self.assertIn('generation-incomplete',p['skipped'])
  (self.root/'pinned-generations.json').write_text('{broken')
  with self.assertRaises(ValueError):apply_prune(self.root)
 def test_apply_replans_after_pin_change(self):
  from generation_store import plan_prune,apply_prune
  self.assertIn('generation-2',plan_prune(self.root)['candidates']);(self.root/'pinned-generations.json').write_text(json.dumps(dict(schema_version=1,generations=['generation-1','generation-2'])));self.assertEqual(apply_prune(self.root)['removed'],[])
