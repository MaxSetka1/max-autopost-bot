# app/generator.py
from __future__ import annotations

import os, json
from typing import Dict, List, Any

from app.retriever import search_book
from app.gpt import _client  # фабрика OpenAI клиента

MODEL_SUMMARY = os.getenv("OPENAI_MODEL_SUMMARY", "gpt-4o-mini")
MODEL_POSTS   = os.getenv("OPENAI_MODEL_POSTS",   "gpt-4o-mini")

_SUMMARY_CACHE: Dict[str, Dict[str, Any]] = {}


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
    system = "Ты редактор делового канала. Сделай структурированный конспект книги. Русский язык."
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
        return {"about":{"title":"","author":"","thesis":"","audience":""},
                "key_ideas":[],"practices":[],"cases":[],"quotes":[],"reflection":[]}


def _ensure_summary(book_id: str, channel_name: str) -> Dict[str, Any]:
    if book_id in _SUMMARY_CACHE:
        return _SUMMARY_CACHE[book_id]
    ctx = _collect_context(book_id)
    summary = _ask_json_summary(ctx, book_id, channel_name)
    _SUMMARY_CACHE[book_id] = summary
    return summary


# ---------- Генерация постов из конспекта ----------

def _gen_with_prompt(fmt: str, summary: Dict[str, Any]) -> str:
    """
    Для каждого формата используем свой промпт, чтобы сделать текст глубже.
    """
    base = json.dumps(summary, ensure_ascii=False, indent=2)
    prompts = {
        "announce": (
            "Сделай анонс книги для Telegram:\n"
            "- Название и автор.\n"
            "- Зачем читать (1 фраза).\n"
            "- Кому особенно полезна.\n"
            "- Крючок: яркая цифра/метафора.\n"
            "Формат: 3–4 буллета, энергичный тон, в конце хэштеги."
        ),
        "insight": (
            "Выдели 3–5 ключевых идей из книги:\n"
            "- Каждая идея = 1–2 предложения.\n"
            "- Дай короткий пример или пояснение.\n"
            "Формат: нумерованный список, стиль лаконичный."
        ),
        "practice": (
            "Выбери 1 практику из книги и опиши пошагово:\n"
            "- Название практики.\n"
            "- 3–5 конкретных шагов.\n"
            "- Добавь пример из повседневной жизни.\n"
            "Формат: список шагов, простой язык."
        ),
        "case": (
            "Опиши 1 кейс из книги в стиле storytelling:\n"
            "- 3–5 предложений.\n"
            "- Упомяни факты: кто, когда, результат.\n"
            "- Сделай вывод: чему это учит.\n"
            "Формат: маленькая история, живой тон."
        ),
        "quote": (
            "Выбери 1 сильную цитату из книги:\n"
            "- Приведи её дословно.\n"
            "- Дай пояснение, как применить.\n"
            "Формат: цитата в кавычках + пояснение."
        ),
        "reflect": (
            "Составь вопрос для рефлексии:\n"
            "- 1–2 вопроса, которые заставляют применить идею к себе.\n"
            "- Коротко, разговорным стилем.\n"
            "Формат: заголовок 'Вопрос дня' + сами вопросы."
        ),
    }
    prompt = prompts.get(fmt, "Сделай краткую выжимку из книги.")
    resp = _client().chat.completions.create(
        model=MODEL_POSTS,
        messages=[
            {"role":"system","content":"Ты редактор Telegram-канала: пиши ярко, по делу."},
            {"role":"user","content":f"Конспект книги:\n{base}\n\nЗадача:\n{prompt}"}
        ],
        temperature=0.7,
    )
    return resp.choices[0].message.content.strip()


# ---------- Публичные функции ----------

def generate_from_book(channel_name: str, book_id: str, fmt: str) -> str:
    s = _ensure_summary(book_id, channel_name)
    return _gen_with_prompt(fmt.lower(), s)


def generate_by_format(fmt: str, items: List[dict]) -> str:
    # fallback (старый режим)
    f = (fmt or "").lower()
    if f == "quote":
        return "«Вы — результат того, что делаете каждый день». #цитата"
    if f == "practice":
        return "Практика недели: правило 2 минут. #практика"
    return "Материалы готовятся. #сводка"
