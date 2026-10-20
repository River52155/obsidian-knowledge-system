"""MCP stdio adapter for the fixed localhost personal-memory service."""
import argparse
import hashlib
import json
from pathlib import Path
from typing import Annotated, Literal
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler

from mcp.server.fastmcp import FastMCP
from pydantic import Field
from memory_search import DEFAULT_VAULT
from retrieval_service import SERVICE_ID

RESEARCH_ARGUMENTS={
    'list_research_documents':{'research_id','query','cursor'},
    'narrow_research':{'research_id','paths'},
    'begin_research':{'question','facets','collection','strategy','paths','date_from','date_to'},
    'search_research':{'research_id','facet_id','query','purpose'},
    'list_research_sections':{'research_id','cursor'},
    'read_research_sections':{'research_id','section_ids','cursor'},
    'assess_research':{'research_id','answers'},
}


class StrictFastMCP(FastMCP):
    async def list_tools(self):
        tools=await super().list_tools()
        for tool in tools:
            if tool.name in RESEARCH_ARGUMENTS:tool.inputSchema['additionalProperties']=False
        return tools
    async def call_tool(self,name,arguments):
        if name in RESEARCH_ARGUMENTS and (not isinstance(arguments,dict) or set(arguments)-RESEARCH_ARGUMENTS[name]):
            raise ValueError('INVALID_REQUEST: 请求包含未知字段。')
        return await super().call_tool(name,arguments)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def load_instructions(path=None):
    return (Path(path) if path is not None else Path(__file__).resolve().parent/'prompts/retrieval-tools.md').read_text(encoding='utf-8')


