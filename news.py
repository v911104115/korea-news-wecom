"""Korean news digest via Google News RSS, delivered to WeCom group robot."""
import os
import re
import sys
import html
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import feedparser
import requests
from dateutil import parser as dateparser

KST = timezone(timedelta(hours=9))
NOW = datetime.now(KST)
START = NOW - timedelta(hours=24)
QUERIES = [
    "韩国 签证 外国人 留学生 政策",
    "韩国 华人 中国人 生活 就业",
    "韩国 物价 经济 房租 交通",
    "韩国 政府 新规 外国人",
    "韩国 大学 留学生 工作",
]
KEYWORDS = {
    "签证": 6, "居留": 6, "外国人": 5, "留学生": 5,
    "中国": 4, "就业": 4, "政策": 4, "韩国": 1,
    "房租": 3, "物价": 3, "工资": 3, "交通": 2,
}
TIMEOUT = 15


def fetch():
    candidates = {}
    for query in QUERIES:
        url = ("https://news.google.com/rss/search?q="
               + quote(query + " when:2d")
               + "&hl=zh-CN&gl=KR&ceid=KR:zh-Hans")
        response = requests.get(url, timeout=TIMEOUT, headers={"User-Agent": "Mozilla/5.0"})
        response.raise_for_status()
        for item in feedparser.parse(response.content).entries:
            title = html.unescape(item.get("title", "")).strip()
            link = item.get("link", "")
            if not title or not link:
                continue
            try:
                published = dateparser.parse(item.get("published", "")).astimezone(KST)
            except (TypeError, ValueError, OverflowError):
                continue
            if published > NOW + timedelta(minutes=5) or published < NOW - timedelta(days=3):
                continue
            normalized = re.sub(r"\W+", "", title.split(" - ")[0]).lower()
            if normalized in candidates:
                continue
            score = sum(weight for word, weight in KEYWORDS.items() if word in title)
            score += 8 if published >= START else 0
            candidates[normalized] = (score, published, title, link)
    return sorted(candidates.values(), key=lambda x: (x[0], x[1]), reverse=True)


def make_message(items):
    recent = [item for item in items if item[1] >= START]
    older = [item for item in items if item[1] < START]
    selected = (recent[:5] + older[:max(0, 5 - len(recent))])[:5]
    lines = [f"## 韩国华人每日新闻｜{NOW:%Y-%m-%d}",
             f"> 截至韩国时间 {NOW:%H:%M}；优先过去24小时，较早报道会标注日期。"]
    if not selected:
        lines.append("当前未获取到可核验的新闻条目，请稍后重试。")
    for idx, (_, published, title, link) in enumerate(selected, 1):
        label = "（较早报道）" if published < START else ""
        lines.append(f"**{idx}. {title}**{label}\n"
                     f"发布日期：{published:%Y-%m-%d %H:%M} KST\n"
                     f"[查看新闻原文]({link})")
    lines.append("> 新闻由公开RSS自动筛选；标题和日期来自新闻索引，"
                 "不代表独立事实核查。请以原文及韩国官方公告为准。")
    return "\n\n".join(lines)


def send(content):
    webhook = os.environ.get("WECOM_WEBHOOK", "").strip()
    if not webhook:
        raise RuntimeError("Missing GitHub Actions secret: WECOM_WEBHOOK")
    if not webhook.startswith("https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key="):
        raise RuntimeError("WECOM_WEBHOOK must be a WeCom group robot webhook URL")
    response = requests.post(webhook, json={"msgtype": "markdown", "markdown": {"content": content}}, timeout=TIMEOUT)
    response.raise_for_status()
    result = response.json()
    if result.get("errcode") != 0:
        raise RuntimeError(f"WeCom error: {result.get('errcode')} {result.get('errmsg')}")


if __name__ == "__main__":
    try:
        digest = make_message(fetch())
        print(digest)
        send(digest)
    except Exception as exc:
        print(f"Delivery failed: {exc}", file=sys.stderr)
        sys.exit(1)
