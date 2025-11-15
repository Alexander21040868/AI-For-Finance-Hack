# -*- coding: utf-8 -*-
import os
import json

from openai import OpenAI

from config import BASE_URL, OPEN_ROUTER_API_KEY
from config import REGULATORY_CONSULTANT_CHUNKS_PATH
from config import REGULATORY_CONSULTANT_FAISS_INDEX_PATH
from config import SAVE_RAG_FILES
from config import USE_LOCAL_RAG_FILES
from document_analyzer import DocumentAnalyzer
from regulatory_consultant import RegulatoryConsultant
from transaction_analyzer import TransactionAnalyzer
from time_logger import timed, time_logger
from token_logger import token_logger

from document_utils import batch_extract_text

# === 1. КОНФИГУРАЦИЯ И НАСТРОЙКА ===
EMBEDDING_MODEL = "openai/text-embedding-3-small"
GENERATION_MODEL = "google/gemini-2.5-flash-lite"

# Инициализация клиентов для OpenAI API
open_router_client = OpenAI(base_url=BASE_URL, api_key=OPEN_ROUTER_API_KEY)

@timed
def choose_tool(user_prompt: str, documents: list[dict[str, str]] | None) -> str:
    """По запросу пользователя определяет, каким инструментом лучше отвечать на его запрос"""
    print("\nЗапуск роутера для выбора инструмента...")

    # Форматируем контекст для подачи в модель
    context = f"Промпт пользователя: '{user_prompt}'\n\n"
    context += "--- Текстовое содержимое предоставленных документов ---\n"
    for doc in documents:
        if "text" in doc:
            context += f"\n[Документ: {doc['filename']}]\n{doc['text']}\n---"

    router_prompt = f"""
    Ты — умный диспетчер для AI-ассистента "ФинПульс". Твоя задача — проанализировать запрос пользователя и определить, какой из доступных инструментов нужно использовать для его выполнения. Ты должен вернуть ТОЛЬКО название одного инструмента.

Вот список доступных инструментов и их описание:
1.  **TransactionAnalyzer**: Используй этот инструмент, когда пользователь загружает файл с банковской выпиской (обычно .csv или .xlsx) или просит проанализировать свои доходы и расходы, рассчитать налог на основе транзакций. Ключевые слова: "выписка", "транзакции", "рассчитай налог", "доходы и расходы", "загрузил файл".
2.  **DocumentAnalyzer**: Используй этот инструмент, когда пользователь загружает документ (обычно .pdf, .docx, .jpg), который нужно проанализировать на предмет рисков, например, договор, акт, счет-оферту. Ключевые слова: "договор", "акт", "счет", "оферта", "проанализируй документ", "риски в договоре".
3.  **RegulatoryConsultant**: Используй этот инструмент, когда пользователь задает прямой вопрос о налогах, бухгалтерии, законах или просит дать совет. Этот инструмент используется для консультаций и ответов на вопросы, а не для анализа файлов. Ключевые слова: "как", "что", "можно ли", "нужно ли", "какой КБК", "налоговый вычет".

### Инструкции:
1.  Внимательно прочитай запрос пользователя.
2.  Кратко порассуждай, к какому типу задач относится запрос.
3.  На основе рассуждения выбери ОДИН наиболее подходящий инструмент.
4.  Выведи ответ в формате JSON: {"thought": "Твои рассуждения здесь.", "tool_name": "НАЗВАНИЕ_ИНСТРУМЕНТА"}

### Запрос пользователя:
{context}

### Твой ответ:
    """

    response = open_router_client.chat.completions.create(
        model=GENERATION_MODEL,
        messages=[{"role": "user", "content": router_prompt}],
        response_format={"type": "json_object"}
    )

    chosen_tool = json.loads(response.choices[0].message.content)

    print(f"Роутер выбрал инструмент: '{chosen_tool['tool_name']}'")
    return chosen_tool

# Инициализация базовых инструментов
regulatory_consultant = RegulatoryConsultant(open_router_client,
                                            EMBEDDING_MODEL,
                                            GENERATION_MODEL,
                                            USE_LOCAL_RAG_FILES,
                                            SAVE_RAG_FILES,
                                            REGULATORY_CONSULTANT_FAISS_INDEX_PATH,
                                            REGULATORY_CONSULTANT_CHUNKS_PATH
                                            )

document_analyzer = DocumentAnalyzer(open_router_client,
                                     GENERATION_MODEL
                                     )

transaction_analyzer = TransactionAnalyzer(open_router_client,
                                           GENERATION_MODEL
                                           )

# Функции, генерирующие ответ для каждого из инструментов
TOOL_REGISTRY = {
    "TransactionAnalyzer": lambda x, y: None,
    "DocumentAnalyzer": document_analyzer.generate_summary,
    "RegulatoryConsultant": regulatory_consultant.answer_question,
}


def respond(user_prompt: str, file_paths: list[str]) -> str | None:
    """Основная функция генерации ответа на промпт пользователя"""
    file_paths = [path for path in file_paths if os.path.exists(path)]

    if not file_paths:
        extracted_documents_text = None
    else:
        extracted_documents_text = batch_extract_text(file_paths)

    routing_decision = choose_tool(user_prompt, extracted_documents_text)
    tool_name = routing_decision.get("tool_name")

    final_result = None
    if tool_name in TOOL_REGISTRY:
        selected_tool = TOOL_REGISTRY[tool_name]

        # Инструмент получает оригинальный промпт и весь извлеченный текст из документов
        final_result = selected_tool(user_prompt, extracted_documents_text)
    else:
        print(f"\n[Ошибка]: Роутер вернул неизвестный инструмент '{tool_name}'")

    time_logger.save_reports()
    token_logger.save_reports()
    return final_result