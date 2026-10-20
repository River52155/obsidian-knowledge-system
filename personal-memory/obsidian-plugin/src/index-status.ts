export function formatIndexStatus(s:any):string{
 if(s.state==='error')return '更新未完成，仍使用上一版。'+(s.active_error?.paths?.join('、')||'请稍后重试。');
 if(s.check_requested)return '已请求检查，等待后台处理…';
 if(s.state==='building'){
  const p=s.progress;return '正在更新资料，搜索使用上一版。'+(p?`新算${p.encoded_vectors}，复用${p.reused_vectors}，共${p.total_vectors}段。`:'');
 }
 if(s.state==='checking')return '正在检查资料变化…';
 return (s.message||'已检查')+(s.last_updated?` 最近更新：${s.last_updated}`:'');
}
export class IndexStatusController{
 private serial=0;private timer:any;private started=0;
 private readStatus:()=>Promise<any>;private show:(s:string)=>void;private schedule:(f:()=>void,ms:number)=>any;private cancel:(id:any)=>void;private clock:()=>number;
 constructor(readStatus:()=>Promise<any>,show:(s:string)=>void,schedule:(f:()=>void,ms:number)=>any=(f,ms)=>globalThis.setTimeout(f,ms),cancel:(id:any)=>void=id=>globalThis.clearTimeout(id),clock:()=>number=Date.now){this.readStatus=readStatus;this.show=show;this.schedule=schedule;this.cancel=cancel;this.clock=clock;}
 async start(){this.stop();this.started=this.clock();const serial=this.serial;await this.poll(serial);}
 stop(){++this.serial;if(this.timer!==undefined)this.cancel(this.timer);this.timer=undefined;}
 private async poll(serial:number):Promise<void>{
  try{
   const s=await this.readStatus();if(serial!==this.serial)return;this.show(formatIndexStatus(s));
   if(s.check_requested||['building','checking'].includes(s.state)){
    if(this.clock()-this.started>=60000){this.show('后台仍在处理，可以稍后再检查。');return;}
    this.timer=this.schedule(()=>{void this.poll(serial);},2000);
   }
  }catch(e){if(serial===this.serial)this.show((e as Error).message);}
 }
}
