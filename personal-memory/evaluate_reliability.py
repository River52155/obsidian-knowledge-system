"""Executable synthetic coverage evaluation, separate from model judgments."""
import argparse,hashlib,json,tempfile
from pathlib import Path
from acceptance.reliability_fixtures import CASES,build_fixture,collections
from memory_search import build
from research_service import ResearchService
from retrieval_service import RetrievalService

def evaluate(case_id,service,extra_target=None):
    c=next(c for c in CASES if c['id']==case_id)
    facets=[dict(id='f'+str(i),question=c['question'],evidence_kind=k) for i,k in enumerate(c['kinds'])]
    dates={} if c['strategy']=='focused' else dict(date_from='2026-08-01' if case_id=='months' else '2026-10-18',date_to='2026-10-19')
    paths=['我的存在/截至9月的日记.md'] if case_id=='months' else None
    s=service.begin_research(c['question'],facets,c['collection'],c['strategy'],paths=paths,**dates);rid=s['research_id']
    listing=service.list_research_sections(rid);items=list(listing['sections'])
    while listing['next_cursor']:
        listing=service.list_research_sections(rid,cursor=listing['next_cursor']);items+=listing['sections']
    hits=[]
    for i in range(0,len(items),8):
        page=service.read_research_sections(rid,[x['section_id'] for x in items[i:i+8]]);hits+=page['hits']
        while page['next_cursor']:
            page=service.read_research_sections(rid,cursor=page['next_cursor']);hits+=page['hits']
    found={h['path'] for h in hits};scope=service._session(rid)['allowed_paths'];missing=sorted(scope-found)
    if extra_target:missing.append(extra_target)
    return dict(case_id=case_id,flow='enumerate_and_read',found=sorted(found),returned_sections=len({h['section_id'] for h in hits}),missing_targets=missing,out_of_scope=sum(h['path'] not in scope for h in hits),coverage=service.sessions.coverage(rid),passed=not missing and all(h['path'] in scope for h in hits))

def run_program(extra_target=None):
    executed=[]
    with tempfile.TemporaryDirectory(prefix='reliability-eval-') as name:
        root=Path(name)
        for c in CASES:
            folder=root/c['id'];v=folder/'vault';spec=build_fixture(v,c['id']);db=folder/'baseline.sqlite3';build(v,db);config=folder/'collections.json';collections(config)
            report=evaluate(c['id'],ResearchService(RetrievalService(lambda:db),config),extra_target)
            report['corpus_hash']=hashlib.sha256(json.dumps(spec['docs'],sort_keys=True).encode()).hexdigest();executed.append(report)
    return dict(executed_cases=executed,passed=all(r['passed'] for r in executed),semantic_evaluation='not performed by program')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--mode',choices=['program'],default='program');p.add_argument('--out',type=Path,required=True);a=p.parse_args();r=run_program();a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(json.dumps(r,ensure_ascii=False,indent=2));print(json.dumps({'passed':r['passed'],'executed_cases':len(r['executed_cases'])}));raise SystemExit(0 if r['passed'] else 1)
