#!/usr/bin/env bash
set -euo pipefail

# обновим pip и поставим зависимости проекта
python -m pip install --upgrade pip
if [ -f requirements.txt ]; then
  pip install -r requirements.txt
fi

# установим aider через pipx (изолированно)
python -m pip install --upgrade pipx
pipx install aider-install
pipx install aider-chat

# небольшие утилиты
pip install ruff black

echo "✅ Post-create готово: Aider установлен."
