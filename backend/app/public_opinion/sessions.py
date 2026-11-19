"""Local single-process session coordinator; never exposes credentials to the browser."""
import asyncio
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import signal
import tempfile
import time
from urllib.parse import urlsplit
from uuid import uuid4

from dotenv import dotenv_values, set_key
from fastapi import HTTPException, Request

from .collector import worker_environment
from .session_protocol import PROFILES

ACTIVE = {"checking", "logging_in"}
MESSAGES = {
    "not_logged_in": "尚未登录该平台，请先登录，或导入已有授权评论。",
    "unverified": "尚未确认会话有效，请重新检查；无法验证时可导入授权评论。",
    "checking": "正在验证平台会话，不会开始采集或调用 AI。",
    "logging_in": "已启动本机独立登录窗口。请本人完成登录，再点击「完成登录并验证」。",
    "verified": "平台会话已验证，可执行在线评论采集；具体帖子仍可能有访问限制。",
    "expired": "平台返回未登录状态，请重新登录。",
    "error": "会话检查未完成，可能是网络、平台访问限制或浏览器环境问题；请重试。",
    "cancelled": "登录或验证已取消，可重新开始。",
    "unavailable": "采集环境尚未配置。",
}


def local_action(request: Request):
    # A web page on another origin must not be able to launch local login browsers.
    host = urlsplit('http://' + request.headers.get('host', '')).hostname
    peer = request.client.host if request.client else ''
    try:
        local_peer = ipaddress.ip_address(peer).is_loopback
    except ValueError:
        local_peer = peer == 'testclient'
    origin = request.headers.get('origin')
    if (host not in {'127.0.0.1', 'localhost', '::1'} or not local_peer or
            request.headers.get('x-eventlens-local-action') != '1' or
            origin and urlsplit(origin).hostname not in {'127.0.0.1', 'localhost', '::1'}):
        raise HTTPException(403, '平台登录仅允许从本机 EventLens 页面发起')


