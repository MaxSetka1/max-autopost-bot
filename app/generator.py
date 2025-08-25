# app/generator.py
from __future__ import annotations

import os, json, re
from typing import Dict, List, Any

from app.retriever import search_book
from app.gpt import _client  # фабрика OpenAI клиента

MODEL_SUMMARY = os.getenv("OPENAI_MODEL_SUMMARY", "gpt-4o-mini")
MODEL_POSTS   = os.getenv("OPENAI_MODEL_POSTS",   "gpt-4o-mini")

_SUMMARY_CACHE: Dict[str, Dict[str, Any]] = {}


# ---------- Утилиты ----------

def _clean_bold(s: str) -> str:
    # убрать **жирное**
    return s.replace("**", "").strip()

def _squash_blanks(s: str) -> str:
    # сжать лишние пустые строки
    return re.sub(r"\n{3,}", "\n\n", s).strip()

def _normalize(s: str) -> str:
    return _squash_blanks(_clean_bold(s))

def _book_title(s: Dict[str, Any], book_id: str, channel_name: str) -> str:
    about = s.get("about") or {}
    t = (about.get("title") or "").strip()
    if t:
        return t
    # fallback — из id или имени канала
    return book_id.replace("_", " ").strip().title() if book_id else channel_name


# ---------- Сбор контекста из книги ----------

def _collect_context(book_id: str) -> str:
    queries = [
        "основная идея книги в целом",
        "ключевые принципы и правила автора",
        "пошаговые практики и упражнения",
        "примеры и кейсы применения",
        "сильные цитаты и формулировки",
        "для кого книга и как использовать материалы",
    ]
    chunks, seen = [], set()
    for q in queries:
        for ch in search_book(book_id, q, top_k=10):
            t = (ch.get("text") or "").strip()
            if t and t not in seen:
                seen.add(t)
                chunks.append(t)
            if len(chunks) >= 60:
                break
        if len(chunks) >= 60:
            break
    joined = "\n\n".join(chunks)
    return joined[:40_000] if len(joined) > 40_000 else joined


# ---------- Построение конспекта ----------

def _ask_json_summary(context: str, book_id: str, channel_name: str) -> Dict[str, Any]:
    system = (
        "Ты редактор делового Telegram-канала. Сделай структурированный, прикладной конспект книги. Русский язык."
    )
    user = f"""
На входе фрагменты книги. Сделай JSON-конспект:

{{
  "about": {{"title":"","author":"","thesis":"","audience":""}},
  "key_ideas": ["..."],
  "practices": [{{"name":"","steps":["шаг 1","шаг 2"]}}],
  "cases": ["..."],
  "quotes": [{{"text":"","note":""}}],
  "reflection": ["..."]
}}

Не выдумывай факты — если чего-то нет, оставь пустым.
Возвращай ТОЛЬКО валидный JSON без пояснений.

Фрагменты:
---
{context}
---
"""
    resp = _client().chat.completions.create(
        model=MODEL_SUMMARY,
        messages=[{"role":"system","content":system},
                  {"role":"user","content":user}],
        temperature=0.2,
        response_format={"type":"json_object"},
    )
    try:
        return json.loads(resp.choices[0].message.content)
    except Exception:
        return {
            "about":{"title":"","author":"","thesis":"","audience":""},
            "key_ideas":[],"practices":[],"cases":[],"quotes":[],"reflection":[]
        }


def _ensure_summary(book_id: str, channel_name: str) -> Dict[str, Any]:
    if book_id in _SUMMARY_CACHE:
        return _SUMMARY_CACHE[book_id]
    ctx = _collect_context(book_id)
    summary = _ask_json_summary(ctx, book_id, channel_name)
    _SUMMARY_CACHE[book_id] = summary
    return summary


# ---------- Генерация постов из конспекта ----------

