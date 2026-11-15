import asyncio
import unittest

import httpx

from app.boards import BoardService
from app.feeds import parse_feed
from app.settings import BoardConfig, Feed, Settings
from app.sources import parse_source

RSS = b"""<rss version="2.0" xmlns:slash="http://purl.org/rss/1.0/modules/slash/">
<channel><title>Source board</title><link>https://example.com/</link>
<item><title>Second in recency, first in rank</title><link>/a</link>
<description><![CDATA[<p>Source excerpt</p><script>ignored()</script>]]></description>
<slash:comments>0</slash:comments></item>
<item><title>Second item</title><link>https://example.com/b</link></item>
</channel></rss>"""


class FeedTests(unittest.TestCase):
    def test_preserves_source_order_optional_metric_and_summary(self):
        config = Feed("/test", "{http://purl.org/rss/1.0/modules/slash/}comments", "Comments")
        result = parse_feed(RSS, "zhihu", config, "http://localhost:1200/test")
        self.assertEqual(result.title, "Source board")
        first, second = result.items
        self.assertEqual((first["url"], first["rank"], second["rank"]), ("https://example.com/a", 1, 2))
        self.assertEqual(first["metric"], {"value": "0", "label": "Comments"})
        self.assertEqual(first["preview"], {"summary": "Source excerpt"})
        self.assertNotIn("metric", second)

    def test_distinguishes_empty_feed_from_other_xml(self):
        self.assertEqual(parse_feed(b"<rss><channel /></rss>", "zhihu", Feed("/test"), "").items, [])
        with self.assertRaises(ValueError):
            parse_feed(b"<html>Upstream error</html>", "zhihu", Feed("/test"), "")
        with self.assertRaises(ValueError):
            parse_feed(b'<!DOCTYPE rss [<!ENTITY x "boom">]><rss><channel><title>&x;</title></channel></rss>',
                       "zhihu", Feed("/test"), "")


class DirectSourceTests(unittest.TestCase):
    def test_article_list_keeps_order_and_skips_pinned_and_offsite_links(self):
        config = Feed(url="https://it.example.com/", adapter="links", title="Latest",
                      link_path=r"/story/\d+", link_host="www.example.com", link_class="title",
                      link_heading="h2", skip_heading_class="pinned")
        page = b"""<h2 class="pinned"><a class="title" href="//www.example.com/story/1">Pinned</a></h2>
        <h2><a class="title" href="//www.example.com/story/3">Earlier in the list</a></h2>
        <h2><a class="title" href="//elsewhere.example.com/story/4">Offsite</a></h2>
        <h2><a class="title" href="//www.example.com/story/2">Later in the list</a></h2>"""
        rows = parse_source(page, "ithome", config).items
        self.assertEqual([(item["rank"], item["url"]) for item in rows], [
            (1, "https://www.example.com/story/3"), (2, "https://www.example.com/story/2"),
        ])

    def test_douyin_keeps_source_order_and_uses_original_topic_url(self):
        config = Feed(url="https://www.douyin.com/hot", adapter="douyin", title="抖音热点榜", metric_label="热度")
        ranking = b'{"status_code":0,"data":{"word_list":[' \
                  b'{"word":"First","sentence_id":"44","hot_value":3},' \
                  b'{"word":"Second","sentence_id":"31","hot_value":9}]}}'
        result = parse_source(ranking, "douyin", config)
        self.assertEqual([(row["title"], row["rank"], row["url"]) for row in result.items], [
            ("First", 1, "https://www.douyin.com/hot/44"), ("Second", 2, "https://www.douyin.com/hot/31"),
        ])
        self.assertEqual(result.items[0]["metric"], {"value": "3", "label": "热度"})
        with self.assertRaises(ValueError):
            parse_source(b'{"status_code":0,"data":{}}', "douyin", config)

    def test_aggregated_ranking_checks_selected_board_and_original_domain(self):
        config = Feed(url="https://rebang.today/?tab=xiaohongshu&sub_tab=like-3d", adapter="rebang", title="Likes")
        page = b'<a aria-current="page" href="/?sub_tab=like-3d&amp;tab=xiaohongshu">Likes</a>' \
               b'<a aria-label="Cover" href="https://www.xiaohongshu.com/explore/a">Cover</a>' \
               b'<a data-item-title-link="true" aria-label="Original" href="https://www.xiaohongshu.com/explore/a"/>' \
               b'<a data-item-title-link="true" aria-label="Unrelated" href="https://example.com/explore/a"/>'
        result = parse_source(page, "xiaohongshu", config)
        self.assertEqual([(item["title"], item["url"]) for item in result.items], [
            ("Original", "https://www.xiaohongshu.com/explore/a"),
        ])
        with self.assertRaises(ValueError):
            parse_source(page.replace(b"like-3d", b"collect-3d"), "xiaohongshu", config)


class BoardTests(unittest.IsolatedAsyncioTestCase):
    async def test_shared_refresh_and_last_success_survive_failure(self):
        calls = 0

        async def handler(request):
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.01)
            return httpx.Response(200, content=RSS) if calls == 1 else httpx.Response(503)

        key = "zhihu/hot"
        settings = Settings("http://localhost:1200", 300, 1, {key: BoardConfig((Feed("/test"),))})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            service = BoardService(settings, client)
            await asyncio.gather(service.refresh(key), service.refresh(key))
            self.assertEqual(calls, 1)
            board = service.boards[key]
            snapshot, updated_at = board.snapshot, board.updated_at
            self.assertIsNotNone(snapshot)
            self.assertFalse(board.failed)
            await service.refresh(key)
            self.assertTrue(board.failed)
            self.assertIs(board.snapshot, snapshot)
            self.assertEqual(board.updated_at, updated_at)

    async def test_switches_sources_on_failure_but_keeps_valid_empty_ranking(self):
        key = "weibo/hot"
        sources = (Feed("/main"), Feed(url="https://example.com/rss"))
        settings = Settings("http://localhost:1200", 300, 1, {key: BoardConfig(sources)})
        calls = []

        def handler(request):
            calls.append(request.url.path)
            if request.url.path == "/main":
                if calls == ["/main"]:
                    return httpx.Response(503)
                return httpx.Response(200, content=b"<rss><channel><title>Empty</title></channel></rss>")
            return httpx.Response(200, content=RSS)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            service = BoardService(settings, client)
            await service.refresh(key)
            board = service.boards[key]
            self.assertEqual(board.snapshot.title, "Source board")
            self.assertEqual(calls, ["/main", "/rss"])
            await service.refresh(key)
            self.assertEqual(board.snapshot.items, [])
            self.assertFalse(board.failed)
            self.assertEqual(calls, ["/main", "/rss", "/main"])
