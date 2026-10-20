import test from 'node:test';
import assert from 'node:assert/strict';
import { allowedNote, locateOriginal, parseMemoryLink, resolveSource, selectOriginal, highlightText, parseProtocolData } from '../src/source-links.ts';

test('current note and selection respect the indexed scope',()=>{
  for(const path of ['wiki/a/相同.md','我的存在/含 空格/笔记.md']) assert.equal(allowedNote(path),true);
  for(const path of ['重要信息/a.md','raw/a.md','wiki/../重要信息/a.md','wiki/.hidden/a.md','/etc/passwd']) assert.equal(allowedNote(path),false);
});
test('edited buffers cannot reuse an obsolete line range',()=>{
  assert.deepEqual(locateOriginal('# 标题\n\n原来的那一句。',3,3,'原来的那一句。'),{from:{line:2,ch:0},to:{line:2,ch:7}});
  assert.throws(()=>locateOriginal('新插入一行\n# 标题\n\n原来的那一句。',3,3,'原来的那一句。'),/变化/);
});
test('only our own bounded source links are routed inside the workspace',()=>{
  const hit='abcdefghijklmnopqrstuvwx',revision='a'.repeat(64);
  assert.deepEqual(parseMemoryLink(`obsidian://memory-source?hit=${hit}&revision=${revision}`),{hit,revision});
  assert.equal(parseMemoryLink('https://example.com/'),null);
  assert.equal(parseMemoryLink('obsidian://open?file=important'),null);
  assert.equal(parseMemoryLink('obsidian://memory-source?hit=../../etc'),null);
});

test('v2 links require a unique full safe identity and preserve Chinese space paths',()=>{
  const fields=new URLSearchParams({v:'2',vault:'b'.repeat(64),path:'wiki/含 空格/同名.md',hit:'abcdefghijklmnopqrstuvwx',revision:'a'.repeat(64)});
  const url='obsidian://memory-source?'+fields;
  assert.deepEqual(parseMemoryLink(url),{version:2,vault:'b'.repeat(64),path:'wiki/含 空格/同名.md',hit:'abcdefghijklmnopqrstuvwx',revision:'a'.repeat(64)});
  for(const key of ['v','vault','path','hit','revision']){const bad=new URLSearchParams(fields);bad.delete(key);assert.equal(parseMemoryLink('obsidian://memory-source?'+bad),null);}
  for(const suffix of ['&v=2','&vault='+ 'b'.repeat(64),'&path=wiki/b.md','#fragment'])assert.equal(parseMemoryLink(url+suffix),null);
  for(const path of ['../wiki/a.md','wiki/../重要信息/a.md','raw/a.md']){const bad=new URLSearchParams(fields);bad.set('path',path);assert.equal(parseMemoryLink('obsidian://memory-source?'+bad),null);}
  assert.equal(parseMemoryLink(url.replace('memory-source?','user@memory-source?')),null);
});
test('only known lifecycle errors permit fallback; old links cannot fallback',async()=>{
  const source={version:2 as const,vault:'b'.repeat(64),path:'wiki/含 空格.md',hit:'abcdefghijklmnopqrstuvwx',revision:'a'.repeat(64)};
  for(const code of ['SOURCE_EXPIRED','INDEX_CHANGED','SOURCE_CHANGED','NETWORK_ERROR','VAULT_MISMATCH','SOURCE_FORBIDDEN','SOURCE_MISSING','UNKNOWN']){
    const calls:string[]=[];
    const request=async(path:string)=>{calls.push(path);if(path.endsWith('excerpt'))throw Object.assign(Error('failed'),{code});return {path:source.path,vault_id:source.vault,title:'含 空格'};};
    if(['SOURCE_EXPIRED','INDEX_CHANGED','SOURCE_CHANGED'].includes(code)){
      const result=await resolveSource(source,request);assert.equal(result.precise,false);assert.deepEqual(calls,['/api/notes/excerpt','/api/notes/resolve']);
    }else{await assert.rejects(()=>resolveSource(source,request));assert.deepEqual(calls,['/api/notes/excerpt']);}
  }
  await assert.rejects(()=>resolveSource({hit:source.hit,revision:source.revision},async()=>{throw Object.assign(Error('expired'),{code:'SOURCE_EXPIRED'});}));
});
test('dirty editor is never overwritten or selected using obsolete lines',()=>{
  let selected=false;const dirty={getValue:()=> 'unsaved insertion\noriginal line',setSelection:()=>{selected=true;}};
  assert.throws(()=>selectOriginal(dirty,1,1,'original line'),/变化/);assert.equal(selected,false);
});

