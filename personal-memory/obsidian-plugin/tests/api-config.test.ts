import test from 'node:test';
import assert from 'node:assert/strict';
import {build} from 'esbuild';
import {fileURLToPath} from 'node:url';
const result=await build({entryPoints:[fileURLToPath(new URL('../src/api.ts',import.meta.url))],bundle:true,format:'esm',platform:'node',write:false,plugins:[{name:'obsidian-test-transport',setup(b){b.onResolve({filter:/^obsidian$/},()=>({path:'obsidian',namespace:'fake'}));b.onLoad({filter:/.*/,namespace:'fake'},()=>({contents:'export const requestUrl = (...args) => globalThis.__memoryRequest(...args);'}));}}]});
const {MemoryAPI}=await import('data:text/javascript;base64,'+Buffer.from(result.outputFiles[0].text).toString('base64'));
const hash=async(s:string)=>Buffer.from(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(s))).toString('hex');
test('only integer loopback ports and correct vault identity allow requests',async()=>{
 for(const port of [0,65536,NaN,1.5,'https://example.com'])assert.throws(()=>new MemoryAPI('/test',port));
 const urls:string[]=[];(globalThis as any).__memoryRequest=async(r:any)=>{urls.push(r.url);return {status:200,json:{service_id:'river.personal-memory',vault_id:await hash('/other'),ready:true}};};
 await assert.rejects(new MemoryAPI('/test',9000).request('/api/notes/folders'),/其他资料库/);assert.equal(urls.length,1);assert.match(urls[0],/^http:\/\/127.0.0.1:9000\//);
});
test('unready service permits monitoring but not note bodies; new API rechecks identity',async()=>{
 let ready=false;const urls:string[]=[];(globalThis as any).__memoryRequest=async(r:any)=>{urls.push(r.url);return {status:200,json:r.url.endsWith('/api/health')?{service_id:'river.personal-memory',vault_id:await hash('/test'),ready}:{state:'building'}};};
 const api=new MemoryAPI('/test',9001);await api.request('/api/index/status');await assert.rejects(api.request('/api/notes/search',{}),/准备/);assert.ok(!urls.some(u=>u.endsWith('/api/notes/search')));
 ready=true;await api.request('/api/notes/search',{});const second=new MemoryAPI('/test',9002);await second.request('/api/index/status');assert.ok(urls.some(u=>u==='http://127.0.0.1:9002/api/health'));
});
