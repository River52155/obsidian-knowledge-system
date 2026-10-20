"""Monthly source-range coverage and bounded reading suggestions, not relevance."""

def period_coverage(session):
    if session['strategy']!='timeline':return dict(periods=[],periods_total=0,periods_truncated=False,recommended_section_ids=[])
    from research_sessions import merge_ranges
    start=session['date_from'];end=session['date_to'];first=int(start[:4])*12+int(start[5:7])-1;last=int(end[:4])*12+int(end[5:7])-1;total=last-first+1
    sections=[s for s in session.get('sections',[]) if s['date_status']=='dated'];periods=[];groups=[]
    for number in range(first,first+min(total,12)):
        month=f'{number//12:04}-{number%12+1:02}';ss=[s for s in sections if s['heading_date'].startswith(month)]
        matched=len(ss);returned=full=chars=size=0;candidates=[]
        for s in ss:
            length=s['end_offset']-s['start_offset'];size+=length
            ranges=merge_ranges([(max(a,s['start_offset']),min(b,s['end_offset'])) for (p,h),values in session['ranges'].items() if p==s['path'] for a,b in values if a<s['end_offset'] and b>s['start_offset']])
            read=sum(b-a for a,b in ranges);chars+=read;returned+=read>0;full+=read==length
            if read<length and s['section_id'] in session['listed']:candidates.append(s)
        periods.append(dict(month=month,matched_sections=matched,returned_sections=returned,fully_returned_sections=full,unread_total=matched-full,returned_chars=chars,total_chars=size))
        if candidates and size:
            candidates.sort(key=lambda s:(s['heading_date'],s['path'],s['start_offset'],s['section_id']))
            groups.append(((returned!=0,chars/size,month),candidates))
    groups.sort(key=lambda g:g[0]);recommended=[]
    while len(recommended)<8 and any(g[1] for g in groups):
        for _,candidates in groups:
            if candidates and len(recommended)<8:recommended.append(candidates.pop(0)['section_id'])
    return dict(periods=periods,periods_total=total,periods_truncated=total>12,recommended_section_ids=recommended)
