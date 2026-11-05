"""Send Korean-language news headlines and source links to a WeCom group."""
import html
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import feedparser
import requests
from dateutil import parser as dateparser

KST = timezone(timedelta(hours=9))
NOW = datetime.now(KST)
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; KoreaNewsDigest/1.0)"}
FEEDS = [
    ("연합뉴스 종합", "https://www.yna.co.kr/rss/news.xml"),
    ("연합뉴스 경제", "https://www.yna.co.kr/rss/economy.xml"),
    ("뉴시스 사회", "https://www.newsis.com/RSS/society.xml"),
    ("뉴시스 경제", "https://www.newsis.com/RSS/economy.xml"),
    ("뉴시스 정치", "https://www.newsis.com/RSS/politics.xml"),
]
KEYWORDS = {
    "외국인": 8, "중국인": 8, "중국": 4, "유학생": 8,
    "비자": 9, "체류": 8, "출입국": 9, "이민": 7,
    "취업": 6, "고용": 5, "노동": 4, "임금": 5,
    "월세": 6, "전세": 6, "주택": 4, "부동산": 4,
    "물가": 6, "교통": 4, "건강보험": 7, "의료": 4,
    "환율": 5, "교육": 3, "대학": 3, "정책": 3,
    "정부": 2, "한국": 1, "서울": 1,
}
HANGUL = re.compile(r"[가-힣]")
TIMEOUT = 12


def published_at(entry):
    for key in ("published", "updated"):
        raw = entry.get(key)
        if raw:
            try:
                parsed = dateparser.parse(raw)
                if parsed:
                    if parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=timezone.utc)
                    return parsed.astimezone(KST)
            except (ValueError, TypeError, OverflowError):
                pass
    return None


def collect():
    stories = {}
    working_feeds = 0
    for name, url in FEEDS:
        try:
            response = requests.get(url, timeout=TIMEOUT, headers=HEADERS)
            response.raise_for_status()
            parsed = feedparser.parse(response.content)
            if not parsed.entries:
                print(f"Feed empty: {name}: {url}")
                continue
            working_feeds += 1
            for entry in parsed.entries:
                title = html.unescape(re.sub(r"<[^>]+>", "", entry.get("title", ""))).strip()
                link = entry.get("link", "").strip()
                date = published_at(entry)
                if not title or not HANGUL.search(title) or not link or not date:
                    continue
                if not link.startswith("https://") and not link.startswith("http://"):
                    continue
                if date > NOW + timedelta(minutes=10) or date < NOW - timedelta(hours=72):
                    continue
                key = re.sub(r"[^가-힣a-z0-9]", "", title.lower())
                score = sum(weight for word, weight in KEYWORDS.items() if word in title)
                if score == 0 or key in stories:
                    continue
                stories[key] = (score, date, title, link, name)
            print(f"Feed OK: {name}: {len(parsed.entries)} entries")
        except requests.RequestException as exc:
            print(f"Feed unavailable: {name}: {type(exc).__name__}: {exc}")
    if not working_feeds:
        raise RuntimeError("All Korean publisher RSS feeds unavailable; nothing sent")
    return sorted(stories.values(), key=lambda item: (item[1] >= NOW - timedelta(hours=24), item[0], item[1]), reverse=True)[:5]


def digest(items):
    lines = [f"## 한국 주요 뉴스 | {NOW:%Y-%m-%d}",
             "> 한국시간 오전 10시 기준 · 한국어 원제목 · 언론사 원문"]
    for index, (_, date, title, link, source) in enumerate(items, 1):
        old = " (지난 기사)" if date < NOW - timedelta(hours=24) else ""
        lines.append(f"{index}. [{title}]({link}){old}\n> {source} · {date:%m-%d %H:%M} KST")
    return "\n\n".join(lines)


def send(message):
    webhook = os.environ.get("WECOM_WEBHOOK", "").strip()
    if not webhook.startswith("https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key="):
        raise RuntimeError("Missing or invalid WECOM_WEBHOOK secret")
    result = requests.post(webhook, json={"msgtype": "markdown", "markdown": {"content": message}}, timeout=TIMEOUT)
    result.raise_for_status()
    payload = result.json()
    if payload.get("errcode") != 0:
        raise RuntimeError(f"WeCom error {payload.get('errcode')}: {payload.get('errmsg')}")


if __name__ == "__main__":
    try:
        news = collect()
        if not news:
            raise RuntimeError("RSS reachable but no relevant Korean headlines in last 72 hours; nothing sent")
        body = digest(news)
        if len(body.encode("utf-8")) > 4096:
            raise RuntimeError("Digest exceeds WeCom markdown size limit")
        send(body)
        print(f"Delivered {len(news)} Korean news headlines")
    except Exception as exc:
        print(f"News delivery failed: {exc}", file=sys.stderr)
        sys.exit(1)
