"""Bounded, idle-expiring research state and source-coordinate accounting."""
import secrets
import threading
import time
from retrieval_service import SourceError


def merge_ranges(ranges):
    result=[]
    for a,b in sorted(ranges):
        if result and a<=result[-1][1]:result[-1]=(result[-1][0],max(b,result[-1][1]))
        else:result.append((a,b))
    return result


class ResearchSessionStore:
    def __init__(self,clock=time.monotonic):
        self.clock=clock;self.lock=threading.RLock();self.rows={}
    def purge(self):
        for key in list(self.rows):
            if self.clock()-self.rows[key]['touched']>=900:del self.rows[key]
    def start(self,spec,revision,scope_hash):
        with self.lock:
            self.purge()
            if len(self.rows)>=16:raise SourceError('RESOURCE_LIMIT','研究会话容量已满，请稍后再试。')
            rid=secrets.token_urlsafe(18);turn=secrets.token_urlsafe(18)
            row=dict(spec,research_id=rid,turn_id=turn,revision=revision,scope_hash=scope_hash,touched=self.clock(),consecutive_no_gain=0,searches=0,reads=0,list_pages=0,ranges={},text_chars=0,tokens={},cursors={},listed=set(),enumeration_complete=False,budget_exhausted=False,stale_sections=0)
            self.rows[rid]=row;return row
    def get(self,rid):
        with self.lock:
            self.purge()
            if not isinstance(rid,str) or rid not in self.rows:raise SourceError('RESEARCH_EXPIRED','研究会话已过期，请保留原问题重新开始。')
            row=self.rows[rid];row['touched']=self.clock();return row
    def admit(self,rid,spans):
        with self.lock:
            row=self.get(rid);updated=dict(row['ranges']);before=sum(b-a for rs in updated.values() for a,b in rs)
            for s in spans:
                key=(s['path'],s['sha256']);updated[key]=merge_ranges(updated.get(key,[])+[(s['start_offset'],s['end_offset'])])
            after=sum(b-a for rs in updated.values() for a,b in rs)
            if after>(96000 if row['strategy']=='timeline' else 24000):
                row['budget_exhausted']=True;raise SourceError('TURN_BUDGET','本轮材料预算已用完；只能根据已读材料作局部回答。')
            row.update(ranges=updated,text_chars=after);return dict(new_chars=after-before,text_chars=after)
    def coverage(self,rid):
        with self.lock:
            row=self.get(rid);sections=row.get('sections',[]);target=[s for s in sections if row['strategy']!='timeline' or s['date_status']=='dated']
            full=[];returned=[]
            for s in target:
                intervals=[r for (p,h),ranges in row['ranges'].items() if p==s['path'] for r in ranges]
                if any(a<s['end_offset'] and b>s['start_offset'] for a,b in intervals):returned.append(s)
                if any(a<=s['start_offset'] and b>=s['end_offset'] for a,b in merge_ranges(intervals)):full.append(s)
            complete=row['enumeration_complete'] and len(full)==len(target) and not row['budget_exhausted'] and not row['stale_sections']
            unknown=sum(s['date_status']=='undated' for s in sections);ambiguous=sum(s['date_status']=='ambiguous' for s in sections)
            full_ids={s['section_id'] for s in full};unread=[s['section_id'] for s in target if s['section_id'] not in full_ids]
            dates=sorted({s['heading_date'] for s in full if s['heading_date']})
            from research_coverage import period_coverage
            return dict(**period_coverage(row),matched_sections=len(target),returned_sections=len(returned),fully_returned_sections=len(full),undated_sections=unknown,ambiguous_sections=ambiguous,stale_sections=row['stale_sections'],enumeration_complete=row['enumeration_complete'],budget_exhausted=row['budget_exhausted'],unread_sections=unread[:50],unread_total=len(unread),covered_heading_dates=dates[:100],covered_heading_dates_total=len(dates),coverage_complete=complete if row['strategy']=='timeline' else None,temporal_scope_complete=complete and not unknown and not ambiguous if row['strategy']=='timeline' else None)
