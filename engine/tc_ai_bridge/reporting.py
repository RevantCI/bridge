from __future__ import annotations

import csv, html, json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .analytics import translation_words_book_analytics, exception_first_queue
from .language_qa_jobs import LANGUAGE_QA_BLOCKING, language_qa_open_counts, reported_language_qa

# The publication gate's advisory line for open medium Language QA findings;
# a setting (`language_qa_medium_advisory`) overrides it.
LANGUAGE_QA_MEDIUM_ADVISORY = 50
from .psalms_qa import analyze_psalm_chapter
from .knowledge_base import TranslationHelpsKnowledgeBase
from .git_service import GitService
from .team import TeamWorkflow


def publication_gate(project) -> dict[str, Any]:
    """The one definition of what blocks an export (layered-rules Phase 4.5):
    open AI critical issues, open Language QA findings of severity high and
    confidence high, and tN/tW checks marked needs-discussion. Cheap on
    purpose -- persisted state only, no project scan -- because export calls it
    on the dispatcher; the full book report builds on it and adds advisory
    inputs. Returns {blocking, items, counts}; each item names its source."""
    items: list[dict[str, Any]] = []
    for review in project.list_ai_review_results():
        ref = f"{review.get('chapter')}:{review.get('verse')}"
        for issue in review.get('qaIssues', []) if isinstance(review.get('qaIssues'), list) else []:
            if str(issue.get('severity', '')).lower() == 'critical':
                items.append({'source': 'aiReview', 'reference': ref,
                              'summary': str(issue.get('title') or issue.get('code') or 'Critical AI issue')})
    try:
        language_qa = reported_language_qa(project)
    except Exception:
        language_qa = []
    for finding in language_qa:
        if finding.get('status') in ('open', 'needs_discussion') and \
                (str(finding.get('severity')), str(finding.get('confidence'))) == LANGUAGE_QA_BLOCKING:
            items.append({'source': 'languageQa', 'reference': f"{finding.get('chapter')}:{finding.get('verse')}",
                          'summary': f"{finding.get('ruleId')}: {finding.get('originalText')}"})
    for decision in project.project_decisions():
        if decision.get('decision') == 'needs_discussion':
            items.append({'source': 'translationHelps',
                          'reference': f"{decision.get('chapter', '')}:{decision.get('verse', '')}",
                          'summary': f"{decision.get('tool') or 'check'} {decision.get('groupId') or decision.get('checkId') or ''} needs discussion".strip()})
    counts = Counter(item['source'] for item in items)
    return {'blocking': bool(items), 'items': items,
            'counts': {k: counts.get(k, 0) for k in ('aiReview', 'languageQa', 'translationHelps')}}


