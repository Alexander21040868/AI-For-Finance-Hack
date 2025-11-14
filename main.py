# -*- coding: utf-8 -*-

from openai import OpenAI

from config import BASE_URL, OPEN_ROUTER_API_KEY
from config import REGULATORY_CONSULTANT_CHUNKS_PATH
from config import REGULATORY_CONSULTANT_FAISS_INDEX_PATH
from config import SAVE_RAG_FILES
from config import USE_LOCAL_RAG_FILES
from regulatory_consultant import RegulatoryConsultant
from time_logger import time_logger
from token_logger import token_logger

# === 1. КОНФИГУРАЦИЯ И НАСТРОЙКА ===
EMBEDDING_MODEL = "openai/text-embedding-3-small"
GENERATION_MODEL = "mistralai/mistral-small-3.2-24b-instruct"

# Инициализация клиентов для OpenAI API
open_router_client = OpenAI(base_url=BASE_URL, api_key=OPEN_ROUTER_API_KEY)

if __name__ == "__main__":
    # Этап I: Инициализация частей агента
    financial_consultant = RegulatoryConsultant(open_router_client,
                                                EMBEDDING_MODEL,
                                                GENERATION_MODEL,
                                                USE_LOCAL_RAG_FILES,
                                                SAVE_RAG_FILES,
                                                REGULATORY_CONSULTANT_FAISS_INDEX_PATH,
                                                REGULATORY_CONSULTANT_CHUNKS_PATH
                                                )

    print("\n--- Инициализация частей агента завершена.")

    # Сохранение логов
    token_logger.save_reports()
    time_logger.save_reports()
