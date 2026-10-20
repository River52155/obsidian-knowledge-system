#!/usr/bin/env python3
"""Local, read-only Obsidian retrieval with lexical and optional local BGE search."""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
from datetime import datetime
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import unicodedata
from urllib.parse import parse_qs, quote, urlparse

HERE = Path(__file__).resolve().parent
DEFAULT_VAULT = Path.home() / 'Documents' / 'Obsidian'
DEFAULT_DB = HERE / 'data/baseline.sqlite3'
ROOTS = ('wiki', '我的存在', '世界知识', '运动健身（大学）', '计算机和AI', '英语', '图谱索引')
BLOCKED_DIRS = {'重要信息', 'archive', 'raw', 'node_modules'}
SENSITIVE_NAME = re.compile(r'卡密|密码|私钥|密钥|凭据|(?:^|[._-])(?:secrets?|credentials?)(?:[._-]|$)', re.I)
SECRET_PATTERNS = [
    re.compile(r'\b(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{25,}|github_pat_[A-Za-z0-9_]{25,}|AKIA[A-Z0-9]{16})\b'),
    re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    re.compile(r'(?im)(?:api[_ -]?key|access[_ -]?token|password|密码|卡密|私钥)\s*[=:：]\s*["\x27]?([A-Za-z0-9_+/=-]{16,})'),
]
QUERY_STOP = set('我想 之前 什么 哪些 时候 帮我 我的 一个 怎么 如何 有没有 能够 一下 现在 记得 关于 以前 可以 里面 笔记 记录'.split())
RETRIEVAL_VERSION = 'title-focus-v2'


def terms(text: str, query: bool = False) -> list[str]:
    text = unicodedata.normalize('NFKC', text).casefold()
    out = []
    for part in re.findall(r'[\u3400-\u9fff]+|[a-z0-9_]+', text):
        if '\u3400' <= part[0] <= '\u9fff':
            # Include unigrams for explicit single-character lookup; normal queries use bigrams.
            if not query or len(part) == 1:
                out.extend('u' + hex(ord(c))[2:] for c in part)
            out.extend(part[i:i + 2] for i in range(len(part) - 1))
        else:
            out.append(part)
    return [t for t in out if not query or t not in QUERY_STOP]


def chunks(text: str, limit: int = 900) -> list[dict]:
    """Keep original line ranges; split at headings and roughly paragraph-sized units."""
    lines = text.splitlines()
    offset = 0
    if lines and lines[0].strip() == '---':
        for i in range(1, len(lines)):
            if lines[i].strip() == '---':
                offset = i + 1
                break
    result, stack, pending = [], [], []
    size = 0
    fenced = False

    def flush():
        nonlocal pending, size
        if pending and any(s.strip() and not re.match(r'^#{1,6}\s+', s) for _, s in pending):
            a, b = pending[0][0], pending[-1][0]
            body = '\n'.join(lines[a - 1:b])
            heading = ' / '.join(s for _, s in stack)
            # A heading date is a source label, not a claim about the event date.
            date_labels = re.findall(r'\b20\d{2}\s*(?:年|[-/.])\s*\d{1,2}\s*(?:月|[-/.])\s*\d{1,2}\s*日?', heading)
            result.append(dict(start_line=a, end_line=b, heading=heading,
                               date_label=date_labels[-1].strip() if date_labels else '', text=body))
        pending, size = [], 0

    for i in range(offset, len(lines)):
        line = lines[i]
        heading = re.match(r'^(#{1,6})\s+(.+)', line) if not fenced else None
        if heading:
            # Carry an otherwise empty parent heading into the first substantive section.
            if any(s.strip() and not re.match(r'^#{1,6}\s+', s) for _, s in pending):
                flush()
            level = len(heading[1])
            stack = [(l, s) for l, s in stack if l < level]
            stack.append((level, heading[2].strip()))
        elif size >= limit and not fenced:
            flush()
        pending.append((i + 1, line))
        size += len(line) + 1
        if line.lstrip().startswith(('```', '~~~')):
            fenced = not fenced
    flush()
    return result


def files_under(base: Path):
    if not base.is_dir() or base.is_symlink():
        return
    for folder, dirs, names in os.walk(base, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not d.startswith('.') and d not in BLOCKED_DIRS
                         and not (Path(folder) / d).is_symlink())
        for name in sorted(names):
            p = Path(folder) / name
            if not name.startswith('.') and not p.is_symlink() and p.is_file():
                yield p


