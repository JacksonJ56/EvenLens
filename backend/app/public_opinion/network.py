"""Public-address verification for research Fetch behind a local Fake-IP proxy.

Never treat a private address as public. Only the dedicated 198.18/15 proxy range
can trigger a fresh, independently validated answer from fixed HTTPS resolvers.
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
DNS_ENDPOINTS = (DNS_ENDPOINT, "https://dns.google/resolve", "https://dns.alidns.com/resolve")


class DNSRejected(ValueError):
    """A resolver returned an unsafe address; another resolver must not override it."""


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
            async with asyncio.timeout(8):
                for endpoint in DNS_ENDPOINTS:
                    # Both record families must be checked. Transport failures may fail over;
                    # a private/malformed address in either family always rejects the host.
                    answers = await asyncio.gather(self.query(host, "A", endpoint),
                        self.query(host, "AAAA", endpoint), return_exceptions=True)
                    if any(isinstance(answer, DNSRejected) for answer in answers):
                        raise UnsafeURL("独立 DNS 返回了非公网或异常地址；未放行该网址")
                    if any(isinstance(answer, Exception) for answer in answers):
                        continue
                    resolved = [ip for answer in answers for ip in answer]
                    if resolved:
                        break
                else:
                    raise ValueError
        except UnsafeURL:
            raise
        except Exception:
            raise UnsafeURL("独立公网 DNS 核验服务不可用或未返回有效地址；未放行该网址") from None
        self.cache[host] = time.monotonic() + 60

    async def query(self, host, kind, endpoint=DNS_ENDPOINT):
        async with self.client.stream("GET", endpoint, params={"name": host, "type": kind},
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
        addresses = []
        for row in answer:
            if not isinstance(row, dict):
                raise ValueError
            if row.get("type") not in {1, 28}:
                continue
            try:
                address = ipaddress.ip_address(row["data"])
            except (KeyError, ValueError, TypeError):
                raise DNSRejected from None
            if not globally_routable(address) or (row["type"] == 1) != (address.version == 4):
                raise DNSRejected
            addresses.append(address)
        return addresses
