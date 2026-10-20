"""Answer structure and literal provenance checks. Never certifies semantics."""


EVIDENCE_CHECKS = {
    'explanation': '只解释资料中的机制；有解释页不证明本人学过、理解、整理过或会用。',
    'practice': '需要本人已经完成具体行为的记录；教程、计划、建议、疑问不能证明已做过，也不能证明尚未做过。',
    'outcome': '需要具体任务的实测结果或使用反馈；搭建成功、预设验收标准都不等于已用好。',
    'first_use': '分开事件日期、来源标注和保存日期；日期含义不明就保留未知，最早找到不等于人生首次。',
    'timeline': '只概括实际返回的正文，保留相反记录与缺失日期；目录数量不等于已读数量。',
}

MISSING_EVIDENCE = {
    'explanation': '直接解释所问对象和机制的原文',
    'practice': '主体明确、已完成具体操作的记录',
    'outcome': '具体使用任务及实际效果数据或反馈',
    'first_use': '含义明确的实际使用日期及能支持首次判断的依据',
    'timeline': '日期含义明确、覆盖范围足够并保留相反情况的记录',
}


def answer_guidance(session, accepted, issues, coverage):
    """Bounded reminders derived from locked facets, never a semantic verdict."""
    reading = {key: coverage[key] for key in (
        'matched_sections', 'returned_sections', 'fully_returned_sections',
        'coverage_complete', 'temporal_scope_complete',
    )}
    matched, full = reading['matched_sections'], reading['fully_returned_sections']
    all_read = matched > 0 and full == matched
    reading['all_matched_sections_fully_returned'] = all_read
    reading['scope_statement'] = (
        f'本轮指定范围有{full}/{matched}个匹配小节完整返回，{matched-full}个小节未完整返回；'
        '这些是小节数，不是文件数。'
        + ('仅表示这些匹配小节的正文完整返回，不证明时间或经历记录完整。' if all_read
           else '不能声称全部读完或已穷尽该范围的证据。')
    )
    if session['strategy']=='timeline':
        reading['periods']=coverage.get('periods',[])
        reading['scope_statement']+=' '.join(f"{p['month']}完整返回{p['fully_returned_sections']}/{p['matched_sections']}小节。" for p in coverage.get('periods',[]))
        reading['scope_statement']+=f" 日期不明{coverage['undated_sections']}，日期歧义{coverage['ambiguous_sections']}；0匹配不代表没有经历。"
        if coverage.get('periods_truncated'):reading['scope_statement']+='月份展示已截断，不能将展示月份当作全部。'
    reviews = []
    for facet in session['facets']:
        fid, kind = facet['id'], facet['evidence_kind']
        proposal = accepted.get(fid)
        valid = proposal is not None and not any(i['facet_id'] == fid for i in issues)
        status = proposal['status'] if proposal else 'missing'
        fallback = None
        if valid and status == 'insufficient':
            fallback = '本轮已读材料还不足以确认这一项。需要' + MISSING_EVIDENCE[kind] + '。'
        reviews.append(dict(
            facet_id=fid, evidence_kind=kind, proposed_status=status,
            structure_and_quotes_valid=valid, requires_semantic_review=True,
            evidence_check=EVIDENCE_CHECKS[kind], fallback_if_insufficient=fallback,
        ))
    return dict(
        statuses_are_model_proposals=True,
        facets=reviews,
        reading=reading,
        scope_check='集合规定在哪查，证据类型规定能证明什么；技术集合也可包含实践记录。'
                    '目录匹配数不是已读数；只能说本轮指定范围已读材料不足，不能说全库没有。',
        final_check='不足时可采用对应条件措辞，不附带学过、整理过或处于规划阶段的额外判断。'
                    '这些提醒不验证主张是否由引文支持，也不拦截最终回答。',
    )


ROLES={'reference','plan','self_action','self_outcome','self_first_use','other_person','fiction','unknown'}
DATES={'explicit_event','heading_only','source_label','unknown'}
FIRST={'explicit_first','earliest_found','unknown'}


def check_evidence_roles(facet,verified_citations):
    kind=facet['evidence_kind'];issues=[];warnings=[]
    if kind not in {'practice','outcome','first_use'}:return dict(issues=issues,warnings=warnings)
    roles=[c.get('evidence_role','unknown') for c in verified_citations]
    if not roles or 'unknown' in roles:
        warnings.append('EVIDENCE_CLASSIFICATION_MISSING')
    allowed={'practice':{'self_action','self_outcome','self_first_use'},'outcome':{'self_outcome'},'first_use':{'self_first_use'}}[kind]
    if roles and 'unknown' not in roles and not any(r in allowed for r in roles):issues.append('EVIDENCE_ROLE_CONFLICT')
    if kind=='first_use' and any(r=='self_first_use' for r in roles) and not any(c.get('evidence_role')=='self_first_use' and c.get('date_basis')=='explicit_event' and c.get('first_basis')=='explicit_first' for c in verified_citations):issues.append('DATE_BASIS_INSUFFICIENT')
    return dict(issues=issues,warnings=warnings)


