"""Private bounded login/check worker. Invoked only with the independent crawler Python.

No model/search/crawler work. Only an explicit login action opens a headed browser.
A private result file carries verified cookies back; stdout/stderr are discarded.
"""
import asyncio
import importlib
import json
import logging
import os
from pathlib import Path
import sys

from session_protocol import PROFILES, cookie_header, cookie_pairs, official_page


async def verify(platform, context, page):
    profile = PROFILES[platform]
    if platform in {"weibo", "bilibili"}:
        url = "https://m.weibo.cn/api/config" if platform == "weibo" else "https://api.bilibili.com/x/web-interface/nav"
        response = await context.request.get(url, timeout=12000)
        if response.status == 401:
            return "expired"
        if response.status != 200:
            return "unverified"
        body = await response.json()
        data = body.get("data", {})
        key = "login" if platform == "weibo" else "isLogin"
        if data.get(key) is True:
            return "verified"
        return "expired" if data.get(key) is False else "unverified"
    if not official_page(platform, page.url):
        return "unverified"
    if platform in {"douyin", "tieba"}:
        # Upstream pong() only tests cookies/localStorage here, not server validity.
        # Keep these honestly unverified until a reliable remote checker is available.
        return "unverified"
    modules = {
        "xiaohongshu": ("xhs", "XiaoHongShuCrawler", "create_xhs_client"),
        "kuaishou": ("kuaishou", "KuaishouCrawler", "create_ks_client"),
    }
    module, cls, factory = modules[platform]
    crawler = getattr(importlib.import_module(f"media_platform.{module}.core"), cls)()
    crawler.browser_context, crawler.context_page = context, page
    client = await getattr(crawler, factory)(httpx_proxy=None)
    if platform == "xiaohongshu":
        body = await client.query_self()
        return "verified" if body and body.get("data", {}).get("result", {}).get("success") is True else "unverified"
    return "verified" if await client.pong() else "unverified"


def result(status, platform, cookie=""):
    path = Path(os.environ["EVENTLENS_SESSION_RESULT"])
    body = {"status": status}
    if status == "verified" and cookie:
        body["cookie"] = cookie
    path.write_text(json.dumps(body))
    path.chmod(0o600)


async def main():
    logging.disable(logging.CRITICAL)
    sys.path.insert(0, os.getcwd())
    import config
    config.ENABLE_IP_PROXY = False
    config.XHS_INTERNATIONAL = False
    platform, mode = os.environ["EVENTLENS_SESSION_PLATFORM"], os.environ["EVENTLENS_SESSION_MODE"]
    profile = PROFILES[platform]
    from playwright.async_api import async_playwright
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=mode == "check")
        try:
            context = await browser.new_context(locale="zh-CN", viewport={"width": 1100, "height": 780})
            page = await context.new_page()
            if mode == "check":
                raw = os.environ.get(f"MEDIACRAWLER_COOKIES_{profile['code'].upper()}", "")
                await context.add_cookies([{"name": name, "value": value, "domain": "." + profile["domains"][0], "path": "/"} for name, value in cookie_pairs(raw).items()])
                if platform not in {"weibo", "bilibili"}:
                    await page.goto(profile["home"], wait_until="domcontentloaded", timeout=18000)
                async with asyncio.timeout(20):
                    status = await verify(platform, context, page)
                result(status, platform)
                return
            # Official pages handle all passwords, QR codes and human verification personally.
            # Weibo's existing helper opens the mobile-compatible official QR flow.
            if platform == "weibo":
                from media_platform.weibo.login import WeiboLogin
                from tools import utils
                utils.show_qrcode = lambda _image: None
                await WeiboLogin(login_type="qrcode", browser_context=context, context_page=page).begin()
                await page.goto(profile["home"], wait_until="domcontentloaded", timeout=18000)
            else:
                await page.goto(profile["login"], wait_until="domcontentloaded", timeout=20000)
            signal = Path(os.environ["EVENTLENS_SESSION_CONFIRM"])
            while not signal.exists():
                if page.is_closed():
                    result("cancelled", platform)
                    return
                await asyncio.sleep(.5)
            # The user explicitly asks for verification after finishing in the native window.
            if not official_page(platform, page.url):
                await page.goto(profile["home"], wait_until="domcontentloaded", timeout=18000)
            async with asyncio.timeout(20):
                status = await verify(platform, context, page)
            cookie = cookie_header(platform, await context.cookies())
            result(status if cookie else "unverified", platform, cookie)
        finally:
            await browser.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        result("cancelled", os.environ["EVENTLENS_SESSION_PLATFORM"])
    except Exception:
        # No raw exception, URL, QR token, cookie or browser logs cross the process boundary.
        result("error", os.environ["EVENTLENS_SESSION_PLATFORM"])