class ReportService:
    """Deterministic, print-friendly publication/QA reporting.

    Reports never call AI. They summarize already persisted translationCore + AI Bridge state so a
    reviewer/consultant can audit exactly what has and has not been completed.
    """
    def __init__(self,project,*,language_qa_medium_advisory:int=LANGUAGE_QA_MEDIUM_ADVISORY):
        self.project=project
        self.language_qa_medium_advisory=max(0,int(language_qa_medium_advisory))

    def _language_qa(self)->dict[str,Any]:
        """Language QA totals from the last check job's stage, current statuses
        (the same reader as the QA report and the exception queue)."""
        try:
            findings=reported_language_qa(self.project)
        except Exception as exc:
            return {'available':False,'error':str(exc),'total':0,'open':0,'blocking':0,'high':0,'medium':0,'low':0,'byCategory':{},'blockingFindings':[]}
        counts=language_qa_open_counts(findings); by_category:dict[str,dict[str,int]]={}
        for f in findings:
            bucket=by_category.setdefault(str(f.get('category') or ''),{'total':0,'open':0})
            bucket['total']+=1; bucket['open']+=1 if f.get('status') in ('open','needs_discussion') else 0
        blocking=[{'chapter':str(f.get('chapter','')),'verse':str(f.get('verse','')),'ruleId':str(f.get('ruleId','')),
                   'originalText':str(f.get('originalText','')),'message':str(f.get('message',''))}
                  for f in findings if f.get('status') in ('open','needs_discussion')
                  and (str(f.get('severity')),str(f.get('confidence')))==LANGUAGE_QA_BLOCKING]
        return {'available':True,'total':len(findings),**counts,'byCategory':by_category,'blockingFindings':blocking}

    def build_book_report(self)->dict[str,Any]:
        scan=self.project.project_scan(); terms=translation_words_book_analytics(self.project); queue=exception_first_queue(self.project)
        language_qa=self._language_qa()
        reviews=self.project.list_ai_review_results(); qa=[]; checks=[]
        for r in reviews:
            ref=f"{r.get('chapter')}:{r.get('verse')}"
            for q in r.get('qaIssues',[]) if isinstance(r.get('qaIssues'),list) else []: qa.append({'reference':ref,**q})
            for c in r.get('checkReviews',[]) if isinstance(r.get('checkReviews'),list) else []: checks.append({'reference':ref,**c})
        psalms=[]
        if self.project.book_id=='psa':
            for ch in self.project.chapters(): psalms.append(analyze_psalm_chapter(self.project,ch))
        decisions=self.project.project_decisions(); discussions=[d for d in decisions if d.get('decision')=='needs_discussion']
        try: provenance=TranslationHelpsKnowledgeBase(self.project).provenance_manifest()
        except Exception as e: provenance={'error':str(e)}
        git=GitService(self.project.path).status(); team=TeamWorkflow(self.project.companion_dir(),self.project.book_id).config()
        severity=Counter(str(q.get('severity','medium')).lower() for q in qa)
        return {
            'schemaVersion':2,'generatedTimestamp':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),
            'project':self.project.summary.display_name,'bookId':self.project.book_id,
            'scan':scan,'exceptionQueue':queue,'terminology':terms,'qaFindings':qa,'checkReviews':checks,
            'qaSeverityCounts':dict(severity),'needsDiscussion':discussions,'psalms':psalms,
            'knowledgeBaseProvenance':provenance,'git':{'available':git.available,'repository':git.repository,'branch':git.branch,'dirty':git.dirty},
            'team':team,'metrics':self._metrics(),
            'languageQa':language_qa,
            'publicationGate':{**self._publication_gate(scan,queue,qa,discussions,language_qa,self.language_qa_medium_advisory),
                               # What an export would be blocked by: the same function export consults.
                               'exportBlocking':publication_gate(self.project)},
            'coverage':{'verses':self._verse_coverage(),'resources':self._resource_coverage()},
        }

    def _verse_coverage(self) -> dict[str, Any]:
        """PASS / ISSUE / REVIEW_REQUIRED / NOT_CHECKED per verse, derived
        entirely from the existing progress rollup (project.load_progress_
        rollup(), written by BridgeEngine._on_check_job_complete) -- no new
        persistence. A verse absent from the rollup was never run through
        checks.start and is NOT_CHECKED, regardless of
        whether it would look fine if it were. Among checked verses: an
        OPEN finding is an unresolved ISSUE; a NEEDS_DISCUSSION finding
        (with no OPEN one) is REVIEW_REQUIRED; everything else a checked
        verse can land in -- no findings, or every finding accepted/
        rejected/ignored/fixed -- is PASS, matching the existing 'reviewed'
        notion _recompute_progress_totals already uses (not OPEN = closed
        out one way or another)."""
        rollup = self.project.load_progress_rollup()
        chapters_rollup = rollup.get('chapters', {}) if isinstance(rollup.get('chapters'), dict) else {}
        counts = {'PASS': 0, 'ISSUE': 0, 'REVIEW_REQUIRED': 0, 'NOT_CHECKED': 0}
        per_chapter: dict[str, dict[str, str]] = {}
        for chapter in self.project.chapters():
            chapter_rollup = chapters_rollup.get(chapter, {})
            verse_map = chapter_rollup.get('verses', {}) if isinstance(chapter_rollup, dict) else {}
            chapter_states: dict[str, str] = {}
            for verse in self.project.verses(chapter):
                entry = verse_map.get(str(verse)) if isinstance(verse_map, dict) else None
                if entry is None:
                    state = 'NOT_CHECKED'
                else:
                    statuses = set((entry.get('findings') or {}).values())
                    if 'open' in statuses:
                        state = 'ISSUE'
                    elif 'needs_discussion' in statuses:
                        state = 'REVIEW_REQUIRED'
                    else:
                        state = 'PASS'
                counts[state] += 1
                chapter_states[str(verse)] = state
            per_chapter[chapter] = chapter_states
        total = sum(counts.values())
        checked_percent = round(100 * (total - counts['NOT_CHECKED']) / total, 1) if total else 0.0
        return {'counts': counts, 'totalVerses': total, 'checkedPercent': checked_percent, 'chapters': per_chapter}

    def _resource_coverage(self) -> dict[str, Any]:
        """Bundled checking-helps availability per tool, straight from the
        capabilities .bridge/import.json already records at materialization
        time (project_import.apply_resource_materialization). Absent
        entirely for an existing translationCore/translationStudio import
        Bridge never materialized itself -- an honest 'not tracked', not an
        error, same convention as BridgeEngine._pinned_resource_versions."""
        import_path = Path(self.project.path) / '.bridge' / 'import.json'
        if not import_path.is_file():
            return {}
        try:
            data = json.loads(import_path.read_text(encoding='utf-8-sig'))
        except (OSError, ValueError):
            return {}
        capabilities = data.get('capabilities')
        return dict(capabilities) if isinstance(capabilities, dict) else {}

    @staticmethod
    def build_collection_report(book_reports: list[dict[str, Any]]) -> dict[str, Any]:
        """Aggregate already-built build_book_report() outputs -- one per
        sibling book in a multi-book collection -- into one project-level
        summary. Takes finished report dicts rather than TranslationCoreProject
        instances so ReportService itself stays single-project like every
        other class in tc_ai_bridge; the caller (BridgeEngine) already knows
        how to enumerate collection siblings (see BridgeEngine's
        _materialized_collection_books, the same resolution reused here)."""
        verse_counts: Counter = Counter()
        severity_counts: Counter = Counter()
        books: list[dict[str, Any]] = []
        all_ready = True
        critical = high = stale = pending_tx = discussions = 0
        lqa_blocking = lqa_medium = 0
        advisories: list[str] = []
        language_qa: Counter = Counter()
        for report in book_reports:
            lqa = report.get('languageQa') or {}
            for key in ('total', 'open', 'blocking', 'high', 'medium', 'low'):
                language_qa[key] += int(lqa.get(key, 0) or 0)
            coverage = (report.get('coverage') or {}).get('verses', {}) or {}
            for state, n in (coverage.get('counts') or {}).items():
                verse_counts[state] += int(n or 0)
            for sev, n in (report.get('qaSeverityCounts') or {}).items():
                severity_counts[sev] += int(n or 0)
            gate = report.get('publicationGate') or {}
            all_ready = all_ready and bool(gate.get('readyForHumanPublicationSignoff'))
            critical += int(gate.get('criticalFindings', 0) or 0)
            high += int(gate.get('highFindings', 0) or 0)
            stale += int(gate.get('staleAIReviews', 0) or 0)
            pending_tx += int(gate.get('pendingTransactions', 0) or 0)
            discussions += int(gate.get('openDiscussions', 0) or 0)
            lqa_blocking += int(gate.get('languageQaBlocking', 0) or 0)
            lqa_medium += int(gate.get('languageQaOpenMedium', 0) or 0)
            advisories.extend(f"{report.get('bookId')}: {line}" for line in gate.get('advisories') or [])
            books.append({
                'bookId': report.get('bookId'), 'project': report.get('project'),
                'coverage': coverage, 'qaSeverityCounts': report.get('qaSeverityCounts', {}),
                'publicationGate': gate,
                'languageQa': {k: lqa.get(k, 0) for k in ('total', 'open', 'blocking', 'high', 'medium', 'low')},
            })
        total_verses = sum(verse_counts.values())
        checked_percent = (
            round(100 * (total_verses - verse_counts.get('NOT_CHECKED', 0)) / total_verses, 1)
            if total_verses else 0.0
        )
        return {
            'schemaVersion': 1,
            'generatedTimestamp': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            'bookCount': len(book_reports),
            'verseCoverage': {
                'counts': dict(verse_counts), 'totalVerses': total_verses, 'checkedPercent': checked_percent,
            },
            'qaSeverityCounts': dict(severity_counts),
            'publicationGate': {
                'readyForHumanPublicationSignoff': all_ready and bool(book_reports),
                'criticalFindings': critical, 'highFindings': high,
                'staleAIReviews': stale, 'pendingTransactions': pending_tx, 'openDiscussions': discussions,
                'languageQaBlocking': lqa_blocking, 'languageQaOpenMedium': lqa_medium,
                'advisories': advisories,
                'note': 'This gate is advisory. Final publication approval remains human/organizational.',
            },
            'languageQa': dict(language_qa),
            'books': books,
        }

    @staticmethod
    def _publication_gate(scan,queue,qa,discussions,language_qa=None,medium_advisory=LANGUAGE_QA_MEDIUM_ADVISORY):
        """Advisory. Language QA (layered-rules Phase 4.2) adds one blocking
        input -- open findings with severity high AND confidence high -- and
        one advisory line when open medium findings exceed `medium_advisory`
        (default 50). The advisory line never blocks."""
        critical=sum(1 for q in qa if str(q.get('severity','')).lower()=='critical')
        high=sum(1 for q in qa if str(q.get('severity','')).lower()=='high')
        stale=int(scan.get('aiReview',{}).get('stale',0) or 0)
        pending_tx=int(scan.get('pendingTransactions',0) or 0)
        language_qa=language_qa or {}
        lqa_blocking=int(language_qa.get('blocking',0) or 0)
        lqa_medium=int(language_qa.get('medium',0) or 0)
        advisories=[]
        if lqa_medium>medium_advisory:
            advisories.append(f'{lqa_medium} open medium Language QA findings (more than {medium_advisory}).')
        ready=not (critical or high or stale or pending_tx or discussions or lqa_blocking)
        return {'readyForHumanPublicationSignoff':ready,'criticalFindings':critical,'highFindings':high,'staleAIReviews':stale,'pendingTransactions':pending_tx,'openDiscussions':len(discussions),
                'languageQaBlocking':lqa_blocking,'languageQaOpenMedium':lqa_medium,'languageQaMediumAdvisory':medium_advisory,'advisories':advisories,
                'note':'This gate is advisory. Final publication approval remains human/organizational.'}

    def _metrics(self):
        try:
            from .metrics import MetricsStore
            return MetricsStore(self.project).summary()
        except Exception:return {}

    def export(self,out_dir:Path)->dict[str,str]:
        out=Path(out_dir); out.mkdir(parents=True,exist_ok=True); data=self.build_book_report(); base=f'{self.project.book_id}_translation_qa_report'
        paths={}
        j=out/f'{base}.json'; j.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n','utf-8'); paths['json']=str(j)
        c=out/f'{base}_issues.csv'
        self._write_csv(c,['reference','severity','source','code','title','detail'],data['qaFindings']); paths['csv']=str(c)
        try: lqa_rows=reported_language_qa(self.project)
        except Exception: lqa_rows=[]
        for r in lqa_rows: r['suggestionsJoined']=' | '.join(str(s.get('text','')) for s in r.get('suggestions') or [] if isinstance(s,dict))
        lq=out/f'{base}_language_qa.csv'
        self._write_csv(lq,['chapter','verse','ruleId','category','layer','severity','confidence','status','originalText','suggestionsJoined','packVersion','message'],lqa_rows); paths['languageQaCsv']=str(lq)
        e=out/f'{base}_exceptions.csv'; self._write_csv(e,['chapter','verse','critical','high','medium','cache','wordAlignment','invalidChecks','discussions','finalState','summary'],data['exceptionQueue']); paths['exceptionsCsv']=str(e)
        t=out/f'{base}_terminology.csv'; term_rows=[]
        for concept in data['terminology'].get('concepts',[]):
            for r in concept.get('renderings',[]) or [{'text':'','count':0,'status':''}]:
                term_rows.append({'conceptId':concept.get('conceptId'),'total':concept.get('total'),'checked':concept.get('checked'),'distinctRenderings':concept.get('distinctRenderings'),'unexplainedOccurrences':concept.get('unexplainedOccurrences'),'rendering':r.get('text'),'count':r.get('count'),'status':r.get('status')})
        self._write_csv(t,['conceptId','total','checked','distinctRenderings','unexplainedOccurrences','rendering','count','status'],term_rows); paths['terminologyCsv']=str(t)
        a=out/f'{base}_human_decisions.json'; a.write_text(json.dumps(data.get('needsDiscussion',[]),ensure_ascii=False,indent=2)+'\n','utf-8'); paths['discussionsJson']=str(a)
        h=out/f'{base}.html'; h.write_text(self._html(data),'utf-8'); paths['html']=str(h)
        return paths

    @staticmethod
    def _write_csv(path,fields,rows):
        with Path(path).open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader()
            for row in rows:w.writerow({k:row.get(k,'') for k in fields})

    def _html(self,d):
        gate=d['publicationGate']; scan=d['scan']
        rows=''.join(f"<tr><td>{html.escape(str(x.get('chapter'))+':'+str(x.get('verse')))}</td><td>{x.get('critical',0)}</td><td>{x.get('high',0)}</td><td>{html.escape(str(x.get('cache','')))}</td><td>{html.escape(str(x.get('summary','')))}</td></tr>" for x in d['exceptionQueue'][:1000])
        term=''.join(f"<tr><td>{html.escape(str(x.get('conceptId','')))}</td><td>{x.get('total',0)}</td><td>{x.get('distinctRenderings',0)}</td><td>{x.get('unexplainedOccurrences',0)}</td></tr>" for x in d['terminology'].get('concepts',[])[:1000])
        gate_class='ok' if gate['readyForHumanPublicationSignoff'] else 'bad'
        lqa=d.get('languageQa') or {}
        lqa_categories=''.join(f"<tr><td>{html.escape(k or '—')}</td><td>{v.get('total',0)}</td><td>{v.get('open',0)}</td></tr>" for k,v in sorted((lqa.get('byCategory') or {}).items()))
        lqa_blocking=''.join(f"<tr><td>{html.escape(x['chapter']+':'+x['verse'])}</td><td>{html.escape(x['ruleId'])}</td><td>{html.escape(x['originalText'])}</td><td>{html.escape(x['message'])}</td></tr>" for x in (lqa.get('blockingFindings') or [])[:500])
        advisories=''.join(f"<li>{html.escape(a)}</li>" for a in gate.get('advisories') or [])
        lqa_html=(f"<h2>Language QA</h2><p>{lqa.get('open',0)} open of {lqa.get('total',0)} findings from the last checked run; "
                  f"{lqa.get('blocking',0)} blocking (severity high, confidence high).</p>"
                  f"<table><thead><tr><th>Category</th><th>Findings</th><th>Open</th></tr></thead><tbody>{lqa_categories}</tbody></table>"
                  + (f"<h3>Blocking</h3><table><thead><tr><th>Reference</th><th>Rule</th><th>Text</th><th>Message</th></tr></thead><tbody>{lqa_blocking}</tbody></table>" if lqa_blocking else "")
                  + (f"<h3>Advisories</h3><ul>{advisories}</ul>" if advisories else "")) if lqa.get('available',True) else ''
        return f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(d['project'])} QA Report</title><style>body{{font:15px system-ui;margin:32px;max-width:1200px;color:#1f2937}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #ddd;padding:7px;vertical-align:top}}th{{background:#f4f4f4}}.bad{{color:#b00020;font-weight:700}}.ok{{color:#08783e;font-weight:700}}pre{{white-space:pre-wrap;background:#f8fafc;padding:12px}}@media print{{body{{margin:12mm}}button{{display:none}}}}</style></head><body><h1>{html.escape(d['project'])} — Translation QA</h1><p>Generated {html.escape(d['generatedTimestamp'])}</p><h2>Publication readiness</h2><p class="{gate_class}">{'Ready for human publication sign-off' if gate['readyForHumanPublicationSignoff'] else 'Not ready: unresolved production gates remain'}</p><pre>{html.escape(json.dumps(gate,ensure_ascii=False,indent=2))}</pre><h2>Project state</h2><pre>{html.escape(json.dumps(scan,ensure_ascii=False,indent=2))}</pre><h2>Exception-first queue</h2><table><thead><tr><th>Reference</th><th>Critical</th><th>High</th><th>Cache</th><th>Summary</th></tr></thead><tbody>{rows}</tbody></table>{lqa_html}<h2>Terminology / Translation Words</h2><table><thead><tr><th>Concept</th><th>Occurrences</th><th>Distinct renderings</th><th>Unexplained</th></tr></thead><tbody>{term}</tbody></table><h2>Quality metrics</h2><pre>{html.escape(json.dumps(d.get('metrics',{}),ensure_ascii=False,indent=2))}</pre><h2>Knowledge Base provenance</h2><pre>{html.escape(json.dumps(d.get('knowledgeBaseProvenance',{}),ensure_ascii=False,indent=2))}</pre><p><strong>Human authority:</strong> This report assists review; it does not itself approve Scripture, terminology, or publication.</p></body></html>'''
