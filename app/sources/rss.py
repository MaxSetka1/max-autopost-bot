# app/sources/rss.py
from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from typing import List, Dict

import requests
import feedparser


# Аккуратный User-Agent — некоторые сайты режут дефолтные клиенты
UA = "Mozilla/5.0 (compatible; MaxAutopostBot/1.0; +https://example.com/bot)"
TIMEOUT = 10


def _strip_html(s: str) -> str:
    """Грубое удаление html-тегов + нормализация пробелов (без bs4)."""
    if not s:
        return ""
    text = re.sub(r"<[^>]+>", " ", s)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _dt_from_entry(e) -> datetime | None:
    """
    Берём дату из published_parsed/updated_parsed и приводим к aware UTC.
    """
    tm = getattr(e, "published_parsed", None) or getattr(e, "updated_parsed", None)
    if not tm:
        return None
    return datetime.fromtimestamp(time.mktime(tm), tz=timezone.utc)


def _to_item(e, source_url: str) -> Dict:
    """Единый формат элемента."""
    return {
        "title": (getattr(e, "title", "") or "").strip(),
        "link": (getattr(e, "link", "") or "").strip(),
        "summary": _strip_html(
            getattr(e, "summary", "") or getattr(e, "description", "") or ""
        ),
        "published_at": _dt_from_entry(e),
        "source": source_url,
    }


def fetch_rss(
    urls: List[str],
    min_pub_dt: datetime | None = None,
    max_items: int = 10,
    pick_latest_if_empty: bool = True,
) -> List[Dict]:
    """
    Собирает элементы из списка RSS-урлов.

    - min_pub_dt: если указан, отсекаем всё, что старше этой даты (UTC)
    - max_items: сколько элементов вернуть итого
    - pick_latest_if_empty: если после фильтра ничего не осталось,
      берём по 1 самому новому элементу из каждой ленты (без фильтра)

    Возвращает список dict: {title, link, summary, published_at, source}
    """
    items: List[Dict] = []

    session = requests.Session()
    session.headers["User-Agent"] = UA

    # 1) Пытаемся собрать «свежие»
    for url in urls:
        try:
            resp = session.get(url, timeout=TIMEOUT)
            resp.raise_for_status()
            feed = feedparser.parse(resp.content)
        except Exception:
            continue

        # берём с запасом, потом обрежем
        for e in feed.entries[: max_items * 3]:
            it = _to_item(e, url)
            if min_pub_dt and it["published_at"] and it["published_at"] < min_pub_dt:
                continue
            if not it["title"] or not it["link"]:
                continue
            items.append(it)

    # 2) Если свежих нет — подстрахуемся и возьмём самые новые вообще
    if not items and pick_latest_if_empty:
        for url in urls:
            try:
                resp = session.get(url, timeout=TIMEOUT)
                resp.raise_for_status()
                feed = feedparser.parse(resp.content)
                e = feed.entries[0] if feed.entries else None
                if not e:
                    continue
                it = _to_item(e, url)
                if not it["title"] or not it["link"]:
                    continue
                items.append(it)
            except Exception:
                continue

    # 3) Сортируем по дате (None в конец), обрезаем до max_items
    items.sort(
        key=lambda x: x["published_at"] or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return items[:max_items]
