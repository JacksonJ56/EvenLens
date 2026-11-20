import asyncio
import json
from deepagents import create_deep_agent
from langchain.agents.structured_output import ToolStrategy
from langchain_core.tools import tool

from ..event_trace.clients import public_url, url_key
from .collector import identify_post, normalized_time
from .llm import BudgetExceeded, ToolPolicy
from .prompts import DISCOVERY
from .schemas import DiscoveryChoice, Post
from .tieba_protocol import topic_url

DOMAINS = {"xiaohongshu": "xiaohongshu.com", "kuaishou": "kuaishou.com",
           "bilibili": "bilibili.com", "weibo": "weibo.com OR site:weibo.cn",
           "tieba": "tieba.baidu.com"}


class PostDiscovery:
    def __init__(self, provider, model, settings, budget, progress, diagnostic=None, reader=None):
        self.provider, self.model, self.settings, self.budget, self.progress = provider, model, settings, budget, progress
        self.search_count = self.fetch_count = 0
        self.queries, self.candidates, self.pages, self.verified = [], {}, {}, {}
        self.errors = []
        self.ranked = []
        self.diagnostic = diagnostic
        self.raw_results = 0
        self.reader = reader
        self.authorized_attempts = self.authorized_reads = self.public_fetch_failures = 0
        self.authorized_restricted = False

    def diagnostics(self):
        return {"searches": self.search_count, "raw_results": self.raw_results, "candidate_posts": len(self.candidates),
                "fetch_attempts": self.fetch_count, "readable_posts": sum("content" in p for p in self.pages.values()),
                "verified_posts": len(self.verified), "ranked_posts": len(self.ranked),
                "public_fetch_failures": self.public_fetch_failures, "authorized_read_attempts": self.authorized_attempts,
                "authorized_reads": self.authorized_reads,
                "authorized_restricted": self.authorized_restricted,
                "last_error": self.errors[-1] if self.errors else None}

    def record(self):
        if self.diagnostic:
            self.diagnostic(self.diagnostics())

    def failure_detail(self):
        stats = self.diagnostics()
        counts = f"检索 {stats['searches']} 次、找到 {stats['candidate_posts']} 个候选、读取成功 {stats['readable_posts']} 个、验证通过 {stats['verified_posts']} 个"
        return counts + ("；最近一次读取/检索失败：" + self.errors[-1] if self.errors else "")

    async def discover(self, payload):
        platform = payload.selection.platform_id
        if payload.event.url and identify_post(platform, payload.event.url):
            self.candidates[url_key(public_url(payload.event.url))] = {
                "url": public_url(payload.event.url), "title": payload.event.title, "date": None}

        @tool
        async def search_web(query: str) -> dict:
            """搜索指定平台上的公开帖子。可以根据结果调整关键词；不是完整平台站内搜索。"""
            query = query.strip()[:90]
            if not query or query in self.queries:
                return {"error": "搜索词为空或已执行，请调整查询"}
            if self.search_count >= self.settings.max_searches:
                return {"error": "已达到帖子搜索次数上限，请使用现有资料结束研究"}
            self.search_count += 1
            self.queries.append(query)
            self.progress("post_discovery", f"正在发现相关帖子（第 {self.search_count} 次检索）")
            self.record()
            try:
                hits = await self.provider.search((query + " site:" + DOMAINS[platform])[:128])
            except Exception as error:
                from ..event_trace.clients import ProviderError
                message = str(error) if isinstance(error, ProviderError) else "帖子搜索服务失败"
                self.errors.append(message)
                self.record()
                return {"error": message}
            self.raw_results += len(hits)
            result = []
            for hit in hits:
                if not identify_post(platform, hit.url):
                    continue
                url = public_url(hit.url)
                item = {"url": url, "title": hit.title[:500], "date": hit.date,
                        "summary": (hit.snippet or hit.summary)[:800]}
                self.candidates[url_key(url)] = item
                result.append(item)
            self.record()
            return {"posts": result[:20], "searches_used": self.search_count, "raw_results": len(hits),
                    "skipped_non_posts": len(hits) - len(result)}

        @tool
        async def fetch_page(url: str) -> dict:
            """阅读已搜索到的指定平台帖子正文；正文不可访问时不能标记为已验证。"""
            try:
                key = url_key(public_url(url))
            except ValueError:
                return {"error": "网址无效或不允许"}
            candidate = self.candidates.get(key)
            if not candidate:
                return {"error": "只能读取真实搜索结果或原始帖子链接"}
            if key in self.pages:
                return self.pages[key]
            if self.fetch_count >= self.settings.max_fetches:
                return {"error": "已达到网页读取上限"}
            prefer_native=platform=='tieba' and self.reader and self.reader.available(platform)
            if prefer_native and self.authorized_attempts>=min(3,self.settings.max_fetches):
                self.pages[key]={'error':'本次授权正文读取次数已用完，该候选尚未读取，不能判断是否可访问；请验证并提交已有候选。','status':'not_read_budget'}
                self.record();return self.pages[key]
            self.fetch_count += 1
            self.progress("post_reading", "正在读取候选帖子")
            self.record()
            page = None
            read_method = "public_fetch"
            published_at = None
            fallback_allowed = True
            try:
                if prefer_native:
                    resolver=getattr(self.provider,'resolve',None)
                    if resolver:await resolver(candidate['url'])
                else:
                    page = await self.provider.fetch(candidate["url"])
                    if len(page.content.strip()) < 80:
                        page = None
                        self.errors.append("公开网页正文不足以确认帖子，尝试已授权的平台阅读")
            except Exception as error:
                from ..event_trace.clients import ProviderError, UnsafeURL
                message = str(error) if isinstance(error, (ProviderError, UnsafeURL)) else "帖子网页读取失败"
                if isinstance(error, ProviderError) and error.status:
                    message += f"（HTTP {error.status}）"
                if isinstance(error, UnsafeURL) or isinstance(error, ProviderError) and error.status in {401, 402, 403, 429}:
                    fallback_allowed = False
                self.errors.append(message)
            if page is None:
                if not prefer_native:self.public_fetch_failures += 1
                if fallback_allowed and not self.authorized_restricted and self.reader and self.reader.available(platform) and self.authorized_attempts < min(3, self.settings.max_fetches):
                    self.authorized_attempts += 1
                    self.progress("post_reading", "正在通过授权贴吧页面读取帖子" if prefer_native else "公开读取未成功，正在通过已授权的平台会话读取帖子")
                    self.record()
                    try:
                        native = await self.reader.read(platform, candidate["url"])
                        if native.post_id != identify_post(platform, candidate["url"]) or not native.content.strip():
                            raise ValueError("identity mismatch")
                        page, read_method, published_at = native, "authorized_platform", native.published_at
                        self.authorized_reads += 1
                    except Exception as error:
                        from .post_reader import PostReadError
                        self.errors.append(str(error) if isinstance(error, PostReadError) else "本机平台阅读未取得身份匹配的正文")
                        if isinstance(error, PostReadError) and error.code in {'restricted', 'ForbiddenError', 'IPBlockError', 'PlatformAccessError'}:
                            self.authorized_restricted = True
                            self.record()
                            raise ValueError("平台拒绝了当前授权会话的正文读取或要求安全验证；已停止任务。"
                                "请在平台官方页面确认该帖子可访问并检查登录状态；不能将此判断为帖子已删除，"
                                "也不会继续重试或绕过限制。可使用已获授权的评论文件继续分析。") from None
            if page is None:
                self.pages[key] = {"error": "未取得可核验文字；不把搜索摘要或标题当正文"}
                self.record()
                return self.pages[key]
            self.pages[key] = {"url": candidate["url"], "title": page.title[:500], "content": page.content[:5000],
                               "read_method": read_method, "published_at": published_at}
            self.record()
            return self.pages[key]

        @tool
        async def validate_posts(urls: list[str]) -> dict:
            """核对已读网页的真实 URL/平台/帖子 ID。验证为可读候选，不代表已确认事件相关性。"""
            self.progress("post_validation", "正在验证候选帖子")
            accepted = []
            for url in urls[:20]:
                try:
                    key = url_key(public_url(url))
                except ValueError:
                    continue
                candidate, page = self.candidates.get(key), self.pages.get(key)
                identifier = identify_post(platform, url)
                if not candidate or not page or "content" not in page or not identifier:
                    continue
                # Reject common login/verification screens; never bypass them.
                if any(marker in page["title"].lower() for marker in ["登录", "安全验证", "验证码", "access denied", "sign in"]):
                    continue
                self.verified[identifier] = Post(id=identifier, platform_id=platform, url=candidate["url"],
                    title=page["title"], summary=page["content"][:1400],
                    published_at=normalized_time(page.get("published_at") or candidate.get("date")), verification="page_read",
                    read_method=page.get("read_method", "public_fetch"))
                accepted.append({"id": identifier, "url": candidate["url"], "title": page["title"]})
            self.record()
            return {"verified": accepted}

        @tool
        async def rank_posts(post_ids: list[str], reasons: list[str]) -> dict:
            """为已验证帖子记录与本次事件的相关性理由。输入按相关性从高到低排列的 ID。"""
            ranked = []
            for identifier, reason in zip(post_ids[:self.settings.max_posts], reasons[:self.settings.max_posts]):
                if identifier in self.verified and reason.strip():
                    self.verified[identifier] = self.verified[identifier].model_copy(update={"relevance": reason[:1000]})
                    ranked.append(identifier)
            self.ranked = list(dict.fromkeys([*self.ranked, *ranked]))
            self.record()
            return {"ranked_post_ids": ranked}

        tools = [search_web, fetch_page, validate_posts, rank_posts]
        if platform=='tieba' and payload.event.url and topic_url(payload.event.url) and self.reader and self.reader.available(platform):
            @tool
            async def read_selected_topic() -> dict:
                """读取用户选中贴吧热点的官方聚合页，发现真实帖子链接；不把聚合页标题当作帖子正文。"""
                if self.fetch_count>=self.settings.max_fetches:return {'error':'已达到网页读取上限'}
                self.fetch_count+=1
                self.progress('post_discovery','正在读取选中贴吧热点的官方关联帖子');self.record()
                try:
                    resolver=getattr(self.provider,'resolve',None)
                    if resolver:await resolver(payload.event.url)
                    items=await self.reader.read(platform,payload.event.url,topic=True)
                except Exception as error:
                    from .post_reader import PostReadError
                    if isinstance(error,PostReadError) and error.code=='restricted':
                        self.authorized_restricted=True;self.record()
                        raise ValueError('贴吧官方热点页面要求本人验证或拒绝访问，已停止任务；请检查官方会话。') from None
                    self.errors.append('贴吧官方聚合页未取得可验证帖子链接');self.record()
                    return {'error':self.errors[-1]}
                result=[]
                for item in items:
                    candidate={'url':item['url'],'title':'贴吧帖子 '+item['post_id'],'date':None}
                    self.candidates[url_key(public_url(item['url']))]=candidate;result.append(candidate)
                self.record()
                return {'posts':result,'scope':'官方聚合页的真实链接；尚未读取或确认帖子相关性，必须继续 fetch_page、validate_posts、rank_posts。'}
            tools.append(read_selected_topic)
        agent = create_deep_agent(self.model, tools=tools, name="PostDiscoveryAgent", system_prompt=DISCOVERY,
            response_format=ToolStrategy(DiscoveryChoice, handle_errors=False),
            middleware=[ToolPolicy({t.name for t in tools}, self.budget)])
        try:
            async with asyncio.timeout(self.settings.discovery_timeout):
                output = await agent.ainvoke({"messages": [{"role": "user", "content": json.dumps({
                    "selection": payload.selection.model_dump(), "event": payload.event.model_dump(mode="json"),
                    "initial_candidates": list(self.candidates.values()), "max_posts": self.settings.max_posts,
                }, ensure_ascii=False)}]}, {"recursion_limit": 35, "max_concurrency": 1})
            choice: DiscoveryChoice = output["structured_response"]
        except TimeoutError:
            if not self.ranked:
                raise ValueError(f"帖子发现超过 {self.settings.discovery_timeout} 秒时限；{self.failure_detail()}。") from None
            choice = DiscoveryChoice(post_ids=self.ranked,
                                     limitations=["帖子发现达到时间上限，仅保留已验证且已排序的部分帖子。"])
        except BudgetExceeded as error:
            if not self.ranked:
                raise ValueError(f"帖子发现预算不足：{error}；{self.failure_detail()}。") from None
            choice = DiscoveryChoice(post_ids=self.ranked, limitations=["帖子发现达到模型预算，仅保留已验证且已排序的部分帖子。"])
        # Model IDs cannot introduce new posts. Rank only verified, explicitly justified candidates.
        seen, posts = set(), []
        for identifier in choice.post_ids:
            post = self.verified.get(identifier)
            if post and post.relevance and identifier not in seen:
                seen.add(identifier)
                posts.append(post)
        if not posts:
            raise ValueError("未发现可读取、验证且相关的帖子；" + self.failure_detail() +
                             "。公开搜索和第三方 Fetch 不使用本机登录会话；可导入授权评论，或检查原始帖子是否仍可访问。")
        warnings = choice.limitations + ["帖子来自公开网页检索或用户选中原始链接，并非完整平台站内搜索。"]
        if any(page.get('status')=='not_read_budget' for page in self.pages.values()):
            warnings.append('部分候选因本次授权正文读取预算已用完而未实际读取，不能据此判断帖子已删除、无法访问或与事件无关。')
        if any(post.read_method == "authorized_platform" for post in posts):
            warnings.append("部分帖子通过本机已授权的平台会话读取，未向第三方 Fetch 提供 Cookie；仅核验返回的文字，未核验图片或视频内容。")
        return posts[:self.settings.max_posts], warnings, {
            "discovery_searches": self.search_count, "discovery_fetches": self.fetch_count}
