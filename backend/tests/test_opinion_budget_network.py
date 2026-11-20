import unittest
from dataclasses import replace

import httpx

from app.event_trace.clients import UnsafeURL
from app.public_opinion.llm import Budget, BudgetExceeded
from app.public_opinion.network import PublicDNSResolver
from app.public_opinion.settings import OpinionSettings
from app.public_opinion.crawler_worker import root_parent


class WeiboRootCommentTests(unittest.TestCase):
    def test_weibo_self_root_is_top_level(self):
        self.assertIsNone(root_parent("wb", {"comment_id": "123", "parent_comment_id": 123}))

    def test_actual_reply_keeps_parent(self):
        self.assertEqual(root_parent("wb", {"comment_id": "124", "parent_comment_id": "123"}), "123")

    def test_other_platforms_are_unchanged(self):
        self.assertEqual(root_parent("bili", {"comment_id": "123", "parent_comment_id": "123"}), "123")
        for parent in [None, "", "0", 0]:
            self.assertIsNone(root_parent("wb", {"comment_id": "123", "parent_comment_id": parent}))


class BudgetSettlementTests(unittest.TestCase):
    def setUp(self):
        self.settings = replace(OpinionSettings("sqlite:///:memory:"), max_tokens=15000)

    def test_successful_calls_release_unused_estimates(self):
        budget = Budget(self.settings)
        for _ in range(4):
            ticket = budget.reserve(["x" * 6000], 2500)
            budget.settle(ticket, {"prompt_tokens": 900, "completion_tokens": 100, "total_tokens": 1000})
        self.assertEqual(budget.tokens, 4000)
        self.assertEqual(budget.reserved, 4000)
        self.assertEqual(budget.settled_calls, 4)
        self.assertEqual(budget.calls, 4)

    def test_failed_or_unreported_call_keeps_reservation(self):
        budget = Budget(self.settings)
        ticket = budget.reserve(["x" * 6000], 2500)
        upper = budget.reserved
        for usage in [{}, None, {"prompt_tokens": 500, "completion_tokens": 500, "total_tokens": 10}]:
            budget.settle(ticket, usage)
            self.assertEqual(budget.reserved, upper)
            self.assertEqual(budget.settled_calls, 0)
        with self.assertRaises(BudgetExceeded):
            budget.reserve(["x" * 6000], 2500)

    def test_actual_spend_plus_next_bound_still_enforces_limit(self):
        budget = Budget(self.settings)
        budget.tokens = budget.reserved = 12000
        with self.assertRaises(BudgetExceeded):
            budget.reserve(["x" * 1000], 2500)
        self.assertEqual(budget.calls, 0)

    def test_context_budget_is_settled_independently(self):
        budget = Budget(self.settings)
        budget.context_mode = True
        ticket = budget.reserve(["x" * 6000], 2500)
        budget.context_mode = False
        budget.settle(ticket, {"prompt_tokens": 500, "completion_tokens": 50, "total_tokens": 550})
        self.assertEqual(budget.context_reserved, 550)
        self.assertEqual(budget.reserved, 550)


