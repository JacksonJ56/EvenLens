"""Normal authorized Tieba pages + MediaCrawler extractors, in its own Python.

No upstream crawler.start(), stealth scripts, manufactured signatures, proxy
rotation or CAPTCHA solving. Only naturally rendered pages/responses are read.
"""
import asyncio
from contextlib import asynccontextmanager
import json
import re
from urllib.parse import urlsplit,urljoin,parse_qs

try:from .tieba_protocol import post_id,topic_url
except ImportError:from tieba_protocol import post_id,topic_url


class TiebaReadError(ValueError):
    def __init__(self,code):super().__init__(code);self.code=code


async def check_page(page,response=None):
    if response and response.status in {401,403,429}:raise TiebaReadError('restricted')
    if response and response.status==404:raise TiebaReadError('not_found')
    p=urlsplit(page.url)
    if p.hostname!='tieba.baidu.com':raise TiebaReadError('restricted')
    title=(await page.title()).lower()
    if any(k in title for k in ['安全验证','验证码','captcha','登录百度']):raise TiebaReadError('restricted')
    for frame in page.frames:
        f=urlsplit(frame.url)
        if (f.hostname or '').endswith('.baidu.com') and any(k in f.path for k in ['/captcha/','/verify/']):
            raise TiebaReadError('restricted')


def minimize_api(body,expected):
    """Require an actual thread identity and first-floor body, not an abstract."""
    if not isinstance(body,dict):return None
    thread=body.get('thread') or {};first=body.get('first_floor') or {}
    if str(thread.get('id') or thread.get('tid') or '')!=expected or not first.get('content'):return None
    from media_platform.tieba.help import TieBaExtractor
    note=TieBaExtractor().extract_note_detail_from_api(body)
    if not (first.get('time') or thread.get('create_time')):note.publish_time=''
    return note if note.note_id==expected and note.desc.strip() else None


class NativeResponses:
    def __init__(self,page,expected):
        self.expected=expected;self.pages=[];self.blocked=False;self.jobs=set()
        self.listener=self.receive;page.on('response',self.listener)

    def receive(self,response):
        p=urlsplit(response.url)
        if p.hostname!='tieba.baidu.com' or p.path.rstrip('/')!='/c/f/pb/page_pc':return
        task=asyncio.create_task(self.consume(response));self.jobs.add(task);task.add_done_callback(self.jobs.discard)

    async def consume(self,response):
        try:
            request=response.request
            params=parse_qs(request.post_data or urlsplit(request.url).query)
            if params.get('kz',[''])[0]!=self.expected:return
            if response.status in {401,403,429}:self.blocked=True;return
            if response.status!=200:return
            raw=await response.body()
            if len(raw)>4_000_000:return
            body=json.loads(raw)
            if minimize_api(body,self.expected):self.pages.append(body)
        except Exception:pass  # Never emit raw account/response data or tokens.

    async def drain(self):
        if self.jobs:await asyncio.gather(*list(self.jobs),return_exceptions=True)


@asynccontextmanager
async def browser_page(cookie):
    from playwright.async_api import async_playwright
    from session_protocol import cookie_pairs
    async with async_playwright() as playwright:
        browser=await playwright.chromium.launch(headless=True)
        try:
            context=await browser.new_context(locale='zh-CN')
            await context.add_cookies([{'name':k,'value':v,'domain':'.baidu.com','path':'/'} for k,v in cookie_pairs(cookie).items()])
            await context.route('**/*',lambda route:route.abort() if route.request.resource_type=='media' or (
                route.request.is_navigation_request() and route.request.frame.parent_frame is None and urlsplit(route.request.url).hostname!='tieba.baidu.com') else route.continue_())
            yield await context.new_page()
        finally:await browser.close()


def html_note(html,expected):
    from media_platform.tieba.help import TieBaExtractor
    from parsel import Selector
    note=TieBaExtractor().extract_note_detail(html)
    if note.note_id!=expected:return None
    root=Selector(text=html).css('.l_post.j_l_post').xpath('./descendant::div[contains(concat(" ",normalize-space(@class)," ")," d_post_content ")][1]')
    text=root.xpath('string(.)').get(default='').strip()
    if not text:return None
    note.desc=text[:5000]
    return note


