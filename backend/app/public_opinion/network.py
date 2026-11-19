"""Public-address verification for research Fetch behind a local Fake-IP proxy.

Never treat a private address as public. Only the dedicated 198.18/15 proxy range
can trigger a fresh, independently validated answer from a fixed HTTPS resolver.
"""
import asyncio
import ipaddress
import json
import socket
import time
from urllib.parse import urlsplit

from ..event_trace.clients import UnsafeURL, public_url

FAKE_IP = ipaddress.ip_network("198.18.0.0/15")
DNS_ENDPOINT = "https://cloudflare-dns.com/dns-query"


async def lookup(host):
    records = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return [record[4][0] for record in records]


def globally_routable(address):
    return address.is_global and not address.is_multicast


class PublicDNSResolver:
    def __init__(self, client, enabled=False, lookup_fn=lookup):
        self.client, self.enabled, self.lookup = client, enabled, lookup_fn
        self.cache = {}

    async def __call__(self, url):
        host = urlsplit(public_url(url)).hostname
        try:
            addresses = [ipaddress.ip_address(value) for value in await self.lookup(host)]
        except (OSError, ValueError):
            raise UnsafeURL("无法验证网址的公网解析") from None
        if addresses and all(globally_routable(ip) for ip in addresses):
            return
        is_fake = addresses and all(ip.version == 4 and ip in FAKE_IP for ip in addresses)
        if not is_fake:
            raise UnsafeURL("网址解析到了非公网地址")
        if not self.enabled:
            raise UnsafeURL("网络代理返回了 Fake-IP 测试地址，尚未启用独立公网 DNS 核验")
        if self.cache.get(host, 0) > time.monotonic():
            return
        try:
            async with asyncio.timeout(3):
                answers = await asyncio.gather(self.query(host, "A"), self.query(host, "AAAA"))
            resolved = [ip for answer in answers for ip in answer]
            if not resolved or not all(globally_routable(ip) for ip in resolved):
                raise ValueError
        except Exception:
            raise UnsafeURL("独立公网 DNS 核验失败；未放行该网址") from None
        self.cache[host] = time.monotonic() + 60

    async def query(self, host, kind):
        async with self.client.stream("GET", DNS_ENDPOINT, params={"name": host, "type": kind},
                headers={"Accept": "application/dns-json"}, follow_redirects=False, timeout=2.5) as response:
            if response.status_code != 200:
                raise ValueError
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > 65536:
                    raise ValueError
        data = json.loads(body)
        if not isinstance(data, dict) or data.get("Status") != 0:
            raise ValueError
        answer = data.get("Answer", [])
        if not isinstance(answer, list) or len(answer) > 32:
            raise ValueError
        return [ipaddress.ip_address(row["data"]) for row in answer if row.get("type") in {1, 28}]
