# app/sources/rss.py
from __future__ import annotations
import feedparser
from bs4 import BeautifulSoup
from datetime import datetime, timezone
from dateutil import parser as dtparse

def _clean_html(html: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    text = soup.get_text(" ", strip=True)
    return " ".join(text.split())

def _parsed_date(entry) -> datetime | None:
    # Пытаемся прочитать дату из разных полей
    for key in ("published", "updated", "created"):
        val = entry.get(key)
        if val:
            try:
                return dtparse.parse(val).astimezone(timezone.utc)
            except Exception:
                pass
    return None

def fetch_rss(urls: list[str], limit: int = 20) -> list[dict]:
    """
    Возвращает унифицированный список материалов:
    {title, link, summary, published_at}
    """
    items: list[dict] = []
    for url in urls:
        try:
            feed = feedparser.parse(url)
            for e in feed.entries[:limit]:
                items.append({
                    "title": (e.get("title") or "").strip(),
                    "link": (e.get("link") or "").strip(),
                    "summary": _clean_html(e.get("summary") or e.get("description") or ""),
                    "published_at": _parsed_date(e)
                })
        except Exception:
            # ничего страшного — просто пропустим источник
            continue

    # сортируем по дате (новое выше)
    items.sort(key=lambda x: x["published_at"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return items