def assess(session,answers,verify,coverage):
    issues=[];sources=[];seen=set();accepted={};role_warnings=[];expected={f['id'] for f in session['facets']}
    def issue(code,fid,message):issues.append(dict(code=code,facet_id=fid,message=message))
    if not isinstance(answers,list) or len(answers)>6:
        answers=[];issue('INVALID_ANSWERS',None,'回答事项须为最多6项的列表。')
    for answer in answers:
        if not isinstance(answer,dict) or set(answer)!={'facet_id','status','claim','citations','limitations'}:
            issue('INVALID_ITEM',None,'回答字段不完整或包含未知字段。');continue
        fid=answer['facet_id'];status=answer['status']
        if not isinstance(fid,str) or fid not in expected or fid in seen:
            issue('FACET_MISMATCH',None,'事项未知或重复。');continue
        seen.add(fid)
        if not isinstance(status,str) or status not in {'supported','insufficient','conflicting'} or not isinstance(answer['claim'],str) or not 1<=len(answer['claim'].strip())<=2000 or not isinstance(answer['limitations'],str) or len(answer['limitations'])>1000 or not isinstance(answer['citations'],list) or len(answer['citations'])>8:
            issue('INVALID_ITEM',fid,'状态、结论、限制或引用格式不正确。');continue
        if status in {'supported','conflicting'} and not answer['citations']:issue('EVIDENCE_MISSING',fid,'有依据或冲突的主张需要引用。')
        if status=='insufficient' and not answer['limitations'].strip():issue('LIMITATION_MISSING',fid,'材料不足时须说明缺什么。')
        if answer['citations']:
            if any(not isinstance(c,dict) or not {'hit_token','quote'}<=set(c) or set(c)-{'hit_token','quote','evidence_role','date_basis','first_basis'} or not isinstance(c.get('hit_token'),str) or not isinstance(c.get('quote'),str) or not isinstance(c.get('evidence_role','unknown'),str) or not isinstance(c.get('date_basis','unknown'),str) or not isinstance(c.get('first_basis','unknown'),str) or c.get('evidence_role','unknown') not in ROLES or c.get('date_basis','unknown') not in DATES or c.get('first_basis','unknown') not in FIRST for c in answer['citations']):
                issue('INVALID_ITEM',fid,'引用仅接受hit_token与quote。');continue
            checked=verify(session['turn_id'],[{k:c[k] for k in ('hit_token','quote')} for c in answer['citations']])
            sources.extend(checked['verified'])
            for bad in checked['rejected']:issue(bad['code'],fid,bad['message'])
            bad_pairs={(answer['citations'][b['index']]['hit_token'],answer['citations'][b['index']]['quote']) for b in checked['rejected']}
            tokens={v['hit_token'] for v in checked['verified']}
            valid=[c for c in answer['citations'] if c['hit_token'] in tokens and (c['hit_token'],c['quote']) not in bad_pairs]
            if status=='supported':
                role=check_evidence_roles(next(f for f in session['facets'] if f['id']==fid),valid)
                for code in role['issues']:issue(code,fid,'引用的声明用途不足以支持本项判断。')
                role_warnings.extend(dict(facet_id=fid,code=code) for code in role['warnings'])
        accepted[fid]=answer
    for fid in sorted(expected-seen):issue('FACET_MISSING',fid,'此项尚未回答。')
    if session['strategy']=='timeline' and not coverage['coverage_complete']:issue('INCOMPLETE_COVERAGE',None,'尚未完整读取日期范围内的材料，只能提供局部总结。')
    if session['strategy']=='timeline' and not coverage['temporal_scope_complete']:issue('TEMPORAL_SCOPE_PARTIAL',None,'仍有日期不确定的材料，不得宣称已穷尽整个时间段。')
    # Provenance can be valid even when this sentence does not follow from it.
    return dict(structural_valid=not issues,semantic_verified=False,evidence_role_checks=dict(classifications_are_model_proposals=True,warnings=role_warnings),issues=issues,coverage=coverage,sources=list({(s['hit_token'],s['quote_start_line'],s['quote_end_line']):s for s in sources}.values()),answer_guidance=answer_guidance(session,accepted,issues,coverage),note='这里只检查事项完整性、来源字句和阅读覆盖；仍须核对解释、主体、实践、效果与首次日期是否由证据支持。')
