# app/generator.py
from __future__ import annotations

import os, json, re
from typing import Dict, List, Any

from app.retriever import search_book
from app.gpt import _client
from app.sheets import get_book_meta  # автор/метаданные из листа books

MODEL_SUMMARY = os.getenv("OPENAI_MODEL_SUMMARY", "gpt-4o-mini")
MODEL_POSTS   = os.getenv("OPENAI_MODEL_POSTS",   "gpt-4o-mini")

_SUMMARY_CACHE: Dict[str, Dict[str, Any]] = {}

# ---------- Текстовые утилиты ----------
def _clean_bold(s: str) -> str:
    return s.replace("**", "").strip()

def _squash_blanks(s: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", s).strip()

def _normalize(s: str) -> str:
    return _squash_blanks(_clean_bold(s))

def _deslug(s: str) -> str:
    # Убираем .pdf/.docx, подчёркивания/дефисы, лишние пробелы
    s = re.sub(r"\.(pdf|docx?|rtf|epub)$", "", s, flags=re.I)
    s = s.replace("_", " ").replace("-", " ")
    s = re.sub(r"\s{2,}", " ", s).strip()
    return s

# Анти-кликбейт: удаляем стартовые «крючки» вида «Знаете ли вы…?», «А что если…?» и т.п.
# ВАЖНО: это строка, а не tuple — чтобы не было TypeError при конкатенации.
_STOP_START = r"(?:знаете ли вы|вы знали|а знаете|а что если|что если|секрет в том|многие не знают|представьте|представь)"

def _declickbait(text: str) -> str:
    if not text:
        return text
    # Удаляем такие «вопросные» подводки в начале строк
    text = re.sub(r"(?im)^\s*" + _STOP_START + r".{0,120}\?\s*\n?", "", text)
    # Чистим повторяющиеся фразы «эта книга…», «в одной из глав…»
    text = re.sub(r"(?im)в\s+одной\s+из\s+глав.*?(?:\.|\n)", "", text)
    text = re.sub(r"(?im)эта\s+книга\s+покажет.*?(?:\.|\n)", "", text)
    return _squash_blanks(text)

# Ограничение эмодзи (оставляем максимум N штук, остальные выкидываем)
_EMOJI_RE = re.compile(
    r"[\U0001F1E6-\U0001F1FF]|"   # флаги
    r"[\U0001F300-\U0001F5FF]|"   # символы/пиктограммы
    r"[\U0001F600-\U0001F64F]|"   # смайлики
    r"[\U0001F680-\U0001F6FF]|"   # транспорт/символы
    r"[\U00002600-\U000026FF]|"   # разное
    r"[\U00002700-\U000027BF]|"   # литералы
    r"[\U0001FA70-\U0001FAFF]",   # расширения
    flags=re.UNICODE
)

def _limit_emojis(text: str, max_count: int) -> str:
    if max_count <= 0:
        return _EMOJI_RE.sub("", text)
    out, used = [], 0
    for ch in text:
        if _EMOJI_RE.fullmatch(ch):
            if used < max_count:
                out.append(ch)
                used += 1
            # иначе пропускаем эмодзи
        else:
            out.append(ch)
    return "".join(out)

# ---------- Метаданные книги ----------
def _book_title(summary: Dict[str, Any], book_id: str, channel_name: str) -> str:
    """Название книги: JSON-конспект → лист books → очищенный id/alias."""
    about = summary.get("about") or {}
    t = (about.get("title") or "").strip()
    if not t:
        try:
            meta = get_book_meta(book_id)
            t = (meta.get("title") or "").strip()
        except Exception:
            t = ""
    if not t:
        t = _deslug(book_id or channel_name)
    return t

def _book_author(summary: Dict[str, Any], book_id: str) -> str:
    """Автор — сначала из конспекта, затем из листа books."""
    about = summary.get("about") or {}
    author = (about.get("author") or "").strip()
    if author:
        return author
    try:
        meta = get_book_meta(book_id)
        return (meta.get("author") or "").strip()
    except Exception:
        return ""

# ---------- Контекст для суммаризации ----------
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

# ---------- Конспект (JSON) ----------
def _ask_json_summary(context: str, book_id: str, channel_name: str) -> Dict[str, Any]:
    system = "Ты редактор делового Telegram-канала. Сделай структурированный, прикладной конспект книги. Русский язык."
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

Точность важнее фантазии: если факта нет — оставь поле пустым.
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

# ---------- Генерация постов ----------
def _gen_with_prompt(fmt: str, summary: Dict[str, Any], *, book_id: str, channel_name: str) -> str:
    base = json.dumps(summary, ensure_ascii=False, indent=2)
    title = _book_title(summary, book_id, channel_name)
    author = _book_author(summary, book_id)

    prompts = {
        "announce": (
            "Сделай анонс книги для Telegram.\n"
            "Структура:\n"
            "- 1 строка: зачем читать (без слов «эта книга покажет»),\n"
            "- 2–3 буллета: кому полезно/какой выигрыш,\n"
            "- 1 крючок: яркая цифра/факт/метафора.\n"
            "Стиль: энергично, конкретно, без воды, 2–3 уместных эмодзи.\n"
            "Избегай общих фраз. Не повторяй название — заголовок добавим отдельно. Без жирного (**)."
        ),
        "insight": (
            "Выдели 3–5 конкретных идей из книги. Каждая — 1–2 предложения + короткий прикладной пример.\n"
            "Стиль: лаконично, разговорно, 1–2 эмодзи суммарно. Без жирного. Заголовок добавим сами."
        ),
        "practice": (
            "Возьми 1 прикладную практику. Дай название и 3–6 чётких шагов.\n"
            "Добавь бытовой пример (одним абзацем).\n"
            "Стиль: дружелюбный, без воды, 1–2 эмодзи. Без жирного. Заголовок добавим сами."
        ),
        "case": (
            "Опиши 1 кейс: контекст → действие → результат → вывод (3–5 предложений).\n"
            "Без общих штампов, 0–1 эмодзи. Без жирного. Заголовок добавим сами."
        ),
        "quote": (
            "Дай 1 сильную цитату дословно в кавычках + 1–2 предложения как применить.\n"
            "Без жирного, 0–1 эмодзи. Заголовок добавим сами."
        ),
        "reflect": (
            "Сформулируй 1–2 вопроса для рефлексии так, чтобы читатель примерил идею на себя.\n"
            "Коротко, 0–1 эмодзи. Без жирного. Заголовок добавим сами."
        ),
    }
    prompt = prompts.get(fmt, "Сделай краткую выжимку по книге: конкретно, без жирного и без повторения заголовка.")

    resp = _client().chat.completions.create(
        model=MODEL_POSTS,
        messages=[
            {"role":"system","content":"Ты редактор Telegram-канала: пиши ярко, по делу, с лёгкими эмодзи и без жирного выделения."},
            {"role":"user","content":f"Конспект книги:\n{base}\n\nЗадача:\n{prompt}"}
        ],
        temperature=0.7,
    )
    body = _normalize(resp.choices[0].message.content or "")
    body = _declickbait(body)

    # лимит эмодзи из п.2: 1 / 2 / 3 в зависимости от длины
    length = len(body)
    max_emoji = 1 if length < 400 else (2 if length < 800 else 3)
    body = _limit_emojis(body, max_emoji)

    # Заголовки/хэштеги
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

    # Заголовок: для анонса добавляем автора, если известен
    if fmt == "announce":
        title_full = f"{title} ({author})" if author else title
        header = f"{emoji} Книга дня — {title_full}"
    else:
        header = f"{emoji} {title} — {label.capitalize()}"

    final = f"{header}\n\n{body}\n\n{tags}"
    return final.strip()

# ---------- Публичные ----------
def generate_from_book(channel_name: str, book_id: str, fmt: str) -> str:
    s = _ensure_summary(book_id, channel_name)
    return _gen_with_prompt(fmt.lower(), s, book_id=book_id, channel_name=channel_name)

def generate_by_format(fmt: str, items: List[dict]) -> str:
    f = (fmt or "").lower()
    if f == "quote":
        return "«Вы — результат того, что делаете каждый день». #цитата"
    if f == "practice":
        return "Практика недели: правило 2 минут. #практика"
    return "Материалы готовятся. #сводка"

def get_author_for_book(book_id: str, channel_name: str) -> str:
    """Возвращает автора книги: сперва из конспекта, затем из листа books."""
    summary = _ensure_summary(book_id, channel_name)
    return _book_author(summary, book_id)
