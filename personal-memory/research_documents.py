"""Bounded metadata-only document lookup within an existing research scope."""
from pathlib import PurePosixPath
import unicodedata
from retrieval_service import SourceError

def normalized(value):return unicodedata.normalize('NFKC',value).casefold()

def document_page(row,query,cursor,make_cursor,fits):
    if not isinstance(query,str) or len(query)>200 or (cursor is not None and not isinstance(cursor,str)):raise ValueError('文件名或目录游标格式不正确。')
    q=normalized(query.strip())
    if cursor is None:
        key='documents:'+q;row['cursors'].setdefault(key,dict(kind='documents',payload=dict(query=q,offset=0),result=None))
    else:key=cursor
    state=row['cursors'].get(key)
    if state is None or state['kind']!='documents' or (q and q!=state['payload']['query']):raise SourceError('CURSOR_INVALID','目录游标不属于当前文件查询。')
    if state['result'] is not None:return state['result']
    if row['list_pages']>=100:return dict(documents=[],next_cursor=None,stop_reason='ENUMERATION_LIMIT')
    q=state['payload']['query'];items=[]
    for path in row['allowed_paths']:
        title=PurePosixPath(path).stem;nt=normalized(title);np=normalized(path)
        if q and q not in np:continue
        sections=[s for s in row['sections'] if s['path']==path]
        rank=0 if nt==q else (1 if q in nt else 2)
        items.append((rank,np,dict(path=path,title=title,section_count=len(sections),dated_section_count=sum(s['date_status']=='dated' for s in sections))))
    items.sort(key=lambda i:(i[0],i[1],i[2]['path']));pos=state['payload']['offset'];selected=[]
    for item in items[pos:pos+20]:
        if not fits(dict(documents=selected+[item[2]],next_cursor='x'*24,stop_reason='')):break
        selected.append(item[2])
    if not selected and pos<len(items):raise SourceError('RESPONSE_BUDGET','目录项超出返回预算。')
    end=pos+len(selected)
    result=dict(documents=selected,next_cursor=make_cursor(row,'documents',dict(query=q,offset=end)) if end<len(items) else None,stop_reason='')
    row['list_pages']+=1;state['result']=result;return result

def narrow_scope(row,paths):
    if row.get('evidence_started') or row['searches'] or row['reads']:raise SourceError('SCOPE_LOCKED','已经开始搜索或读取正文，不能再次更改范围。')
    if not isinstance(paths,list) or not 1<=len(paths)<=100 or any(not isinstance(p,str) or p not in row['allowed_paths'] for p in paths):raise SourceError('SCOPE_FORBIDDEN','只能收窄到当前集合中的笔记。')
    row['allowed_paths']=set(paths);row['sections']=[s for s in row['sections'] if s['path'] in row['allowed_paths']]
    row['scope']=dict(row['scope'],document_count=len(row['allowed_paths']));row['cursors']={};row['listed']=set();row['enumeration_complete']=False