def build(vault: Path, db_path: Path) -> dict:
    vault, db_path = vault.resolve(), db_path.resolve()
    if not vault.is_dir():
        raise ValueError('Vault directory does not exist')
    if db_path.is_relative_to(vault):
        raise ValueError('Experiment output must be outside the Vault')
    db_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temp_name = tempfile.mkstemp(prefix='.building-', suffix='.sqlite3', dir=db_path.parent)
    os.close(fd)
    temp_path = Path(temp_name)
    inventory, total_chunks = [], 0
    try:
        con = sqlite3.connect(temp_path)
        con.executescript('''
        CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE documents(path TEXT PRIMARY KEY, sha256 TEXT, mtime_ns INTEGER, kind TEXT);
        CREATE TABLE chunks(id INTEGER PRIMARY KEY, path TEXT, heading TEXT, date_label TEXT,
                            start_line INTEGER, end_line INTEGER, text TEXT);
        CREATE VIRTUAL TABLE search USING fts5(title, heading, body, tokenize='unicode61');
        ''')
        from research_catalog import create_schema, build_catalog
        create_schema(con)
        for root in ROOTS:
            for p in files_under(vault / root):
                relative = p.relative_to(vault).as_posix()
                info = dict(path=relative, root=root, extension=p.suffix.lower(), bytes=p.stat().st_size)
                if any(SENSITIVE_NAME.search(part) for part in p.relative_to(vault).parts):
                    info['status'] = 'excluded_sensitive_name'
                elif p.suffix.lower() not in {'.md', '.txt'}:
                    info['status'] = 'needs_text_extraction'
                elif root == '图谱索引' or relative in {'wiki/index.md', 'wiki/gaps.md'} or p.name in {'AGENTS.md', 'CLAUDE.md'}:
                    info['status'] = 'navigation_only'
                else:
                    try:
                        before = p.stat()
                        raw = p.read_bytes()
                        after = p.stat()
                        if (before.st_mtime_ns, before.st_size) != (after.st_mtime_ns, after.st_size):
                            info['status'] = 'changed_during_read'
                            inventory.append(info)
                            continue
                        source = raw.decode('utf-8-sig')
                    except (UnicodeError, OSError):
                        info['status'] = 'read_failed'
                        inventory.append(info)
                        continue
                    if any(pattern.search(source) for pattern in SECRET_PATTERNS):
                        info['status'] = 'excluded_suspected_secret'
                    else:
                        parts = chunks(source)
                        info['sha256'] = hashlib.sha256(raw).hexdigest()
                        info['chunks'] = len(parts)
                        info['status'] = 'indexed' if parts else 'empty_text'
                        kind = 'wiki' if root == 'wiki' else 'source'
                        con.execute('INSERT INTO documents VALUES (?,?,?,?)',
                                    (relative, info['sha256'], after.st_mtime_ns, kind))
                        chunk_rows=[]
                        for part in parts:
                            cur = con.execute('INSERT INTO chunks(path,heading,date_label,start_line,end_line,text) VALUES (?,?,?,?,?,?)',
                                              (relative, part['heading'], part['date_label'], part['start_line'], part['end_line'], part['text']))
                            con.execute('INSERT INTO search(rowid,title,heading,body) VALUES (?,?,?,?)',
                                        (cur.lastrowid, ' '.join(terms(p.stem)), ' '.join(terms(part['heading'])), ' '.join(terms(part['text']))))
                            chunk_rows.append(dict(id=cur.lastrowid,**part))
                        build_catalog(con,relative,source,chunk_rows)
                        total_chunks += len(parts)
                inventory.append(info)
        statuses = Counter(row['status'] for row in inventory)
        attachments = Counter(row['extension'] for row in inventory if row['status'] == 'needs_text_extraction')
        summary = dict(built_at=datetime.now().astimezone().isoformat(timespec='seconds'),
                       vault=str(vault), roots=list(ROOTS), files=len(inventory),
                       statuses=dict(statuses), attachments=dict(attachments), chunks=total_chunks,
                       mode='Chinese character bigrams + SQLite FTS5 BM25; no embedding or LLM',
                       scope_note='Raw, protected/hidden/archive directories, symlinks and other roots excluded. Attachments inventoried only.')
        con.execute('INSERT INTO meta VALUES (?,?)', ('summary', json.dumps(summary, ensure_ascii=False)))
        con.execute('INSERT INTO meta VALUES (?,?)', ('inventory', json.dumps(inventory, ensure_ascii=False)))
        con.commit()
        con.close()
        os.replace(temp_path, db_path)
        return summary
    finally:
        if temp_path.exists():
            temp_path.unlink()


