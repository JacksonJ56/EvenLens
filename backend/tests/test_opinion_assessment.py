"""No paid services. Test final synthesis grounding, migration and lazy evidence API."""
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI
from app.public_opinion.api import router
from app.public_opinion.assessment import synthesis_input, synthesize_assessment, validate_synthesis
from app.public_opinion.llm import Budget, BudgetExceeded
from app.public_opinion.preparation import prepare_comments
from app.public_opinion.schemas import Evidence, OverallAssessment, OpinionReport, ReportSynthesis, Section
from app.public_opinion.settings import OpinionSettings
from app.public_opinion.store import OpinionStore
from app.public_opinion.visualization import enrich_report
from test_public_opinion import post, request_data, rows, ScriptedModel


class AssessmentTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.settings = OpinionSettings('sqlite:///' + str(Path(self.tmp.name)/'test.sqlite'))
        self.store = OpinionStore(self.settings.database_url)
        self.payload = request_data()
        records = rows(8)
        records[0].content = 'TEST 原始长评论。' * 90
        prepared, stats = prepare_comments([post()], records, self.settings)
        self.dataset = self.store.save_dataset(self.payload,[post()],prepared,stats)
        self.comments = self.store.read_comments(self.dataset)
        refs = [Evidence(post_id=c.post_id,comment_id=c.comment_id) for c in prepared]
        section = Section(type='discussion_topics',title='TEST 讨论主题',summary='TEST',status='completed',analyzed_sample=refs,
            data=[{'label':'信息透明','explanation':'TEST 希望获得更完整的信息，不能推断全平台意见。','evidence':refs}])
        self.report = OpinionReport(task_id='TEST',dataset_id=self.dataset,selection=self.payload.selection,selected_event=self.payload.event,
            generated_at='2026-11-19T00:00:00Z',status='partial',insight='TEST 历史真实摘要',stats=stats,sections=[section],posts=[post()],sources=[],limitations=[],usage={})
        self.report = enrich_report(self.report,self.comments)
        self.packet,self.visible,self.sources = synthesis_input(self.report,self.comments)

    def tearDown(self):
        self.store.engine.dispose();self.tmp.cleanup()

    def output(self):
        return ReportSynthesis(overall_assessment=OverallAssessment(summary='TEST 讨论集中于信息公开，评论依据只能支持样本内的判断。',core_judgment='TEST 优先核实信息。',
            section_types=['discussion_topics'],evidence=[{'post_id':p,'comment_id':c} for p,c in self.visible]),chart_interpretations=[])

    def test_legacy_alias_serializes_only_one_overall_field(self):
        self.assertEqual(self.report.overall_assessment.status,'legacy')
        self.assertNotIn('insight',self.report.model_dump())
        self.assertIn('overall_assessment',self.report.model_dump())

    def test_generic_legacy_placeholder_is_not_presented_as_research(self):
        data=self.report.model_dump();data.pop('overall_assessment');data['insight']='本次仅完成部分评论研究，请结合以下模块和数据范围理解结果。'
        result=OpinionReport.model_validate(data)
        self.assertEqual(result.overall_assessment.status,'unavailable');self.assertEqual(result.overall_assessment.summary,'')

    def test_packet_is_bounded_and_contains_actual_comment_ids(self):
        self.assertLessEqual(len(json.dumps(self.packet,ensure_ascii=False).encode()),12000)
        self.assertTrue(self.visible)
        self.assertLessEqual(len(self.packet['evidence_comments']),8)
        self.assertTrue(self.visible <= {(c['post_id'],c['comment_id']) for c in self.comments})

    def test_invalid_references_sections_sources_and_free_numbers_rejected(self):
        for update in [{'evidence':[{'post_id':post().id,'comment_id':'invented'}]}, {'section_types':['public_emotions']},
                       {'source_ids':['not-read']}, {'summary':'TEST 全平台80%的人支持。'}]:
            data=self.output().model_dump();data['overall_assessment'].update(update)
            with self.assertRaises(ValueError):
                validate_synthesis(ReportSynthesis.model_validate(data),self.report,self.visible,self.sources)

    def test_chart_interpretation_must_reference_its_actual_chart(self):
        data=self.output().model_dump()
        data['chart_interpretations']=[{'chart_id':'invented','analysis':'TEST'}]
        self.assertFalse(validate_synthesis(ReportSynthesis.model_validate(data),self.report,self.visible,self.sources).chart_interpretations)
        data['chart_interpretations']=[{'chart_id':'section-0','analysis':'TEST','evidence':[{'post_id':post().id,'comment_id':'invented'}]}]
        self.assertFalse(validate_synthesis(ReportSynthesis.model_validate(data),self.report,self.visible,self.sources).chart_interpretations)

    def test_verified_sample_count_can_be_cited_but_not_invented_population(self):
        data=self.output().model_dump();data['overall_assessment']['summary']='TEST 本次保留8条评论，不能推断全平台态度。'
        self.assertTrue(validate_synthesis(ReportSynthesis.model_validate(data),self.report,self.visible,self.sources).overall_assessment.summary)
        data['overall_assessment']['summary']='TEST 全平台有8人支持。'
        with self.assertRaises(ValueError):validate_synthesis(ReportSynthesis.model_validate(data),self.report,self.visible,self.sources)

    async def test_synthesis_success_and_cache_avoid_duplicate_model_calls(self):
        model=ScriptedModel()
        first=await synthesize_assessment(model,self.report,self.comments,self.store)
        self.assertEqual(first.overall_assessment.status,'partial')
        self.assertIn('信息透明',first.overall_assessment.summary)
        calls=model._calls
        second=await synthesize_assessment(model,self.report,self.comments,self.store)
        self.assertEqual(model._calls,calls)
        self.assertEqual(second.overall_assessment.summary,first.overall_assessment.summary)

    async def test_model_failure_keeps_sections_and_does_not_invent_summary(self):
        with patch('app.public_opinion.assessment.structured',new=AsyncMock(side_effect=TimeoutError)):
            result=await synthesize_assessment(ScriptedModel(),self.report,self.comments)
        self.assertEqual(result.overall_assessment.status,'unavailable')
        self.assertFalse(result.overall_assessment.summary)
        self.assertTrue(self.report.sections[0].data)

    async def test_no_evidence_means_no_synthesis_request(self):
        report=self.report.model_copy(update={'sections':[]})
        with patch('app.public_opinion.assessment.structured',new=AsyncMock()) as call:
            result=await synthesize_assessment(ScriptedModel(),report,self.comments)
            call.assert_not_awaited()
        self.assertEqual(result.overall_assessment.status,'unavailable')

    def test_headroom_enforces_budget_without_fake_spending(self):
        settings=replace(self.settings,max_tokens=15000,max_model_calls=3)
        budget=Budget(settings);budget.headroom_tokens=8000;budget.headroom_calls=1
        with self.assertRaises(BudgetExceeded):budget.reserve(['x'*8000],1000)
        self.assertEqual(budget.snapshot()['reported_tokens'],0);self.assertEqual(budget.reserved,0)
        budget.headroom_tokens=0;budget.headroom_calls=0
        ticket=budget.reserve(['x'*8000],1000)
        budget.settle(ticket,{'prompt_tokens':1000,'completion_tokens':100,'total_tokens':1100})
        self.assertEqual(budget.reserved,1100)

    async def test_evidence_pagination_preview_fulltext_and_no_llm_on_read(self):
        report=self.report.model_copy(update={'overall_assessment':self.output().overall_assessment})
        report.sections.append(Section(type='representative_comments',title='TEST',status='completed',summary='TEST',evidence=report.sections[0].analyzed_sample))
        task,_=self.store.create_task(self.payload);report.task_id=task['id']
        self.store.save_report(task['id'],report.model_dump(mode='json'))
        self.store.update_task(task['id'],status='partial',checkpoint={'dataset_id':self.dataset})
        app=FastAPI();app.include_router(router);app.state.opinion_store=self.store
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            base='/api/public-opinion/tasks/'+task['id']
            with patch('app.public_opinion.assessment.structured',new=AsyncMock()) as call:
                result=await client.get(base+'/report');self.assertEqual(result.status_code,200);self.assertNotIn('insight',result.json());call.assert_not_awaited()
            result=await client.get(base+'/evidence',params={'section_index':1,'limit':3})
            self.assertEqual(result.json()['total'],8);self.assertEqual(len(result.json()['comments']),3)
            preview=result.json()['comments'][0];self.assertLessEqual(len(preview['content']),240);self.assertNotIn('raw_content',preview)
            full=await client.get(base+'/comments',params={'post_id':preview['post_id'],'comment_id':preview['comment_id']})
            self.assertGreater(len(full.json()['content']),240)
            result=await client.get(base+'/evidence',params={'section_index':0,'group_index':0,'offset':3,'limit':3})
            self.assertEqual(result.json()['comments'][0]['comment_id'],'c3')
            result=await client.get(base+'/evidence',params={'assessment':True})
            self.assertEqual(result.json()['total'],len(self.visible))
            self.assertEqual((await client.get(base+'/evidence',params={'section_index':99})).status_code,404)
            self.assertEqual((await client.get(base+'/evidence',params={'assessment':True,'chart_id':'section-0'})).status_code,422)
