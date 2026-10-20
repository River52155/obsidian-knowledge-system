"""Temporary synthetic BGE benchmark; every index destination is explicit."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import argparse,json,tempfile,time
import numpy as np
from memory_search import build,search
from semantic_search import build_embeddings,validate_index

def run(chars):
 with tempfile.TemporaryDirectory(prefix='index-benchmark-') as folder:
  root=Path(folder);v=root/'vault';(v/'我的存在').mkdir(parents=True);topics=['河流散步','山峰登高','音乐练习','图书阅读','游泳运动']
  for j,topic in enumerate(topics):
   header='# 2026-10-19\n';lines=[];size=0;i=0;target=chars//5+(j<chars%5)
   while size<target:
    line=f'{topic}合成记录第{i}行，学习与记录变化，观察当天过程和不同细节。\n';lines.append(line);size+=len(line);i+=1
   (v/'我的存在'/f'{topic}.md').write_text((header+''.join(lines))[:target])
  def generate(name,reuse=None):
   d=root/name/'baseline.sqlite3';t=time.monotonic();build(v,d);meta=build_embeddings(d,d.parent/'embedding-index.npz',write_report=False,reuse_from=reuse);validate_index(d,force=True);return d,dict(meta,wall_seconds=round(time.monotonic()-t,3))
  old,initial=generate('initial');note=v/'我的存在'/f'{topics[0]}.md';note.write_text(note.read_text().replace('学习与记录变化','学习与记录调整',1))
  inc,incremental=generate('incremental',old.parent);full,full_meta=generate('full')
  with np.load(inc.parent/'embedding-index.npz') as a,np.load(full.parent/'embedding-index.npz') as b:
   minimum=float(np.min(np.sum(a['vectors']*b['vectors'],axis=1))) if len(a['vectors']) else 1.0
  queries=[]
  for topic in topics:
   left=search(inc,topic,mode='hybrid')['results'];right=search(full,topic,mode='hybrid')['results'];expected=f'我的存在/{topic}.md';queries.append(dict(query=topic,target=expected,incremental_found=expected in {r['path'] for r in left},full_found=expected in {r['path'] for r in right}))
  return dict(chars=chars,initial=initial,incremental=incremental,full=full_meta,min_cosine=minimum,queries=queries,passed=minimum>=.9999 and all(q['incremental_found'] and q['full_found'] for q in queries))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--chars',type=int,default=300000);p.add_argument('--out',type=Path,required=True);a=p.parse_args();r=run(a.chars);a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(json.dumps(r,ensure_ascii=False,indent=2));print(json.dumps(r,ensure_ascii=False));raise SystemExit(0 if r['passed'] else 1)