class PublicDNSResolverTests(unittest.IsolatedAsyncioTestCase):
    async def check(self, addresses, *, enabled=True, answer_a="36.51.224.126", answer_aaaa="2400:89c0:3013:1::11:84", status=0):
        requests = []

        async def lookup(_host):
            return addresses

        def handler(request):
            requests.append(request)
            self.assertEqual(request.url.host, "cloudflare-dns.com")
            self.assertNotIn("authorization", request.headers)
            kind = request.url.params["type"]
            value = answer_a if kind == "A" else answer_aaaa
            return httpx.Response(200, json={"Status": status, "Answer": [] if value is None else [
                {"type": 1 if kind == "A" else 28, "data": value}]})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        self.addAsyncCleanup(client.aclose)
        return PublicDNSResolver(client, enabled=enabled, lookup_fn=lookup), requests

    async def test_normal_public_resolution_needs_no_external_dns(self):
        resolver, requests = await self.check(["36.51.224.126"])
        await resolver("https://m.weibo.cn/status/123")
        self.assertFalse(requests)

    async def test_fake_ip_requires_explicit_setting(self):
        resolver, requests = await self.check(["198.18.0.15"], enabled=False)
        with self.assertRaises(UnsafeURL):
            await resolver("https://m.weibo.cn/status/123")
        self.assertFalse(requests)

    async def test_fake_ip_verified_independently_and_cached(self):
        resolver, requests = await self.check(["198.18.0.15"])
        await resolver("https://m.weibo.cn/status/123")
        await resolver("https://m.weibo.cn/status/456")
        self.assertEqual(len(requests), 2)

    async def test_private_system_address_never_falls_back(self):
        resolver, requests = await self.check(["192.168.1.1"])
        with self.assertRaises(UnsafeURL):
            await resolver("https://m.weibo.cn/status/123")
        self.assertFalse(requests)

    async def test_private_dns_answer_is_rejected(self):
        for a, aaaa in [("127.0.0.1", None), ("36.51.224.126", "::1"), ("198.18.0.2", None)]:
            resolver, _ = await self.check(["198.18.0.15"], answer_a=a, answer_aaaa=aaaa)
            with self.assertRaises(UnsafeURL):
                await resolver("https://m.weibo.cn/status/123")

    async def test_dns_error_and_private_url_fail_closed(self):
        resolver, requests = await self.check(["198.18.0.15"], status=3)
        with self.assertRaises(UnsafeURL):
            await resolver("https://m.weibo.cn/status/123")
        count = len(requests)
        with self.assertRaises(UnsafeURL):
            await resolver("http://127.0.0.1/private")
        self.assertEqual(len(requests), count)

    async def test_transport_failure_uses_fixed_backup_and_caches(self):
        hosts = []
        async def lookup(_): return ['198.18.0.15']
        def handler(request):
            hosts.append(request.url.host)
            self.assertNotIn('authorization', request.headers)
            self.assertEqual(request.url.params['name'], 'www.xiaohongshu.com')
            if request.url.host == 'cloudflare-dns.com':
                raise httpx.ConnectError('TEST unreachable', request=request)
            return httpx.Response(200, json={'Status':0, 'Answer':
                [{'type':1,'data':'36.51.224.126'}] if request.url.params['type']=='A' else []})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            resolver = PublicDNSResolver(client,enabled=True,lookup_fn=lookup)
            await resolver('https://www.xiaohongshu.com/explore/test')
            count = len(hosts)
            await resolver('https://www.xiaohongshu.com/explore/another')
        self.assertEqual(hosts.count('cloudflare-dns.com'),2)
        self.assertEqual(hosts.count('dns.google'),2)
        self.assertEqual(len(hosts),count)

    async def test_private_answer_never_fails_over_even_if_other_query_fails(self):
        hosts = []
        async def lookup(_): return ['198.18.0.15']
        def handler(request):
            hosts.append(request.url.host)
            if request.url.params['type']=='AAAA':
                raise httpx.ReadTimeout('TEST timeout', request=request)
            return httpx.Response(200,json={'Status':0,'Answer':[{'type':1,'data':'127.0.0.1'}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            resolver=PublicDNSResolver(client,enabled=True,lookup_fn=lookup)
            with self.assertRaisesRegex(UnsafeURL,'非公网'):
                await resolver('https://www.xiaohongshu.com/explore/test')
            self.assertFalse(resolver.cache)
        self.assertEqual(set(hosts),{'cloudflare-dns.com'})

    async def test_all_fixed_services_unavailable_does_not_allow_host(self):
        hosts=[]
        async def lookup(_): return ['198.18.0.15']
        def handler(request):
            hosts.append(request.url.host)
            return httpx.Response(503)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            resolver=PublicDNSResolver(client,enabled=True,lookup_fn=lookup)
            with self.assertRaisesRegex(UnsafeURL,'服务不可用'):
                await resolver('https://www.xiaohongshu.com/explore/test')
            self.assertFalse(resolver.cache)
        self.assertEqual(set(hosts),{'cloudflare-dns.com','dns.google','dns.alidns.com'})
