import unittest,json
from unittest.mock import patch
import numpy as np
import test_embedding_artifacts as support
from memory_search import build
import semantic_search as sem

class ReuseTest(unittest.TestCase):
 setUp=support.ArtifactTest.setUp
 tearDown=support.ArtifactTest.tearDown
 def rebuild(self):
  target=self.root/'new/baseline.sqlite3';build(self.vault,target);self.encoder.encoded=[];meta=sem.build_embeddings(target,target.parent/'embedding-index.npz',reuse_from=self.db.parent,write_report=False);sem.validate_index(target);return meta,target
 def test_no_change_encodes_zero(self):
  meta,p=self.rebuild();self.assertEqual(self.encoder.encoded,[]);self.assertEqual(meta['encoded_unique_inputs'],0);self.assertGreater(meta['reused_vectors'],0)
 def test_one_input_change_only_encodes_missing_key(self):
  self.note.write_text(self.note.read_text().replace('这','那',1));meta,p=self.rebuild();self.assertEqual(len(self.encoder.encoded),1);self.assertIn('那是一段',self.encoder.encoded[0]);self.assertGreater(meta['reused_vectors'],0)
 def test_chunk_id_shift_preserves_vectors_with_new_coordinates(self):
  (self.vault/'wiki/000.md').write_text('# 新页\n新加在前面的内容。');meta,p=self.rebuild();self.assertEqual(len(self.encoder.encoded),1);self.assertIn('新加在前面',self.encoder.encoded[0])
 def test_heading_and_model_contract_invalidate_inputs(self):
  self.note.write_text(self.note.read_text().replace('标题','新标题'));meta,p=self.rebuild();self.assertEqual(meta['reused_vectors'],0)
  with patch.dict(sem.CONFIG,query_instruction='契约改变'):
   meta,p=self.rebuild();self.assertEqual(meta['reused_vectors'],0)

 def test_identical_input_different_positions_keeps_both_references(self):
  self.note.write_text('# x\n'+'甲'*100);meta,p=self.rebuild();self.assertEqual(meta['vectors'],6);self.assertEqual(meta['encoded_unique_inputs'],3)
