from __future__ import annotations
from typing import List, Dict

# === СТАРЫЕ функции для RSS ===
def cut(s: str, n: int) -> str:
    return s if len(s) <= n else s[: max(0, n-1)] + "…"

def generate_summary5(items: List[Dict]) -> str:
    top = items[:5]
    if not top:
        return "Свежих материалов пока нет. Загляните позже 🕐"
    lines = ["5 идей из дня:"]
    for i, it in enumerate(top, 1):
        title = cut(it.get("title") or "(без названия)", 120)
        link = it.get("link") or ""
        lines.append(f"{i}. {title}\n{link}")
    lines.append("\n#дайджест #сводка")
    return "\n".join(lines)

def generate_card(items: List[Dict]) -> str:
    if not items:
        return "Мысль дня: делайте маленькие шаги — каждый день. #карточка"
    it = items[0]
    title = it.get("title") or "Мысль дня"
    link = it.get("link") or ""
    return f"Мысль дня: {title}\n{link}\n\n#карточка"

def generate_practice() -> str:
    return "Практика недели: правило 2 минут. Начните с малого — сделайте за 2 минуты то, что откладывали. #практика"

def generate_quote() -> str:
    return "«Вы — результат того, что делаете каждый день». #цитата"

def generate_by_format(fmt: str, items: List[Dict]) -> str:
    fmt = (fmt or "").lower()
    if fmt == "summary5":
        return generate_summary5(items)
    if fmt == "card":
        return generate_card(items)
    if fmt == "practice":
        return generate_practice()
    if fmt == "quote":
        return generate_quote()
    return generate_summary5(items)


# === НОВОЕ: генерация из книжных чанков ===
from pathlib import Path
import yaml
from app.gpt import chat
from app.retriever import search_book

ROOT = Path(__file__).resolve().parents[1]
TOV = yaml.safe_load((ROOT / "config" / "tov.yaml").read_text(encoding="utf-8"))

def _load_tov(channel: str, fmt: str) -> tuple[str, int]:
    ch = TOV["channels"].get(channel, {})
    tone = ch.get("tone", "")
    ff = ch.get("formats", {}).get(fmt, {})
    instr = ff.get("instructions", "")
    max_len = int(ff.get("max_len", 800))
    return (f"{tone}\n\n{instr}".strip(), max_len)

def generate_from_book(channel: str, book_id: str, fmt: str) -> str:
    prompts = {
        "quote": "Лучшая короткая цитата/мысль автора — ёмко и точно",
        "core": "Главная мысль книги — формулировка сути подхода",
        "insight": "Почему подход работает — причинно-следственные идеи",
        "practice": "Практические шаги/чеклист по книге",
    }
    query = prompts.get(fmt.lower(), "Ключевая идея книги")
    chunks = search_book(book_id, query, top_k=5)
    joined = "\n\n---\n\n".join([c["text"] for c in chunks]) if chunks else ""
    tov, max_len = _load_tov(channel, fmt.lower())
    sys = ("Ты редактор канала. Переписывай своими словами, без копипаста длинных фрагментов. "
           "Не выдумывай фактов вне исходника. Соблюдай лимит длины.")
    usr = f"""Канал: {channel}
Формат: {fmt}
Правила стиля:
{tov}

Исходные фрагменты (из книги {book_id}):
{joined}

Требование: один готовый пост, не более {max_len} символов."""
    out = chat(sys, usr, max_tokens=900)
    return out[:max_len]
