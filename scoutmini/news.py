"""Recent F1 news via free RSS feeds.

Deliberately minimal (v1): fetch a feed, parse it with the stdlib XML parser (no
extra dependency), optionally filter by a keyword, and return the latest few
headlines with their links so the report can cite them.

News is *non-critical*: any fetch/parse failure returns an empty list rather than
breaking the report.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Optional
from xml.etree import ElementTree

import requests

# A free, public F1 news feed. Kept as a list so more can be added later.
DEFAULT_FEEDS = ["https://www.autosport.com/rss/feed/f1"]
_TIMEOUT = 15

FetchText = Callable[[str], str]


@dataclass(frozen=True)
class NewsItem:
    title: str
    link: str
    published: str = ""
    summary: str = ""


def parse_rss(xml_text: str) -> List[NewsItem]:
    """Parse RSS 2.0 XML into NewsItems. Returns [] on malformed input."""
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        return []

    items: List[NewsItem] = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        if not title and not link:
            continue
        items.append(
            NewsItem(
                title=title,
                link=link,
                published=(item.findtext("pubDate") or "").strip(),
                summary=(item.findtext("description") or "").strip(),
            )
        )
    return items


def _default_fetch_text(url: str) -> str:
    resp = requests.get(url, timeout=_TIMEOUT, headers={"User-Agent": "ScoutMini/0.1"})
    resp.raise_for_status()
    return resp.text


def get_news(
    query: Optional[str] = None,
    *,
    limit: int = 5,
    feeds: Optional[List[str]] = None,
    fetch_text: FetchText = _default_fetch_text,
) -> List[NewsItem]:
    """Return up to ``limit`` recent F1 headlines, optionally filtered by ``query``.

    If a query is given but nothing matches, fall back to the latest items so the
    report still has *some* news context. Any failure returns []."""
    feeds = feeds or DEFAULT_FEEDS
    all_items: List[NewsItem] = []
    for url in feeds:
        try:
            all_items.extend(parse_rss(fetch_text(url)))
        except Exception:
            continue  # news is non-critical

    if not all_items:
        return []

    if query:
        q = query.strip().lower()
        matches = [
            it for it in all_items if q in (it.title + " " + it.summary).lower()
        ]
        if matches:
            return matches[:limit]

    return all_items[:limit]
