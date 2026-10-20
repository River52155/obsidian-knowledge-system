"""Exact encoding-input manifests; no source writes or model inference."""
from collections import Counter
import hashlib,json
import numpy as np

def passage_manifest(rows,encoder,config_digest,inference_version):
    result=[]
    for cid,a,b,text in encoder.passages(rows):
        key=hashlib.sha256(json.dumps(dict(config_hash=config_digest,inference_version=inference_version,text=text),ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        result.append(dict(chunk_id=cid,start_char=a,end_char=b,input_key=key,text=text))
    return result

def validate_arrays(manifest,arrays,metadata,*,dimension):
    try:
        vectors=arrays['vectors'];ids=arrays['chunk_ids'];starts=arrays['start_chars'];ends=arrays['end_chars'];version=metadata.get('artifact_version',1)
        if version not in (1,2):raise ValueError()
        n=len(manifest)
        if vectors.shape!=(n,dimension) or not np.issubdtype(vectors.dtype,np.floating) or not np.isfinite(vectors).all():raise ValueError()
        if not np.allclose(np.linalg.norm(vectors,axis=1),1,atol=1e-4):raise ValueError()
        for values in [ids,starts,ends]:
            if values.shape!=(n,) or not np.issubdtype(values.dtype,np.integer):raise ValueError()
        expected=Counter((p['chunk_id'],p['start_char'],p['end_char']) for p in manifest)
        if Counter(zip(ids.tolist(),starts.tolist(),ends.tolist()))!=expected:raise ValueError()
        if version==2:
            keys=arrays['input_keys']
            if keys.shape!=(n,) or keys.dtype.kind!='U':raise ValueError()
            want=Counter((*k,key) for k,key in [((p['chunk_id'],p['start_char'],p['end_char']),p['input_key']) for p in manifest])
            if Counter(zip(ids.tolist(),starts.tolist(),ends.tolist(),keys.tolist()))!=want:raise ValueError()
        if metadata.get('vectors')!=n or metadata.get('embedded_chunks')!=len({p['chunk_id'] for p in manifest}) or metadata.get('dimension')!=dimension:raise ValueError()
        return dict(artifact_version=version,upgrade_required=version!=2)
    except (KeyError,TypeError,IndexError,ValueError):
        raise ValueError('向量产物清单不完整或格式错误，请重新生成索引。') from None