async def visit(page,url,records):
    expected=post_id(url)
    if not expected:raise TiebaReadError('identity_mismatch')
    response=await page.goto(url,wait_until='domcontentloaded',timeout=18000)
    await check_page(page,response)
    if post_id(page.url)!=expected:raise TiebaReadError('identity_mismatch')
    for _ in range(12):
        await check_page(page);await records.drain()
        if records.blocked:raise TiebaReadError('restricted')
        for body in records.pages:
            note=minimize_api(body,expected)
            if note:return note
        html=await page.content()
        if len(html)<=4_000_000:
            note=html_note(html,expected)
            if note:return note
        await page.wait_for_timeout(400)
    raise TiebaReadError('no_text')


async def read_post(cookie,url):
    async with browser_page(cookie) as page:
        records=NativeResponses(page,post_id(url));note=await visit(page,url,records)
        return {'status':'ok','post_id':note.note_id,'title':note.title[:500],'content':note.desc[:5000],'published_at':note.publish_time or None}


async def topic_posts(cookie,url):
    if not topic_url(url):raise TiebaReadError('identity_mismatch')
    async with browser_page(cookie) as page:
        response=await page.goto(url,wait_until='domcontentloaded',timeout=18000);await check_page(page,response)
        if not topic_url(page.url) or parse_qs(urlsplit(page.url).query)!=parse_qs(urlsplit(url).query):raise TiebaReadError('identity_mismatch')
        html=await page.content()
        if len(html)>4_000_000:raise TiebaReadError('failed')
        identifiers=list(dict.fromkeys(re.findall(r'(?:https?://tieba\.baidu\.com)?/p/(\d+)',html)))[:20]
        return {'status':'ok','items':[{'post_id':i,'url':'https://tieba.baidu.com/p/'+i} for i in identifiers]}


def page_comments(html,body,note):
    """Preserve source order, excluding the article itself from the denominator."""
    from media_platform.tieba.help import TieBaExtractor
    from parsel import Selector
    extractor=TieBaExtractor();original_ids=set()
    if body is not None:
        first=body.get('first_floor') or {}
        original_ids.add(str(first.get('id') or first.get('post_id') or ''))
        posts=[p for p in body.get('post_list',[]) if str(p.get('floor',p.get('post_no','')))!='1']
        comments=extractor.extract_tieba_note_parent_comments_from_api({**body,'post_list':posts},note)
        times={str(p.get('id')):p.get('time') for p in posts}
        for comment in comments:
            if not times.get(comment.comment_id):comment.publish_time=''
    else:
        comments=extractor.extract_tieba_note_parment_comments(html,note.note_id)
        for node in Selector(text=html).css('.l_post.j_l_post'):
            data=extractor.extract_data_field_value(node).get('content',{})
            if str(data.get('post_no'))=='1':original_ids.add(str(data.get('post_id') or ''))
    return [c for c in comments if c.note_id==note.note_id and c.comment_id not in original_ids and c.content.strip()]


async def collect_comments(cookie,url,limit,callback):
    expected=post_id(url);seen=set();count=0
    async with browser_page(cookie) as page:
        records=NativeResponses(page,expected);note=await visit(page,url,records)
        for number in range(1,6):
            await check_page(page);await records.drain()
            if records.blocked:raise TiebaReadError('restricted')
            html=await page.content();comments=page_comments(html,records.pages[-1] if records.pages else None,note)
            for comment in comments:
                if comment.comment_id in seen:continue
                seen.add(comment.comment_id);await callback(expected,[comment]);count+=1
                if count>=limit:return 'completed'
            next_link=page.get_by_role('link',name='下一页',exact=True).first
            if not await next_link.count():return 'completed'
            next_url=urljoin(page.url,await next_link.get_attribute('href') or '')
            if post_id(next_url)!=expected:return 'partial'
            pn=parse_qs(urlsplit(next_url).query).get('pn',[''])[0]
            if not pn.isdigit() or int(pn)<=number:return 'partial'
            records.pages=[]
            await page.wait_for_timeout(1000)
            response=await page.goto(next_url,wait_until='domcontentloaded',timeout=18000);await check_page(page,response)
        return 'partial'
