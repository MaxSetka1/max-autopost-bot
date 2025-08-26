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

# ---------- Утилиты ----------

def _clean_bold(s: str) -> str:
    return s.replace("**", "").strip()

def _squash_blanks(s: str) -> str:
    s = re.sub(r"[ \t]+\n", "\n", s)          # хвостовые пробелы в концах строк
    s = re.sub(r"\n{3,}", "\n\n", s).strip()  # лишние пустые строки
    return s

def _normalize(s: str) -> str:
    s = _clean_bold(s)
    s = re.sub(r"!{3,}", "!!", s)  # умеряем «!!!»
    return _squash_blanks(s)

def _deslug(s: str) -> str:
    # Убираем .pdf/.docx, подчёркивания, мусорные суффиксы
    s = re.sub(r"\.(pdf|docx?|rtf|txt|epub)$", "", s, flags=re.I)
    s = s.replace("_", " ")
    # если всё латиницей и без пробелов — предполагаем slug → ставим пробелы по дефисам/капсам
    s = re.sub(r"[-]+", " ", s)
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", s)
    s = re.sub(r"\s{2,}", " ", s).strip()
    return s

def _beautify_quotes(s: str) -> str:
    # прямые кавычки -> «ёлочки» (осторожно, только вокруг коротких цитат в начале/в конце строки)
    s = re.sub(r'(^|\s)"([^"\n]{3,200})"(\s|$)', r'\1«\2»\3', s)
    return s

_EMOJI_RE = re.compile(
    r"([\U0001F1E6-\U0001F1FF]|"   # флаги
    r"[\U0001F300-\U0001F5FF]|"    # символы и пиктограммы
    r"[\U0001F600-\U0001F64F]|"    # смайлики
    r"[\U0001F680-\U0001F6FF]|"    # транспорт и т.п.
    r"[\U00002600-\U000026FF]|"    # разное
    r"[\U00002700-\U000027BF])"    # разное
)

def _limit_emojis(body: str, max_count: int) -> str:
    # оставим первые N эмодзи, остальные выпилим
    out, cnt = [], 0
    for ch in body:
        if _EMOJI_RE.match(ch):
            if cnt < max_count:
                out.append(ch); cnt += 1
            else:
                # пропускаем лишние эмодзи
                continue
        else:
            out.append(ch)
    # не допускаем эмодзи в начале каждой строки подряд
    s = "".join(out)
    s = re.sub(r"(?m)^[\s]*(" + _EMOJI_RE.pattern + r")\s*", r"\1 ", s)
    return s

_STOP_START = (
    r"^(Хотите|Готовы|Знаете ли вы|Представьте|В одной из глав|Автор рассказывает)",
)

def _declickbait(text: str) -> str:
    # убираем кликбейтные заходы в начале абзацев
    text = re.sub(r"(?m)" + _STOP_START + r".{0,80}\?\s*", "", text)
    # выравниваем «в одной из глав/в 2020 году компания...»
    text = re.sub(r"(?mi)^в одной из глав[^.\n]*\.\s*", "", text)
    text = re.sub(r"(?mi)^в \d{4} году компания[^.\n]*\.\s*", "", text)
    return text

def _emoji_budget_for_length(s: str) -> int:
    n = len(s)
    if n < 400:  return 1
    if n < 800:  return 2
    return 3

# ---------- Название / Автор ----------

def _book_title(summary: Dict[str, Any], book_id: str, channel_name: str) -> str:
    """Название: сначала из конспекта, затем из листа books, иначе — очищенный id."""
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
    # косметика
    t = re.sub(r"\s+-\s+$", "", t)
    t = _beautify_quotes(t)
    return t

def _book_author(summary: Dict[str, Any], book_id: str) -> str:
    """Автор — сначала из конспекта, затем из листа books (ничего не выдумываем)."""
    about = summary.get("about") or {}
    author = (about.get("author") or "").strip()
    if author:
        return author
    try:
        meta = get_book_meta(book_id)
        author = (meta.get("author") or "").strip()
    except Exception:
        author = ""
    return author

# ---------- Сбор контекста ----------

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
                seen.add(t); chunks.append(t)
            if len(chunks) >= 60:
                break
        if len(chunks) >= 60:
            break
    joined = "\n\n".join(chunks)
    return joined[:40_000] if len(joined) > 40_000 else joined

# ---------- Конспект ----------

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
            "Избегай общих фраз вроде «в одной из глав автор рассказывает». Не повторяй название — заголовок добавим отдельно. Без жирного (**)."
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
            "Опиши 1 кейс: контекст → действие → результат (с цифрой, если есть) → вывод (3–5 предложений).\n"
            "Без общих штампов, 0–1 эмодзи. Без жирного. Заголовок добавим сами."
        ),
        "quote": (
            "Дай 1 сильную цитату дословно в кавычках + 1–2 предложения «как применить».\n"
            "Не придумывай автора. Если в конспекте есть автор — он будет указан отдельно. Без жирного, 0–1 эмодзи."
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
    body = resp.choices[0].message.content or ""
    body = _normalize(body)
    body = _declickbait(body)
    body = _beautify_quotes(body)

    # Лимит эмодзи по длине
    max_emoji = _emoji_budget_for_length(body)
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

    # Заголовок
    if fmt == "announce":
        title_full = f"{title} ({author})" if author else title
        header = f"{emoji} Книга дня — {title_full}"
    else:
        header = f"{emoji} {title} — {label.capitalize()}"

    # Для цитаты — аккуратная атрибуция автора, если он известен и не встречается в тексте
    if fmt == "quote" and author:
        # если в тексте уже есть длинное тире + что-то похожее на имя — оставляем как есть
        if not re.search(r"—\s*[A-Za-zА-Яа-яЁё][^\n]{1,60}$", body, flags=re.M):
            body = re.sub(r'(?s)^(«.*?»|"[^"]{3,200}")', r"\1 — " + author, body)

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
