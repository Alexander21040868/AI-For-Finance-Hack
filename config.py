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
RAW_DOCUMENTS_PATH = "knowledge_base_builder/output/raw_documents.jsonl"

# Использование локальных файлов RAG
USE_LOCAL_RAG_FILES = True
SAVE_RAG_FILES = True

# Параметры для TransactionAnalyzer
TRANSACTION_ANALYZER_CONFIG = {
    "batch_size": 20,  # Количество транзакций в одном батче
    "max_retries": 3,  # Максимальное количество попыток при ошибке API
    "retry_delay": 1.0,  # Задержка между попытками (секунды)
    "timeout": 30.0,  # Таймаут для LLM запроса (секунды)
    "new_counterparty_threshold": 10000,  # Порог суммы для уведомления о новом контрагенте
    "outlier_sigma_threshold": 2.5,  # Порог для определения outliers (стандартные отклонения) - снижен для более чувствительного обнаружения
    "cac_warning_threshold": 0.3,  # Порог для предупреждения о высоком CAC
}

# Параметры для RAG (RegulatoryConsultant)
RAG_CONFIG = {
    "chunk_size": 1024,  # Размер чанка в символах для разбиения документов
    "chunk_overlap": 150,  # Перекрытие между чанками (символы)
    "embedding_batch_size": 100,  # Количество чанков в одном батче для создания эмбеддингов
    "faiss_dimension": 1536,  # Размерность векторов для модели text-embedding-3-small
    "k_final_chunks": 7,  # Количество наиболее релевантных чанков для поиска
    "use_reranker": False,  # Использовать ли reranker (отключено, так как нет в OpenRouter)
    "retrieval_k_for_rerank": 30,  # Сколько чанков изначально достаем из FAISS для переранжирования
}

# Параметры для Knowledge Base Builder
KNOWLEDGE_BASE_BUILDER_CONFIG = {
    "article_limit_per_section": 30,  # Количество статей на раздел при парсинге klerk.ru
    "chunk_size": 1500,  # Размер чанка для chunk_data.py (если используется отдельно)
    "chunk_overlap": 200,  # Перекрытие чанков для chunk_data.py (если используется отдельно)
}
