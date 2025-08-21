import random

def make_content(fmt: str) -> str:
    if fmt == "quote":
        return random.choice([
            "«Успех — это ежедневные маленькие шаги».",
            "«Чтение — это тренировка ума».",
            "«Привычки сильнее мотивации»."
        ])
    elif fmt == "summary5":
        return "5 идей из книги дня: 1) ... 2) ... 3) ... 4) ... 5) ..."
    elif fmt == "practice":
        return "Практика недели: правило 2 минут."
    elif fmt == "card":
        return "Карточка: одна мысль — одно действие. #ЧитайДелай"
    else:
        return "Пост по расписанию."
