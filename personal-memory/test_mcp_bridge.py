import json
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
import tempfile
import threading
import unittest

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from memory_search import build, make_server


class BridgeTest(unittest.IsolatedAsyncioTestCase):
    async def test_stdio_handshake_search_excerpt_and_invalid_token(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'vault/wiki').mkdir(parents=True)
            (root/'vault/wiki/学习.md').write_text('# 星光\n夜晚星光是一条真实的测试笔记，保留完整出处。\n')
            db=root/'index.sqlite3';build(root/'vault',db)
            collections=root/'collections.json'
            collections.write_text(json.dumps({'schema_version':1,'collections':[dict(id='allowed',description='synthetic',include_prefixes=['wiki'],include_paths=[],exclude_prefixes=[])]}))
            server=make_server(db,0,collections_path=collections);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            bridge=Path(__file__).with_name('mcp_bridge.py')
            self.assertTrue(bridge.exists(),'MCP bridge is not implemented')
            params=StdioServerParameters(command=sys.executable,args=[str(bridge),'--port',str(server.server_port),'--vault',str(root/'vault')])
            try:
                async with stdio_client(params) as (reader,writer):
                    async with ClientSession(reader,writer) as session:
                        await session.initialize()
                        tools=await session.list_tools()
                        self.assertEqual({t.name for t in tools.tools},{'search_notes','get_excerpt','index_status','refresh_index','verify_evidence','begin_research','search_research','list_research_sections','read_research_sections','assess_research','list_research_documents','narrow_research'})
                        result=await session.call_tool('search_notes',{'query':'星光','mode':'keyword'})
                        self.assertFalse(result.isError)
                        value=json.loads(result.content[0].text)
                        hit=value['hits'][0]
                        excerpt=await session.call_tool('get_excerpt',{'hit_token':hit['hit_token'],'context_lines':0})
                        self.assertIn('保留完整出处',json.loads(excerpt.content[0].text)['text'])
                        self.assertTrue(next(t for t in tools.tools if t.name=='verify_evidence').annotations.readOnlyHint)
                        verified=await session.call_tool('verify_evidence',{'turn_id':value['turn_id'],'items':[{'hit_token':hit['hit_token'],'quote':'夜晚星光是一条真实的测试笔记，保留完整出处。'}]})
                        self.assertFalse(verified.isError);self.assertTrue(json.loads(verified.content[0].text)['all_valid'])
                        invalid=await session.call_tool('get_excerpt',{'hit_token':'../../重要信息'})
                        self.assertTrue(invalid.isError)
                        spec=dict(question='查合成资料',facets=[dict(id='a',question='星光',evidence_kind='explanation')],collection='allowed',strategy='focused')
                        started=await session.call_tool('begin_research',spec)
                        self.assertFalse(started.isError);research=json.loads(started.content[0].text)
                        docs=await session.call_tool('list_research_documents',{'research_id':research['research_id'],'query':'学习'})
                        self.assertEqual(json.loads(docs.content[0].text)['documents'][0]['path'],'wiki/学习.md')
                        narrow=await session.call_tool('narrow_research',{'research_id':research['research_id'],'paths':['wiki/学习.md']})
                        self.assertFalse(narrow.isError)
                        listing=await session.call_tool('list_research_sections',{'research_id':research['research_id']})
                        sections=json.loads(listing.content[0].text)['sections']
                        page=await session.call_tool('read_research_sections',{'research_id':research['research_id'],'section_ids':[sections[0]['section_id']]})
                        self.assertIn('保留完整出处',json.loads(page.content[0].text)['hits'][0]['text'])
                        assessment=await session.call_tool('assess_research',{'research_id':research['research_id'],'answers':[dict(facet_id='a',status='insufficient',claim='不证明个人经历',citations=[],limitations='这是合成技术资料') ]})
                        checked=json.loads(assessment.content[0].text)
                        self.assertFalse(checked['semantic_verified'])
                        self.assertIn('本轮已读材料',checked['answer_guidance']['facets'][0]['fallback_if_insufficient'])
                        bad=await session.call_tool('begin_research',spec|{'unknown':True});self.assertTrue(bad.isError)
                        bad=await session.call_tool('list_research_sections',{'research_id':'expired'});self.assertTrue(bad.isError);self.assertIn('RESEARCH_EXPIRED',bad.content[0].text)
            finally:
                server.shutdown();server.server_close();thread.join()

    async def test_instructions_are_loaded_from_module_location_and_missing_file_fails(self):
        import os
        from mcp_bridge import create_bridge, load_instructions
        expected=Path(__file__).with_name('prompts').joinpath('retrieval-tools.md').read_text(encoding='utf-8')
        previous=Path.cwd()
        with tempfile.TemporaryDirectory() as folder:
            try:
                os.chdir(folder)
                self.assertEqual(create_bridge().instructions,expected)
                with self.assertRaises(FileNotFoundError):load_instructions(Path(folder)/'missing.md')
            finally:os.chdir(previous)

    async def test_foreign_service_or_vault_is_rejected_before_query(self):
        for identity in ['service', 'vault']:
            with self.subTest(identity=identity), tempfile.TemporaryDirectory() as folder:
                vault=Path(folder).resolve()
                health=dict(service_id='river.personal-memory',
                            vault_id=hashlib.sha256(str(vault).encode()).hexdigest(),ready=False)
                health['service_id' if identity=='service' else 'vault_id']='unrelated'
                calls=[]
                class Handler(BaseHTTPRequestHandler):
                    def do_GET(self):
                        calls.append(self.path)
                        body=json.dumps(health).encode()
                        self.send_response(200);self.end_headers();self.wfile.write(body)
                    def do_POST(self):
                        calls.append(self.path)
                        self.send_response(200);self.end_headers();self.wfile.write(b'{"hits":[]}')
                    def log_message(self,*args):pass
                server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
                thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
                bridge=Path(__file__).with_name('mcp_bridge.py')
                params=StdioServerParameters(command=sys.executable,args=[str(bridge),'--port',str(server.server_port),'--vault',str(vault)])
                try:
                    async with stdio_client(params) as (reader,writer):
                        async with ClientSession(reader,writer) as session:
                            await session.initialize()
                            result=await session.call_tool('search_notes',{'query':'私人问题','mode':'keyword'})
                            self.assertTrue(result.isError)
                            self.assertEqual(calls,['/api/health'])
                finally:
                    server.shutdown();server.server_close();thread.join()


if __name__=='__main__':unittest.main()
