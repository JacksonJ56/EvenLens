"""Executed by MediaCrawler's own Python interpreter, from its checkout directory.

Verified against upstream main on 2026-11-19. No dependency on EventLens packages.
No secrets in argv/stdout or persisted profile. Not a generic shell execution tool.
"""
import asyncio
import importlib
import json
import os
import sys
from pathlib import Path


class EnoughComments(BaseException):
    pass


def root_parent(code, comment):
    parent = comment.get("parent_comment_id")
    # Weibo hotflow roots can refer to themselves. Genuine replies refer to a
    # different comment; do not promote these or apply Weibo semantics elsewhere.
    if code == "wb" and str(parent) == str(comment.get("comment_id")):
        return None
    return None if parent in {None, "", "0", 0} else parent


async def collect_weibo(cookie, post_id, limit, callback):
    """Reuse upstream authenticated mobile client, pagination and store callback.

    Discovery already read and validated this post. No desktop homepage, profile,
    CDP session or unrelated detail/media download is needed to collect comments.
    """
    from playwright.async_api import async_playwright
    from media_platform.weibo.core import WeiboCrawler
    from media_platform.weibo.login import WeiboLogin
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            context = await browser.new_context()
            page = await context.new_page()
            await WeiboLogin(login_type="cookie", browser_context=context,
                            context_page=page, cookie_str=cookie).begin()
            crawler = WeiboCrawler()
            crawler.browser_context, crawler.context_page = context, page
            client = await crawler.create_weibo_client(httpx_proxy=None)
            if not await client.pong():
                raise ValueError("weibo_session_unavailable")
            await client.get_note_all_comments(post_id, crawl_interval=1.0,
                                               callback=callback, max_count=limit)
        finally:
            await browser.close()


async def run():
    sys.path.insert(0, os.getcwd())
    import config
    code = os.environ["EVENTLENS_MC_CODE"]
    limit = int(os.environ["EVENTLENS_MC_LIMIT"])
    url, post_id = os.environ["EVENTLENS_MC_URL"], os.environ["EVENTLENS_MC_ID"]
    factories = {"xhs": ("xhs", "XhsStoreFactory"), "dy": ("douyin", "DouyinStoreFactory"),
                 "ks": ("kuaishou", "KuaishouStoreFactory"), "bili": ("bilibili", "BiliStoreFactory"),
                 "wb": ("weibo", "WeibostoreFactory"), "tieba": ("tieba", "TieBaStoreFactory")}
    config.COOKIES = os.environ[f"MEDIACRAWLER_COOKIES_{code.upper()}"]
    config.HEADLESS = True
    config.ENABLE_CDP_MODE = False
    config.SAVE_LOGIN_STATE = False
    config.ENABLE_IP_PROXY = False
    config.ENABLE_GET_SUB_COMMENTS = False
    config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES = limit
    config.MAX_CONCURRENCY_NUM = 1
    config.CRAWLER_MAX_NOTES_COUNT = 1
    # Disable media downloads and ancillary word-cloud generation.
    config.ENABLE_GET_IMAGES = False
    config.ENABLE_GET_MEDIA = False
    config.ENABLE_GET_WORDCLOUD = False
    destination = Path(os.environ["EVENTLENS_MC_OUTPUT"])

    class Sink:
        def __init__(self):
            self.rank = 0
            self.count = 0
            self.seen = set()

        async def store_content(self, *args, **kwargs):
            pass

        async def store_comment(self, comment_item):
            parent = root_parent(code, comment_item)
            if parent is not None:
                return
            self.rank += 1
            identifier = str(comment_item.get("comment_id") or "")
            if not identifier or identifier in self.seen or not str(comment_item.get("content") or "").strip():
                return
            self.seen.add(identifier)
            fields = {k: comment_item.get(k) for k in ("comment_id", "content", "create_time", "publish_time",
                       "parent_comment_id", "like_count", "comment_like_count")}
            fields["parent_comment_id"] = parent
            # Bili's DEFAULT is documented in upstream field.py as popularity. We do not claim
            # a platform-frontend ranking. All other modes are kept unknown conservatively.
            mode = "unknown"
            if code == "bili":
                from media_platform.bilibili.field import CommentOrderType
                if CommentOrderType.DEFAULT.value == 0:
                    mode = "hot"
            fields.update(_source_rank=self.rank, _sort_mode=mode)
            with destination.open("a") as file:
                file.write(json.dumps(fields, ensure_ascii=False) + "\n")
            self.count += 1
            if self.count >= limit:
                raise EnoughComments()

    module, name = factories[code]
    factory = getattr(importlib.import_module("store." + module), name)
    sink = Sink()
    factory.create_store = staticmethod(lambda: sink)
    if code == "wb":
        try:
            await collect_weibo(config.COOKIES, post_id, limit,
                                importlib.import_module("store.weibo").batch_update_weibo_note_comments)
        except EnoughComments:
            pass
        return
    if code == "xhs":
        from xhs_context import xhs_client
        try:
            async with xhs_client(config.COOKIES, url) as (client, info):
                if info.note_id != post_id:
                    raise ValueError("Post identity mismatch")
                await client.get_note_all_comments(info.note_id, info.xsec_token, crawl_interval=1.0,
                    callback=importlib.import_module("store.xhs").batch_update_xhs_note_comments, max_count=limit)
        except EnoughComments:
            pass
        return
    # Use real, verified CLI flags; keep credentials out of argv.
    specified = url if code == "xhs" else post_id
    sys.argv = ["main.py", "--platform", code, "--lt", "cookie", "--type", "detail",
                "--specified_id", specified, "--get_comment", "yes", "--get_sub_comment", "no",
                "--save_data_option", "jsonl"]
    upstream = importlib.import_module("main")
    try:
        await upstream.main()
    except EnoughComments:
        pass
    finally:
        await upstream.async_cleanup()


if __name__ == "__main__":
    asyncio.run(run())
