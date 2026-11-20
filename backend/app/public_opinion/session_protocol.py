"""Stdlib-only contract shared with MediaCrawler's separate Python process."""
import re
from urllib.parse import urlsplit

PROFILES = {
    "weibo": {"name": "微博", "code": "wb", "home": "https://m.weibo.cn/", "login": "https://passport.weibo.com/sso/signin?entry=miniblog&source=miniblog", "domains": ["weibo.cn"], "auth": ["SUB"]},
    "xiaohongshu": {"name": "小红书", "code": "xhs", "home": "https://www.xiaohongshu.com/", "login": "https://www.xiaohongshu.com/", "domains": ["xiaohongshu.com"], "auth": ["web_session"]},
    "kuaishou": {"name": "快手", "code": "ks", "home": "https://www.kuaishou.com/", "login": "https://www.kuaishou.com/", "domains": ["kuaishou.com"], "auth": ["passToken"]},
    "bilibili": {"name": "哔哩哔哩", "code": "bili", "home": "https://www.bilibili.com/", "login": "https://passport.bilibili.com/login", "domains": ["bilibili.com"], "auth": ["SESSDATA"]},
    "tieba": {"name": "百度贴吧", "code": "tieba", "home": "https://tieba.baidu.com/", "login": "https://tieba.baidu.com/", "domains": ["baidu.com"], "auth": ["BDUSS", "STOKEN", "PTOKEN"]},
}


def cookie_header(platform, cookies):
    values = {}
    for cookie in cookies:
        domain = cookie.get("domain", "").lstrip(".").lower()
        if not any(domain == root or domain.endswith("." + root) for root in PROFILES[platform]["domains"]):
            continue
        name, value = cookie.get("name", ""), cookie.get("value", "")
        if re.fullmatch(r"[!#$%&'*+\-.^_`|~0-9A-Za-z]+", name) and value and not re.search(r"[\r\n;]", value):
            values[name] = value
    return "; ".join(f"{key}={value}" for key, value in values.items())


def cookie_pairs(header):
    return dict(part.strip().split("=", 1) for part in header.split(";") if "=" in part)


def official_page(platform, url):
    parsed = urlsplit(url)
    return parsed.scheme == "https" and any(parsed.hostname == root or (parsed.hostname or "").endswith("." + root) for root in PROFILES[platform]["domains"])
