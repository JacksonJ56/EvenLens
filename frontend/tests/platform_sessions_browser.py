"""Explicit TEST session replies; no real login window or paid Agent task."""
import argparse,asyncio,json
from urllib.parse import urlsplit
from playwright.async_api import async_playwright

async def run(base):
 states,calls,errors={},{},[]
 platforms=['weibo','xiaohongshu','douyin','bilibili','tieba','kuaishou']
 def value(platform,status='not_logged_in'):
  return {'platform_id':platform,'status':status,'message':'TEST: '+status,'configured':platform=='weibo' or status=='verified','session_verified':status=='verified','collector_ready':status=='verified','runtime_ready':True,'login_available':True,'remote_verification_supported':True,'job_id':'TEST_JOB','checked_at':None}
 async with async_playwright() as p:
  browser=await p.chromium.launch(headless=True)
  page=await browser.new_page(viewport={'width':1360,'height':1000},reduced_motion='reduce');page.set_default_timeout(10000)
  page.on('pageerror',lambda error:errors.append(str(error)))
  async def sessions(route):
   parts=urlsplit(route.request.url).path.strip('/').split('/');platform=parts[3];action=parts[4] if len(parts)>4 else 'get';method=route.request.method
   calls[(platform,action)]=calls.get((platform,action),0)+1
   if method=='POST':states[platform]=value(platform,{'check':'verified','login':'logging_in','confirm':'verified'}[action])
   elif method=='DELETE':states[platform]=value(platform)
   elif platform not in states:states[platform]=value(platform,'unverified' if platform=='weibo' else 'not_logged_in')
   await route.fulfill(json=states[platform],status=202 if method=='POST' else 200)
  await page.route('**/api/public-opinion/sessions/**',sessions)
  await page.route('**/api/public-opinion/capabilities',lambda r:r.fulfill(json={'platforms':{x:{'supported':True,'collector_ready':False,'adapter_implemented':True,'message':''} for x in platforms},'import_available':True,'llm_configured':True}))
  async def boards(route):
   platform=urlsplit(route.request.url).path.split('/')[3]
   await route.fulfill(json={'mode':'live','status':'fresh','items':[{'id':'TEST_EVENT','title':'TEST 登录交互验收','rank':1,'platform':platform,'url':'https://example.com/'}]})
  await page.route('**/api/boards/**',boards)
  async def no_task(route):raise AssertionError('UI test cannot start Agent tasks')
  await page.route('**/api/public-opinion/tasks',no_task)
  await page.goto(base);await page.get_by_role('button',name='事件实验室',exact=True).click()
  async def choose(label,text):
   await page.get_by_role('combobox',name=label,exact=True).click();await page.get_by_role('option').filter(has_text=text).first.click()
  await choose('热点分区','综合');await choose('热点平台','小红书');await choose('榜单选择','点赞榜');await choose('热点事件','TEST 登录交互验收');await choose('实验功能','公众舆情分析')
  notice=page.get_by_role('region',name='小红书登录状态');execute=page.get_by_role('button',name='执行',exact=True)
  await notice.get_by_text('尚未登录',exact=False).wait_for();assert await execute.is_disabled();assert not any(a=='login' for _,a in calls)
  await notice.get_by_role('button',name='登录小红书').click();await notice.get_by_role('button',name='完成登录并验证').wait_for();assert await execute.is_disabled()
  await notice.get_by_role('button',name='取消登录').click();await notice.get_by_text('尚未登录',exact=False).wait_for()
  await notice.get_by_role('button',name='登录小红书').click();await notice.get_by_role('button',name='完成登录并验证').click();await notice.get_by_text('会话已验证',exact=False).wait_for();assert await execute.is_enabled()
  platform=page.get_by_role('combobox',name='热点平台',exact=True)
  await platform.click();zhihu=page.get_by_role('option').filter(has_text='知乎')
  assert await zhihu.get_attribute('aria-disabled')=='true'
  await zhihu.scroll_into_view_if_needed()
  assert float(await zhihu.evaluate('(element) => getComputedStyle(element).opacity')) < .5
  await page.screenshot(path='/tmp/eventlens-zhihu-disabled.png')
  await zhihu.click(force=True);assert await platform.get_attribute('title')=='小红书'
  for key in ['ArrowDown','ArrowUp','Home','End']:
   await platform.press(key);assert await platform.get_attribute('aria-activedescendant')!=await zhihu.get_attribute('id')
  await platform.press('Escape')
  await choose('实验功能','事件溯源');await choose('热点平台','知乎');await choose('热点事件','TEST 登录交互验收');assert await execute.is_enabled()
  await choose('实验功能','公众舆情分析');await page.get_by_text('当前平台暂不支持公众舆情分析，请重新选择支持的平台。',exact=True).wait_for()
  assert await platform.get_attribute('aria-invalid')=='true';assert await execute.is_disabled()
  assert await page.get_by_role('region',name='知乎登录状态').count()==0
  await choose('实验功能','事件溯源');assert await execute.is_enabled()
  await choose('实验功能','公众舆情分析')
  states['xiaohongshu']=value('xiaohongshu')
  await choose('热点平台','小红书');await choose('榜单选择','点赞榜');await choose('热点事件','TEST 登录交互验收')
  await page.get_by_role('region',name='小红书登录状态').get_by_text('尚未登录',exact=False).wait_for();assert await execute.is_disabled()
  await page.get_by_text('使用已有授权评论 · JSON / CSV',exact=True).click()
  await page.get_by_label('选择授权评论文件').set_input_files({'name':'TEST-comments.json','mimeType':'application/json','buffer':b'{"TEST":true}'})
  await page.get_by_role('checkbox').check()
  await page.route('**/api/public-opinion/datasets/import',lambda r:r.fulfill(status=201,json={'dataset_id':'TEST_IMPORT','stats':{'prepared_count':3}}))
  await page.get_by_role('button',name='导入评论',exact=True).click();await page.get_by_text('已绑定当前热点的 3 条一级评论。',exact=True).wait_for();assert await execute.is_enabled()
  await choose('热点平台','微博');await choose('热点事件','TEST 登录交互验收');await page.get_by_role('region',name='微博登录状态').get_by_text('会话已验证',exact=False).wait_for();assert await execute.is_enabled();assert calls.get(('weibo','check'))
  async def failed(route):await route.fulfill(status=503,json={'detail':'TEST session unavailable'})
  await page.route('**/api/public-opinion/sessions/xiaohongshu',failed);await choose('热点平台','小红书');await choose('榜单选择','阅读榜');await choose('热点事件','TEST 登录交互验收')
  notice=page.get_by_role('region',name='小红书登录状态');await notice.get_by_role('alert').wait_for();assert await execute.is_disabled()
  states['xiaohongshu']=value('xiaohongshu');await page.unroute('**/api/public-opinion/sessions/xiaohongshu',failed);await notice.get_by_role('button',name='重新读取').click();await notice.get_by_text('尚未登录',exact=False).wait_for()
  await page.set_viewport_size({'width':390,'height':844});await notice.scroll_into_view_if_needed();assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
  await page.screenshot(path='/tmp/eventlens-platform-session-mobile.png');assert not errors,errors
  print(json.dumps({'browser':'passed','switch_login_cancel_verify_import_tracing_retry_mobile':'passed','real_login_windows':0,'agent_tasks':0,'session_requests':sum(calls.values())}));await browser.close()

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--base',default='http://127.0.0.1:3100');args=parser.parse_args();asyncio.run(run(args.base))