@contextmanager
def connect(db_path: Path):
    if not db_path.is_file():
        raise ValueError('Index does not exist; run build first')
    con = sqlite3.connect(db_path.resolve().as_uri() + '?mode=ro', uri=True)
    con.row_factory = sqlite3.Row
    try:
        yield con
    finally:
        con.close()


def metadata(db_path: Path, key='summary'):
    with connect(db_path) as con:
        return json.loads(con.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()[0])


def candidate_filter(allowed_paths=None,allowed_chunk_ids=None):
    clauses=[];args=[]
    for column,values in [('c.path',allowed_paths),('c.id',allowed_chunk_ids)]:
        if values is not None:
            if not values:clauses.append('0')
            else:
                ordered=sorted(values);clauses.append(column+' IN ('+','.join('?' for _ in ordered)+')');args.extend(ordered)
    return (' AND '+' AND '.join(clauses) if clauses else ''),args


def keyword_candidates(db_path: Path, tokens: list[str], kind='all', folder='',allowed_paths=None,allowed_chunk_ids=None) -> list[dict]:
    if not tokens:
        return []
    expression = ' OR '.join('"' + t.replace('"', '""') + '"' for t in tokens)
    with connect(db_path) as con:
        where,args=candidate_filter(allowed_paths,allowed_chunk_ids)
        candidates = con.execute('''
        SELECT c.*, d.sha256, d.kind, bm25(search, 2.0, 1.5, 1.0) AS rank
        FROM search JOIN chunks c ON c.id=search.rowid JOIN documents d ON d.path=c.path
        WHERE search MATCH ? AND (?='all' OR d.kind=?)
        AND (?='' OR instr(d.path, ?||'/')=1) '''+where+''' ORDER BY rank LIMIT 160
        ''', [expression, kind, kind, folder, folder]+args).fetchall()
    return [dict(row) for row in candidates]


def title_focus_candidates(db_path: Path, query: str, kind: str, lexical: list[dict], folder='',allowed_paths=None,allowed_chunk_ids=None):
    """Reserve one substantive passage per explicitly named, indexed topic (max 3).

    This is a bounded exact-title route, not LLM query rewriting or a relevance claim.
    Chinese names must match a full filename stem; Latin terms must match whole words.
    The normal lexical/semantic ordering fills the remaining result slots.
    """
    normalize = lambda text: unicodedata.normalize('NFKC', text).casefold()
    normalized = normalize(query)
    latin_pattern = r'(?<![a-z0-9_])[a-z][a-z0-9_]{2,}(?![a-z0-9_])'
    latin = {m[0]: m.start() for m in re.finditer(latin_pattern, normalized)}
    groups = {}
    with connect(db_path) as con:
        documents = con.execute("SELECT path FROM documents WHERE (?='all' OR kind=?)", (kind, kind))
        for document in documents:
            path = document['path']
            if allowed_paths is not None and path not in allowed_paths:continue
            if allowed_chunk_ids is not None and not con.execute('SELECT 1 FROM chunks WHERE path=? AND id IN ('+(','.join('?' for _ in allowed_chunk_ids) or 'NULL')+') LIMIT 1',[path]+sorted(allowed_chunk_ids)).fetchone():continue
            if folder and not path.startswith(folder+'/'):
                continue
            title = normalize(Path(path).stem)
            labels = set(re.findall(latin_pattern, title)) & latin.keys()
            # Exact Chinese/mixed-language titles are useful without a Chinese tokenizer.
            if len(title) >= 4 and re.search(r'[\u3400-\u9fff]', title) and title in normalized:
                labels.add(title)
            for label in labels:
                groups.setdefault(label, []).append(path)
        # Prefer a full named title over a Latin component of the same mention.
        labels = [label for label in groups if not any(label != other and label in other
                  and normalized.find(other) <= normalized.find(label) < normalized.find(other)+len(other)
                  for other in groups)]
        labels.sort(key=lambda label: (normalized.find(label), -len(label)))
        rank = {row['id']: i for i, row in enumerate(lexical)}
        focused, used = [], set()
        for label in labels[:3]:
            paths = groups[label]
            marks = ','.join('?' for _ in paths)
            where,args=candidate_filter(allowed_paths,allowed_chunk_ids)
            rows = [dict(row) for row in con.execute(f'''
                SELECT c.*,d.sha256,d.kind FROM chunks c JOIN documents d ON c.path=d.path
                WHERE c.path IN ({marks}) {where}
            ''', paths+args)]

            def priority(row):
                title = normalize(Path(row['path']).stem)
                leaf = row['heading'].split(' / ')[-1].strip()
                navigation = bool(re.fullmatch(r'关联|相关(?:链接|页面|资料)?|参考(?:资料|文献)?|待验证|待补|我的疑问', leaf))
                intro = bool(re.search(r'一句话|定义|核心结论', leaf))
                substantive = len(re.sub(r'[#\s\W_]', '', row['text'])) >= 12
                return (navigation or not substantive, title != label, len(title),
                        not intro, rank.get(row['id'], 10000), row['start_line'])

            rows.sort(key=priority)
            chosen = next((row for row in rows if row['id'] not in used and not priority(row)[0]), None)
            if chosen:
                focused.append(dict(chosen, retrieval=['title'], focus_term=label))
                used.add(chosen['id'])
    return focused


