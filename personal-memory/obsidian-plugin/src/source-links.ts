const roots = new Set(['wiki','我的存在','世界知识','运动健身（大学）','计算机和AI','英语','图谱索引']);
const blocked = new Set(['raw','重要信息','archive','node_modules']);
export function allowedNote(path: string): boolean {
  if(typeof path!=='string'||path.startsWith('/')||path.includes('\\'))return false;
  const parts=path.split('/');
  return roots.has(parts[0])&&parts.every(p=>!!p&&p!=='.'&&p!=='..'&&!p.startsWith('.')&&!blocked.has(p)&&!/卡密|密码|私钥|密钥|凭据|(?:^|[._-])(?:secrets?|credentials?)(?:[._-]|$)/i.test(p));
}
export function locateOriginal(buffer:string,start:number,end:number,expected:string,startCol?:number,endCol?:number){
  const lines=buffer.split(/\r?\n/);
  if(!Number.isInteger(start)||!Number.isInteger(end)||start<1||end<start||end>lines.length)
    throw Error('编辑器里的原文已经变化，请保存并更新后重新搜索。');
  const a=startCol??0,b=endCol??Array.from(lines[end-1]).length;
  if(!Number.isInteger(a)||!Number.isInteger(b)||a<0||b<0||a>Array.from(lines[start-1]).length||b>Array.from(lines[end-1]).length||(start===end&&b<a))throw Error('来源字符范围不正确。');
  const fromCh=Array.from(lines[start-1]).slice(0,a).join('').length,toCh=Array.from(lines[end-1]).slice(0,b).join('').length;
  const selected=lines.slice(start-1,end);
  selected[0]=selected[0].slice(fromCh);
  selected[selected.length-1]=selected[selected.length-1].slice(0,start===end?toCh-fromCh:toCh);
  if(selected.join('\n')!==expected)throw Error('编辑器里的原文已经变化，请保存并更新后重新搜索。');
  return {from:{line:start-1,ch:fromCh},to:{line:end-1,ch:toCh}};
}
export type MemoryLink={hit:string;revision:string}|{hit:string;revision:string;version:2;vault:string;path:string};
export function parseMemoryLink(href:string):MemoryLink|null{
  try{
    const url=new URL(href),q=url.searchParams;
    if(url.protocol!=='obsidian:'||url.hostname!=='memory-source'||url.username||url.password||url.port||url.hash||url.pathname)return null;
    for(const [key] of q)if(q.getAll(key).length!==1||!['v','vault','vault_id','note','path','hit','revision'].includes(key))return null;
    decodeURIComponent(url.search);
    const hit=q.get('hit')||'',revision=q.get('revision')||'';
    if(!/^[A-Za-z0-9_-]{24}$/.test(hit)||!/^[a-f0-9]{64}$/.test(revision))return null;
    if(q.has('v')||q.has('vault')||q.has('vault_id')||q.has('note')||q.has('path')){
      const route=q.get('vault')||'',vault=q.get('vault_id')??route,path=q.get('note')??q.get('path')??'';
      if(q.has('note')&&q.has('path'))return null;
      // Obsidian consumes `vault` and absolute `path` before the plugin runs.
      // New links use a route name plus vault_id/note; old in-app v2 links remain valid.
      if(q.has('vault_id')&&(!route||route==='.'||route==='..'||route.length>255||/[\\/\x00-\x1f]/.test(route)))return null;
      if(q.get('v')!=='2'||!/^[a-f0-9]{64}$/.test(vault)||!allowedNote(path))return null;
      return {hit,revision,version:2,vault,path};
    }
    return {hit,revision};
  }catch{return null;}
}
export function parseProtocolData(params:Record<string,string>,currentVaultName?:string):MemoryLink|null{
  const {action,...query}=params;
  if(action!=='memory-source')return null;
  // Obsidian may consume `vault` when dispatching the public callback.
  // Reconstruct routing metadata only; the separate SHA remains mandatory.
  if(query.vault_id&&!Object.hasOwn(query,'vault')&&currentVaultName)query.vault=currentVaultName;
  return parseMemoryLink('obsidian://memory-source?'+new URLSearchParams(query));
}
export async function resolveSource(link:MemoryLink,request:(path:string,body:unknown)=>Promise<any>){
  let source;
  try{source=await request('/api/notes/excerpt',{hit_token:link.hit,context_lines:0});}
  catch(error){
    if(!('version' in link)||!['SOURCE_EXPIRED','INDEX_CHANGED','SOURCE_CHANGED'].includes((error as {code?:string}).code||''))throw error;
    const current=await request('/api/notes/resolve',{path:link.path,vault_id:link.vault});
    if(current.path!==link.path||current.vault_id!==link.vault||!allowedNote(current.path))throw Error('来源身份不匹配。');
    return {precise:false,source:current};
  }
  if(source.index_revision!==link.revision||!allowedNote(source.path)||('version' in link&&(source.path!==link.path||source.vault_id!==link.vault)))throw Error('来源身份不匹配，请重新搜索。');
  return {precise:true,source};
}
export function highlightText(source:{text:string;start_line:number;start_col?:number;highlight_start_line:number;highlight_end_line:number;highlight_start_col?:number;highlight_end_col?:number;highlight_text?:string}):string{
  if(source.highlight_text!==undefined)return source.highlight_text;
  const lines=source.text.split('\n').slice(source.highlight_start_line-source.start_line,source.highlight_end_line-source.start_line+1);
  const a=(source.highlight_start_col??0)-(source.highlight_start_line===source.start_line?(source.start_col??0):0);
  const b=source.highlight_end_col===undefined?undefined:source.highlight_end_col-(source.highlight_end_line===source.start_line?(source.start_col??0):0);
  if(lines.length===1)return Array.from(lines[0]).slice(a,b).join('');
  lines[0]=Array.from(lines[0]).slice(a).join('');
  if(b!==undefined)lines[lines.length-1]=Array.from(lines[lines.length-1]).slice(0,b).join('');
  return lines.join('\n');
}
export function selectOriginal(editor:{getValue:()=>string;setSelection:(from:{line:number;ch:number},to:{line:number;ch:number})=>void},start:number,end:number,text:string,startCol?:number,endCol?:number){
  const range=locateOriginal(editor.getValue(),start,end,text,startCol,endCol);
  editor.setSelection(range.from,range.to);return range;
}

export function compactSources<T extends {path:string}>(hits:T[]):{hit:T;label:string}[]{
  const unique=[...new Map(hits.map(h=>[h.path,h])).values()];
  return unique.map(hit=>{
    const parts=hit.path.replace(/\.md$/i,'').split('/'),title=parts.at(-1)!;
    const peers=unique.filter(h=>h.path!==hit.path&&h.path.replace(/\.md$/i,'').split('/').at(-1)===title);
    let depth=1;
    while(peers.some(h=>h.path.replace(/\.md$/i,'').split('/').slice(-depth).join('/')===parts.slice(-depth).join('/'))&&depth<parts.length)depth++;
    return {hit,label:depth===1?title:`${title}（${parts.slice(-depth,-1).join('/')}）`};
  });
}
