"""Tieba contracts and actual harness tests. No network, accounts or paid models."""
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock,patch

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage,ToolMessage
from langchain_core.outputs import ChatGeneration,ChatResult

from app.public_opinion.tieba_protocol import server_login,account_page,post_id,topic_url
from app.public_opinion.tieba_context import check_page,TiebaReadError
from app.public_opinion.discovery import PostDiscovery
from app.public_opinion.llm import Budget
from app.public_opinion.settings import OpinionSettings
from app.public_opinion.schemas import OpinionRequest
from app.event_trace.clients import url_key

POST='https://tieba.baidu.com/p/123456'
TOPIC='https://tieba.baidu.com/hottopic/browse/hottopic?topic_id=123'


class TiebaModel(BaseChatModel):
    @property
    def _llm_type(self):return 'tieba-test-only'
    def bind_tools(self,tools,**kwargs):return self
    def _generate(self,messages,**kwargs):
        index=len([m for m in messages if isinstance(m,ToolMessage)])
        names=['read_selected_topic','fetch_page','validate_posts','rank_posts','DiscoveryChoice']
        args=[{}, {'url':POST},{'urls':[POST]},{'post_ids':['123456'],'reasons':['TEST 与所选事件相关']},
            {'post_ids':['123456'],'limitations':[]}]
        index=min(index,4)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content='',tool_calls=[
            {'name':names[index],'args':args[index],'id':'test_'+str(index)}]))])
    async def _agenerate(self,messages,**kwargs):return self._generate(messages,**kwargs)


class ProtocolTests(unittest.TestCase):
    def test_server_login_needs_explicit_flag_and_identity(self):
        self.assertEqual(server_login('<script>PageData.user={is_login:1,user_id:"123"};</script>'),'verified')
        self.assertEqual(server_login("<script>PageData.user={is_login:true,id:'123'};</script>"),'verified')
        self.assertEqual(server_login('<script>PageData.user={is_login:0};</script>'),'expired')
        for html in ['<p>PageData.user={is_login:1,user_id:123};</p>',
            '<script>PageData.user={other:{is_login:1,user_id:123}};</script>',
            '<script>PageData.user={name:"is_login:1,user_id:123"};</script>',
            '<script>PageData.user={is_login:1,user_id:0};</script>',
            '<script>PageData.other={is_login:1,user_id:123};</script>',
            '<script>PageData.user={BDUSS:"TEST"};</script>']:
            self.assertEqual(server_login(html),'unverified')

    def test_dynamic_account_page_and_url_boundaries(self):
        self.assertEqual(account_page({'errno':0,'data':{'bang_topic':{'topic_list':[{'topic_id':123}]}}}),TOPIC)
        self.assertIsNone(account_page({'errno':0,'data':{'bang_topic':{'topic_list':[{'topic_id':'evil'}]}}}))
        self.assertEqual(post_id(POST),'123456');self.assertTrue(topic_url(TOPIC))
        for url in ['https://tieba.baidu.com.evil.org/p/123','http://127.0.0.1/p/123','https://tieba.baidu.com:9000/p/123']:
            self.assertIsNone(post_id(url));self.assertFalse(topic_url(url))

    def test_installed_mediacrawler_extractors_offline(self):
        home=Path(os.getenv('MEDIACRAWLER_HOME') or Path(__file__).resolve().parents[3]/'MediaCrawler')
        python=Path(os.getenv('MEDIACRAWLER_PYTHON') or home/'.venv/bin/python')
        if not python.is_file():self.skipTest('independent MediaCrawler runtime not installed')
        script='''
import sys
sys.path.insert(1,sys.argv[1])
from tieba_context import minimize_api,page_comments
body={'thread':{'id':'123456','title':'TEST title'},'first_floor':{'id':'1','content':[{'text':'TEST real article fixture'}]},
      'post_list':[{'id':'1','floor':1,'content':[{'text':'article'}]},
                   {'id':'2','floor':2,'content':[{'text':'same text'}]},
                   {'id':'3','floor':3,'content':[{'text':'same text'}]}]}
note=minimize_api(body,'123456')
assert note and note.publish_time==''
assert minimize_api(body,'999') is None
rows=page_comments('',body,note)
assert [r.comment_id for r in rows]==['2','3']
assert all(r.publish_time=='' and not r.parent_comment_id for r in rows)
'''
        result=subprocess.run([str(python),'-c',script,str(Path(__file__).parents[1]/'app/public_opinion')],cwd=home,
            capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr[-1500:])


class TiebaIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_deep_agent_topic_to_verified_post(self):
        reader=SimpleNamespace(available=lambda p:p=='tieba',read=AsyncMock(side_effect=[
            [{'post_id':'123456','url':POST}],SimpleNamespace(post_id='123456',title='TEST actual post',content='TEST actual body',published_at=None)]))
        provider=SimpleNamespace(resolve=AsyncMock(),fetch=AsyncMock(side_effect=AssertionError('No third-party Fetch for logged-in Tieba')),
            search=AsyncMock(side_effect=AssertionError('Selected topic has a real link already')))
        payload=OpinionRequest(function_id='public_opinion',idempotency_key='test-tieba',selection={'category_id':'general','category_name':'综合',
            'platform_id':'tieba','platform_name':'百度贴吧','feed_id':'hot'},event={'id':'test','title':'TEST topic','url':TOPIC})
        settings=OpinionSettings('sqlite:///:memory:')
        agent=PostDiscovery(provider,TiebaModel(),settings,Budget(settings),lambda *a:None,reader=reader)
        posts,_,usage=await agent.discover(payload)
        self.assertEqual([p.id for p in posts],['123456']);self.assertEqual(posts[0].read_method,'authorized_platform')
        self.assertEqual(usage['discovery_searches'],0);self.assertEqual(usage['discovery_fetches'],2)
        reader.read.assert_any_await('tieba',TOPIC,topic=True)
        provider.fetch.assert_not_awaited();provider.search.assert_not_awaited()

    async def test_server_verification_worker_uses_fresh_official_page(self):
        import app.public_opinion.session_protocol as protocol
        import app.public_opinion.tieba_protocol as tieba
        with patch.dict(sys.modules,{'session_protocol':protocol,'tieba_protocol':tieba}):
            file=Path(__file__).parents[1]/'app/public_opinion/session_worker.py'
            spec=importlib.util.spec_from_file_location('tieba_session_test',file);worker=importlib.util.module_from_spec(spec);spec.loader.exec_module(worker)
            listing=SimpleNamespace(status=200,json=AsyncMock(return_value={'errno':0,'data':{'bang_topic':{'topic_list':[{'topic_id':123}]}}}))
            for html,expected in [('<script>PageData.user={is_login:1,user_id:123};</script>','verified'),
                                  ('<script>PageData.user={is_login:0};</script>','expired'),('<html>验证码</html>','unverified')]:
                response=SimpleNamespace(status=200,text=AsyncMock(return_value=html))
                request=SimpleNamespace(get=AsyncMock(side_effect=[listing,response]))
                self.assertEqual(await worker.verify('tieba',SimpleNamespace(request=request),SimpleNamespace(url='https://tieba.baidu.com/')),expected)

    async def test_read_budget_is_not_reported_as_inaccessible_post(self):
        urls=[POST[:-1]+str(6+i) for i in range(4)]
        class LimitedModel(TiebaModel):
            def _generate(self,messages,**kwargs):
                index=len([m for m in messages if isinstance(m,ToolMessage)])
                names=['read_selected_topic',*['fetch_page']*4,'validate_posts','rank_posts','DiscoveryChoice']
                args=[{},*[{'url':u} for u in urls],{'urls':[POST]},
                    {'post_ids':['123456'],'reasons':['TEST matches']},{'post_ids':['123456'],'limitations':[]}]
                index=min(index,len(names)-1)
                return ChatResult(generations=[ChatGeneration(message=AIMessage(content='',tool_calls=[
                    {'name':names[index],'args':args[index],'id':'limit_'+str(index)}]))])
        async def read(platform,url,topic=False):
            if topic:return [{'post_id':u.rsplit('/',1)[1],'url':u} for u in urls]
            return SimpleNamespace(post_id=url.rsplit('/',1)[1],title='TEST post',content='TEST actual fixture body',published_at=None)
        reader=SimpleNamespace(available=lambda p:True,read=AsyncMock(side_effect=read))
        provider=SimpleNamespace(resolve=AsyncMock())
        payload=OpinionRequest(function_id='public_opinion',idempotency_key='test-limit',selection={'category_id':'general',
            'category_name':'综合','platform_id':'tieba','platform_name':'百度贴吧','feed_id':'hot'},
            event={'id':'test','title':'TEST topic','url':TOPIC})
        settings=OpinionSettings('sqlite:///:memory:')
        agent=PostDiscovery(provider,LimitedModel(),settings,Budget(settings),lambda *a:None,reader=reader)
        _,warnings,usage=await agent.discover(payload)
        self.assertEqual(reader.read.await_count,4)  # topic + three actual reads
        self.assertEqual(agent.pages[url_key(urls[-1])]['status'],'not_read_budget')
        self.assertTrue(any('未实际读取' in warning for warning in warnings))
        self.assertEqual(usage['discovery_fetches'],4)

    async def test_verification_page_stops_without_retry(self):
        page=SimpleNamespace(url=POST,title=AsyncMock(return_value='百度安全验证'),frames=[])
        with self.assertRaises(TiebaReadError) as caught:await check_page(page,SimpleNamespace(status=200))
        self.assertEqual(caught.exception.code,'restricted')


if __name__=='__main__':unittest.main()
