"""Chart statistics and drill-down contract: no external APIs or model spending."""
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from fastapi import FastAPI
from pydantic import ValidationError

from app.public_opinion import api
from app.public_opinion.preparation import prepare_comments
from app.public_opinion.schemas import ContextInsight, Evidence, ExternalSource, OpinionChart, OpinionReport, Section
from app.public_opinion.settings import OpinionSettings
from app.public_opinion.store import OpinionStore
from app.public_opinion.visualization import enrich_report
from app.public_opinion.workflow import validate_report
from test_public_opinion import post, rows, request_data


class VisualizationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.settings = OpinionSettings('sqlite:///' + str(Path(self.tmp.name) / 'charts.sqlite3'))
        self.store = OpinionStore(self.settings.database_url)
        self.payload = request_data()
        self.comments, self.stats = prepare_comments([post()], rows(9), self.settings)
        self.dataset = self.store.save_dataset(self.payload, [post()], self.comments, self.stats)
        self.saved = self.store.read_comments(self.dataset)

    def tearDown(self):
        self.store.engine.dispose()
        self.tmp.cleanup()

    def section(self, kind='public_emotions', **kwargs):
        return Section(type=kind, title='测试分类', status='completed', summary='真实归属',
            analyzed_sample=[Evidence(post_id=c.post_id, comment_id=c.comment_id) for c in self.comments],
            data=[{'label': '中立' if kind == 'public_emotions' else '主题 A', 'count': 999, 'percent': 99,
                   'evidence': [{'post_id': post().id, 'comment_id': f'c{i}'} for i in range(3)]}], **kwargs)

    def report(self, sections=None):
        return OpinionReport(task_id='test', dataset_id=self.dataset, selection=self.payload.selection,
            selected_event=self.payload.event, generated_at='2026-11-19T10:00:00Z', status='partial',
            insight='测试', stats=self.stats, posts=[post()], sources=[], limitations=[], usage={},
            sections=sections or [self.section()])

    def chart(self, report, kind):
        return next(c for c in report.charts if c.type == kind)

    def test_counts_ignore_model_numbers_and_unknowns_are_retained(self):
        result = enrich_report(self.report(), self.saved)
        chart = self.chart(result, 'emotion_distribution')
        self.assertEqual(chart.sample_size, 9)
        self.assertEqual({p.label: p.count for p in chart.points}, {'中立': 3, '无法判断': 6})
        self.assertEqual(sum(p.count for p in chart.points), chart.sample_size)
        self.assertEqual(sum(p.percent for p in chart.points), 100)

    def test_topic_overlap_preserved_and_counted_once_within_each_group(self):
        section = self.section('discussion_topics')
        section.data.append(section.data[0].model_copy(update={'label': '主题 B'}))
        result = validate_report(self.report([section]), self.store)
        chart = self.chart(result, 'discussion_topics')
        self.assertTrue(chart.overlapping)
        self.assertEqual([p.count for p in chart.points], [3, 3])
        self.assertIn('不相加', chart.description)
        self.assertEqual(chart.sample_size, 9)

    def test_emotion_overlap_is_rejected_by_report_validation(self):
        section = self.section()
        section.data.append(section.data[0].model_copy(update={'label': '喜悦'}))
        with self.assertRaises(ValueError):
            validate_report(self.report([section]), self.store)

    def test_stance_requires_explicit_issue_and_real_assignments(self):
        self.assertFalse(any(c.type == 'stance_comparison' for c in enrich_report(self.report([self.section('stance_analysis')]), self.saved).charts))
        result = enrich_report(self.report([self.section('stance_analysis', issue='是否需要公开说明')]), self.saved)
        chart = self.chart(result, 'stance_comparison')
        self.assertEqual(chart.issue, '是否需要公开说明')
        self.assertEqual(sum(p.count for p in chart.points), 9)

    def test_post_counts_use_stored_roots_not_stats_or_replies(self):
        report = self.report()
        report.stats.per_post = {post().id: 10000}
        reply = {**self.saved[0], 'comment_id': 'reply', 'parent_comment_id': 'c0'}
        chart = self.chart(enrich_report(report, self.saved + [reply]), 'post_contribution')
        self.assertEqual(chart.points[0].count, 9)
        self.assertEqual(chart.sample_size, 9)

    def dated(self, step=timedelta(hours=1)):
        start = datetime(2026, 11, 18, tzinfo=timezone.utc)
        return [{**c, 'created_at': (start + step * i).isoformat()} for i, c in enumerate(self.saved)]

    def test_time_chart_uses_real_bins_and_timezone(self):
        report = enrich_report(self.report(), self.dated())
        chart = self.chart(report, 'comment_timeline')
        self.assertEqual(chart.timezone, 'Asia/Shanghai')
        self.assertEqual(chart.granularity, '小时')
        self.assertEqual(len(chart.points), 9)
        self.assertEqual(sum(p.count for p in chart.points), 9)
        self.assertTrue(chart.points[0].start_at.endswith('+08:00'))
        self.assertIn('样本的评论发布时间', chart.title)

    def test_time_chart_hidden_for_missing_naive_or_single_bucket_dates(self):
        cases = [self.saved, [{**r, 'created_at': None} for r in self.saved],
                 [{**r, 'created_at': '2026-11-19T12:00:00'} for r in self.saved], self.dated(timedelta(seconds=1)),
                 [{**r, 'created_at': None if i < 2 else r['created_at']} for i, r in enumerate(self.dated())]]
        for comments in cases:
            result = enrich_report(self.report(), comments)
            self.assertFalse(any(c.type == 'comment_timeline' for c in result.charts))

    def test_time_granularity_and_no_filled_gaps(self):
        for delta, grain in [(timedelta(minutes=20), '15 分钟'), (timedelta(days=2), '天'), (timedelta(days=15), '周')]:
            chart = self.chart(enrich_report(self.report(), self.dated(delta)), 'comment_timeline')
            self.assertEqual(chart.granularity, grain)
            self.assertTrue(all(p.count > 0 for p in chart.points))
            self.assertEqual(sum(p.count for p in chart.points), 9)

    def test_partial_empty_failed_and_no_unfounded_radar(self):
        report = self.report([self.section().model_copy(update={'status': 'failed'})])
        result = enrich_report(report, [])
        self.assertFalse(result.charts)
        self.assertFalse(result.context_timeline)
        self.assertIn('radar', result.visualization_notes)
        result = enrich_report(self.report([self.section().model_copy(update={'status': 'insufficient_data'})]), self.saved)
        self.assertIn('部分批次', self.chart(result, 'emotion_distribution').description)

    def test_context_timeline_keeps_unknown_time_and_sources(self):
        report = self.report()
        report.sources = [ExternalSource(
            id='s1', title='背景', url='https://example.com/article', access='body', published_at='2026-11-17')]
        report.sections[0].contextual_insights = [ContextInsight(title='文化背景', dimension='cultural', explanation='有关联来源的谨慎解释',
            classification='supported_inference', source_ids=['s1'], evidence=[{'source_id': 's1', 'excerpt': '真实来源的原始摘录文字'}], uncertainty='不证明因果关系')]
        result = enrich_report(report, self.saved)
        insight = next(n for n in result.context_timeline if n.kind == 'insight')
        self.assertIsNone(insight.occurred_at)
        source = next(n for n in result.context_timeline if n.kind == 'source')
        self.assertEqual(source.occurred_at, '2026-11-17')

    def feature_sample(self):
        texts = ['短问？'] * 3 + ['长' * 55 + '？'] * 2 + [f'其他真实样本文字{i}' for i in range(15)]
        comments = [{**self.saved[0], 'comment_id': f'm{i}', 'content': text, 'like_count': 1 if i < 4 else 0}
                    for i, text in enumerate(texts)]
        report = self.report()
        report.sections[0].analyzed_sample = [Evidence(post_id=c['post_id'], comment_id=c['comment_id']) for c in comments]
        return report, comments

    def test_radar_uses_defined_binary_counts_and_common_denominator(self):
        report, comments = self.feature_sample()
        chart = self.chart(enrich_report(report, comments), 'discussion_radar')
        self.assertEqual(chart.unit, '%')
        self.assertEqual(chart.normalization, 'comment_share')
        self.assertEqual(chart.sample_size, 20)
        self.assertEqual({p.id: p.count for p in chart.points}, {'question_mark': 5, 'long_text': 2, 'repeated_text': 5, 'liked': 4})
        for point in chart.points:
            self.assertTrue(point.metric_definition)
            self.assertEqual(point.percent, round(point.count / 20 * 100, 1))
            self.assertEqual(len(point.evidence), point.count)

    def test_unknown_likes_omitted_instead_of_zero_and_replies_excluded(self):
        report, comments = self.feature_sample()
        comments[0]['like_count'] = None
        reply = {**comments[0], 'comment_id': 'reply', 'parent_comment_id': comments[1]['comment_id']}
        chart = self.chart(enrich_report(report, comments + [reply]), 'discussion_radar')
        self.assertNotIn('liked', [point.id for point in chart.points])
        self.assertEqual(chart.sample_size, 20)
        self.assertEqual(len(chart.points), 3)

    def test_unanalyzed_comments_never_change_feature_denominator(self):
        report, comments = self.feature_sample()
        extra = {**comments[0], 'comment_id': 'not-analyzed'}
        chart = self.chart(enrich_report(report, comments + [extra]), 'discussion_radar')
        self.assertEqual(chart.sample_size, 20)
        self.assertNotIn('not-analyzed', [ref.comment_id for p in chart.points for ref in p.evidence])

    def test_radar_hidden_when_all_metrics_zero_or_sample_small(self):
        report, comments = self.feature_sample()
        for i, row in enumerate(comments):
            row.update(content=f'普通文字{i}', like_count=0)
        self.assertFalse(any(c.type == 'discussion_radar' for c in enrich_report(report, comments).charts))
        self.assertFalse(any(c.type == 'discussion_radar' for c in enrich_report(report, comments[:10]).charts))

    def test_radar_schema_rejects_wrong_normalization_and_model_scores(self):
        report, comments = self.feature_sample()
        chart = self.chart(enrich_report(report, comments), 'discussion_radar')
        for change in [{'unit': '条'}, {'normalization': None}, {'points': chart.model_dump()['points'][:2]}]:
            with self.assertRaises(ValidationError):
                OpinionChart.model_validate(chart.model_dump() | change)
        body = chart.model_dump()
        body['points'][0]['percent'] = 99
        with self.assertRaises(ValidationError):
            OpinionChart.model_validate(body)

    def test_context_sorts_real_instants_across_timezones(self):
        report = self.report()
        report.sources = [ExternalSource(id='s1', title='背景', url='https://example.com', access='body', published_at='2026-11-18T18:00:00Z')]
        report.posts[0].published_at = datetime.fromisoformat('2026-11-19T01:00:00+08:00')
        report.sections[0].contextual_insights = [ContextInsight(title='背景', dimension='temporal', explanation='TEST',
            classification='supported_inference', source_ids=['s1'], evidence=[{'source_id': 's1', 'excerpt': '测试中已核验的来源文字'}], uncertainty='不能推断因果')]
        nodes = enrich_report(report, self.saved).context_timeline
        self.assertLess(next(i for i,n in enumerate(nodes) if n.kind == 'post'), next(i for i,n in enumerate(nodes) if n.kind == 'source'))
        report.sources[0].access = 'summary'
        self.assertFalse(enrich_report(report, self.saved).context_timeline)

    async def test_api_enriches_legacy_report_and_paginates_exact_assignments(self):
        task, _ = self.store.create_task(self.payload)
        report = self.report().model_copy(update={'task_id': task['id']})
        # Simulate a stored report predating visualization fields.
        body = report.model_dump(mode='json', exclude={'charts', 'context_timeline', 'visualization_notes'})
        self.store.save_report(task['id'], body)
        self.store.update_task(task['id'], status='partial')
        app = FastAPI();app.include_router(api.router);app.state.opinion_store = self.store
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            base = '/api/public-opinion/tasks/' + task['id']
            response = await client.get(base + '/report')
            self.assertEqual(response.status_code, 200)
            chart = next(c for c in response.json()['charts'] if c['type'] == 'emotion_distribution')
            point = next(p for p in chart['points'] if p['label'] == '中立')
            params = {'chart_id': chart['id'], 'point_id': point['id'], 'limit': 2}
            page = await client.get(base + '/chart-comments', params=params)
            self.assertEqual(page.status_code, 200)
            self.assertEqual(page.json()['total'], 3)
            self.assertEqual([c['comment_id'] for c in page.json()['comments']], ['c0', 'c1'])
            params['offset'] = 2
            page = await client.get(base + '/chart-comments', params=params)
            self.assertEqual([c['comment_id'] for c in page.json()['comments']], ['c2'])
            params['point_id'] = 'invented'
            self.assertEqual((await client.get(base + '/chart-comments', params=params)).status_code, 404)
            params['limit'] = 31
            self.assertEqual((await client.get(base + '/chart-comments', params=params)).status_code, 422)
        self.assertNotIn('charts', self.store.report(task['id']))
