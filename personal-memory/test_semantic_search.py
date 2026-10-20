"""Checks that prevent silent text loss or mismatched vector/source references."""
import unittest
from semantic_search import CONFIG, INFERENCE_VERSION, config_hash, token_windows, validate_artifact, fuse_rankings


class SemanticContractTest(unittest.TestCase):
    def test_token_windows_cover_the_end_without_truncation(self):
        text = ''.join(chr(0x4e00 + i) for i in range(1100))
        offsets = [(i, i + 1) for i in range(len(text))]
        windows = list(token_windows(text, offsets, 360, 48))
        covered = set()
        for start, stop, body in windows:
            self.assertEqual(body, text[start:stop])
            self.assertLessEqual(stop - start, 360)
            covered.update(range(start, stop))
        self.assertEqual(covered, set(range(len(text))))
        self.assertEqual(windows[-1][1], len(text))

    def test_stale_corpus_and_changed_config_are_rejected(self):
        meta = dict(config_hash=config_hash(), inference_version=INFERENCE_VERSION, corpus_fingerprint='old')
        validate_artifact(meta, 'old')
        with self.assertRaisesRegex(ValueError, '文字索引'):
            validate_artifact(meta, 'new')
        meta['config_hash'] = 'different'
        with self.assertRaisesRegex(ValueError, '模型配置'):
            validate_artifact(meta, 'old')

    def test_fusion_preserves_both_routes_and_no_duplicate_boost(self):
        self.assertEqual(fuse_rankings([1, 2, 2], [3, 2]), [2, 1, 3])
        self.assertEqual(set(fuse_rankings([1, 2], [3, 4])), {1, 2, 3, 4})


if __name__ == '__main__':
    unittest.main()
