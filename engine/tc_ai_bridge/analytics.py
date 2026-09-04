from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any


def _selection_text(entry:dict)->str:
    sel=entry.get('selections')
    if not isinstance(sel,list): return ''
    return ' '.join(str(x.get('text','')).strip() for x in sel if isinstance(x,dict) and str(x.get('text','')).strip()).strip()


def translation_words_book_analytics(project) -> dict[str, Any]:
    groups: dict[str,dict[str,Any]]={}
    for e in project._load_index_tool('translationWords'):
        c=e.get('contextId',{}) if isinstance(e,dict) else {}; gid=str(c.get('groupId',''))
        if not gid: continue
        g=groups.setdefault(gid,{'conceptId':gid,'total':0,'checked':0,'invalidated':0,'nothingToSelect':0,'renderings':Counter(),'references':[]})
        g['total']+=1
        if e.get('invalidated'): g['invalidated']+=1
        if e.get('nothingToSelect'): g['nothingToSelect']+=1
        text=_selection_text(e)
        if isinstance(e.get('selections'),list) or e.get('nothingToSelect'):
            g['checked']+=1
        if text: g['renderings'][text]+=1
        r=c.get('reference',{}) if isinstance(c,dict) else {}
        g['references'].append({'reference':f"{r.get('chapter')}:{r.get('verse')}",'sourceQuote':c.get('quoteString',''),'rendering':text,'invalidated':bool(e.get('invalidated',False))})
    rules={str(r.get('conceptId')):r for r in project.terminology_rules()}
    out=[]
    for gid,g in groups.items():
        counts=g.pop('renderings'); rule=rules.get(gid,{})
        approved=set(rule.get('approvedRenderings',[]) or []); allowed=set(rule.get('allowedAlternatives',[]) or []); rejected=set(rule.get('rejectedRenderings',[]) or [])
        rendering_rows=[]; unexplained=0
        for text,count in counts.most_common():
            status='approved' if text in approved else 'allowed' if text in allowed else 'rejected' if text in rejected else 'unclassified'
            if status in ('rejected','unclassified'): unexplained += count
            rendering_rows.append({'text':text,'count':count,'status':status})
        out.append({**g,'renderings':rendering_rows,'distinctRenderings':len(counts),'unexplainedOccurrences':unexplained,'hasHumanRule':bool(rule),'humanRule':rule})
    out.sort(key=lambda x:(-x['unexplainedOccurrences'],-x['distinctRenderings'],x['conceptId']))
    return {'bookId':project.book_id,'conceptCount':len(out),'concepts':out}


def _local_findings_by_verse(project) -> dict[tuple[str, str], list[dict[str, Any]]]:
    """Local (Wildebeest/USFM/Names) QaFinding dicts already persisted in
    checkCache.json (see BridgeEngine.build_project_report's cache-warming
    and each engine's own _*_findings_for_book), grouped by (chapter, verse)
    and filtered to still-open status via the same progress rollup
    _verse_coverage() reads for the coverage bar — so the exception queue
    and the coverage bar agree on what still needs attention instead of
    reading two different pictures of the same data (issue #24)."""
    cache = project.load_check_cache()
    rollup = project.load_progress_rollup()
    chapters_rollup = rollup.get('chapters', {}) if isinstance(rollup.get('chapters'), dict) else {}
    by_verse: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for section in ('wildebeest', 'usfm', 'names'):
        for f in (cache.get(section) or {}).get('findings', []) or []:
            chapter = str(f.get('chapter', ''))
            verse = str(f.get('verse', ''))
            chapter_entry = chapters_rollup.get(chapter)
            verse_map = chapter_entry.get('verses', {}) if isinstance(chapter_entry, dict) else {}
            verse_entry = verse_map.get(verse) if isinstance(verse_map, dict) else None
            statuses = verse_entry.get('findings', {}) if isinstance(verse_entry, dict) else {}
            status = statuses.get(str(f.get('id', '')), 'open') if isinstance(statuses, dict) else 'open'
            if status != 'open':
                continue
            by_verse.setdefault((chapter, verse), []).append(f)
    return by_verse


