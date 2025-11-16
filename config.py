import os

from dotenv import load_dotenv

# Загружаем переменные окружения (API ключи) из файла .env
load_dotenv()

# Ключ для доступа к API (поддержка обоих вариантов названия)
OPEN_ROUTER_API_KEY = os.getenv("OPEN_ROUTER_API_KEY") or os.getenv("OPENROUTER_API_KEY")

# Базовый URL для всех запросов
BASE_URL = "https://openrouter.ai/api/v1"

LOGGING_TOKEN_USAGE = True  # Логгировать использование токенов
LOGGING_TIME_USAGE = True  # Логгировать использование времени

# Файлы для артефактов
REGULATORY_CONSULTANT_FAISS_INDEX_PATH = "artefacts/regulatory_consultant_faiss_index.bin"
REGULATORY_CONSULTANT_CHUNKS_PATH = "artefacts/corpus_chunks.pkl"

# Использование локальных файлов RAG
USE_LOCAL_RAG_FILES = True
SAVE_RAG_FILES = True
