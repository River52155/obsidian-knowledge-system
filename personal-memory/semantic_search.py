"""Local BGE embeddings, versioned against the exact source index. No inference API."""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import zipfile
import zlib

HERE = Path(__file__).resolve().parent
CONFIG = json.loads((HERE / 'embedding-model.json').read_text())
DEFAULT_INDEX = HERE / 'data/embedding-index.npz'
DEFAULT_DB = HERE / 'data/baseline.sqlite3'
INFERENCE_VERSION = 1

# Model inference loads only the downloaded local snapshot. Never send note text over HTTP.
os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
os.environ['HF_HUB_DISABLE_IMPLICIT_TOKEN'] = '1'
os.environ['TOKENIZERS_PARALLELISM'] = 'false'


def config_hash():
    return hashlib.sha256(json.dumps(CONFIG, sort_keys=True).encode()).hexdigest()


def read_corpus(db: Path):
    con = sqlite3.connect(db.resolve().as_uri() + '?mode=ro', uri=True)
    con.row_factory = sqlite3.Row
    try:
        rows = [dict(row) for row in con.execute('''
            SELECT c.*, d.kind, d.sha256 FROM chunks c JOIN documents d ON d.path=c.path ORDER BY c.id
        ''')]
    finally:
        con.close()
    signature = hashlib.sha256()
    for row in rows:
        signature.update(json.dumps(row, ensure_ascii=False, sort_keys=True).encode())
        signature.update(b'\n')
    return rows, signature.hexdigest()


def download_model():
    from huggingface_hub import snapshot_download
    path = snapshot_download(
        repo_id=CONFIG['model_id'], revision=CONFIG['revision'], token=False,
        local_dir=HERE / CONFIG['model_dir'],
        allow_patterns=['model.safetensors', 'config.json', 'tokenizer.json',
                        'tokenizer_config.json', 'special_tokens_map.json', 'vocab.txt'],
    )
    print('Downloaded official model snapshot:', path, flush=True)


def token_windows(text: str, offsets: list, window: int, overlap: int):
    """Return contiguous source substrings; overlap avoids losing boundary context."""
    if not 0 <= overlap < window:
        raise ValueError('Invalid token window settings')
    start = 0
    while start < len(offsets):
        stop = min(start + window, len(offsets))
        a = offsets[start][0]
        b = offsets[stop - 1][1]
        if b > a:
            yield a, b, text[a:b]
        if stop == len(offsets):
            break
        start = stop - overlap


class Encoder:
    def __init__(self):
        import torch
        from transformers import AutoModel, AutoTokenizer
        self.torch = torch
        model_dir = HERE / CONFIG['model_dir']
        if not (model_dir / 'model.safetensors').is_file():
            raise ValueError('模型尚未下载，请先运行 semantic_search.py download。')
        self.device = 'mps' if torch.backends.mps.is_available() else 'cpu'
        torch.set_num_threads(4)
        self.tokenizer = AutoTokenizer.from_pretrained(model_dir, local_files_only=True,
                                                      trust_remote_code=False, use_fast=True)
        self.model = AutoModel.from_pretrained(model_dir, local_files_only=True,
                                               trust_remote_code=False, use_safetensors=True).to(self.device)
        self.model.eval()
        if self.model.config.hidden_size != CONFIG['dimension']:
            raise ValueError('模型维度与配置不一致。')
        self.lock = threading.RLock()

    def tokenize(self, *args, **kwargs):
        with self.lock:
            return self.tokenizer(*args, **kwargs)

    def encode(self, texts: list[str]):
        # The fast tokenizer also mutates padding/truncation settings internally.
        # Serialize preprocessing and inference while background builds share this model.
        with self.lock:
            return self._encode(texts)

    def _encode(self, texts: list[str]):
        import numpy as np
        encoded = self.tokenizer(texts, padding=True, truncation=False, return_tensors='pt')
        if encoded['input_ids'].shape[1] > CONFIG['max_input_tokens']:
            raise ValueError('输入超出模型长度，请缩短问题或重新切分片段。')
        encoded = {key: value.to(self.device) for key, value in encoded.items()}
        with self.lock, self.torch.inference_mode():
            # BGE model card specifies the CLS representation, followed by L2 normalization.
            cls = self.model(**encoded).last_hidden_state[:, 0]
            result = self.torch.nn.functional.normalize(cls, p=2, dim=1).cpu().numpy().astype(np.float32)
        if not np.isfinite(result).all():
            raise ValueError('模型输出含非有限数值。')
        return result

    def query(self, text: str):
        return self.encode([CONFIG['query_instruction'] + text])[0]

    def passages(self, rows):
        for row in rows:
            title = Path(row['path']).stem + '\n' + row['heading']
            head = self.tokenize(title, add_special_tokens=False, return_offsets_mapping=True, verbose=False)['offset_mapping']
            if head:
                title = title[:head[min(len(head), CONFIG['prefix_tokens']) - 1][1]]
            offsets = self.tokenize(row['text'], add_special_tokens=False, return_offsets_mapping=True, verbose=False)['offset_mapping']
            for a, b, body in token_windows(row['text'], offsets, CONFIG['body_window_tokens'], CONFIG['overlap_tokens']):
                yield row['id'], a, b, title + '\n' + body


