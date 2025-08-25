# app/generator.py
from __future__ import annotations

import os
from typing import Dict, List, Any

from app.retriever import search_book
from app.gpt import client  # используем того же клиента, что и для эмбеддингов

# Модель для конспекта и постов (можно переопределить в Config Vars: OPENAI_MODEL_SUMMARY)
MODEL_SUMMARY = os.getenv("OPENAI_MODEL_SUMMARY", "gpt-4o-mini")
MODEL_POSTS   = os.getenv("OPENAI_MODEL_POSTS",   "gpt-4o-mini")

# Памятка на процесс (чтобы не гонять конспект для одной книги по нескольку раз)
_SUMMARY_CACHE: Dict[str, Dict[str, Any]] = {}


def _collect_context(book_id: str) -> str:
    """
    Забираем «сырьё» из книги несколькими целевыми запросами.
    Достаточно 30–50 коротких фрагментов (модель сама агрегирует).
    """
    queries = [
        "основная идея книги в целом",
        "ключевые принципы и правила автора",
        "пошаговые практики и упражнения",
        "примеры и кейсы применения",
        "сильные цитаты и формулировки",
        "для кого книга и как использовать материалы",
    ]
    chunks: List[str] = []
    seen = set()

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

    # Сильная усечка контекста (безопасно для токенов)
    joined = "\n\n".join(chunks)
    if len(joined) > 40_000:
        joined = joined[:40_000]
    return joined


def _ask_json_summary(context: str, book_id: str, channel_name: str) -> Dict[str, Any]:
    """
    Просим модель вернуть СТРОГО структурированный JSON‑конспект.
    """
    system = (
        "Ты редактор делового канала. Делаешь короткий, точный, прикладной конспект книги. "
        "Пиши просто, без воды, избегай общих слов. Русский язык."
    )
    user = f"""
У тебя на входе фрагменты из книги (ниже). Сделай единый конспект в JSON для дальнейшего использования каналом «{channel_name}».

Требуемая структура JSON (ключи именно такие):

{{
  "about": {{
    "title": "",           // если в тексте есть
    "author": "",          // если есть
    "thesis": "",          // одна фраза — зачем книга
    "audience": ""         // кому и когда полезна
  }},
  "key_ideas": [           // 3–6 идей, каждая 1–2 предложения
    "…"
  ],
  "practices": [           // 2–4 практики, каждая: короткий пошаговый алгоритм
    {{
      "name": "",
      "steps": ["шаг 1", "шаг 2"]
    }}
  ],
  "cases": [               // 1–3 мини‑кейса примения идеи (по 2–4 предложения)
    "…"
  ],
  "quotes": [              // 2–4 цитаты: точные формулировки (если в тексте есть)
    {{
      "text": "цитата",
      "note": "краткое пояснение"
    }}
  ],
  "reflection": [          // 2–3 вопроса для самопроверки/рефлексии
    "…"
  ]
}}

Правила:
- Возвращай ТОЛЬКО валидный JSON без пояснений.
- Если чего-то нет в тексте — оставь поле пустым/список пустым, не выдумывай.
- Сохраняй смысл, избегай повторов. Короткие, практичные формулировки.

Фрагменты из книги:
---
{context}
---
"""

    resp = client.chat.completions.create(
        model=MODEL_SUMMARY,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",    "content": user},
        ],
        temperature=0.2,
        response_format={"type": "json_object"},
    )
    content = resp.choices[0].message.content
    import json
    try:
        data = json.loads(content)
    except Exception:
        # fallback: минимальный каркас
        data = {
            "about": {"title": "", "author": "", "thesis": "", "audience": ""},
            "key_ideas": [],
            "practices": [],
            "cases": [],
            "quotes": [],
            "reflection": [],
        }
    return data


def _ensure_summary(book_id: str, channel_name: str) -> Dict[str, Any]:
    """
    Достаём конспект из кэша или строим заново.
    (Персист в БД/файл добавим позже; для Heroku достаточно кэша на процесс.)
    """
    if book_id in _SUMMARY_CACHE:
        return _SUMMARY_CACHE[book_id]

    ctx = _collect_context(book_id)
    summary = _ask_json_summary(ctx, book_id, channel_name)
    _SUMMARY_CACHE[book_id] = summary
    return summary


# ---------- Рендеры форматов из конспекта ----------

