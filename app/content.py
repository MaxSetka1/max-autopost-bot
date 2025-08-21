# app/content.py
from __future__ import annotations
import yaml
from pathlib import Path
from app.sources import fetch_rss
from app.generator import generate_by_format

ROOT = Path(__file__).resolve().parents[1]
CFG_SOURCES = ROOT / "config" / "sources.yaml"

def load_yaml(p: Path):
    with p.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def make_content(fmt: str, channel_name: str) -> str:
    """
    1) читаем sources.yaml
    2) тянем материалы из RSS
    3) генерим текст поста под формат
    """
    cfg = load_yaml(CFG_SOURCES)
    urls = (cfg.get("sources", {}).get(channel_name, {}) or {}).get("rss", [])
    items = fetch_rss(urls, limit=30) if urls else []
    return generate_by_format(fmt, items)