class PlatformSessions:
    def __init__(self, settings, env_file=None):
        self.settings = settings
        self.env_file = Path(env_file or Path(__file__).resolve().parents[2] / '.env')
        self.states, self.jobs, self.confirmations = {}, {}, {}
        self.lock = asyncio.Lock()
        self.closed = False

    def cookie(self, platform):
        key = 'MEDIACRAWLER_COOKIES_' + PROFILES[platform]['code'].upper()
        values = dotenv_values(self.env_file) if self.env_file.is_file() else {}
        value = values.get(key, os.getenv(key, '')) or ''
        # Refresh only this platform; do not reload or forward unrelated API keys.
        os.environ[key] = value
        return value

    def status(self, platform):
        if platform not in PROFILES:
            raise HTTPException(422, '当前平台暂不支持公众舆情分析')
        cookie = self.cookie(platform)
        fingerprint = hashlib.sha256(cookie.encode()).hexdigest()
        saved = self.states.get(platform, {})
        active = platform in self.jobs
        ready, reason = self.settings.collector_status(platform)
        if saved.get('fingerprint') != fingerprint and not active:
            saved = {}
        state = saved.get('status', 'unverified' if cookie else 'not_logged_in')
        if not cookie and not active and state not in {'error', 'cancelled', 'expired', 'unverified'}:
            state = 'not_logged_in'
        if state == 'verified' and saved.get('valid_until', 0) <= time.monotonic():
            state = 'unverified'
        # Missing session is different from missing runtime/authorization.
        runtime = ready or (bool(cookie) is False and 'Cookie' in reason)
        if not runtime and not active:
            state = 'unavailable'
        remote_supported = platform not in {'douyin', 'tieba'}
        message = MESSAGES[state]
        if state == 'unavailable':
            message = reason
        elif state in {'unverified', 'not_logged_in'} and not remote_supported:
            message = '当前上游适配器仅提供 Cookie/本地标记检查，尚无法可靠确认服务器登录有效；请使用授权评论导入。'
        return {'platform_id': platform, 'status': state, 'message': message,
                'configured': bool(cookie), 'session_verified': state == 'verified',
                'collector_ready': ready and state == 'verified', 'runtime_ready': runtime,
                'login_available': runtime and remote_supported, 'remote_verification_supported': remote_supported,
                'job_id': saved.get('job_id'), 'checked_at': saved.get('checked_at')}

    async def start(self, platform, mode):
        current = self.status(platform)
        if self.closed:
            raise HTTPException(503, '会话服务正在关闭')
        if platform in self.jobs:
            return current
        if not current['runtime_ready']:
            raise HTTPException(503, current['message'])
        if mode == 'login' and not current['login_available']:
            raise HTTPException(503, current['message'])
        if mode == 'check' and not current['configured']:
            return current
        if mode == 'login' and any(self.states[p].get('mode') == 'login' for p in self.jobs):
            raise HTTPException(409, '已有其他平台正在登录，请先完成或取消该登录')
        if len(self.jobs) >= 2:
            raise HTTPException(429, '已有会话操作正在进行，请稍后重试')
        self.states[platform] = {'status': 'checking' if mode == 'check' else 'logging_in', 'job_id': uuid4().hex,
                                'mode': mode,
                                'fingerprint': hashlib.sha256(self.cookie(platform).encode()).hexdigest()}
        self.jobs[platform] = asyncio.create_task(self.run(platform, mode))
        return self.status(platform)

    async def run(self, platform, mode):
        process = None
        try:
            # Checks launch headless Chromium; login launches a headed browser only on explicit action.
            with tempfile.TemporaryDirectory(prefix='eventlens-session-') as directory:
                output, confirm = Path(directory) / 'result.json', Path(directory) / 'confirm'
                self.confirmations[platform] = confirm
                code = PROFILES[platform]['code'].upper()
                env = {**worker_environment(), 'EVENTLENS_SESSION_PLATFORM': platform,
                       'EVENTLENS_SESSION_MODE': mode, 'EVENTLENS_SESSION_RESULT': str(output),
                       'EVENTLENS_SESSION_CONFIRM': str(confirm), f'MEDIACRAWLER_COOKIES_{code}': self.cookie(platform)}
                process = await asyncio.create_subprocess_exec(self.settings.crawler_python,
                    str(Path(__file__).with_name('session_worker.py')), cwd=self.settings.crawler_home,
                    env=env, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL, start_new_session=True)
                async with asyncio.timeout(330 if mode == 'login' else 45):
                    await process.wait()
                state = 'error'
                if process.returncode == 0 and output.is_file() and output.stat().st_size < 131072:
                    data = json.loads(output.read_text())
                    state = data.get('status', 'error')
                    if state not in {'verified', 'expired', 'unverified', 'cancelled', 'error'}:
                        state = 'error'
                    if mode == 'login' and state == 'verified':
                        cookie = data.get('cookie')
                        if not isinstance(cookie, str) or not cookie or '\n' in cookie or '\r' in cookie:
                            state = 'error'
                        else:
                            await self.save(platform, cookie)
                from datetime import datetime, timezone
                self.states[platform].update(status=state, checked_at=datetime.now(timezone.utc).isoformat(),
                    valid_until=time.monotonic() + 300 if state == 'verified' else 0,
                    fingerprint=hashlib.sha256(self.cookie(platform).encode()).hexdigest())
        except asyncio.CancelledError:
            self.states[platform].update(status='cancelled', valid_until=0)
        except Exception:
            # Browser/HTTP exceptions may contain cookies or login URLs. Never expose them.
            self.states[platform].update(status='error', valid_until=0)
        finally:
            if process and process.returncode is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                    await asyncio.wait_for(process.wait(), 3)
                except TimeoutError:
                    os.killpg(process.pid, signal.SIGKILL)
                    await process.wait()
                except ProcessLookupError:
                    pass
            self.confirmations.pop(platform, None)
            self.jobs.pop(platform, None)

    async def save(self, platform, cookie):
        # Atomic replacement under a process-wide lock; retain every unrelated .env setting.
        async with self.lock:
            self.env_file.parent.mkdir(parents=True, exist_ok=True)
            key = 'MEDIACRAWLER_COOKIES_' + PROFILES[platform]['code'].upper()
            path = None
            try:
                with tempfile.NamedTemporaryFile(mode='w', dir=self.env_file.parent, delete=False, prefix='.session-', suffix='.env') as file:
                    path = Path(file.name)
                    file.write(self.env_file.read_text() if self.env_file.exists() else '')
                path.chmod(0o600)
                set_key(path, key, cookie, quote_mode='always')
                path.replace(self.env_file)
                os.environ[key] = cookie
            finally:
                if path:
                    path.unlink(missing_ok=True)

    def confirm(self, platform):
        current = self.status(platform)
        path = self.confirmations.get(platform)
        if current['status'] != 'logging_in' or path is None:
            raise HTTPException(409, '当前没有等待确认的登录窗口')
        path.touch(mode=0o600)
        self.states[platform]['status'] = 'checking'
        return self.status(platform)

    async def cancel(self, platform):
        self.status(platform)
        job = self.jobs.get(platform)
        if job:
            job.cancel()
            await asyncio.gather(job, return_exceptions=True)
        return self.status(platform)

    async def require_verified(self, platform):
        current = self.status(platform)
        if not current['session_verified']:
            raise HTTPException(409, current['message'])
        return current

    async def close(self):
        self.closed = True
        for job in list(self.jobs.values()):
            job.cancel()
        await asyncio.gather(*list(self.jobs.values()), return_exceptions=True)
