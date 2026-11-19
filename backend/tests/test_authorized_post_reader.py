"""Native reader fixtures: no real accounts or paid model/search requests."""
import asyncio, importlib.util, json, os, unittest
from pathlib import Path
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from app.event_trace.clients import FetchedPage, ProviderError, UnsafeURL
from app.public_opinion.discovery import PostDiscovery
from app.public_opinion.llm import Budget
from app.public_opinion.post_reader import AuthenticatedPage, AuthenticatedPostReader, PostReadError
from app.public_opinion.settings import OpinionSettings
from test_public_opinion import request_data, ScriptedModel
ID='6afaac79000000002a02a46d'
URL='https://www.xiaohongshu.com/explore/'+ID+'?xsec_token=TEST&xsec_source=pc_search'

class NativeScript(ScriptedModel):
 async def _agenerate(self,messages,stop=None,run_manager=None,**kwargs):
  results=[m for m in messages if isinstance(m,ToolMessage)];name=results[-1].name if results else None
  if name is None:tool,data='fetch_page',{'url':URL}
  elif name=='fetch_page':tool,data='validate_posts',{'urls':[URL]}
  elif name=='validate_posts':tool,data='rank_posts',{'post_ids':[ID],'reasons':['TEST 实际文字相关']}
  else:tool,data='DiscoveryChoice',{'post_ids':[ID],'limitations':['TEST 单帖']}
  return ChatResult(generations=[ChatGeneration(message=AIMessage(content='',tool_calls=[{'name':tool,'args':data,'id':'call-'+str(len(results))}]))])

class DiscoveryReaderTests(unittest.IsolatedAsyncioTestCase):
 async def setup_discovery(self,page,error=None):
  settings=OpinionSettings('sqlite:///:memory:')
  provider=SimpleNamespace(fetch=AsyncMock(side_effect=error) if error else AsyncMock(return_value=FetchedPage(title='TEST',content='x'*100)))
  reader=SimpleNamespace(available=lambda platform:True,read=AsyncMock(return_value=page))
  payload=request_data('xiaohongshu');payload.event=payload.event.model_copy(update={'url':URL,'title':'TEST 短帖'})
  return PostDiscovery(provider,NativeScript(),settings,Budget(settings),lambda *args:None,reader=reader),reader,payload
 async def test_public_404_reads_native_short_text_with_actual_identity(self):
  discovery,reader,payload=await self.setup_discovery(AuthenticatedPage(ID,'TEST 短帖','真实取得的短正文'),ProviderError('Fetch','empty',404))
  posts,warnings,usage=await discovery.discover(payload)
  self.assertEqual(posts[0].read_method,'authorized_platform');self.assertEqual(discovery.diagnostics()['authorized_reads'],1)
  self.assertEqual(usage['discovery_searches'],0);self.assertTrue(any('未向第三方' in w for w in warnings));reader.read.assert_awaited_once()
 async def test_public_success_never_uses_native_reader(self):
  discovery,reader,payload=await self.setup_discovery(AuthenticatedPage(ID,'TEST','短文'))
  posts,_,_=await discovery.discover(payload);self.assertEqual(posts[0].read_method,'public_fetch');reader.read.assert_not_awaited()
 async def test_wrong_identity_and_title_only_never_verify(self):
  for page in [AuthenticatedPage('wrong','TEST','text'),AuthenticatedPage(ID,'只有标题','')]:
   discovery,_,payload=await self.setup_discovery(page,ProviderError('Fetch','empty',404))
   with self.assertRaises(ValueError):await discovery.discover(payload)
   self.assertEqual(discovery.diagnostics()['verified_posts'],0)
 async def test_access_denials_and_unsafe_dns_not_bypassed(self):
  for error in [UnsafeURL('私网'),ProviderError('Fetch','拒绝',403),ProviderError('Fetch','限流',429)]:
   discovery,reader,payload=await self.setup_discovery(AuthenticatedPage(ID,'TEST','文字'),error)
   with self.assertRaises(ValueError):await discovery.discover(payload)
   reader.read.assert_not_awaited()

