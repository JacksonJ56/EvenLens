"""Interactive login only; never run the crawler's search/detail workflow.

Run using MediaCrawler's interpreter. The account owner completes login personally.
Only the selected platform's session is saved locally, never printed or sent elsewhere.
"""
import argparse
import asyncio
import contextlib
import logging
import os
from pathlib import Path
import re
import sys

from dotenv import dotenv_values, set_key


def mobile_cookie_header(cookies: list[dict]) -> str:
    values = {}
    for cookie in cookies:
        if cookie.get("domain", "").lstrip(".").lower() not in {"weibo.cn", "m.weibo.cn"}:
            continue
        name, value = cookie.get("name", ""), cookie.get("value", "")
        if not re.fullmatch(r"[!#$%&'*+\-.^_`|~0-9A-Za-z]+", name) or re.search(r"[\r\n;]", value):
            continue
        values[name] = value
    return "; ".join(f"{key}={value}" for key, value in values.items())


def save_session(env_file: Path, cookie: str):
    if not cookie:
        raise ValueError("未取得有效的微博移动端会话")
    set_key(env_file, "MEDIACRAWLER_COOKIES_WB", cookie, quote_mode="always")
    os.chmod(env_file, 0o600)


async def login(env_file: Path, timeout: int):
    config_values = dotenv_values(env_file)
    home = Path(config_values.get("MEDIACRAWLER_HOME") or "")
    if not (home / "main.py").is_file():
        raise ValueError("请先配置已安装的 MEDIACRAWLER_HOME")
    sys.path.insert(0, str(home))
    # Do not forward EventLens keys to any browser or model; no LLM is used here.
    os.environ.pop("DEBUG", None)
    logging.disable(logging.CRITICAL)
    from playwright.async_api import async_playwright
    from media_platform.weibo.login import WeiboLogin
    from tools import utils

    output = sys.stdout

    def ready(_image):
        # The QR is already on the headed official login page. Do not log the image or token.
        print("微博登录二维码已就绪，请在 Chrome for Testing 窗口使用手机微博扫码并确认。", file=output, flush=True)

    utils.show_qrcode = ready
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=False)
        try:
            context = await browser.new_context(locale="zh-CN", viewport={"width": 1100, "height": 780})
            page = await context.new_page()
            page.set_default_timeout(30000)
            login_helper = WeiboLogin(login_type="qrcode", browser_context=context, context_page=page)
            print("正在打开独立的微博官方登录窗口；此操作不会开始采集。", flush=True)
            try:
                with open(os.devnull, "w") as discarded, contextlib.redirect_stdout(discarded), contextlib.redirect_stderr(discarded):
                    async with asyncio.timeout(timeout):
                        await login_helper.begin()
            except SystemExit:
                raise ValueError("微博扫码入口未能自动识别，请检查登录页面或平台访问限制") from None

            # Upstream's changed-cookie check alone is not proof of login. Verify the actual
            # mobile API session before writing any cookie to EventLens.
            print("正在验证微博移动端登录状态……", flush=True)
            await page.goto("https://m.weibo.cn/", wait_until="domcontentloaded", timeout=30000)
            for attempt in range(10):
                response = await context.request.get("https://m.weibo.cn/api/config", timeout=10000)
                if response.status == 200:
                    data = await response.json()
                    if isinstance(data, dict) and isinstance(data.get("data"), dict) and data["data"].get("login") is True:
                        cookies = await context.cookies(["https://m.weibo.cn/"])
                        save_session(env_file, mobile_cookie_header(cookies))
                        print("微博登录验证成功，会话已保存到本机 backend/.env（不输出凭据）。", flush=True)
                        return
                await asyncio.sleep(2)
            raise ValueError("未确认有效的微博移动端登录；未保存会话。可能需要重新登录或检查访问限制。")
        finally:
            await browser.close()


def main():
    parser = argparse.ArgumentParser(description="EventLens 平台登录配置，不采集数据")
    parser.add_argument("--platform", choices=["weibo"], required=True)
    parser.add_argument("--confirm-authorized", action="store_true", required=True,
                        help="仅在确认非商业学习研究用途与数据访问权限后使用")
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()
    if not 30 <= args.timeout <= 600:
        parser.error("登录等待时间须为 30–600 秒")
    env_file = Path(__file__).resolve().parents[1] / ".env"
    if not env_file.is_file():
        parser.error("backend/.env 不存在")
    set_key(env_file, "MEDIACRAWLER_AUTHORIZED", "true", quote_mode="never")
    try:
        asyncio.run(login(env_file, args.timeout))
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("登录已取消，未确认的会话不会保存。", flush=True)
        return 1
    except ValueError as error:
        print(str(error), flush=True)
        return 1
    except Exception as error:
        # Browser errors may contain login URLs/tokens; never print the raw exception.
        print(f"登录未完成（{type(error).__name__}）；未验证的会话不会保存。", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
