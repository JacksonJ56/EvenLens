"""Isolated session coordinator/API tests: no real login, browsing or secrets."""
import asyncio
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI, HTTPException

from app.public_opinion.session_api import router
from app.public_opinion.session_protocol import PROFILES, cookie_header, official_page
from app.public_opinion.sessions import PlatformSessions
from app.public_opinion.settings import OpinionSettings
from dotenv import dotenv_values


class SessionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'main.py').touch()
        self.env = self.root / '.env'
        self.env.write_text('DEEPSEEK_API_KEY=TEST-DO-NOT-FORWARD\nMEDIACRAWLER_COOKIES_WB=SUB=test\n')
        self.environ = patch.dict(os.environ, {**{'MEDIACRAWLER_COOKIES_' + p['code'].upper(): '' for p in PROFILES.values()}, 'DEEPSEEK_API_KEY': 'TEST-DO-NOT-FORWARD'})
        self.environ.start()
        self.settings = OpinionSettings('sqlite:///:memory:', crawler_home=str(self.root), crawler_python=sys.executable, crawler_authorized=True)
        self.manager = PlatformSessions(self.settings, self.env)

    async def asyncTearDown(self):
        await self.manager.close()
        self.environ.stop()
        self.tmp.cleanup()

    def process(self, body, sent):
        async def spawn(*args, **kwargs):
            env = kwargs['env'];sent.append(env)
            Path(env['EVENTLENS_SESSION_RESULT']).write_text(json.dumps(body))
            return SimpleNamespace(returncode=0, wait=AsyncMock(return_value=0))
        return spawn

    async def finish(self):
        await asyncio.gather(*list(self.manager.jobs.values()))

    def test_missing_cookie_is_not_a_task_failure(self):
        state = self.manager.status('xiaohongshu')
        self.assertEqual(state['status'], 'not_logged_in')
        self.assertTrue(state['login_available'])
        self.assertFalse(state['collector_ready'])
        self.assertNotIn('cookie', state)

    async def test_removed_platforms_have_no_login_or_check_operation(self):
        for platform in ['zhihu','douyin']:
            with self.assertRaises(HTTPException) as error:
                self.manager.status(platform)
            self.assertEqual(error.exception.status_code,422)
            with patch('asyncio.create_subprocess_exec') as spawn:
                for mode in ['login','check']:
                    with self.assertRaises(HTTPException) as error:
                        await self.manager.start(platform,mode)
                    self.assertEqual(error.exception.status_code,422)
                spawn.assert_not_called()

    def test_configured_cookie_is_not_verified(self):
        state = self.manager.status('weibo')
        self.assertEqual(state['status'], 'unverified')
        self.assertTrue(state['configured'])
        self.assertFalse(state['session_verified'])

    async def test_missing_session_check_never_starts_browser(self):
        with patch('asyncio.create_subprocess_exec') as spawn:
            result = await self.manager.start('xiaohongshu', 'check')
            self.assertEqual(result['status'], 'not_logged_in')
            spawn.assert_not_called()

    async def test_verified_check_has_ttl_and_no_key_forwarding(self):
        sent = []
        with patch('asyncio.create_subprocess_exec', new=self.process({'status': 'verified'}, sent)):
            state = await self.manager.start('weibo', 'check')
            self.assertEqual(state['status'], 'checking')
            await self.finish()
        state = self.manager.status('weibo')
        self.assertTrue(state['collector_ready'])
        self.assertNotIn('DEEPSEEK_API_KEY', sent[0])
        self.assertIn('MEDIACRAWLER_COOKIES_WB', sent[0])
        self.assertNotIn('MEDIACRAWLER_COOKIES_XHS', sent[0])
        self.manager.states['weibo']['valid_until'] = time.monotonic() - 1
        self.assertFalse(self.manager.status('weibo')['collector_ready'])

    async def test_login_saves_only_verified_cookie_atomically(self):
        with patch('asyncio.create_subprocess_exec', new=self.process({'status': 'verified', 'cookie': 'web_session=TEST-XHS'}, [])):
            await self.manager.start('xiaohongshu', 'login');await self.finish()
        self.assertTrue(self.manager.status('xiaohongshu')['collector_ready'])
        values = dotenv_values(self.env)
        self.assertEqual(values['MEDIACRAWLER_COOKIES_XHS'], 'web_session=TEST-XHS')
        self.assertEqual(values['DEEPSEEK_API_KEY'], 'TEST-DO-NOT-FORWARD')
        self.assertEqual(values['MEDIACRAWLER_COOKIES_WB'], 'SUB=test')
        self.assertEqual(self.env.stat().st_mode & 0o777, 0o600)
        self.assertEqual(os.environ['MEDIACRAWLER_COOKIES_XHS'], 'web_session=TEST-XHS')

    async def test_unverified_error_and_expiry_do_not_save_cookie(self):
        for status in ['unverified', 'error', 'expired']:
            with patch('asyncio.create_subprocess_exec', new=self.process({'status': status, 'cookie': 'web_session=UNVERIFIED'}, [])):
                await self.manager.start('xiaohongshu', 'login');await self.finish()
            self.assertFalse(self.manager.status('xiaohongshu')['collector_ready'])
            self.assertEqual(self.manager.status('xiaohongshu')['status'], status)
            self.assertNotIn('MEDIACRAWLER_COOKIES_XHS', dotenv_values(self.env))

    async def test_cookie_change_invalidates_previously_verified_state(self):
        with patch('asyncio.create_subprocess_exec', new=self.process({'status': 'verified'}, [])):
            await self.manager.start('weibo', 'check');await self.finish()
        self.env.write_text('MEDIACRAWLER_COOKIES_WB=SUB=changed\n')
        self.assertFalse(self.manager.status('weibo')['session_verified'])

    async def test_network_error_is_not_called_expired(self):
        with patch('asyncio.create_subprocess_exec', new=self.process({'status': 'error'}, [])):
            await self.manager.start('weibo', 'check');await self.finish()
        self.assertEqual(self.manager.status('weibo')['status'], 'error')
        self.assertNotIn('过期', self.manager.status('weibo')['message'])

    async def test_execution_requires_current_verified_session(self):
        with self.assertRaises(HTTPException) as error:
            await self.manager.require_verified('weibo')
        self.assertEqual(error.exception.status_code, 409)
        with patch('asyncio.create_subprocess_exec', new=self.process({'status': 'verified'}, [])):
            await self.manager.start('weibo', 'check');await self.finish()
        await self.manager.require_verified('weibo')
        with self.assertRaises(HTTPException):
            await self.manager.require_verified('xiaohongshu')

    async def test_tieba_login_enabled_but_needs_server_confirmation(self):
        state=self.manager.status('tieba')
        self.assertTrue(state['remote_verification_supported'])
        self.assertTrue(state['login_available'])
        self.assertFalse(state['session_verified'])
        self.assertFalse(state['collector_ready'])

    async def test_dedup_confirm_and_cancel_release_worker(self):
        entered, exit_event = asyncio.Event(), asyncio.Event()
        process = SimpleNamespace(returncode=None, pid=123456)
        async def wait():
            entered.set();await exit_event.wait();return process.returncode
        process.wait = wait
        async def spawn(*args, **kwargs): return process
        def stop(*args): process.returncode = -15;exit_event.set()
        with patch('asyncio.create_subprocess_exec', new=spawn), patch('os.killpg', side_effect=stop):
            first = await self.manager.start('weibo', 'login')
            await entered.wait()
            second = await self.manager.start('weibo', 'login')
            self.assertEqual(first['job_id'], second['job_id'])
            self.manager.confirm('weibo')
            self.assertTrue(self.manager.confirmations['weibo'].exists())
            self.assertEqual(self.manager.status('weibo')['status'], 'checking')
            with self.assertRaises(HTTPException):
                await self.manager.start('xiaohongshu', 'login')
            await self.manager.cancel('weibo')
        self.assertFalse(self.manager.jobs)
        self.assertEqual(self.manager.status('weibo')['status'], 'cancelled')
        self.assertEqual(dotenv_values(self.env)['MEDIACRAWLER_COOKIES_WB'], 'SUB=test')

    async def test_local_action_and_api_reject_remote_and_missing_header(self):
        app = FastAPI();app.include_router(router);app.state.opinion_sessions = self.manager
        transport = httpx.ASGITransport(app=app, client=('127.0.0.1', 9000))
        async with httpx.AsyncClient(transport=transport, base_url='http://127.0.0.1:8000') as client:
            path = '/api/public-opinion/sessions/xiaohongshu'
            self.assertEqual((await client.get(path)).json()['status'], 'not_logged_in')
            self.assertEqual((await client.post(path + '/login')).status_code, 403)
            headers = {'X-EventLens-Local-Action': '1', 'Origin': 'https://evil.example'}
            self.assertEqual((await client.post(path + '/login', headers=headers)).status_code, 403)
            headers = {'X-EventLens-Local-Action': '1'}
            self.assertEqual((await client.post(path + '/check', headers=headers)).status_code, 202)
            self.assertEqual((await client.get('/api/public-opinion/sessions/ithome')).status_code, 422)

    def test_cookie_and_host_allowlist(self):
        value = cookie_header('xiaohongshu', [{'domain': '.xiaohongshu.com', 'name': 'web_session', 'value': 'TEST'},
            {'domain': 'xiaohongshu.com.evil.org', 'name': 'bad', 'value': 'bad'},
            {'domain': '.xiaohongshu.com', 'name': 'bad', 'value': 'bad\r\nvalue'}])
        self.assertEqual(value, 'web_session=TEST')
        self.assertTrue(official_page('xiaohongshu', 'https://www.xiaohongshu.com/explore'))
        self.assertFalse(official_page('xiaohongshu', 'https://xiaohongshu.com.evil.org/'))


class WorkerVerificationTests(unittest.IsolatedAsyncioTestCase):
    async def test_weibo_requires_remote_explicit_login(self):
        # Worker imports only stdlib at module level; no MediaCrawler dependency in backend tests.
        import app.public_opinion.session_protocol as protocol
        with patch.dict(sys.modules, {'session_protocol': protocol}):
            path = Path(__file__).parents[1] / 'app/public_opinion/session_worker.py'
            spec = importlib.util.spec_from_file_location('test_session_worker', path)
            worker = importlib.util.module_from_spec(spec);spec.loader.exec_module(worker)
        for body, expected in [({'data': {'login': True}}, 'verified'), ({'data': {'login': False}}, 'expired'), ({'data': {}}, 'unverified')]:
            response = SimpleNamespace(status=200, json=AsyncMock(return_value=body))
            context = SimpleNamespace(request=SimpleNamespace(get=AsyncMock(return_value=response)))
            self.assertEqual(await worker.verify('weibo', context, None), expected)