def search(db_path: Path, query: str, kind: str = 'all', limit: int = 8, mode: str = 'keyword', folder: str = '', current_only: bool = False, exclude_texts: set[str] | None = None, accept_result=None,allowed_paths=None,allowed_chunk_ids=None) -> dict:
    if kind not in {'all', 'source', 'wiki'} or mode not in {'keyword', 'semantic', 'hybrid'}:
        raise ValueError('Unknown source filter or search mode')
    if len(query) > 500:
        raise ValueError('Please keep the query within 500 characters')
    tokens = list(dict.fromkeys(terms(query, query=True)))[:100]
    response = dict(query=query, tokens=tokens, results=[], mode=mode, retrieval_version=RETRIEVAL_VERSION,
                    note='检索结果是候选材料，尚未经过大模型核对。语义检索即使缺少相关资料也可能返回候选。')
    if not query.strip() or not tokens:
        return response
    summary = metadata(db_path)
    lexical = keyword_candidates(db_path, tokens, kind, folder,allowed_paths,allowed_chunk_ids) if mode != 'semantic' else []
    if mode == 'keyword':
        candidates = [dict(row, retrieval=['keyword']) for row in lexical]
    else:
        from semantic_search import get_index, fuse_rankings
        engine = get_index(db_path)
        filters={} if allowed_paths is None and allowed_chunk_ids is None else dict(allowed_paths=allowed_paths,allowed_chunk_ids=allowed_chunk_ids)
        semantic = engine.ranked(query, kind, folder=folder,**filters)
        response['embedding_model'] = engine.meta['model_id']
        response['embedding_revision'] = engine.meta['revision']
        response['inference_location'] = 'local'
        if mode == 'semantic':
            candidates = [dict(row, retrieval=['semantic']) for row in semantic]
        else:
            by_id = {row['id']: dict(row, retrieval=['keyword']) for row in lexical}
            for row in semantic:
                if row['id'] in by_id:
                    by_id[row['id']]['retrieval'].append('semantic')
                    by_id[row['id']]['semantic_similarity'] = row['semantic_similarity']
                else:
                    by_id[row['id']] = dict(row, retrieval=['semantic'])
            order = fuse_rankings([r['id'] for r in lexical], [r['id'] for r in semantic])
            candidates = [by_id[chunk_id] for chunk_id in order]
    if mode != 'semantic':
        focused = title_focus_candidates(db_path, query, kind, lexical, folder,allowed_paths,allowed_chunk_ids)
        previous = {row['id']: row for row in candidates}
        for row in focused:
            row['retrieval'] += previous.get(row['id'], {}).get('retrieval', [])
        focus_ids = {row['id'] for row in focused}
        candidates = focused + [row for row in candidates if row['id'] not in focus_ids]
        response['query_focus'] = [row['focus_term'] for row in focused]
    seen, per_doc, source_status = set(), Counter(), {}
    for row in candidates:
        result = dict(row)
        fingerprint = hashlib.sha256(result['text'].strip().encode()).hexdigest()
        if fingerprint in seen or per_doc[result['path']] >= 2:
            continue
        path = Path(summary['vault']) / result['path']
        if result['path'] not in source_status:
            try:
                if path.is_symlink() or path.resolve() != path or not path.is_file():
                    source_status[result['path']] = 'missing_or_moved'
                else:
                    source_status[result['path']] = 'current' if hashlib.sha256(path.read_bytes()).hexdigest() == result['sha256'] else 'changed'
            except OSError:
                source_status[result['path']] = 'missing_or_moved'
        result['source_status'] = source_status[result['path']]
        if current_only and result['source_status'] != 'current':
            continue
        if exclude_texts and hashlib.sha256(result['text'].encode()).hexdigest() in exclude_texts:
            seen_texts=response.setdefault('seen_texts',[])
            digest=hashlib.sha256(result['text'].encode()).hexdigest()
            if len(seen_texts)<8 and digest not in seen_texts:seen_texts.append(digest)
            continue
        result['absolute_path'] = str(path)
        result['obsidian_url'] = 'obsidian://open?path=' + quote(str(path), safe='')
        result['matched_terms'] = sorted(set(tokens) & set(terms(result['text'])))
        # BM25 is a ranking score, not a probability or confidence rating.
        result.pop('rank', None)
        result.pop('sha256')
        if accept_result is not None and not accept_result(result):
            continue
        seen.add(fingerprint)
        per_doc[result['path']] += 1
        response['results'].append(result)
        if len(response['results']) >= max(1, min(limit, 30)):
            break
    response['built_at'] = summary['built_at']
    return response


