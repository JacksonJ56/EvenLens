import csv
import html
import io
import json
import re
import unicodedata
from html.parser import HTMLParser
from collections import Counter
from datetime import datetime, timezone

from ..event_trace.clients import public_url
from .schemas import Comment, CommentInput, DatasetStats, Post
from .settings import OpinionSettings


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.hidden = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        if tag in {"br", "p", "div"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFC", html.unescape(text)).replace("\r\n", "\n")
    parser = PlainText()
    parser.feed(text)
    text = "".join(parser.parts)
    text = "".join(ch for ch in text if ch in "\n\t" or not unicodedata.category(ch).startswith("C"))
    return re.sub(r"[ \t]+", " ", re.sub(r"\n{3,}", "\n\n", text)).strip()


def parse_import(content: str, format: str, platform: str) -> tuple[list[Post], list[CommentInput]]:
    """Strict, portable format; no guessed MediaCrawler column names in authorized imports."""
    if format == "json":
        data = json.loads(content)
        if not isinstance(data, dict) or set(data) - {"posts", "comments"}:
            raise ValueError("JSON 须包含 posts 和 comments 数组")
        posts = [Post.model_validate({**p, "verification": "authorized_import"}) for p in data.get("posts", [])]
        rows = [CommentInput.model_validate(c) for c in data.get("comments", [])]
    else:
        records = list(csv.DictReader(io.StringIO(content.lstrip("\ufeff"))))
        rows, post_map = [], {}
        for record in records:
            url = record.pop("post_url", "")
            title = record.pop("post_title", "")
            record = {key: value for key, value in record.items() if value != ""}
            comment = CommentInput.model_validate(record)
            rows.append(comment)
            post_map.setdefault(comment.post_id, Post(id=comment.post_id, platform_id=platform,
                                url=url, title=title, verification="authorized_import"))
        posts = list(post_map.values())
    if not 1 <= len(posts) <= 100 or not 1 <= len(rows) <= 10000:
        raise ValueError("导入须包含 1–100 条帖子和 1–10000 条评论")
    seen = set()
    for post in posts:
        if post.platform_id != platform or post.id in seen:
            raise ValueError("帖子平台不匹配或帖子 ID 重复")
        from .collector import identify_post
        identity = identify_post(platform, public_url(post.url))
        if not identity or identity != post.id:
            raise ValueError("帖子 URL 与平台或帖子 ID 不匹配")
        seen.add(post.id)
    for row in rows:
        if row.platform_id != platform or row.post_id not in seen:
            raise ValueError("评论所属平台或帖子不匹配")
        if row.source_url:
            if identify_post(platform, public_url(row.source_url)) != row.post_id:
                raise ValueError("评论来源链接与所属帖子不匹配")
    return posts, rows


def prepare_comments(posts: list[Post], rows: list[CommentInput], settings: OpinionSettings):
    allowed = {p.id for p in posts[:settings.max_posts]}
    post_map = {p.id: p for p in posts}
    seen_ids, seen_text = set(), set()
    counts, reply_count, prepared = Counter(), 0, []
    collected = len(rows)
    for row in rows:  # Preserve incoming order; never sort by likes or randomly sample.
        identity = (row.platform_id, row.post_id, row.comment_id)
        if row.post_id not in allowed or identity in seen_ids:
            continue
        seen_ids.add(identity)
        text = normalize(row.content)
        if not text:
            continue
        if row.parent_comment_id:
            # Replies are context only, and only retained when the parent is in the selected roots.
            if (row.platform_id, row.post_id, row.parent_comment_id) not in {
                (c.platform_id, c.post_id, c.comment_id) for c in prepared if not c.parent_comment_id
            } or reply_count >= settings.max_replies:
                continue
            reply_count += 1
        else:
            if counts[row.post_id] >= settings.per_post or sum(counts.values()) >= settings.max_comments:
                continue
            counts[row.post_id] += 1
        prepared.append(Comment(**row.model_dump(exclude={"content", "source_url"}), content=text,
                                source_url=row.source_url or post_map[row.post_id].url,
                                raw_content=row.content, duplicate_text=text in seen_text))
        seen_text.add(text)
    times = [c.created_at.replace(tzinfo=c.created_at.tzinfo or timezone.utc).astimezone(timezone.utc)
             for c in prepared if c.created_at and not c.parent_comment_id]
    modes = sorted({c.sort_mode for c in prepared if not c.parent_comment_id})
    limitations = ["仅分析指定平台有限帖子的前排评论，不代表全平台或全社会观点分布。",
                   "按采集或导入顺序取每帖前 N 条有效一级评论；未按点赞数重新排序。",
                   "二级回复只作上下文，不计入一级评论统计分母。"]
    if any(p.verification == "authorized_import" for p in posts):
        limitations.append("评论真实性、事件相关性和排序由导入者声明，系统仅校验格式、平台链接和数据关联，未独立在线核验。")
    if any(len(c.content) > 1200 for c in prepared):
        limitations.append("长评论保留原文，但模型分析仅使用前 1200 字。")
    if "unknown" in modes:
        limitations.append("部分评论的热门排序未经确认，不能称为平台热门排名。")
    if any(p.platform_id == "bilibili" and p.verification == "page_read" for p in posts):
        limitations.append("B站上游适配器会将置顶评论放在首批回复前；source_rank 表示含置顶的回调顺序，不是严格点赞排名。")
    if any(c.source_rank is None for c in prepared):
        limitations.append("部分评论未提供可靠的原始排名；仅保留文件或接口返回顺序。")
    if collected > len(prepared):
        limitations.append(f"输入共 {collected} 条记录，经过有效性、去重和数量限制保留 {len(prepared)} 条；原文件不作为全量分析。")
    imported = any(p.verification == "authorized_import" for p in posts)
    stats = DatasetStats(post_count=len(allowed), collected_count=0 if imported else collected, input_count=collected,
                         origin="imported" if imported else "collected", analyzed_count=0, prepared_count=sum(counts.values()),
                         reply_count=reply_count, per_post=dict(counts), sort_modes=modes,
                         time_start=min(times).isoformat() if times else None,
                         time_end=max(times).isoformat() if times else None, limitations=limitations)
    return prepared, stats
