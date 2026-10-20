"""Explicit collections; absence or ambiguity never widens to the whole Vault."""
import hashlib
import json
from pathlib import Path
from retrieval_service import allowed_path,SourceError


def validate_config(config):
    if not isinstance(config,dict) or set(config)!={'schema_version','collections'} or config['schema_version']!=1 or not isinstance(config['collections'],list):
        raise SourceError('SCOPE_UNCONFIGURED','资料集合配置不正确。')
    seen=set()
    for c in config['collections']:
        if not isinstance(c,dict) or set(c)!={'id','description','include_prefixes','include_paths','exclude_prefixes'} or not isinstance(c['id'],str) or c['id'] in seen or not isinstance(c['description'],str):raise SourceError('SCOPE_UNCONFIGURED','集合字段不正确或重复。')
        seen.add(c['id'])
        for key in ['include_prefixes','include_paths','exclude_prefixes']:
            if not isinstance(c[key],list):raise SourceError('SCOPE_UNCONFIGURED','集合范围必须是相对路径列表。')
            for p in c[key]:
                if not allowed_path(p) or any(ch in p for ch in '*?[]\x00') or (c['id']=='technical' and p.split('/')[0]=='我的存在'):
                    raise SourceError('SCOPE_UNCONFIGURED','资料集合包含不允许的路径。')
    return config


def config_hash(config):
    return hashlib.sha256(json.dumps(config,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def load_collections(path: Path):
    try:config=validate_config(json.loads(path.read_text(encoding='utf-8')))
    except (OSError,ValueError,TypeError,KeyError) as e:
        if isinstance(e,SourceError):raise
        raise SourceError('SCOPE_UNCONFIGURED','资料集合尚未配置，请先检查本机集合。') from None
    return config,config_hash(config)


def resolve_collection(config,collection,indexed_paths,requested_paths=None):
    validate_config(config)
    chosen=next((c for c in config['collections'] if c['id']==collection),None)
    if chosen is None:raise SourceError('SCOPE_UNCONFIGURED','指定的资料集合不存在。')
    under=lambda p,prefixes:any(p==s or p.startswith(s+'/') for s in prefixes)
    allowed={p for p in indexed_paths if allowed_path(p) and (p in chosen['include_paths'] or under(p,chosen['include_prefixes'])) and not under(p,chosen['exclude_prefixes'])}
    if requested_paths is not None:
        if not isinstance(requested_paths,list) or not requested_paths or any(not isinstance(p,str) or p not in allowed for p in requested_paths):raise SourceError('SCOPE_FORBIDDEN','指定笔记不在本次集合内。')
        allowed &= set(requested_paths)
    return dict(allowed_paths=allowed,scope_hash=config_hash(config),description=chosen['description'],scope_limitations='只覆盖已纳入本集合的已索引资料；未审核的散落笔记可能遗漏，不等于全库分类。')
