# max-autopost-bot

Автопостинг в Max/Telegram через Bot API.

## Структура
- `app/` — основной код
- `config/channels.yaml` — список каналов
- `config/schedules.yaml` — расписание
- `requirements.txt` — зависимости
- `Procfile` — команда запуска для облака

## Локальный запуск
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# отредактируй .env и запусти
python -m app.main