def system_summary(db_path):
    result = metadata(db_path)
    result['retrieval_version'] = RETRIEVAL_VERSION
    try:
        from semantic_search import status
        result['embedding'] = status(db_path)
    except (ImportError, OSError, ValueError) as error:
        result['embedding'] = dict(ready=False, reason=str(error))
    return result


def write_reports(db_path: Path, directory: Path):
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    summary, inventory = metadata(db_path), metadata(db_path, 'inventory')
    (directory / 'inventory.json').write_text(json.dumps(dict(summary=summary, files=inventory), ensure_ascii=False, indent=2), encoding='utf-8')
    lines = ['# 检索覆盖报告', '', '生成时间：' + summary['built_at'], '',
             '这是本机实验索引的覆盖情况。文件计数不等于内容正确率或检索召回率。', '',
             '| 目录 | 已索引文件 | 待提取附件 | 导航页 | 其他未索引 |', '|---|---:|---:|---:|---:|']
    for root in ROOTS:
        count = Counter(r['status'] for r in inventory if r['root'] == root)
        other = sum(v for k, v in count.items() if k not in {'indexed', 'needs_text_extraction', 'navigation_only'})
        lines.append(f"| {root} | {count['indexed']} | {count['needs_text_extraction']} | {count['navigation_only']} | {other} |")
    lines += ['', f"共 {summary['statuses'].get('indexed', 0)} 份文字文件、{summary['chunks']} 个可定位片段。", '',
              '## 附件缺口', '', '以下只按文件格式盘点，尚未判断 PDF 是否含文字层，也未执行 OCR。', '']
    lines += [f'- `{ext}`：{count} 个。' for ext, count in sorted(summary['attachments'].items())]
    lines += ['', '## 范围与限制', '',
              '- Raw 正文、重要信息、隐藏目录、归档、符号链接，以及不在所列目录内的文件没有进入索引。',
              '- Wiki 的 index/gaps 和图谱索引作为导航盘点，不作为回答证据检索。',
              '- 名称或内容出现疑似凭据的文件跳过；该筛选不能替代人工内容分类。',
              '- 主题目录记录可能混有摘录、AI 对话或自己的文字，目录位置不代表作者或认可程度。',
              '- 小节日期仅作为原文标签；文件修改时间不当作事件时间。',
              '- 本报告统计文字索引覆盖；Embedding 状态另见 embedding-build.json 或页面模型状态。尚无自动同步或大模型回答。',
              '- 再运行 build 会重新生成索引，删除或重命名文件不会继续留在新索引中。',
              '- 搜索时检查命中文件指纹；变化后会提示，原引用行号以建索引时的快照为准。', '',
              '## 需要单独检查的文件', '']
    unusual = [r for r in inventory if r['status'] not in {'indexed', 'needs_text_extraction', 'navigation_only'}]
    lines += [f"- `{r['path']}`：{r['status']}。" for r in unusual] or ['无。']
    (directory / 'coverage.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def make_server(db_path: Path, port: int, provider=None, updates=None,collections_path=None):
    from answering import DeepSeek, PreviewStore, prepare, public_preview
    from retrieval_service import RetrievalService
    provider = provider or DeepSeek()
    previews = PreviewStore()
    notes = RetrievalService(lambda: updates.current_db() if updates else db_path)
    from research_service import ResearchService
    research=ResearchService(notes,collections_path or HERE/'data/research-collections.json')

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Queries are personal data; do not write them to access logs.

        def send(self, payload: bytes, content_type: str, status=200):
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(payload)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            self.end_headers()
            self.wfile.write(payload)

        def json_response(self, payload, status=200):
            self.send(json.dumps(payload, ensure_ascii=False).encode(), 'application/json; charset=utf-8', status)

        def valid_origin(self, require_origin=False):
            hosts = {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}
            host = self.headers.get('Host', '')
            origin = self.headers.get('Origin')
            return (host in hosts and self.headers.get('Sec-Fetch-Site') != 'cross-site'
                    and (origin == 'http://' + host if require_origin or origin else True))

        def do_POST(self):
            if not self.valid_origin(require_origin=True):
                return self.json_response({'error': '仅允许本机页面发起操作。'}, 403)
            if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                return self.json_response({'error': '需要 JSON 请求。'}, 415)
            try:
                length = int(self.headers.get('Content-Length', '0'))
                route=urlparse(self.path).path
                if not 0 < length <= (65536 if route.startswith('/api/research/') else 16384):
                    return self.json_response({'error': '请求长度不正确。'}, 413)
                self.connection.settimeout(65)
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError('请求格式不正确。')
                path = urlparse(self.path).path
                if path.startswith('/api/research/'):
                    import inspect
                    routes={'/api/research/documents':research.list_research_documents,'/api/research/narrow':research.narrow_research,'/api/research/begin':research.begin_research,'/api/research/search':research.search_research,'/api/research/sections':research.list_research_sections,'/api/research/read':research.read_research_sections,'/api/research/assess':research.assess_research}
                    method=routes.get(path)
                    if method is None:return self.json_response({'error':'Not found'},404)
                    try:inspect.signature(method).bind(**data)
                    except TypeError:raise ValueError('请求缺少字段或包含未知字段。') from None
                    result=method(**data)
                    if len(json.dumps(result,ensure_ascii=False))>16000:
                        from retrieval_service import SourceError
                        raise SourceError('RESPONSE_BUDGET','本次结构或来源超过返回预算，请减少单次事项/引文。')
                    return self.json_response(result)
                if path == '/api/notes/search':
                    return self.json_response(notes.search_notes(data.get('query',''), data.get('scope','all'),
                        data.get('folder'), data.get('limit',8), data.get('mode','hybrid'),data.get('turn_id'),data.get('purpose','')))
                if path == '/api/notes/excerpt':
                    return self.json_response(notes.get_excerpt(data.get('hit_token'), data.get('context_lines',8),data.get('turn_id')))
                if path == '/api/notes/verify':
                    return self.json_response(notes.verify_evidence(data.get('turn_id'),data.get('items')))
                if path == '/api/notes/resolve':
                    return self.json_response(notes.resolve_note(data.get('path'),data.get('vault_id')))
                if path == '/api/index/check':
                    if updates is None:
                        raise ValueError('此服务未启用自动更新。')
                    return self.json_response(updates.trigger())
                if path == '/api/prepare':
                    active_db = updates.current_db() if updates else db_path
                    if data.get('selected_ids') is not None and data.get('index_revision') != index_revision(active_db):
                        raise ValueError('索引已更新，请重新找一找，再选择回答材料。')
                    pack = prepare(active_db, data.get('query', ''), data.get('kind', 'all'),
                                   data.get('mode', 'hybrid'), data.get('selected_ids'))
                    value = public_preview(pack) | {'preview_id': previews.add(pack)}
                elif path == '/api/answer':
                    value = provider.answer(previews.get(data.get('preview_id')), data.get('model'))
                elif path == '/api/provider/connect':
                    value = provider.configure(data.get('api_key'))
                elif path == '/api/provider/disconnect':
                    value = provider.disconnect()
                else:
                    return self.json_response({'error': 'Not found'}, 404)
                return self.json_response(value)
            except (ValueError, ImportError) as error:
                # JSON decoder messages do not include the submitted body or API key.
                return self.json_response({'error': str(error), 'code': getattr(error,'code','INVALID_REQUEST')}, 400)
            except (OSError, sqlite3.Error):
                return self.json_response({'error': '本机索引或连接暂时不可用，请重试。'}, 503)

        def do_OPTIONS(self):
            self.send(b'Forbidden', 'text/plain', 403)

        def do_GET(self):
            if not self.valid_origin():
                return self.send(b'Forbidden', 'text/plain', 403)
            parsed = urlparse(self.path)
            try:
                if parsed.path == '/':
                    return self.send((HERE / 'index.html').read_bytes(), 'text/html; charset=utf-8')
                if parsed.path == '/api/health':
                    value = notes.health()
                elif parsed.path == '/api/notes/folders':
                    value = dict(folders=notes.folders())
                elif parsed.path == '/api/index/status':
                    value = updates.status() if updates else dict(enabled=False)
                elif parsed.path == '/api/summary':
                    value = system_summary(updates.current_db() if updates else db_path)
                elif parsed.path == '/api/provider/status':
                    value = provider.status()
                elif parsed.path == '/api/search':
                    params = parse_qs(parsed.query)
                    active_db = updates.current_db() if updates else db_path
                    value = search(active_db, params.get('q', [''])[0], params.get('kind', ['all'])[0],
                                   mode=params.get('mode', ['keyword'])[0])
                    value['index_revision'] = index_revision(active_db)
                else:
                    return self.send(b'Not found', 'text/plain', 404)
                self.send(json.dumps(value, ensure_ascii=False).encode(), 'application/json; charset=utf-8')
            except (ValueError, ImportError) as error:
                self.send(json.dumps({'error': str(error)}).encode(), 'application/json', 400)
            except (OSError, sqlite3.Error):
                self.send(b'{"error":"Index unavailable; rebuild it and retry."}', 'application/json', 503)
    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    return server


def index_revision(db):
    stat = db.stat()
    return hashlib.sha256(f'{db.resolve()}:{stat.st_mtime_ns}:{stat.st_size}'.encode()).hexdigest()


def serve(db_path: Path, port: int):
    from generation_store import service_lock
    with service_lock(db_path.parent):
        from index_updates import IndexUpdates
        updates = IndexUpdates(db_path)
        server = make_server(db_path, port, updates=updates)
        updates.start()
        print(f'Local search: http://127.0.0.1:{server.server_port}', flush=True)
        try:
            server.serve_forever()
        finally:
            updates.stop()
            server.server_close()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, default=DEFAULT_DB)
    subs = parser.add_subparsers(dest='command', required=True)
    b = subs.add_parser('build')
    b.add_argument('--vault', type=Path, default=DEFAULT_VAULT)
    b.add_argument('--reports', type=Path, default=HERE / 'outputs')
    q = subs.add_parser('search')
    q.add_argument('query')
    q.add_argument('--kind', choices=['all', 'source', 'wiki'], default='all')
    q.add_argument('--limit', type=int, default=8)
    q.add_argument('--mode', choices=['keyword', 'semantic', 'hybrid'], default='keyword')
    subs.add_parser('summary')
    s = subs.add_parser('serve')
    s.add_argument('--port', type=int, default=8767)
    args = parser.parse_args()
    if args.command in {'search', 'summary'} and args.db == DEFAULT_DB:
        from index_updates import active_db
        args.db = active_db(args.db)
    if args.command == 'build':
        value = build(args.vault, args.db)
        write_reports(args.db, args.reports)
    elif args.command == 'search':
        value = search(args.db, args.query, args.kind, args.limit, args.mode)
    elif args.command == 'summary':
        value = system_summary(args.db)
    else:
        return serve(args.db, args.port)
    print(json.dumps(value, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
