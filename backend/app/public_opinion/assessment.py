"""PublicOpinionAgent's bounded final synthesis, after research/evidence validation.

Never called on GET report. Does not search, collect comments or increase task budgets.
"""
import json
import hashlib
import re
from .analysis import non_statistical
from .llm import structured
from .prompts import ASSESSMENT
from .schemas import OverallAssessment, ReportSynthesis


def reference(ref):
    return ref.post_id, ref.comment_id


def verified_numbers(text, report):
    counts = {report.stats.prepared_count, report.stats.post_count}
    percentages = set()
    for chart in report.charts:
        counts.add(chart.sample_size)
        for point in chart.points:
            counts.add(point.count)
            if point.percent is not None:percentages.add(point.percent)
    matches = list(re.finditer(r'(\d+(?:\.\d+)?)\s*(%|％|条|人|成|倍|位)', text))
    for match in matches:
        number, unit = float(match.group(1)), match.group(2)
        if unit == '条' and number in counts:continue
        if unit in {'%', '％'} and number in percentages:continue
        return False
    # Unparsed Chinese statistical claims cannot be grounded by number matching.
    remainder = re.sub(r'(\d+(?:\.\d+)?)\s*(%|％|条|人|成|倍|位)', '', text)
    return bool(non_statistical(remainder, '')) or not remainder


def synthesis_input(report, comments):
    limitations = list(dict.fromkeys([*report.limitations[:2], *report.limitations[-6:]]))
    packet = {'event_title': report.selected_event.title[:160], 'platform': report.selection.platform_name,
              'limitations': [text[:160] for text in limitations],
              'posts': [{'title': post.title[:100], 'text_excerpt': post.summary[:240], 'read_method': post.read_method} for post in report.posts[:1]],
              'sections': [], 'charts': [],
              'contextual_insights': [], 'evidence_comments': [], 'truncated': False}
    def append(key, item, ceiling):
        packet[key].append(item)
        if len(json.dumps(packet, ensure_ascii=False).encode()) > ceiling:
            packet[key].pop();packet['truncated'] = True;return False
        return True
    sections = [s for s in report.sections if s.status in {'completed', 'insufficient_data'} and s.type != 'representative_comments']
    sources = set()
    for section in sections:
        for insight in section.contextual_insights:
            item = {'title': insight.title, 'explanation': insight.explanation[:240], 'uncertainty': insight.uncertainty[:160],
                    'source_ids': insight.source_ids, 'evidence': [q.model_dump() for q in insight.evidence[:2]]}
            if append('contextual_insights', item, 2500):sources.update(insight.source_ids)
    for section in sections:
        append('sections', {'type': section.type, 'title': section.title, 'status': section.status, 'issue': section.issue,
            'groups': [{'label': g.label[:40], 'explanation': g.explanation[:70],
                        'evidence': [r.model_dump() for r in g.evidence[:1]]} for g in section.data[:2]],
            'reason': (section.reason or '')[:120]}, 8500)
    for chart in report.charts:
        append('charts', {'chart_id': chart.id, 'type': chart.type, 'title': chart.title, 'sample_size': chart.sample_size,
            'scope': chart.description[:120], 'points': [{'label': p.label[:40], 'count': p.count, 'percent': p.percent,
            'evidence': [r.model_dump() for r in p.evidence[:1]]} for p in chart.points[:3]]}, 10500)
    eligible = {reference(r) for s in sections for g in s.data for r in g.evidence}
    # Prefer representative evidence across groups, not an unbounded comment dump.
    selected = list(dict.fromkeys(reference(r) for s in sections for g in s.data[:3] for r in g.evidence[:1]))
    roots = {(c['post_id'], c['comment_id']): c for c in comments if not c.get('parent_comment_id')}
    visible = set()
    for key in selected[:8]:
        if key not in roots or key not in eligible:continue
        row = roots[key]
        if append('evidence_comments', {'post_id': key[0], 'comment_id': key[1], 'content': row['content'][:160]}, 12000):
            visible.add(key)
    return packet, visible, sources


def validate_synthesis(output, report, visible, source_ids):
    available = {s.type for s in report.sections if s.status in {'completed', 'insufficient_data'}}
    assessment = output.overall_assessment
    if (not assessment.summary.strip() or not assessment.section_types or not set(assessment.section_types) <= available
            or not assessment.evidence or not {reference(r) for r in assessment.evidence} <= visible
            or not set(assessment.source_ids) <= source_ids):
        raise ValueError('总体评价必须关联真实已完成分析与实际证据')
    prose = [assessment.summary, assessment.core_judgment or '', *assessment.key_findings]
    if any(text and not verified_numbers(text, report) for text in prose):
        raise ValueError('总体评价包含未核验的统计叙述')
    charts = {c.id: c for c in report.charts}
    seen = set()
    interpretations = []
    for interpretation in output.chart_interpretations:
        chart = charts.get(interpretation.chart_id)
        if not chart or interpretation.chart_id in seen:continue
        allowed = {reference(ref) for point in chart.points for ref in point.evidence}
        if chart.type in {'discussion_topics', 'emotion_distribution', 'stance_comparison'} and not interpretation.evidence:
            continue
        if not {reference(r) for r in interpretation.evidence} <= allowed or not set(interpretation.source_ids) <= source_ids:
            continue
        if not verified_numbers(interpretation.analysis, report):continue
        seen.add(interpretation.chart_id);interpretations.append(interpretation)
    # One invalid chart paragraph must not erase a separately validated overall assessment.
    output.chart_interpretations = interpretations
    return output


async def synthesize_assessment(model, report, comments, store=None):
    packet, visible, source_ids = synthesis_input(report, comments)
    if not visible or not packet['sections']:
        return ReportSynthesis(overall_assessment=OverallAssessment(status='unavailable', reason='尚无可核验的分析及评论证据，未生成总体评价。'))
    try:
        key = hashlib.sha256(json.dumps(['assessment-v1', ASSESSMENT, model.model_name,
            getattr(model, 'openai_api_base', ''), packet], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        cached = store.cache_get(key) if store else None
        output = ReportSynthesis.model_validate(cached) if cached else await structured(model, ASSESSMENT, packet, ReportSynthesis)
        output = validate_synthesis(output, report, visible, source_ids)
        output.overall_assessment.status = 'partial' if report.status == 'partial' else 'completed'
        if store and not cached:store.cache_put(key, output.model_dump())
        return output
    except Exception:
        # Preserve trustworthy modules; never replace failed synthesis with invented prose.
        return ReportSynthesis(overall_assessment=OverallAssessment(status='unavailable',
            reason='综合评价因模型预算、请求或证据校验未完成；已保留实际完成的分析与证据。'))