def build_embeddings(db=DEFAULT_DB, destination=DEFAULT_INDEX, *, write_report=True, reuse_from=None, progress=None):
    import numpy as np
    rows, fingerprint = read_corpus(db)
    started = time.monotonic()
    encoder = get_encoder()
    from embedding_artifacts import passage_manifest
    manifest = passage_manifest(rows, encoder, config_hash(), INFERENCE_VERSION)
    passages = [(p["chunk_id"], p["start_char"], p["end_char"], p["text"]) for p in manifest]
    cache={}
    if reuse_from is not None:
        previous=Path(reuse_from)
        try:
            validated=validate_index(previous/'baseline.sqlite3',encoder=encoder)
            if validated['artifact_version']==2:
                with np.load(previous/'embedding-index.npz',allow_pickle=False) as old:
                    cache={str(k):v.copy() for k,v in zip(old['input_keys'],old['vectors'])}
        except (ValueError,OSError):pass
    reused=sum(p['input_key'] in cache for p in manifest)
    missing={p['input_key']:p['text'] for p in manifest if p['input_key'] not in cache}
    keys=list(missing);done=set()
    def report():
        if progress:progress(dict(encoded_vectors=sum(p['input_key'] in done for p in manifest),reused_vectors=reused,total_vectors=len(manifest)))
    report()
    max_seen=max((len(ids) for i in range(0,len(passages),16) for ids in encoder.tokenize([p[3] for p in passages[i:i+16]],truncation=False)['input_ids']),default=0)
    for i in range(0,len(keys),16):
        batch_keys=keys[i:i+16];values=encoder.encode([missing[k] for k in batch_keys])
        cache.update(zip(batch_keys,values));done.update(batch_keys);report()
    vectors=np.stack([cache[p['input_key']] for p in manifest]) if manifest else np.empty((0,CONFIG['dimension']),dtype=np.float32)
    _, after = read_corpus(db)
    if after != fingerprint:
        raise ValueError('文字索引在计算期间改变，未替换向量索引。')
    meta = dict(artifact_version=2, model_id=CONFIG['model_id'], revision=CONFIG['revision'], dimension=int(vectors.shape[1]),
                config_hash=config_hash(), inference_version=INFERENCE_VERSION, corpus_fingerprint=fingerprint,
                encoded_unique_inputs=len(keys), encoded_vectors=len(manifest)-reused, reused_vectors=reused,
                chunks=len(rows), embedded_chunks=len(set(p[0] for p in passages)), vectors=len(passages),
                max_input_tokens_observed=max_seen, token_truncation=False, device=encoder.device,
                built_at=datetime.now().astimezone().isoformat(timespec='seconds'),
                build_seconds=round(time.monotonic() - started, 2))
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix='.embedding-', suffix='.npz', dir=destination.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            np.savez_compressed(stream, vectors=vectors, chunk_ids=np.array([p[0] for p in passages], dtype=np.int64),
                                start_chars=np.array([p[1] for p in passages], dtype=np.int64),
                                end_chars=np.array([p[2] for p in passages], dtype=np.int64),
                                input_keys=np.array([p['input_key'] for p in manifest], dtype='U64'),
                                metadata=np.array(json.dumps(meta, ensure_ascii=False)))
        os.replace(temporary, destination)
    finally:
        if Path(temporary).exists():
            Path(temporary).unlink()
    if write_report:
        (HERE / 'outputs').mkdir(exist_ok=True)
        (HERE / 'outputs/embedding-build.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    return meta


def validate_artifact(meta: dict, fingerprint: str):
    if meta.get('config_hash') != config_hash() or meta.get('inference_version') != INFERENCE_VERSION:
        raise ValueError('模型配置已经变化，请重新生成向量索引。')
    if meta.get('corpus_fingerprint') != fingerprint:
        raise ValueError('文字索引已经变化，请重新生成向量索引。')


def fuse_rankings(keyword_ids, semantic_ids, k=60):
    """Reciprocal rank fusion; scores are ordering aids, not confidence."""
    scores = {}
    for ranking in (keyword_ids, semantic_ids):
        for rank, chunk_id in enumerate(dict.fromkeys(ranking), start=1):
            scores[chunk_id] = scores.get(chunk_id, 0) + 1 / (k + rank)
    return sorted(scores, key=lambda chunk_id: (-scores[chunk_id], chunk_id))


class SemanticIndex:
    def __init__(self, db=DEFAULT_DB, index=None):
        import numpy as np
        index = index or index_path(db)
        if not index.is_file():
            raise ValueError('向量索引尚未建立，请先运行 semantic_search.py build。')
        self.db, self.index = db, index
        self.meta = validate_index(db, index)
        rows, _ = read_corpus(db)
        with np.load(index, allow_pickle=False) as data:
            self.vectors = data['vectors']
            self.ids = data['chunk_ids']
        self.rows = {row['id']: row for row in rows}
        self.stat = self.file_state()
        self.encoder = get_encoder()

    def file_state(self):
        return tuple((p.stat().st_mtime_ns, p.stat().st_size) for p in (self.db, self.index))

    def ranked(self, query, kind='all', limit=160, folder='',allowed_paths=None,allowed_chunk_ids=None):
        import numpy as np
        if self.file_state() != self.stat:
            raise ValueError('索引文件已经更新，请重启检索服务后查询。')
        scores = self.vectors @ self.encoder.query(query)
        order = np.argsort(-scores, kind='stable')
        seen, result = set(), []
        for position in order:
            chunk_id = int(self.ids[position])
            row = self.rows[chunk_id]
            if allowed_paths is not None and row['path'] not in allowed_paths:continue
            if allowed_chunk_ids is not None and chunk_id not in allowed_chunk_ids:continue
            if chunk_id in seen or (kind != 'all' and row['kind'] != kind) or (folder and not row['path'].startswith(folder+'/')):
                continue
            seen.add(chunk_id)
            result.append(dict(row, semantic_similarity=float(scores[position])))
            if len(result) >= limit:
                break
        return result


def index_path(db):
    return Path(db).parent / 'embedding-index.npz'


_ENCODER = None
_ENCODER_LOCK = threading.Lock()


def get_encoder():
    global _ENCODER
    with _ENCODER_LOCK:
        if _ENCODER is None:
            _ENCODER = Encoder()
        return _ENCODER


_ENGINES = {}
_ENGINE_LOCK = threading.Lock()


def get_index(db=DEFAULT_DB):
    key = str(db.resolve())
    with _ENGINE_LOCK:
        if key not in _ENGINES:
            engine = SemanticIndex(db)
            if len(_ENGINES) >= 2:
                _ENGINES.pop(next(iter(_ENGINES)))
            _ENGINES[key] = engine
        return _ENGINES[key]


_VALIDATED = {}
_VALIDATION_LOCK = threading.RLock()


def validate_index(db, index=None, *, encoder=None, force=False):
    import numpy as np
    from embedding_artifacts import passage_manifest, validate_arrays
    db=Path(db);index=Path(index) if index is not None else index_path(db)
    try:
        key=(str(db.resolve()),str(index.resolve()),*(x for p in (db,index) for x in (p.stat().st_size,p.stat().st_mtime_ns)),config_hash(),INFERENCE_VERSION)
        with _VALIDATION_LOCK:
            if not force and key in _VALIDATED:return dict(_VALIDATED[key])
            rows,fingerprint=read_corpus(db)
            manifest=passage_manifest(rows,encoder or get_encoder(),config_hash(),INFERENCE_VERSION)
            with np.load(index,allow_pickle=False) as data:
                meta=json.loads(str(data['metadata']))
                if not isinstance(meta,dict):raise ValueError('产物元数据格式错误。')
                validate_artifact(meta,fingerprint)
                if meta.get('chunks')!=len(rows):raise ValueError('片段计数不一致。')
                result=validate_arrays(manifest,data,meta,dimension=CONFIG['dimension'])
            output=dict(meta,**result)
            if len(_VALIDATED)>=4:_VALIDATED.pop(next(iter(_VALIDATED)))
            _VALIDATED[key]=output
            return dict(output)
    except (KeyError,TypeError,IndexError,OSError,ValueError,sqlite3.Error,zipfile.BadZipFile,zlib.error,EOFError):
        raise ValueError('向量索引无效或不完整，请检查更新。') from None


def status(db=DEFAULT_DB):
    try:
        meta=validate_index(db)
        return dict(meta,ready=True)
    except (ValueError,ImportError,OSError):
        return dict(ready=False,reason='向量索引未就绪或不完整，请检查更新。')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['download', 'build', 'status'])
    args = parser.parse_args()
    if args.command == 'download':
        download_model()
    else:
        from index_updates import active_db
        value = build_embeddings() if args.command == 'build' else status(active_db(DEFAULT_DB))
        print(json.dumps(value, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