def create_bridge(port=8767, vault=DEFAULT_VAULT):
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError('Invalid local port')
    base=f'http://127.0.0.1:{port}'
    vault_id=hashlib.sha256(str(Path(vault).resolve()).encode()).hexdigest()
    opener=build_opener(ProxyHandler({}),NoRedirect())
    def raw_request(path, data=None):
        req=Request(base+path, None if data is None else json.dumps(data,ensure_ascii=False).encode(),
                    {'Content-Type':'application/json','Origin':base})
        try:
            with opener.open(req,timeout=60) as response:
                return json.load(response)
        except HTTPError as error:
            try:
                payload=json.load(error);message=payload.get('error','本机资料查询失败。')
                if payload.get('code'):message=payload['code']+': '+message
            except (ValueError,AttributeError): message='本机资料查询失败。'
            raise ValueError(message) from None
        except (URLError,TimeoutError,OSError):
            raise ValueError('本机资料服务尚未就绪，请检查个人资料服务状态。') from None

    def request(path, data=None):
        health=raw_request('/api/health')
        if not isinstance(health,dict) or health.get('service_id')!=SERVICE_ID:
            raise ValueError('本机端口上的服务不匹配，已停止资料查询。')
        if health.get('vault_id')!=vault_id:
            raise ValueError('资料服务连接的不是当前资料库，已停止查询。')
        return health if path=='/api/health' else raw_request(path,data)

    server=StrictFastMCP('personal-memory',instructions=load_instructions())

    @server.tool(annotations={'readOnlyHint':True})
    def begin_research(question:Annotated[str,Field(min_length=1,max_length=2000)],facets:Annotated[list[dict],Field(min_length=1,max_length=6)],collection:Literal['technical','personal','allowed'],strategy:Literal['focused','timeline'],paths:list[str]|None=None,date_from:str|None=None,date_to:str|None=None)->dict:
        """开始有范围的研究。明确范围、多事项、实践/效果/首次时间或时间回顾时使用。facets为1–6项{id,question,evidence_kind}，evidence_kind取explanation/practice/outcome/first_use/timeline。technical/personal/allowed是资料范围，实践等是证据用途，技术集合也可包含实践记录。timeline必填ISO起止日期。后续锁定research_id，不额外读取全库。"""
        return request('/api/research/begin',dict(question=question,facets=facets,collection=collection,strategy=strategy,paths=paths,date_from=date_from,date_to=date_to))

    @server.tool(annotations={'readOnlyHint':True})
    def list_research_documents(research_id:str,query:Annotated[str,Field(max_length=200)]='',cursor:str|None=None)->dict:
        """在锁定集合内按文件名/路径定位，每页20项元数据，无正文。同名先消歧；无匹配不扩大范围。续页沿用cursor。"""
        return request('/api/research/documents',dict(research_id=research_id,query=query,cursor=cursor))

    @server.tool(annotations={'readOnlyHint':True})
    def narrow_research(research_id:str,paths:Annotated[list[str],Field(min_length=1,max_length=100)])->dict:
        """只在尚未搜索/读正文时，把现有研究收窄到已定位的文件；不清零预算、不扩大集合。"""
        return request('/api/research/narrow',dict(research_id=research_id,paths=paths))

    @server.tool(annotations={'readOnlyHint':True})
    def search_research(research_id:str,facet_id:str,query:Annotated[str,Field(min_length=1,max_length=500)],purpose:Annotated[str,Field(min_length=1,max_length=200)])->dict:
        """为一个事项补查明确缺口，不得扩大锁定范围。6次是上限，不是目标；已读材料可跨事项复用，同类补查没有新证据就停止并说明不足。返回来源、预算和覆盖；教程不证明实践，最早记录不证明人生首次。"""
        return request('/api/research/search',dict(research_id=research_id,facet_id=facet_id,query=query,purpose=purpose))

    @server.tool(annotations={'readOnlyHint':True})
    def list_research_sections(research_id:str,cursor:str|None=None)->dict:
        """分页列出研究范围内章节/日期目录，每页最多50项。timeline先遍历目录；未知日期单独标记。目录只列出不算已读；有next_cursor继续本工具，不用语义排名冒充查全。"""
        return request('/api/research/sections',dict(research_id=research_id,cursor=cursor))

    @server.tool(annotations={'readOnlyHint':True})
    def read_research_sections(research_id:str,section_ids:Annotated[list[str],Field(min_length=1,max_length=8)]|None=None,cursor:str|None=None)->dict:
        """读取目录中的1–8个section_id；有next_cursor时只传research_id和cursor续读。长段按原始范围分批，返回hit_token及实际覆盖；预算耗尽只能局部总结，不另开会话绕过。研究token不使用旧get_excerpt扩大范围。"""
        return request('/api/research/read',dict(research_id=research_id,section_ids=section_ids,cursor=cursor))

    @server.tool(annotations={'readOnlyHint':True})
    def assess_research(research_id:str,answers:Annotated[list[dict],Field(max_length=6)])->dict:
        """回答前逐项核对。answers每项{facet_id,status,claim,citations:[{hit_token,quote}],limitations}；status=supported/insufficient/conflicting，quote12–240字连续原文。每个facet一次。返回结构、引文、实际覆盖及answer_guidance分项边界；按对应证据要求收窄，不足可采用条件措辞，不附加学过/整理过/规划阶段等判断。已核对引文，无需再verify_evidence。语义仍未验证，末尾只列短来源。"""
        return request('/api/research/assess',dict(research_id=research_id,answers=answers))

    @server.tool(annotations={'readOnlyHint':True})
    def search_notes(query:Annotated[str,Field(min_length=1,max_length=500)], scope:Literal['all','source','wiki']='all', folder:str|None=None, limit:Annotated[int,Field(ge=1,le=8)]=8, mode:Literal['keyword','semantic','hybrid']='hybrid', turn_id:str|None=None, purpose:Annotated[str,Field(max_length=200)]='')->dict:
        """在用户已索引的 Obsidian 资料中查找原文。新的资料问题应重新查找，避免复用已过期的来源链接。query保留原始问题对象/时间/用途；同题补查须复用turn_id并给purpose，新题省略ID。scope为all/source/wiki，folder限定已允许目录。返回真实片段及可点击来源，不调用大模型。"""
        return request('/api/notes/search',dict(query=query,scope=scope,folder=folder,limit=limit,mode=mode,turn_id=turn_id,purpose=purpose))

    @server.tool(annotations={'readOnlyHint':True})
    def get_excerpt(hit_token:str, context_lines:Annotated[int,Field(ge=0,le=24)]=8, turn_id:str|None=None)->dict:
        """取回search_notes某条命中的前后文，再次核对当前原文；只接受命中编号，不接受文件路径。沿用turn_id；省略ID仍按token所属问题计入总预算。"""
        return request('/api/notes/excerpt',dict(hit_token=hit_token,context_lines=context_lines,turn_id=turn_id))

    @server.tool(annotations={'readOnlyHint':True})
    def verify_evidence(turn_id:str, items:Annotated[list[dict],Field(min_length=1,max_length=8)])->dict:
        """核对本轮已读的逐字引文及当前来源。items为1至8条{hit_token,quote}，quote连续12至240字符；不验证解释、语义或用户是否经历过。只返回核对状态与短来源链接，不再返回正文。"""
        return request('/api/notes/verify',dict(turn_id=turn_id,items=items))

    @server.tool(annotations={'readOnlyHint':True})
    def index_status()->dict:
        """查看本机资料服务及索引更新状态。"""
        return dict(service=request('/api/health'),updates=request('/api/index/status'))

    @server.tool(annotations={'readOnlyHint':False,'destructiveHint':False,'idempotentHint':True})
    def refresh_index()->dict:
        """请求检查已允许目录的变更并更新派生索引，不修改或整理原始笔记。"""
        return request('/api/index/check',{})

    return server


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8767)
    parser.add_argument('--vault',type=Path,default=DEFAULT_VAULT)
    args=parser.parse_args()
    create_bridge(args.port,args.vault).run(transport='stdio')
