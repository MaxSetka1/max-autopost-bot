# app/generator.py
from __future__ import annotations

def cut(s: str, n: int) -> str:
    return s if len(s) <= n else s[: max(0, n-1)] + "…"

def generate_summary5(items: list[dict]) -> str:
    """
    Собираем 5 самых свежих заголовков (если меньше — сколько есть).
    """
    top = items[:5]
    if not top:
        return "Свежих материалов пока нет. Загляните позже 🕐"

    lines = ["5 идей из дня:"]
    for i, it in enumerate(top, 1):
        title = cut(it["title"] or "(без названия)", 120)
        link = it["link"] or ""
        lines.append(f"{i}. {title}\n{link}")
    lines.append("\n#дайджест #сводка")
    return "\n".join(lines)

def generate_card(items: list[dict]) -> str:
    """
    Временная логика: одна «мысль‑заметка» из первого материала.
    """
    if not items:
        return "Мысль дня: делайте маленькие шаги — каждый день. #карточка"
    it = items[0]
    title = it["title"] or "Мысль дня"
    link = it["link"] or ""
    return f"Мысль дня: {title}\n{link}\n\n#карточка"

def generate_practice() -> str:
    return "Практика недели: правило 2 минут. Начните с малого — сделайте за 2 минуты то, что откладывали. #практика"

def generate_quote() -> str:
    return "«Вы — результат того, что делаете каждый день». #цитата"

def generate_by_format(fmt: str, items: list[dict]) -> str:
    fmt = (fmt or "").lower()
    if fmt == "summary5":
        return generate_summary5(items)
    if fmt == "card":
        return generate_card(items)
    if fmt == "practice":
        return generate_practice()
    if fmt == "quote":
        return generate_quote()
    # дефолт
    return generate_summary5(items)
