"""Scoped research orchestration; no model calls or source writes."""
from datetime import date
import hashlib
import json
from pathlib import Path
import re
import secrets
import time
from copy import deepcopy
from functools import wraps
from urllib.parse import urlencode,quote
from memory_search import connect,metadata,index_revision,search
from research_catalog import enumerate_sections,catalog_schema_version,normalized_text,position
from research_scope import load_collections,resolve_collection
from research_sessions import ResearchSessionStore
from retrieval_service import SourceError


def atomic_research(method):
    """A failed response must not become evidence the caller supposedly read."""
    @wraps(method)
    def run(self,research_id,*args,**kwargs):
        with self.lock:
            row=self._session(research_id)
            fields=('ranges','text_chars','tokens','cursors','listed','enumeration_complete','reads','list_pages','allowed_paths','sections','scope','consecutive_no_gain')
            saved={key:deepcopy(row[key]) for key in fields}
            try:
                result=method(self,research_id,*args,**kwargs)
                self._check_read_sources(row)
                if len(json.dumps(result,ensure_ascii=False))>16000:raise SourceError('RESPONSE_BUDGET','本次结构或来源超过返回预算；未标记为已读。')
                return result
            except Exception:
                row.update(saved)
                raise
    return run


class ResearchService:
    def __init__(self,retrieval_service,collections_path):
        self.notes=retrieval_service;self.collections_path=Path(collections_path);self.sessions=ResearchSessionStore();self.lock=self.notes.lock
        self.notes.research=self
    def _session(self,rid):
        row=self.sessions.get(rid)
        if row['revision']!=index_revision(self.notes.current_db()):raise SourceError('INDEX_CHANGED','索引已更新，请保留原问题重新开始。')
        if row['scope_hash']!=load_collections(self.collections_path)[1]:raise SourceError('SCOPE_CHANGED','资料集合已变化，请保留原问题重新开始。')
        return row
    def by_turn(self,turn):
        self.sessions.purge()
        for rid,row in self.sessions.rows.items():
            if row['turn_id']==turn:return self._session(rid)
        raise SourceError('RESEARCH_EXPIRED','研究会话已过期。')
    def lookup(self,token):
        self.sessions.purge()
        for rid,row in self.sessions.rows.items():
            if token in row['tokens']:
                self._session(rid);return row['tokens'][token]
        return None
    def begin_research(self,question,facets,collection,strategy,paths=None,date_from=None,date_to=None):
        if not isinstance(question,str) or not 1<=len(question.strip())<=2000:raise ValueError('问题须为1至2000字符。')
        if not isinstance(strategy,str) or strategy not in {'focused','timeline'} or not isinstance(collection,str):raise ValueError('查询方式或集合不正确。')
        if not isinstance(facets,list) or not 1<=len(facets)<=6:raise ValueError('请提供1至6个待回答事项。')
        ids=set()
        for f in facets:
            if not isinstance(f,dict) or set(f)!={'id','question','evidence_kind'} or not isinstance(f['id'],str) or not re.fullmatch(r'[A-Za-z0-9_]{1,32}',f['id']) or f['id'] in ids or not isinstance(f['question'],str) or not 1<=len(f['question'].strip())<=500 or not isinstance(f['evidence_kind'],str) or f['evidence_kind'] not in {'explanation','practice','outcome','first_use','timeline'}:raise ValueError('待回答事项格式不正确或重复。')
            ids.add(f['id'])
        for value in [date_from,date_to]:
            if value is not None and (not isinstance(value,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',value)):raise ValueError('时间须为ISO日期。')
            if value is not None:date.fromisoformat(value)
        if (strategy=='timeline' and (not date_from or not date_to)) or bool(date_from)!=bool(date_to) or (date_from and date_from>date_to):raise ValueError('请提供完整且顺序正确的起止日期。')
        with self.lock:
            db=self.notes.current_db();config,sha=load_collections(self.collections_path)
            with connect(db) as con:
                if catalog_schema_version(con)!=1:raise SourceError('REINDEX_REQUIRED','请先完成新版目录索引。')
                scope=resolve_collection(config,collection,{r['path'] for r in con.execute('SELECT path FROM documents')},paths)
                sections=enumerate_sections(con,scope['allowed_paths'],date_from,date_to)
            row=self.sessions.start(dict(question=question,facets=facets,collection=collection,strategy=strategy,allowed_paths=scope['allowed_paths'],sections=sections,date_from=date_from,date_to=date_to),index_revision(db),sha)
            row['scope']=dict(collection=collection,description=scope['description'],document_count=len(scope['allowed_paths']),scope_limitations=scope['scope_limitations'])
            return dict(research_id=row['research_id'],turn_id=row['turn_id'],scope=row['scope'],index_revision=row['revision'],scope_hash=sha,facets=facets,limits=dict(searches=6,text_chars=96000 if strategy=='timeline' else 24000,reads=32,list_pages=100,tokens=512),coverage=self.sessions.coverage(row['research_id']))
    @atomic_research
    def list_research_documents(self,research_id,query='',cursor=None):
        from research_documents import document_page
        row=self._session(research_id)
        return self._envelope(row,document_page(row,query,cursor,self._cursor,lambda content:self._fits_content(row,content,256)))

    @atomic_research
    def narrow_research(self,research_id,paths):
        from research_documents import narrow_scope
        row=self._session(research_id);narrow_scope(row,paths)
        return self._envelope(row,dict(scope=row['scope']))

    def _source(self,row,path):
        self._session(row['research_id']);vault=Path(metadata(self.notes.current_db())['vault'])
        self.notes.resolve_note(path,hashlib.sha256(str(vault).encode()).hexdigest())
        raw=(vault/path).read_bytes();sha=hashlib.sha256(raw).hexdigest()
        with connect(self.notes.current_db()) as con:expected=con.execute('SELECT sha256 FROM documents WHERE path=?',(path,)).fetchone()[0]
        if sha!=expected:
            row['stale_sections']+=1;raise SourceError('SOURCE_CHANGED','原文已变化，请等待索引更新并重新查询。')
        return normalized_text(raw.decode('utf-8-sig')),sha,vault
    def _publish(self,row,path,text,start,end,section_id,heading='',preview=False):
        if len(row['tokens'])>=512:raise SourceError('RESOURCE_LIMIT','本轮来源容量已满。')
        if path not in row['allowed_paths']:raise SourceError('SCOPE_FORBIDDEN','来源不属于锁定的资料范围。')
        source,sha,vault=self._source(row,path)
        if source[start:end]!=text[start:end]:raise SourceError('SOURCE_CHANGED','原文已变化。')
        body=source[start:end];sl,sc=position(source,start);el,ec=position(source,end);token=secrets.token_urlsafe(18);vault_id=hashlib.sha256(str(vault).encode()).hexdigest()
        hit=dict(path=path,heading=heading[:300],section_id=section_id,start_line=sl,end_line=el,start_col=sc,end_col=ec,text=body,kind='wiki' if path.startswith('wiki/') else 'source',source_status='current',date_label='',hit_token=token,vault_id=vault_id,open_url='obsidian://memory-source?'+urlencode(dict(v='2',vault=vault.name,vault_id=vault_id,note=path,hit=token,revision=row['revision']),quote_via=quote))
        if preview:return hit
        self.sessions.admit(row['research_id'],[dict(path=path,sha256=sha,start_offset=start,end_offset=end)])
        row['tokens'][token]=dict(hit=hit,revision=row['revision'],sha256=sha,vault=str(vault),created=time.monotonic(),turn_id=row['turn_id'],returned=[(sl,body)],research_id=row['research_id'])
        return hit
    def _budget(self,row):return dict(searches=row['searches'],reads=row['reads'],text_chars=row['text_chars'],tokens=len(row['tokens']))
    @atomic_research
    def search_research(self,research_id,facet_id,query,purpose):
        if not isinstance(query,str) or not 1<=len(query.strip())<=500 or not isinstance(purpose,str) or not 1<=len(purpose.strip())<=200:raise ValueError('搜索问题或补查目的不正确。')
        with self.lock:
            row=self._session(research_id)
            if not isinstance(facet_id,str) or facet_id not in {f['id'] for f in row['facets']}:raise ValueError('该事项不属于当前问题。')
            if row['searches']>=6:raise SourceError('SEARCH_LIMIT','本轮搜索次数已用完，请按已有证据回答。')
            before_chars=row['text_chars'];before_sections={v['hit']['section_id'] for v in row['tokens'].values()};before_docs={v['hit']['path'] for v in row['tokens'].values()}
            row['evidence_started']=True
            row['searches']+=1;hits=[];db=self.notes.current_db();section_ids={s['id'] for s in row['sections']};by_id={s['id']:s for s in row['sections']};spans={}
            with connect(db) as con:
                for s in con.execute('SELECT * FROM research_spans'):
                    if s['section_id'] in section_ids and s['chunk_id'] is not None:spans.setdefault(s['chunk_id'],[]).append(dict(s))
            def accept(candidate):
                initial=len(hits)
                for span in spans.get(candidate['id'],[]):
                    if len(hits)>=8:break
                    section=by_id[span['section_id']];text,sha,_=self._source(row,candidate['path']);a,b=span['start_offset'],span['end_offset']
                    # Search supplies a bounded first page; full section reading is explicit.
                    b=min(b,a+9000)
                    if any(x<=a and y>=b for x,y in row['ranges'].get((candidate['path'],sha),[])):continue
                    preview=self._publish(row,candidate['path'],text,a,b,section['section_id'],section['heading'],preview=True)
                    preview.update(date_status=section['date_status'],date_label=section['heading_date'] or '')
                    if not self._fits(row,hits+[preview]):continue
                    try:hit=self._publish(row,candidate['path'],text,a,b,section['section_id'],section['heading'])
                    except SourceError as e:
                        if e.code=='TURN_BUDGET':return False
                        raise
                    hit.update(date_status=section['date_status'],date_label=section['heading_date'] or '')
                    hits.append(hit)
                    if len(hits)>=8:break
                return len(hits)>initial
            search(db,query,mode='hybrid',allowed_paths=row['allowed_paths'],allowed_chunk_ids=set(spans),current_only=True,accept_result=accept)
            gain=row['text_chars']-before_chars;row['consecutive_no_gain']=0 if gain else row['consecutive_no_gain']+1
            return dict(new_evidence_chars=gain,new_sections=len({h['section_id'] for h in hits}-before_sections),new_documents=len({h['path'] for h in hits}-before_docs),consecutive_no_gain=row['consecutive_no_gain'],recommendation='stop_no_gain' if row['consecutive_no_gain']>=2 else 'review_gap',research_id=research_id,turn_id=row['turn_id'],facet_id=facet_id,hits=hits,budget=self._budget(row),coverage=self.sessions.coverage(research_id),stop_reason='TURN_BUDGET' if row['budget_exhausted'] else ('' if hits else 'NO_NEW_MATERIAL'),note='只覆盖锁定集合；没有新增不代表没有相关记录。')

    def _cursor(self,row,kind,payload):
        key=secrets.token_urlsafe(18);row['cursors'][key]=dict(kind=kind,payload=payload,result=None);return key

    def _envelope(self,row,content):
        self._check_read_sources(row)
        return dict(content,research_id=row['research_id'],turn_id=row['turn_id'],budget=self._budget(row),coverage=self.sessions.coverage(row['research_id']))

    def _fits_content(self,row,content,margin=1024):
        return len(json.dumps(self._envelope(row,content),ensure_ascii=False))+margin<=16000

    def _fits(self,row,hits):
        return self._fits_content(row,dict(hits=hits,next_cursor='x'*24,stop_reason=''))

    def _check_read_sources(self,row):
        for path in {p for p,sha in row['ranges']}:self._source(row,path)

    @atomic_research
    def list_research_sections(self,research_id,cursor=None):
        with self.lock:
            row=self._session(research_id)
            if cursor is not None and not isinstance(cursor,str):raise SourceError('CURSOR_INVALID','游标格式不正确。')
            if cursor is None:
                key='list:0';row['cursors'].setdefault(key,dict(kind='list',payload=0,result=None))
            else:key=cursor
            state=row['cursors'].get(key)
            if state is None or state['kind']!='list':raise SourceError('CURSOR_INVALID','目录游标不属于本次问题。')
            if state['result'] is not None:return self._envelope(row,state['result'])
            if row['list_pages']>=100:return self._envelope(row,dict(sections=[],next_cursor=None,stop_reason='ENUMERATION_LIMIT'))
            items=[];pos=state['payload']
            for s in row['sections'][pos:pos+50]:
                item={k:s[k] for k in ('section_id','path','heading','date_status','heading_date','span_count')};item['heading']=item['heading'][:300]
                if not self._fits_content(row,dict(sections=items+[item],next_cursor='x'*24,stop_reason=''),256):break
                items.append(item)
            if not items and pos<len(row['sections']):raise SourceError('RESPONSE_BUDGET','单条目录超出返回预算，未标记为已读。')
            end=pos+len(items);row['listed'].update(i['section_id'] for i in items);row['list_pages']+=1
            row['enumeration_complete']=len(row['listed'])==len(row['sections'])
            nxt=self._cursor(row,'list',end) if end<len(row['sections']) and row['list_pages']<100 else None
            result=dict(sections=items,next_cursor=nxt,stop_reason='ENUMERATION_LIMIT' if not nxt and not row['enumeration_complete'] else '')
            state['result']=result;return self._envelope(row,result)

    @atomic_research
    def read_research_sections(self,research_id,section_ids=None,cursor=None):
        with self.lock:
            row=self._session(research_id)
            if cursor is not None and not isinstance(cursor,str):raise SourceError('CURSOR_INVALID','游标格式不正确。')
            row['evidence_started']=True
            by_id={s['section_id']:s for s in row['sections']}
            if cursor is not None:
                if section_ids is not None:raise ValueError('续读只提供游标。')
                state=row['cursors'].get(cursor)
                if state is None or state['kind']!='read':raise SourceError('CURSOR_INVALID','阅读游标不属于本次问题。')
                if state['result'] is not None:
                    for h in state['result']['hits']:self._source(row,h['path'])
                    return self._envelope(row,state['result'])
                jobs=list(state['payload'])
            else:
                if not isinstance(section_ids,list) or not 1<=len(section_ids)<=8 or any(not isinstance(s,str) or s not in by_id for s in section_ids) or len(set(section_ids))!=len(section_ids):raise SourceError('SECTION_INVALID','请指定本次目录中的1至8个不同章节。')
                chosen=sorted([by_id[i] for i in section_ids],key=lambda s:(s['path'],s['start_offset']))
                jobs=[(s['section_id'],s['start_offset']) for s in chosen];state=dict(result=None)
            if row['reads']>=32:
                row['budget_exhausted']=True;return self._envelope(row,dict(hits=[],next_cursor=None,stop_reason='READ_LIMIT'))
            hits=[];stop=''
            with connect(self.notes.current_db()) as con:
                while jobs and len(hits)<8:
                    sid,offset=jobs[0];section=by_id[sid];text,sha,_=self._source(row,section['path'])
                    a=max(section['start_offset'],offset-239) if offset>section['start_offset'] else offset
                    span=con.execute('SELECT end_offset FROM research_spans WHERE section_id=? AND end_offset>? ORDER BY end_offset LIMIT 1',(section['id'],offset)).fetchone()
                    b=min(span[0] if span else section['end_offset'],offset+9000,section['end_offset'])
                    preview=self._publish(row,section['path'],text,a,b,sid,section['heading'],preview=True)
                    preview.update(date_status=section['date_status'],date_label=section['heading_date'] or '')
                    if not self._fits(row,hits+[preview]):
                        if hits:break
                        b=min(b,offset+1000);preview=self._publish(row,section['path'],text,a,b,sid,section['heading'],preview=True)
                        if not self._fits(row,[preview]):raise SourceError('RESPONSE_BUDGET','原文页超出返回预算。')
                    try:hit=self._publish(row,section['path'],text,a,b,sid,section['heading'])
                    except SourceError as e:
                        if e.code!='TURN_BUDGET':raise
                        stop='TURN_BUDGET';break
                    hit.update(date_status=section['date_status'],date_label=section['heading_date'] or '');hits.append(hit)
                    if b<section['end_offset']:jobs[0]=(sid,b)
                    else:jobs.pop(0)
            if hits:row['reads']+=1
            nxt=self._cursor(row,'read',jobs) if jobs and not stop else None
            result=dict(hits=hits,next_cursor=nxt,stop_reason=stop)
            state['result']=result;return self._envelope(row,result)

    @atomic_research
    def assess_research(self,research_id,answers):
        from research_assessment import assess
        with self.lock:
            row=self._session(research_id)
            self._check_read_sources(row)
            return assess(row,answers,self.notes.verify_evidence,self.sessions.coverage(research_id))