def _gen_with_prompt(fmt: str, summary: Dict[str, Any], *, book_id: str, channel_name: str) -> str:
    base = json.dumps(summary, ensure_ascii=False, indent=2)
    title = _book_title(summary, book_id, channel_name)

    prompts = {
        "announce": (
            "Сделай анонс книги для Telegram:\n"
            "- зачем читать (1 фраза),\n"
            "- кому особенно полезна,\n"
            "- крючок: яркая цифра/метафора.\n"
            "Стиль: энергично, 3–4 буллета, 2–3 уместных эмодзи.\n"
            "Не используй жирное (**). Не повторяй название книги в тексте (заголовок будет добавлен отдельно)."
        ),
        "insight": (
            "Выдели 3–5 ключевых идей из книги. Каждая идея — 1–2 предложения + короткий пример/пояснение.\n"
            "Стиль: лаконично, разговорно, 1–2 эмодзи суммарно. Без жирного. Заголовок мы добавим сами."
        ),
        "practice": (
            "Выбери 1 практику и опиши пошагово: 3–6 конкретных шагов.\n"
            "Обязательно добавь бытовой пример применения (например: ...).\n"
            "Стиль: простой язык, дружелюбно, 1–2 эмодзи. Без жирного. Заголовок мы добавим сами."
        ),
        "case": (
            "Опиши 1 кейс из книги в 3–5 предложениях: кто/когда/что сделали/результат.\n"
            "Добавь вывод: чему это учит. Можно 1 эмодзи. Без жирного. Заголовок мы добавим сами."
        ),
        "quote": (
            "Выбери 1 сильную цитату из книги (если есть). Приведи дословно в кавычках и добавь 1–2 предложения пояснения: как применить.\n"
            "Без жирного, 0–1 эмодзи. Заголовок мы добавим сами."
        ),
        "reflect": (
            "Сформулируй 1–2 вопроса для рефлексии, чтобы читатель применил идею к себе.\n"
            "Коротко, дружелюбно, 0–1 эмодзи. Без жирного. Заголовок мы добавим сами."
        ),
    }
    prompt = prompts.get(fmt, "Сделай краткую выжимку из книги без жирного и без повторения заголовка.")

    resp = _client().chat.completions.create(
        model=MODEL_POSTS,
        messages=[
            {"role":"system","content":"Ты редактор Telegram-канала: пиши ярко, по делу, с лёгкими эмодзи и без жирного выделения."},
            {"role":"user","content":f"Конспект книги:\n{base}\n\nЗадача:\n{prompt}"}
        ],
        temperature=0.7,
    )
    body = _normalize(resp.choices[0].message.content or "")

    # Заголовки и хэштеги по формату
    map_emoji = {
        "announce": "📚",
        "insight":  "💡",
        "practice": "🛠️",
        "case":     "📌",
        "quote":    "🗣️",
        "reflect":  "🧭",
    }
    map_tag = {
        "announce": "#анонс #книга",
        "insight":  "#инсайт",
        "practice": "#практика",
        "case":     "#кейс",
        "quote":    "#цитата",
        "reflect":  "#рефлексия",
    }
    map_label = {
        "announce": "анонс",
        "insight":  "ключевые идеи",
        "practice": "практика",
        "case":     "кейс",
        "quote":    "цитата",
        "reflect":  "вопрос дня",
    }
    emoji = map_emoji.get(fmt, "📝")
    label = map_label.get(fmt, fmt)
    tags  = map_tag.get(fmt, "#сводка")

    header = f"{emoji} {title} — {label.capitalize()}"
    final = f"{header}\n\n{body}\n\n{tags}"
    return final.strip()


# ---------- Публичные функции ----------

def generate_from_book(channel_name: str, book_id: str, fmt: str) -> str:
    s = _ensure_summary(book_id, channel_name)
    return _gen_with_prompt(fmt.lower(), s, book_id=book_id, channel_name=channel_name)


def generate_by_format(fmt: str, items: List[dict]) -> str:
    # fallback (старый режим)
    f = (fmt or "").lower()
    if f == "quote":
        return "«Вы — результат того, что делаете каждый день». #цитата"
    if f == "practice":
        return "Практика недели: правило 2 минут. #практика"
    return "Материалы готовятся. #сводка"
