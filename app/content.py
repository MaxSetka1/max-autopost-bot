# app/content.py
from __future__ import annotations

import os
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import List

import yaml

from app.sources.rss import fetch_rss
from app.generator import generate_by_format


ROOT = Path(__file__).resolve().parents[1]
# Поддержим оба варианта имени файла на всякий случай
CFG_SOURCES_LOWER = ROOT / "config" / "sources.yaml"
CFG_SOURCES_UPPER = ROOT / "config" / "Sources.yaml"


def _config_path() -> Path:
    """Возвращает путь к конфигу источников (lower/upper)."""
    if CFG_SOURCES_LOWER.exists():
        return CFG_SOURCES_LOWER
    return CFG_SOURCES_UPPER


def _load_yaml(p: Path) -> dict:
    with p.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _extract_urls(cfg: dict, channel_name: str) -> List[str]:
    """
    Поддерживаем две схемы:

    1) Новая (рекомендуемая):
       channels:
         ChitaiDelai:
           rss: [ ... ]
       defaults:
         rss: [ ... ]

    2) Старая (вдруг осталась где-то):
       sources:
         ChitaiDelai:
           rss: [ ... ]
    """
    urls: List[str] = []

    # Новая
    ch = (cfg.get("channels", {}) or {}).get(channel_name, {}) or {}
    urls.extend(ch.get("rss", []) or [])

    # defaults (глобальные источники)
    defaults = cfg.get("defaults", {}) or {}
    urls.extend(defaults.get("rss", []) or [])

    # Старая (если вдруг нет новых полей)
    if not urls:
        urls.extend(((cfg.get("sources", {}) or {}).get(channel_name, {}) or {}).get("rss", []) or [])

    # Уникализируем, сохраняем порядок
    seen = set()
    uniq = []
    for u in urls:
        if u and u not in seen:
            seen.add(u)
            uniq.append(u)
    return uniq


def make_content(fmt: str, channel_name: str) -> str:
    """
    1) читаем sources.yaml
    2) тянем материалы из RSS (с «окном свежести»)
    3) генерим текст поста под формат через generate_by_format()
    """
    cfg = _load_yaml(_config_path())
    urls = _extract_urls(cfg, channel_name)

    # «Окно свежести» — по умолчанию 48 часов; меняется переменной окружения RSS_WINDOW_HOURS
    hours = int(os.getenv("RSS_WINDOW_HOURS", "48"))
    min_pub_dt = datetime.now(timezone.utc) - timedelta(hours=hours)

    items = []
    if urls:
        items = fetch_rss(
            urls=urls,
            min_pub_dt=min_pub_dt,
            max_items=30,
            pick_latest_if_empty=True,  # если свежих нет — возьмем по одному новому из каждой ленты
        )

    # Дальше форматирование берёт на себя генератор
    return generate_by_format(fmt, items)
