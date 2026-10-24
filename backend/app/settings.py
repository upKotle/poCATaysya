import json
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
# Загружаем только файл проекта, независимо от рабочей директории запуска.
# Явно переданные переменные окружения имеют приоритет.
load_dotenv(ROOT / ".env", override=False)
CONFIG = json.loads((ROOT / "config/moscow.json").read_text())
WARNING = "Время рассчитано без актуальных пробок. Это планировщик поездок, не навигатор"
