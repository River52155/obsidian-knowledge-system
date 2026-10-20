"""Reproducible synthetic research evaluation; native answers are separate."""
import argparse
import json
import hashlib
from pathlib import Path
from acceptance.research_fixtures import build_fixture
from memory_search import build, search


def evaluate(phase, root):
    root.mkdir(parents=True,exist_ok=True)
    vault=root/'vault'; expected=build_fixture(vault);db=root/'baseline.sqlite3'
    build(vault,db)
    cases=json.loads((Path(__file__).parent/'acceptance/research-cases.json').read_text())['cases']
    old=search(db,'2026年10月记录',kind='source',mode='keyword')
    result=dict(phase=phase,expected=expected,declared_cases=cases,executed_flows=['four_date_reading','five_facet_scoped_retrieval'] if phase=='after' else ['legacy_diary_top_k'],corpus_hashes={p.relative_to(vault).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in vault.rglob('*.md')},legacy_diary_segments=sum(r['path']==expected['diary'] for r in old['results']),native='not measured by this script; declared cases are not all executed by this evaluator')
    if phase=='baseline':result['new_tools']='unsupported on baseline'
    else:
        from research_service import ResearchService
        from retrieval_service import RetrievalService
        config=root/'collections.json'
        config.write_text(json.dumps({'schema_version':1,'collections':[
            dict(id='technical',description='Synthetic technical',include_prefixes=['计算机和AI'],include_paths=[],exclude_prefixes=[]),
            dict(id='personal',description='Synthetic personal',include_prefixes=['我的存在'],include_paths=[],exclude_prefixes=[])]},ensure_ascii=False))
        service=ResearchService(RetrievalService(lambda:db),config)
        session=service.begin_research('回顾10月',[dict(id='dates',question='哪些变化',evidence_kind='timeline')],'personal','timeline',paths=[expected['diary']],date_from='2026-10-01',date_to='2026-10-31')
        rid=session['research_id'];listing=service.list_research_sections(rid);ids=[s['section_id'] for s in listing['sections']]
        read=service.read_research_sections(rid,ids)
        while read['next_cursor']:read=service.read_research_sections(rid,cursor=read['next_cursor'])
        coverage=read['coverage']; result['coverage']=coverage
        from semantic_search import build_embeddings
        build_embeddings(db,root/'embedding-index.npz',write_report=False)
        facets=[dict(id=fid,question=q,evidence_kind=kind) for fid,q,kind in [('architecture','Transformer架构','explanation'),('retrieval','Embedding语义检索','explanation'),('practice','搭建RAG原型','practice'),('outcome','效果测试','outcome'),('first','首次日期','first_use')]]
        s=service.begin_research('五事项技术问题',facets,'technical','focused');all_hits=[]
        for f in facets:all_hits.extend(service.search_research(s['research_id'],f['id'],f['question'],'核对该事项所缺的证据')['hits'])
        answers=[]
        for f in facets:
            matches=[h for h in all_hits if {'architecture':'架构','retrieval':'检索','practice':'实践'}.get(f['id'],'<missing>') in h['path']]
            h=matches[0] if matches else None
            answers.append(dict(facet_id=f['id'],status='supported' if h else 'insufficient',claim='合成证据存在' if h else '没有足够证据',citations=[dict(hit_token=h['hit_token'],quote=h['text'][:min(60,len(h['text']))])] if h else [],limitations='日期标签不是人生首次，教程不是实践或效果证明。'))
        assessment=service.assess_research(s['research_id'],answers)
        targets=set(expected['technical_targets']);found={h['path'] for h in all_hits}
        result['technical']=dict(facets=len(answers),missing_targets=sorted(targets-found),out_of_scope=sum(not h['path'].startswith('计算机和AI/') for h in all_hits),assessment=assessment)
        result['passed']=coverage['coverage_complete'] and coverage['covered_heading_dates']==expected['expected_dates'] and not targets-found and result['technical']['out_of_scope']==0 and assessment['structural_valid']
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--phase',choices=['baseline','after'],required=True);p.add_argument('--fixture-root',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    value=evaluate(a.phase,a.fixture_root);a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n');print(json.dumps(value,ensure_ascii=False))
    if a.phase=='after' and not value['passed']:raise SystemExit(1)
