import test from 'node:test';
import assert from 'node:assert/strict';
import {IndexStatusController,formatIndexStatus} from '../src/index-status.ts';
test('queued current status keeps polling and close ignores late response',async()=>{
 const shown:string[]=[];let next:(()=>void)|undefined;let reads=0;
 const c=new IndexStatusController(async()=>{reads++;return {state:'current',check_requested:reads===1,message:'已检查'};},s=>shown.push(s),(f)=>{next=f;return 1;},()=>{},()=>0);
 await c.start();assert.ok(next);next!();await new Promise(r=>setImmediate(r));assert.equal(reads,2);assert.ok(shown.at(-1)?.includes('已检查'));
 let resolve:(s:any)=>void=()=>{};const d=new IndexStatusController(()=>new Promise(r=>{resolve=r;}),s=>shown.push(s),(f)=>1,()=>{},()=>0);
 const p=d.start();d.stop();const count=shown.length;resolve({state:'current',message:'不应覆盖'});await p;assert.equal(shown.length,count);
});
test('error displays safe paths and timeout remains processing',async()=>{
 assert.match(formatIndexStatus({state:'error',active_error:{paths:['wiki/坏.txt']}}),/坏.txt/);
 let now=0;let next:(()=>void)|undefined;const shown:string[]=[];
 const c=new IndexStatusController(async()=>({state:'building',phase:'embedding'}),s=>shown.push(s),(f)=>{next=f;return 1;},()=>{},()=>now);
 await c.start();now=61000;next!();await new Promise(r=>setImmediate(r));assert.match(shown.at(-1)!,/后台仍在处理/);
});
test('default timers work with browser host receiver requirements',async(t)=>{
 // Browser timer functions reject a controller instance as their receiver.
 const shown:string[]=[];const handle={} as ReturnType<typeof setTimeout>;let scheduled=0;let cancelled=0;
 t.mock.method(globalThis,'setTimeout',function(this:unknown){
  assert.equal(this,globalThis);scheduled++;return handle;
 });
 t.mock.method(globalThis,'clearTimeout',function(this:unknown,id:unknown){
  assert.equal(this,globalThis);assert.equal(id,handle);cancelled++;
 });
 const c=new IndexStatusController(async()=>({state:'current',check_requested:true}),s=>shown.push(s));
 await c.start();c.stop();
 assert.equal(scheduled,1);assert.equal(cancelled,1);
 assert.deepEqual(shown,['已请求检查，等待后台处理…']);
});
