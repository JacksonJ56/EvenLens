"""Optional authenticated platform reader, separate from third-party public Fetch.

Only same-platform candidate URLs are accepted. Cookies stay in the local worker.
A real native post ID and nonempty description are mandatory, even for short posts.
"""
import asyncio
from dataclasses import dataclass
import json
import os
from pathlib import Path
import signal
import tempfile

from ..event_trace.clients import public_url
from .collector import identify_post, normalized_time, worker_environment
from .tieba_protocol import topic_url


class PostReadError(ValueError):
    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class AuthenticatedPage:
    post_id: str
    title: str
    content: str
    published_at: str | None = None


class AuthenticatedPostReader:
    def __init__(self, settings):
        self.settings = settings

    def available(self, platform):
        return platform in {'xiaohongshu','tieba'} and self.settings.collector_status(platform)[0]

    async def read(self, platform, url, *, topic=False):
        if not self.available(platform):
            raise PostReadError('本机平台阅读未配置有效授权与会话')
        url = public_url(url)
        expected = identify_post(platform, url)
        if not expected and not (topic and platform=='tieba' and topic_url(url)):
            raise PostReadError('仅允许读取当前平台的真实候选帖子链接')
        process = None
        with tempfile.TemporaryDirectory(prefix='eventlens-post-read-') as work:
            output = Path(work) / 'post.json'
            code='TIEBA' if platform=='tieba' else 'XHS'
            env = {**worker_environment(), f'MEDIACRAWLER_COOKIES_{code}': os.environ[f'MEDIACRAWLER_COOKIES_{code}'],
                   'EVENTLENS_POST_PLATFORM':platform,'EVENTLENS_POST_ACTION':'topic' if topic else 'read',
                   'EVENTLENS_POST_URL': url, 'EVENTLENS_POST_OUTPUT': str(output)}
            try:
                process = await asyncio.create_subprocess_exec(self.settings.crawler_python,
                    str(Path(__file__).with_name('post_read_worker.py')), cwd=self.settings.crawler_home,
                    env=env, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL, start_new_session=True)
                async with asyncio.timeout(min(30, self.settings.collector_timeout)):
                    await process.wait()
                if process.returncode or not output.exists() or output.stat().st_size > 100000:
                    raise PostReadError('本机平台阅读未完成，请检查独立浏览器环境')
                data = json.loads(output.read_text())
                messages = {'restricted': '平台拒绝访问或要求安全验证；已停止读取，不绕过限制',
                            'not_found': '平台返回帖子不存在、已删除或当前不可用',
                            'no_text': '帖子没有可读取的文字正文，不能仅用标题冒充正文',
                            'identity_mismatch': '返回帖子 ID 与候选链接不一致，未采用内容'}
                if data.get('status') != 'ok':
                    raise PostReadError(messages.get(data.get('status'), '本机平台读取失败，无法确认正文'), data.get('status'))
                if topic:
                    return [item for item in data.get('items',[])[:20] if isinstance(item,dict)
                            and identify_post(platform,item.get('url',''))==item.get('post_id')]
                if data.get('post_id') != expected or not isinstance(data.get('content'), str) or not data['content'].strip():
                    raise PostReadError('本机平台返回的帖子身份或正文无效')
                date = normalized_time(data.get('published_at'))
                return AuthenticatedPage(expected, str(data.get('title') or '')[:500], data['content'][:5000], date.isoformat() if date else None)
            except TimeoutError:
                raise PostReadError('本机平台正文读取超时，未获得可核验内容') from None
            except (OSError, json.JSONDecodeError):
                raise PostReadError('本机平台阅读环境或返回数据不可用') from None
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