test('long excerpts can locate the original without a duplicated highlight body',()=>{
  const source={text:'context before\noriginal line one\noriginal line two\ncontext after',start_line:8,highlight_start_line:9,highlight_end_line:10};
  assert.equal(highlightText(source),'original line one\noriginal line two');
  let selected:unknown;
  selectOriginal({getValue:()=> '0\n1\n2\n3\n4\n5\n6\ncontext before\noriginal line one\noriginal line two\ncontext after',setSelection:(from,to)=>{selected={from,to};}},9,10,highlightText(source));
  assert.deepEqual(selected,{from:{line:8,ch:0},to:{line:9,ch:17}});
});

test('public Obsidian protocol callback includes action metadata, not a query parameter',()=>{
  const data={action:'memory-source',v:'2',vault:'b'.repeat(64),path:'wiki/中文 空格.md',hit:'abcdefghijklmnopqrstuvwx',revision:'a'.repeat(64)};
  assert.deepEqual(parseProtocolData(data),{version:2,vault:data.vault,path:data.path,hit:data.hit,revision:data.revision});
  assert.equal(parseProtocolData({...data,action:'open'}),null);
  assert.equal(parseProtocolData({...data,path:'wiki/../重要信息/a.md'}),null);
});

test('native routing uses the Vault name while identity remains a separate hash',()=>{
  const fields=new URLSearchParams({v:'2',vault:'中文 Vault',vault_id:'b'.repeat(64),note:'wiki/含 空格.md',hit:'abcdefghijklmnopqrstuvwx',revision:'a'.repeat(64)});
  assert.deepEqual(parseMemoryLink('obsidian://memory-source?'+fields),{version:2,vault:'b'.repeat(64),path:'wiki/含 空格.md',hit:'abcdefghijklmnopqrstuvwx',revision:'a'.repeat(64)});
  assert.equal(parseMemoryLink('obsidian://memory-source?'+fields+'&vault_id='+ 'b'.repeat(64)),null);
  for(const field of ['vault','vault_id']){const bad=new URLSearchParams(fields);bad.delete(field);assert.equal(parseMemoryLink('obsidian://memory-source?'+bad),null);}
  const bad=new URLSearchParams(fields);bad.set('vault','../other');assert.equal(parseMemoryLink('obsidian://memory-source?'+bad),null);
});

// Obsidian's main-process router consumes `path` before `vault`, and its parser
// uses decodeURIComponent rather than form decoding (so generated spaces need %20).
test('native callback note path survives without triggering absolute-path routing',()=>{
  const data={action:'memory-source',v:'2',vault:'中文 Vault',vault_id:'b'.repeat(64),note:'wiki/含 空格.md',hit:'abcdefghijklmnopqrstuvwx',revision:'a'.repeat(64)};
  assert.deepEqual(parseProtocolData(data),{version:2,vault:'b'.repeat(64),path:data.note,hit:data.hit,revision:data.revision});
  assert.equal(parseProtocolData({...data,path:'wiki/other.md'}),null);
});

test('public callback consumes vault routing metadata; current workspace supplies it',()=>{
  const data={action:'memory-source',v:'2',vault_id:'b'.repeat(64),note:'wiki/含 空格.md',hit:'abcdefghijklmnopqrstuvwx',revision:'a'.repeat(64)};
  assert.deepEqual(parseProtocolData(data,'中文 Vault'),{version:2,vault:'b'.repeat(64),path:data.note,hit:data.hit,revision:data.revision});
  assert.equal(parseProtocolData(data),null);
  assert.equal(parseProtocolData({...data,vault_id:'not-a-hash'},'中文 Vault'),null);
  assert.equal(parseProtocolData({...data,note:'wiki/../重要信息/a.md'},'中文 Vault'),null);
});
