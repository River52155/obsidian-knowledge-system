import { requestUrl } from 'obsidian';
export interface Hit {hit_token:string;vault_id:string;path:string;heading:string;text:string;start_line:number;end_line:number;open_url:string;kind:string;source_status:string;}
export interface SearchResult {turn_id:string;turn_stats:{original_query:string;searches:number;text_chars:number};already_seen:{hit_token:string}[];stop_reason:string;hits:Hit[];index_revision:string;skipped:{path:string;reason:string}[];}
export interface Excerpt extends Hit {turn_id:string;sha256:string;highlight_text?:string;highlight_start_line:number;highlight_end_line:number;index_revision:string;}
export class MemoryAPI {
  private checkedAt=0;
  private ready=false;
  constructor(private vaultPath:string,private port:number=8767){
    if(!Number.isInteger(port)||port<1||port>65535)throw Error('端口必须是1至65535的整数。');
  }
  private async raw(path:string,body?:unknown){
    let response;
    try{
      response=await requestUrl({url:'http://127.0.0.1:'+this.port+path,method:body===undefined?'GET':'POST',
        headers:{Origin:'http://127.0.0.1:'+this.port},contentType:'application/json',
        body:body===undefined?undefined:JSON.stringify(body),throw:false});
    }catch{throw Object.assign(Error('本机资料服务暂不可用，请检查连接。'),{code:'NETWORK_ERROR'});}
    if(response.status!==200)throw Object.assign(Error(response.json?.error||'本机资料查询失败。'),{code:response.json?.code||'UNKNOWN'});
    return response.json;
  }

  async health(requireReady=true){
    const h=await this.raw('/api/health');
    const digest=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(this.vaultPath));
    const expected=[...new Uint8Array(digest)].map(v=>v.toString(16).padStart(2,'0')).join('');
    if(h.service_id!=='river.personal-memory'||h.vault_id!==expected)throw Object.assign(Error('本机服务对应其他资料库，已停止读取。'),{code:'VAULT_MISMATCH'});
    this.ready=!!h.ready;this.checkedAt=Date.now();
    if(requireReady&&!this.ready)throw Error('资料索引还在准备，请稍后重试。');
    return h;
  }
  async request(path:string,body?:unknown){
    const monitoring=['/api/index/status','/api/index/check'].includes(path);
    if(Date.now()-this.checkedAt>15000||(!monitoring&&!this.ready))await this.health(!monitoring);
    return this.raw(path,body);
  }
}
