import unittest,json
from memory_search import build
from research_test_support import ReadingFixture

class ReadingTest(ReadingFixture,unittest.TestCase):
    def test_all_four_dates_read_across_pages(self):
        s=self.timeline([self.expected['diary']]);rid=s['research_id'];out=self.service.list_research_sections(rid)
        self.assertEqual([x['heading_date'] for x in out['sections']],self.expected['expected_dates'])
        out=self.service.read_research_sections(rid,[x['section_id'] for x in out['sections']])
        while out['next_cursor']:out=self.service.read_research_sections(rid,cursor=out['next_cursor'])
        self.assertTrue(out['coverage']['coverage_complete']);self.assertEqual(out['coverage']['fully_returned_sections'],4)
    def test_one_chunk_of_section_is_not_complete(self):
        note=self.vault/'我的存在/长.md';note.write_text('# 2026-10-04\n'+'这是合成日记记录。\n'*2000);build(self.vault,self.db)
        s=self.timeline(['我的存在/长.md']);rid=s['research_id'];ids=[x['section_id'] for x in self.service.list_research_sections(rid)['sections']]
        out=self.service.read_research_sections(rid,ids)
        self.assertFalse(out['coverage']['coverage_complete']);self.assertIsNotNone(out['next_cursor'])
    def test_unknown_dates_prevent_temporal_completeness(self):
        s=self.timeline();rid=s['research_id'];sections=self.service.list_research_sections(rid)['sections']
        for i in range(0,len(sections),8):
            out=self.service.read_research_sections(rid,[x['section_id'] for x in sections[i:i+8]])
            while out['next_cursor']:out=self.service.read_research_sections(rid,cursor=out['next_cursor'])
        self.assertTrue(out['coverage']['coverage_complete']);self.assertFalse(out['coverage']['temporal_scope_complete'])
    def test_large_single_line_resumes_without_loss(self):
        s=self.begin();rid=s['research_id'];listing=self.service.list_research_sections(rid)
        sid=next(x['section_id'] for x in listing['sections'] if x['path']=='计算机和AI/长行.md')
        out=self.service.read_research_sections(rid,[sid]);hits=list(out['hits'])
        while out['next_cursor']:
            out=self.service.read_research_sections(rid,cursor=out['next_cursor']);hits+=out['hits']
        source=(self.vault/'计算机和AI/长行.md').read_text().rstrip('\n');ranges={}
        for h in hits:
            self.assertLessEqual(len(json.dumps(out,ensure_ascii=False)),16000)
            lineoff=sum(len(l)+1 for l in source.split('\n')[:h['start_line']-1]);a=lineoff+h['start_col']
            for i,c in enumerate(h['text'],a):ranges[i]=c
            page=self.notes.get_excerpt(h['hit_token'],0);self.assertEqual(page['text'],h['text'])
        self.assertEqual(''.join(ranges[i] for i in sorted(ranges)),source)
        self.assertEqual(self.service._session(rid)['text_chars'],len(source))
    def test_replayed_cursor_is_idempotent(self):
        s=self.begin();rid=s['research_id'];items=self.service.list_research_sections(rid)['sections'];sid=next(x['section_id'] for x in items if '长行' in x['path']);out=self.service.read_research_sections(rid,[sid]);cursor=out['next_cursor'];self.assertTrue(cursor)
        a=self.service.read_research_sections(rid,cursor=cursor);b=self.service.read_research_sections(rid,cursor=cursor)
        self.assertEqual(a['hits'],b['hits']);self.assertEqual(a['budget'],b['budget'])
    def test_cross_session_and_changed_source_cursor_rejected(self):
        a=self.begin();b=self.begin();rid=a['research_id'];items=self.service.list_research_sections(rid)['sections'];sid=next(x['section_id'] for x in items if '长行' in x['path']);page=self.service.read_research_sections(rid,[sid]);cursor=page['next_cursor']
        with self.assertRaises(ValueError):self.service.read_research_sections(b['research_id'],cursor=cursor)
        (self.vault/'计算机和AI/长行.md').write_text('变了')
        with self.assertRaises(ValueError):self.service.read_research_sections(rid,cursor=cursor)
    def test_excerpt_cannot_escape_research_section(self):
        s=self.begin();rid=s['research_id'];sid=self.service.list_research_sections(rid)['sections'][0]['section_id'];hit=self.service.read_research_sections(rid,[sid])['hits'][0]
        with self.assertRaises(ValueError):self.notes.get_excerpt(hit['hit_token'],1)
    def test_239_character_overlap_validates_boundary_quote(self):
        s=self.begin();rid=s['research_id'];sid=next(x['section_id'] for x in self.service.list_research_sections(rid)['sections'] if '长行' in x['path']);a=self.service.read_research_sections(rid,[sid]);b=self.service.read_research_sections(rid,cursor=a['next_cursor']);h=b['hits'][0]
        quote=h['text'][200:440];self.assertTrue(self.notes.verify_evidence(s['turn_id'],[dict(hit_token=h['hit_token'],quote=quote)])['all_valid'])
    def test_directory_budget_reports_incomplete(self):
        row=self.service._session(self.timeline()['research_id']);row['list_pages']=100
        out=self.service.list_research_sections(row['research_id']);self.assertFalse(out['coverage']['enumeration_complete']);self.assertEqual(out['stop_reason'],'ENUMERATION_LIMIT')
    def test_unread_gap_never_stitched(self):
        s=self.timeline([self.expected['diary']]);rid=s['research_id'];items=self.service.list_research_sections(rid)['sections'];a=self.service.read_research_sections(rid,[items[0]['section_id']])['hits'][0];b=self.service.read_research_sections(rid,[items[-1]['section_id']])['hits'][0]
        self.assertFalse(self.notes.verify_evidence(s['turn_id'],[dict(hit_token=a['hit_token'],quote=a['text'][-10:]+b['text'][-10:])])['all_valid'])

    def test_filename_date_never_filters_body(self):
        self.test_all_four_dates_read_across_pages()
    def test_json_budget_preserves_continuation(self):
        self.test_large_single_line_resumes_without_loss()
    def test_read_and_text_budget_are_explicit(self):
        row=self.service._session(self.timeline([self.expected['diary']])['research_id']);rid=row['research_id'];sid=self.service.list_research_sections(rid)['sections'][0]['section_id']
        row['reads']=32;out=self.service.read_research_sections(rid,[sid]);self.assertEqual(out['stop_reason'],'READ_LIMIT');self.assertFalse(out['coverage']['coverage_complete'])
        other=self.service._session(self.begin()['research_id']);other['ranges']={('synthetic','sha'):[(0,24000)]};other['text_chars']=24000
        with self.assertRaises(ValueError):self.service.sessions.admit(other['research_id'],[dict(path='new',sha256='s',start_offset=0,end_offset=1)])
        self.assertEqual(other['text_chars'],24000)
    def test_failed_batch_does_not_mark_unreturned_content_read(self):
        for name in ['a','b']:(self.vault/f'我的存在/{name}.md').write_text('# 2026-10-04\n这是一条足够长的合成观察记录。')
        build(self.vault,self.db);s=self.timeline(['我的存在/a.md','我的存在/b.md']);rid=s['research_id'];items=self.service.list_research_sections(rid)['sections']
        (self.vault/'我的存在/b.md').write_text('变化了')
        with self.assertRaises(ValueError):self.service.read_research_sections(rid,[x['section_id'] for x in items])
        row=self.service._session(rid);self.assertEqual(row['text_chars'],0);self.assertEqual(len(row['tokens']),0);self.assertEqual(self.service.sessions.coverage(rid)['fully_returned_sections'],0)
    def test_response_overflow_rolls_back_unreturned_state(self):
        from unittest.mock import patch
        s=self.timeline([self.expected['diary']]);rid=s['research_id'];sid=self.service.list_research_sections(rid)['sections'][0]['section_id']
        with patch.object(self.service,'_envelope',return_value={'oversized':'x'*16001}):
            with self.assertRaises(ValueError):self.service.read_research_sections(rid,[sid])
        row=self.service._session(rid);self.assertEqual(row['text_chars'],0);self.assertEqual(len(row['tokens']),0)
    def test_more_than_5000_sections_never_claims_enumeration_complete(self):
        row=self.service._session(self.timeline()['research_id']);template=row['sections'][0];row['sections']=[dict(template,id=i,section_id=str(i)) for i in range(5001)];rid=row['research_id'];out=self.service.list_research_sections(rid)
        pages=1
        while out['next_cursor']:
            out=self.service.list_research_sections(rid,out['next_cursor']);pages+=1
        self.assertEqual(pages,100);self.assertEqual(out['stop_reason'],'ENUMERATION_LIMIT');self.assertFalse(out['coverage']['enumeration_complete'])