def _translation_helps_findings(
    project, chapter: str, verse: str, checks: list[dict[str, Any]],
) -> tuple[int, list[dict[str, Any]]]:
    """tN/tW problems for one verse, plus the invalidated/stale count the
    exception queue already reported.

    Built from the `checks` list the caller has already loaded, so surfacing
    these on the project report costs no extra disk I/O per verse — which
    matters because exception_first_queue walks the whole book and
    BridgeEngine.build_project_report runs on the single-threaded stdio
    dispatcher (see its docstring for the ~800-verse incident that made
    eager whole-book work there unacceptable).

    The codes/severities deliberately mirror
    local_checks.translationcore_check_issues() so the dashboard and the
    verse review panel describe the same check the same way. The one
    difference is staleness: that function asks for every check, this one
    only where a selection exists, because check_staleness() reads per-check
    state files and a whole-book pass cannot afford one per unselected check.
    A check with no selection is reported as pending, which is what it is.
    """
    invalid_count = 0
    findings: list[dict[str, Any]] = []
    for entry in checks:
        ctx = entry.get('contextId', {}) if isinstance(entry.get('contextId'), dict) else {}
        tool = str(ctx.get('tool', ''))
        if tool not in ('translationNotes', 'translationWords'):
            continue
        group = str(ctx.get('groupId', ''))
        check_id = str(ctx.get('checkId', ''))
        category = 'translation_note' if tool == 'translationNotes' else 'translation_word'
        selection = entry.get('selections', False)
        invalidated = bool(entry.get('invalidated', False))
        stale = (
            selection not in (False, None)
            and project.check_staleness(chapter, verse, check_id, tool, group) == 'stale'
        )
        if invalidated or stale:
            invalid_count += 1
            findings.append({
                'tool': tool, 'category': category, 'severity': 'high',
                'checkType': 'TC_INVALIDATED' if invalidated else 'TC_STALE_AFTER_EDIT',
                'groupId': group,
                'explanation': f'{group} / {check_id} is '
                               f'{"invalidated" if invalidated else "stale after a later Scripture edit"}.',
            })
        elif selection is False and not bool(entry.get('nothingToSelect', False)):
            findings.append({
                'tool': tool, 'category': category,
                'severity': 'medium' if tool == 'translationNotes' else 'high',
                'checkType': 'TC_PENDING', 'groupId': group,
                'explanation': str(ctx.get('occurrenceNote', '') or '')
                               or f'{group} / {check_id} has no selection yet.',
            })
    return invalid_count, findings


def exception_first_queue(project) -> list[dict[str,Any]]:
    rows=[]
    ai={(str(x.get('chapter')),str(x.get('verse'))):x for x in project.list_ai_review_results()}
    local_by_verse=_local_findings_by_verse(project)
    for ch in project.chapters():
        for vs in project.verses(ch):
            if vs=='front': continue
            saved=ai.get((str(ch),str(vs)),{}); cache=project.ai_review_cache_status(ch,vs)
            critical=high=medium=0
            for q in saved.get('qaIssues',[]) if isinstance(saved.get('qaIssues'),list) else []:
                sev=str(q.get('severity','medium')).lower()
                if sev=='critical':critical+=1
                elif sev=='high':high+=1
                elif sev=='medium':medium+=1
            for r in saved.get('checkReviews',[]) if isinstance(saved.get('checkReviews'),list) else []:
                if str(r.get('verdict','')).lower() in ('problem','review') or float(r.get('confidence',0) or 0)<.7:
                    sev=str(r.get('severity','medium')).lower()
                    if sev=='critical':critical+=1
                    elif sev=='high':high+=1
                    elif sev=='medium':medium+=1
            local_findings=local_by_verse.get((str(ch),str(vs)),[])
            for f in local_findings:
                sev=str(f.get('severity','medium')).lower()
                if sev=='critical':critical+=1
                elif sev=='high':high+=1
                elif sev=='medium':medium+=1
            wa=project.word_alignment_state(ch,vs)
            checks=project.checks_for_verse(ch,vs)
            invalid,helps_findings=_translation_helps_findings(project,str(ch),str(vs),checks)
            discussion=sum(1 for d in project.decisions_for_verse(ch,vs) if d.get('decision')=='needs_discussion')
            review=project.load_review_state(ch,vs) or {}; final_state=str(review.get('status',''))
            if critical or high or cache in ('stale','missing') or invalid or wa=='invalid' or discussion or final_state.startswith('stale') or local_findings:
                summary=str(saved.get('summary','')) or '; '.join(
                    str(f.get('explanation','')) for f in local_findings[:3] if f.get('explanation')
                )
                rows.append({
                    'chapter':str(ch),'verse':str(vs),'critical':critical,'high':high,'medium':medium,
                    'cache':cache,'wordAlignment':wa,'invalidChecks':invalid,'discussions':discussion,
                    'finalState':final_state,'summary':summary,
                    'localFindings':[
                        {
                            'engine':str(f.get('engine','')),
                            'severity':str(f.get('severity','medium')).lower(),
                            'checkType':str(f.get('check_type','')),
                            'explanation':str(f.get('explanation','')),
                        }
                        for f in local_findings
                    ],
                    # tN/tW problems, kept in their own list rather than merged
                    # into localFindings: that one means Greek Room
                    # (Wildebeest/USFM/Names) and the dashboard colour-codes the
                    # two differently.
                    'helpsFindings':helps_findings,
                })
    rank={'stale':0,'missing':1,'current':2}
    rows.sort(key=lambda r:(-r['critical'],-r['high'],-r['invalidChecks'],-r['discussions'],rank.get(r['cache'],9),int(r['chapter']) if r['chapter'].isdigit() else 999,int(r['verse']) if r['verse'].isdigit() else 999))
    return rows