class ReaderAdapterTests(unittest.IsolatedAsyncioTestCase):
 def setUp(self):self.settings=OpinionSettings('sqlite:///:memory:',crawler_home='/tmp',crawler_python='python')
 def spawn(self,body,sent):
  async def execute(*args,**kwargs):
   sent.append(kwargs['env']);Path(kwargs['env']['EVENTLENS_POST_OUTPUT']).write_text(json.dumps(body))
   return SimpleNamespace(returncode=0,wait=AsyncMock(return_value=0))
  return execute
 async def test_minimal_payload_and_no_key_forwarding(self):
  sent=[]
  with patch.object(OpinionSettings,'collector_status',return_value=(True,'TEST')),patch.dict(os.environ,{'MEDIACRAWLER_COOKIES_XHS':'TEST','DEEPSEEK_API_KEY':'DO-NOT-FORWARD'}),patch('asyncio.create_subprocess_exec',new=self.spawn({'status':'ok','post_id':ID,'title':'TEST','content':'短文','published_at':1700000000000},sent)):
   page=await AuthenticatedPostReader(self.settings).read('xiaohongshu',URL)
  self.assertEqual(page.content,'短文');self.assertIsNotNone(page.published_at);self.assertNotIn('DEEPSEEK_API_KEY',sent[0]);self.assertIn('MEDIACRAWLER_COOKIES_XHS',sent[0])
 async def test_authorization_and_url_allowlist(self):
  with patch.object(OpinionSettings,'collector_status',return_value=(False,'TEST')),patch('asyncio.create_subprocess_exec') as spawn:
   with self.assertRaises(PostReadError):await AuthenticatedPostReader(self.settings).read('xiaohongshu',URL)
   spawn.assert_not_called()
  with patch.object(OpinionSettings,'collector_status',return_value=(True,'TEST')),patch('asyncio.create_subprocess_exec') as spawn:
   for url in ['http://127.0.0.1/x','https://xiaohongshu.com.evil.org/explore/'+ID]:
    with self.assertRaises(ValueError):await AuthenticatedPostReader(self.settings).read('xiaohongshu',url)
   spawn.assert_not_called()
 async def test_restricted_empty_and_mismatched_results_fail(self):
  for body in [{'status':'restricted'},{'status':'no_text'},{'status':'identity_mismatch'},{'status':'ok','post_id':'wrong','content':'text'}]:
   with patch.object(OpinionSettings,'collector_status',return_value=(True,'TEST')),patch.dict(os.environ,{'MEDIACRAWLER_COOKIES_XHS':'TEST'}),patch('asyncio.create_subprocess_exec',new=self.spawn(body,[])):
    with self.assertRaises(PostReadError):await AuthenticatedPostReader(self.settings).read('xiaohongshu',URL)
 async def test_timeout_stops_worker(self):
  event=asyncio.Event();process=SimpleNamespace(returncode=None,pid=123456)
  async def wait():await event.wait()
  process.wait=wait
  def stop(*args):process.returncode=-15;event.set()
  with patch.object(OpinionSettings,'collector_status',return_value=(True,'TEST')),patch.dict(os.environ,{'MEDIACRAWLER_COOKIES_XHS':'TEST'}),patch('asyncio.create_subprocess_exec',new=AsyncMock(return_value=process)),patch('os.killpg',side_effect=stop):
   with self.assertRaises(PostReadError):await AuthenticatedPostReader(replace(self.settings,collector_timeout=.01)).read('xiaohongshu',URL)
  self.assertEqual(process.returncode,-15)
 def test_worker_does_not_invent_body_or_return_profile(self):
  spec=importlib.util.spec_from_file_location('reader_worker_test',Path(__file__).parents[1]/'app/public_opinion/post_read_worker.py')
  module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
  self.assertEqual(module.minimize_note({'note_id':ID,'title':'TEST','desc':''},ID)['status'],'no_text')
  self.assertEqual(module.minimize_note({'note_id':'wrong','desc':'text'},ID)['status'],'identity_mismatch')
  value=module.minimize_note({'note_id':ID,'title':'TEST','desc':'短帖文字','user':{'id':'PRIVATE'}},ID)
  self.assertEqual(value['status'],'ok');self.assertNotIn('user',value)
