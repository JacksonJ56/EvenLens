"""Shared authorized upstream client for native text reading and bounded comments.

Imported only by MediaCrawler's Python. Never launches login, proxies, CDP or media work.
"""
from contextlib import asynccontextmanager


@asynccontextmanager
async def xhs_client(cookie, url):
    import config
    from playwright.async_api import async_playwright
    from media_platform.xhs.core import XiaoHongShuCrawler
    from media_platform.xhs.help import parse_note_info_from_note_url
    config.ENABLE_IP_PROXY = False
    config.ENABLE_GET_SUB_COMMENTS = False
    config.XHS_INTERNATIONAL = False
    info = parse_note_info_from_note_url(url)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            context = await browser.new_context()
            await context.add_cookies([{'name': part.strip().split('=', 1)[0],
                'value': part.strip().split('=', 1)[1], 'domain': '.xiaohongshu.com', 'path': '/'}
                for part in cookie.split(';') if '=' in part])
            page = await context.new_page()
            await page.goto('https://www.xiaohongshu.com/', wait_until='domcontentloaded', timeout=18000)
            crawler = XiaoHongShuCrawler()
            crawler.browser_context, crawler.context_page = context, page
            client = await crawler.create_xhs_client(httpx_proxy=None)
            yield client, info
        finally:
            await browser.close()
