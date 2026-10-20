"""Small in-memory retrieval turns. No chat history, persistence or model calls."""
from collections import OrderedDict
import hashlib
import secrets
import threading
import time


class ContextError(ValueError):
    def __init__(self,message,code='TURN_EXPIRED'):
        super().__init__(message);self.code=code


class QueryContextStore:
    def __init__(self, clock=time.monotonic):
        self.clock=clock;self.lock=threading.RLock();self.turns=OrderedDict()

    def _get(self, turn_id):
        now=self.clock()
        for key in list(self.turns):
            if now-self.turns[key]['touched']>=900:del self.turns[key]
        if not isinstance(turn_id,str) or turn_id not in self.turns:
            raise ContextError('查询上下文已失效，请作为新问题重新检索。')
        row=self.turns[turn_id];row['touched']=now;self.turns.move_to_end(turn_id)
        return row

    def start(self, original_query: str) -> str:
        if not isinstance(original_query,str) or not original_query.strip() or len(original_query)>500:
            raise ValueError('问题须为1至500字符。')
        with self.lock:
            for key in list(self.turns):
                if self.clock()-self.turns[key]['touched']>=900:del self.turns[key]
            while len(self.turns)>=128:self.turns.popitem(last=False)
            turn=secrets.token_urlsafe(18)
            self.turns[turn]=dict(original_query=original_query,searches=0,text_chars=0,seen=set(),references={},touched=self.clock())
            return turn

    def get(self, turn_id: str):
        with self.lock:
            row=self._get(turn_id)
            return dict(row,seen=set(row['seen']),references=dict(row['references']))

    def bind_index(self, turn_id, revision, vault_id):
        with self.lock:
            row=self._get(turn_id)
            if row.get('vault_id',vault_id)!=vault_id:
                raise ContextError('查询上下文不属于当前资料库。','VAULT_MISMATCH')
            if row.get('revision',revision)!=revision:
                del self.turns[turn_id]
                raise ContextError('索引已更新，本轮上下文已失效；请用原始问题省略turn_id重新检索。','INDEX_CHANGED')
            row.update(revision=revision,vault_id=vault_id)

    def begin_search(self, turn_id: str, purpose: str):
        with self.lock:
            row=self._get(turn_id)
            if not isinstance(purpose,str) or len(purpose)>200 or (row['searches'] and not purpose.strip()):
                raise ValueError('补查需说明1至200字符的具体资料缺口。')
            if row['searches']>=3:return False
            row['searches']+=1;return True

    def admit_text(self, turn_id: str, text: str) -> bool:
        digest=hashlib.sha256(text.encode()).hexdigest()
        with self.lock:
            row=self._get(turn_id)
            if digest in row['seen'] or row['text_chars']+len(text)>24000:return False
            row['seen'].add(digest);row['text_chars']+=len(text);return True

    def reference(self, turn_id, text, token):
        with self.lock:self._get(turn_id)['references'][hashlib.sha256(text.encode()).hexdigest()]=token

    def stats(self, turn_id: str) -> dict:
        with self.lock:
            row=self._get(turn_id)
            return dict(original_query=row['original_query'][:200],searches=row['searches'],text_chars=row['text_chars'],unique_texts=len(row['seen']))
