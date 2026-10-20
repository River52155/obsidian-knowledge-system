import unittest
from evidence_checks import locate_quote

class QuoteTest(unittest.TestCase):
    def test_continuous_exact_quote_and_line_numbers(self):
        self.assertEqual(locate_quote('title\n星光照亮夜晚，这是原来保存的一条观察记录。\nending','星光照亮夜晚，这是原来保存的一条观察记录。',10),(11,11))
        self.assertEqual(locate_quote('第一行测试原文内容\n第二行测试原文内容','测试原文内容\n第二行测试',3),(3,4))
    def test_fabricated_joined_short_long_and_nontext_are_rejected(self):
        for quote in ['太短','x'*241,'星光照亮夜晚，观察记录。',None,12]:
            with self.subTest(quote=quote),self.assertRaises(ValueError):locate_quote('星光照亮夜晚，这是原来保存的一条观察记录。',quote,1)
