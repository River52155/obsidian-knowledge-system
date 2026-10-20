"""Read-only per-case evaluation against an explicit frozen generation."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo
from memory_search import RETRIEVAL_VERSION, search


def ranks(results, targets):
    return [next((i+1 for i, r in enumerate(results) if r['path']==t['path']
                  and (t.get('line') is None or r['start_line']<=t['line']<=r['end_line'])), None) for t in targets]


def evaluate(cases, snapshot_dir):
    directory=Path(snapshot_dir).resolve(); db=directory/'baseline.sqlite3'
    if not db.is_file() or db.is_symlink():
        raise ValueError('Explicit snapshot baseline.sqlite3 required; live/default fallback forbidden')
    artifacts=[db]+[p for p in [directory/'embedding-index.npz',directory/'snapshot.json'] if p.is_file()]
    hashes=lambda:{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in artifacts}
    before=hashes(); rows=[]
    for case in cases:
        result=search(db,case['query'],case.get('scope','all'),mode=case.get('mode','hybrid'))
        targets=case.get('targets',[]); positions=ranks(result['results'],targets)
        rows.append(dict(label=case['label'],query=case['query'],ranks=positions,
                         missing_targets=[t['path'] for t,r in zip(targets,positions) if r is None],
                         result_count=len(result['results']),
                         results=[{k:r[k] for k in ('path','start_line','end_line','source_status')} for r in result['results']]))
    if before!=hashes():raise ValueError('Snapshot changed during evaluation')
    return dict(checked_at=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),snapshot_db=str(db),
                snapshot_hashes=before,unchanged=True,retrieval_version=RETRIEVAL_VERSION,rows=rows,
                note='Retrieval only. Frozen corpus; current file freshness reported separately. Chat/save cases need separate acceptance.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('cases','snapshot-dir','out'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args(); cases=json.loads(args.cases.read_text(encoding='utf-8'))
    result=evaluate(cases['cases'] if isinstance(cases,dict) else cases,args.snapshot_dir)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    for row in result['rows']:print(row['label'],row['ranks'],'candidates:',row['result_count'])

if __name__=='__main__':main()