def _render_announce(s: Dict[str, Any]) -> str:
    about = s.get("about") or {}
    title = (about.get("title") or "").strip() or "Книга дня"
    author = (about.get("author") or "").strip()
    thesis = (about.get("thesis") or "").strip()
    audience = (about.get("audience") or "").strip()

    bullets = []
    if thesis:
        bullets.append(f"• Зачем: {thesis}")
    if audience:
        bullets.append(f"• Кому: {audience}")
    ideas = s.get("key_ideas") or []
    if ideas:
        bullets.append(f"• Внутри: {min(len(ideas), 5)} ключевых идеи и практики")

    body = "\n".join(bullets[:3]) if bullets else ""
    by = f" — {author}" if author else ""
    return f"📚 **{title}**{by}\n\n{body}\n\n#анонс #книга"


def _render_insight(s: Dict[str, Any]) -> str:
    ideas: List[str] = s.get("key_ideas") or []
    top = ideas[:5] if ideas else []
    if not top:
        return "3–5 идей из книги: материалы готовятся. #инсайт"
    lines = ["💡 **Ключевые идеи:**"]
    for i, it in enumerate(top, 1):
        lines.append(f"{i}. {it}")
    lines.append("\n#инсайт")
    return "\n".join(lines)


def _render_practice(s: Dict[str, Any]) -> str:
    prs = s.get("practices") or []
    if not prs:
        return "Практика дня появится позже. #практика"
    p = prs[0]
    name = (p.get("name") or "Практика дня").strip()
    steps: List[str] = p.get("steps") or []
    lines = [f"🛠️ **{name}**"]
    for i, st in enumerate(steps[:8], 1):
        lines.append(f"{i}) {st}")
    lines.append("\n#практика")
    return "\n".join(lines)


def _render_case(s: Dict[str, Any]) -> str:
    cases: List[str] = s.get("cases") or []
    if not cases:
        return "Кейс применения идеи добавим позже. #кейс"
    txt = cases[0]
    return f"📌 **Кейс применения:**\n{txt}\n\n#кейс"


def _render_quote(s: Dict[str, Any]) -> str:
    quotes: List[Dict[str, str]] = s.get("quotes") or []
    if not quotes:
        return "«Цитата дня появится позже.» #цитата"
    q = quotes[0]
    t = (q.get("text") or "").strip()
    note = (q.get("note") or "").strip()
    extra = f"\n— {note}" if note else ""
    return f"«{t}»{extra}\n\n#цитата"


def _render_reflect(s: Dict[str, Any]) -> str:
    qs: List[str] = s.get("reflection") or []
    if not qs:
        return "Вопрос на размышление появится позже. #рефлексия"
    lines = ["🧭 **Вопрос дня:**", qs[0]]
    if len(qs) > 1:
        lines += ["", "Дополнительно:", f"— {qs[1]}"]
    lines.append("\n#рефлексия")
    return "\n".join(lines)


# ---------- Публичные функции ----------

def generate_from_book(channel_name: str, book_id: str, fmt: str) -> str:
    """
    Главная точка: возвращает текст для формата, НО
    всегда опирается на единый конспект книги.
    """
    s = _ensure_summary(book_id, channel_name)
    f = (fmt or "").lower()
    if f == "announce":
        return _render_announce(s)
    if f == "insight":
        return _render_insight(s)
    if f == "practice":
        return _render_practice(s)
    if f == "case":
        return _render_case(s)
    if f == "quote":
        return _render_quote(s)
    if f == "reflect":
        return _render_reflect(s)
    # дефолт — сводка идей
    return _render_insight(s)


def generate_by_format(fmt: str, items: List[dict]) -> str:
    """
    legacy-хелпер (оставляем для совместимости, если где-то зовётся).
    Сейчас не используется в основном пайплайне, но не мешает.
    """
    f = (fmt or "").lower()
    if f == "quote":
        return "«Вы — результат того, что делаете каждый день». #цитата"
    if f == "practice":
        return "Практика недели: правило 2 минут. #практика"
    # базовый дайджест на случай пустого ввода
    top = items[:5] if items else []
    if not top:
        return "Свежих материалов пока нет. Загляните позже 🕐"
    def cut(s: str, n: int) -> str:
        return s if len(s) <= n else s[: max(0, n-1)] + "…"
    lines = ["5 идей из дня:"]
    for i, it in enumerate(top, 1):
        title = cut(it.get("title") or "(без названия)", 120)
        link = it.get("link") or ""
        lines.append(f"{i}. {title}\n{link}")
    lines.append("\n#дайджест #сводка")
    return "\n".join(lines)
