from concurrent.futures import ThreadPoolExecutor
import unittest
from query_context import QueryContextStore


class ContextTest(unittest.TestCase):
    def test_search_cap_and_required_purpose_are_atomic(self):
        store=QueryContextStore(); turn=store.start('original')
        self.assertTrue(store.begin_search(turn,''))
        with self.assertRaises(ValueError):store.begin_search(turn,'')
        with self.assertRaises(ValueError):store.begin_search(turn,'a'*201)
        with ThreadPoolExecutor(max_workers=12) as pool:
            accepted=list(pool.map(lambda _:store.begin_search(turn,'specific missing evidence'),range(20)))
        self.assertEqual(sum(accepted),2);self.assertEqual(store.stats(turn)['searches'],3)

    def test_budget_dedup_and_independent_turns(self):
        store=QueryContextStore();a=store.start('a');b=store.start('b')
        self.assertTrue(store.admit_text(a,'x'*23999));self.assertFalse(store.admit_text(a,'x'*23999))
        self.assertFalse(store.admit_text(a,'xx'));self.assertTrue(store.admit_text(a,'y'))
        self.assertEqual(store.stats(a)['text_chars'],24000);self.assertTrue(store.admit_text(b,'x'*23999))
        with ThreadPoolExecutor(max_workers=12) as pool:
            self.assertEqual(sum(pool.map(lambda _:store.admit_text(b,'z'),range(20))),1)

    def test_idle_ttl_and_lru_capacity_and_invalid_ids(self):
        clock=[0];store=QueryContextStore(clock=lambda:clock[0]);old=store.start('old')
        first=store.start('first')
        for _ in range(126):store.start('new')
        clock[0]=100;store.get(old);new=store.start('latest')
        self.assertEqual(store.stats(old)['original_query'],'old')
        with self.assertRaises(ValueError):store.get(first)
        clock[0]=999;store.get(old);clock[0]=1001;store.get(old)
        with self.assertRaises(ValueError):store.get(new)
        clock[0]=1901
        with self.assertRaises(ValueError):store.get(old)
        for bad in [None,[], 'bogus']:
            with self.assertRaises(ValueError):store.get(bad)
