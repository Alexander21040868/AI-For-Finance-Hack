# -*- coding: utf-8 -*-

import os
import requests
import pandas as pd
import numpy as np
import faiss
from tqdm import tqdm
from dotenv import load_dotenv
from openai import OpenAI
from langchain_text_splitters import RecursiveCharacterTextSplitter
import concurrent.futures
import pickle
import threading
import datetime
import time
import functools

# === 1. КОНФИГУРАЦИЯ И НАСТРОЙКА ===

# Загружаем переменные окружения (API ключи) из файла .env
load_dotenv()

# Ключи для доступа к API
LLM_API_KEY = os.getenv("LLM_API_KEY")
EMBEDDER_API_KEY = os.getenv("EMBEDDER_API_KEY")

# Базовый URL для всех запросов
BASE_URL = "https://ai-for-finance-hack.up.railway.app/"

# Названия моделей
EMBEDDING_MODEL = "text-embedding-3-small"
GENERATION_MODEL = "openrouter/mistralai/mistral-small-3.2-24b-instruct"

# Параметры для обработки данных
CHUNK_SIZE = 1024
CHUNK_OVERLAP = 150
EMBEDDING_BATCH_SIZE = 100  # Отправляем по 100 чанков за один API-запрос
FAISS_DIMENSION = 1536  # Размерность векторов для модели text-embedding-3-small
K_FINAL_CHUNKS = 7  # Количество наиболее релевантных чанков для поиска

# NEW:
ASYNC_MODE = True # Обрабатывать вопросы пользователей в асинхронном (True) либо синхронном (False) режиме
MAX_WORKERS = 10 # Число параллельных обработчиков
USE_LOCAL_RAG_FILES = True # Использовать RAG-артефакты, которые уже сохранены в директории
FAISS_INDEX_PATH = "faiss_index.bin"
CHUNKS_PATH = "corpus_chunks.pkl"
LOGGING_TOKEN_USAGE = True
LOGGING_TIME_USAGE = True

# Настройки Rerank:
USE_RERANKER = True
RETRIEVAL_K_FOR_RERANK = 30 # Сколько чанков изначально достаем из FAISS для переранжирования

# Инициализация клиентов для OpenAI API
# Один клиент для генерации ответов, другой для создания эмбеддингов
llm_client = OpenAI(base_url=BASE_URL, api_key=LLM_API_KEY)
embedder_client = OpenAI(base_url=BASE_URL, api_key=EMBEDDER_API_KEY)

class TokenUsageLogger:
    def __init__(self):
        self.data = []
        self._lock = threading.Lock()
        self.run_timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    def log_usage(self, usage, model_name: str, task: str, task_data: str) -> None:
        """Сохраняет данные об использовании токенов моделью"""
        if not LOGGING_TOKEN_USAGE:
            return
        with self._lock:
            log = {
                "model_name": model_name,
                "task": task,
                "task_data": task_data,
                "prompt_tokens": getattr(usage, 'prompt_tokens', 0),
                "completion_tokens": getattr(usage, 'completion_tokens', 0),
                "total_tokens": getattr(usage, 'total_tokens', 0),
            }
            self.data.append(log)

    def save_reports(self, output_dir="logs"):
        if not LOGGING_TOKEN_USAGE:
            pass
        os.makedirs(output_dir, exist_ok=True)

        full_log_df = pd.DataFrame(self.data)
        full_log_path = os.path.join(output_dir, f"{self.run_timestamp}_token_usage_full_log.csv")
        full_log_df.to_csv(full_log_path, index=False, encoding='utf-8')
        print(f"\nПолный лог использования токенов сохранен в: {full_log_path}")

        by_model_task = full_log_df.groupby(['model_name', 'task']).agg(
            prompt_tokens=('prompt_tokens', 'sum'),
            completion_tokens=('completion_tokens', 'sum'),
            total_tokens=('total_tokens', 'sum'),
            call_count=('model_name', 'size')
        ).reset_index()

        total_tokens_overall = by_model_task['total_tokens'].sum()
        if total_tokens_overall > 0:
            by_model_task['percentage_of_total'] = (by_model_task['total_tokens'] / total_tokens_overall * 100).round(2)

        by_model_task_path = os.path.join(output_dir, f"{self.run_timestamp}_token_usage_by_model_task.csv")
        by_model_task.to_csv(by_model_task_path, index=False, encoding='utf-8')
        print(f"Агрегированный отчет по задачам сохранен в: {by_model_task_path}")

        print("\n--- Сводный отчет по использованию токенов (Модель + Задача) ---")
        by_model_task_display = by_model_task.copy()
        for col in ['prompt_tokens', 'completion_tokens', 'total_tokens', 'call_count']:
            by_model_task_display[col] = by_model_task_display[col].apply(lambda x: f"{x:,}")
        if 'percentage_of_total' in by_model_task_display.columns:
            by_model_task_display['percentage_of_total'] = by_model_task_display['percentage_of_total'].apply(
                lambda x: f"{x}%")

        print(by_model_task_display.to_string(index=False))
        print("-----------------------------------------------------------------")


class TimeUsageLogger:
    """Класс для сбора и анализа времени выполнения различных задач."""

    def __init__(self):
        self.data = []
        self._lock = threading.Lock()
        self.run_timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    def log_time(self, task_name: str, duration_seconds: float) -> None:
        """Сохраняет данные о времени выполнения задачи."""
        if not LOGGING_TIME_USAGE:
            return
        with self._lock:
            log_entry = {
                "task_name": task_name,
                "duration_seconds": duration_seconds,
            }
            self.data.append(log_entry)

    def save_reports(self, output_dir="logs"):
        """Сохраняет полный и агрегированный отчеты по времени выполнения."""
        if not LOGGING_TIME_USAGE or not self.data:
            return
        os.makedirs(output_dir, exist_ok=True)

        # 1. Сохранение полного лога
        full_log_df = pd.DataFrame(self.data)
        full_log_path = os.path.join(output_dir, f"{self.run_timestamp}_time_usage_full_log.csv")
        full_log_df.to_csv(full_log_path, index=False, encoding='utf-8')
        print(f"\nПолный лог времени выполнения сохранен в: {full_log_path}")

        # 2. Создание и сохранение агрегированного отчета
        agg_report = full_log_df.groupby('task_name').agg(
            total_duration_sec=('duration_seconds', 'sum'),
            call_count=('task_name', 'size'),
            avg_duration_sec=('duration_seconds', 'mean'),
            min_duration_sec=('duration_seconds', 'min'),
            max_duration_sec=('duration_seconds', 'max')
        ).reset_index()

        agg_report = agg_report.sort_values(by='total_duration_sec', ascending=False)

        # Добавляем процент от общего времени
        total_time_overall = agg_report['total_duration_sec'].sum()
        if total_time_overall > 0:
            agg_report['percentage_of_total_time'] = \
                (agg_report['total_duration_sec'] / total_time_overall * 100).round(2)

        agg_report_path = os.path.join(output_dir, f"{self.run_timestamp}_time_usage_summary.csv")
        agg_report.to_csv(agg_report_path, index=False, encoding='utf-8')
        print(f"Агрегированный отчет по времени выполнения сохранен в: {agg_report_path}")

        # 3. Вывод красивой таблицы в консоль
        print("\n--- Сводный отчет по времени выполнения (Задача) ---")
        display_df = agg_report.copy()
        for col in ['total_duration_sec', 'avg_duration_sec', 'min_duration_sec', 'max_duration_sec']:
            display_df[col] = display_df[col].apply(lambda x: f"{x:.3f}s")
        if 'percentage_of_total_time' in display_df.columns:
            display_df['percentage_of_total_time'] = display_df['percentage_of_total_time'].apply(
                lambda x: f"{x}%")

        print(display_df.to_string(index=False))
        print("-------------------------------------------------------")

token_logger = TokenUsageLogger()
time_logger = TimeUsageLogger()

def timed(func):
    """Декоратор для измерения времени выполнения функции."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        if not LOGGING_TIME_USAGE:  # Проверяем флаг в начале
            return func(*args, **kwargs)
        start_time = time.perf_counter()
        result = func(*args, **kwargs)
        end_time = time.perf_counter()
        duration = end_time - start_time
        time_logger.log_time(func.__name__, duration)
        return result

    return wrapper

@timed
def rerank_docs(query, documents, key):
    url = "https://ai-for-finance-hack.up.railway.app/rerank"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {key}"
    }
    payload = {
        "model": "deepinfra/Qwen/Qwen3-Reranker-4B",
        "query": query,
        "documents": documents
    }
    response = requests.post(url, headers=headers, json=payload)
    return response.json()


# === 2. ФУНКЦИИ ПАЙПЛАЙНА ===
@timed
def get_embeddings_in_batches(texts_list, model, batch_size, show_progress=False):
    """
    Получает эмбеддинги для списка текстов, отправляя их пакетами (батчами).
    Это значительно эффективнее, чем отправлять по одному.
    """
    all_embeddings = []
    iterator = range(0, len(texts_list), batch_size)

    if show_progress:
        iterator = tqdm(iterator, desc="Создание эмбеддингов")

    for i in iterator:
        batch = texts_list[i:i + batch_size]
        try:
            response = embedder_client.embeddings.create(input=batch, model=model)
            embeddings = [item.embedding for item in response.data]
            all_embeddings.extend(embeddings)
        except Exception as e:
            print(f"Ошибка при обработке батча {i // batch_size}: {e}")
            all_embeddings.extend([[0.0] * FAISS_DIMENSION] * len(batch))

    return np.array(all_embeddings).astype('float32')

@timed
def create_rag_artifacts(file_path):
    """
    Основная функция для создания артефактов RAG:
    1. Загружает и подготавливает данные.
    2. Разбивает текст на чанки.
    3. Создает векторные представления (эмбеддинги) для чанков.
    4. Создает и наполняет поисковый индекс FAISS.
    Возвращает: индекс FAISS и список всех текстовых чанков.
    """
    print("Шаг 1: Загрузка и подготовка данных...")
    df = pd.read_csv(file_path)
    df['combined_text'] = ("Тэги: " + df['tags'].fillna('').astype(str) +
                           ". Аннотация: " + df['annotation'].fillna('').astype(str) +
                           ". Текст: " + df['text'].fillna('').astype(str))

    print("Шаг 2: Разбиение документов на чанки...")
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)
    all_chunks = []
    for _, row in df.iterrows():
        metadata_prefix = f"Источник: {row['id']}. Тэги: {row['tags']}. "

        annotation_text = str(row['annotation']) if pd.notna(row['annotation']) else ""
        main_text = str(row['text']) if pd.notna(row['text']) else ""
        text_to_split = annotation_text + "\n\n" + main_text

        chunks = text_splitter.split_text(text_to_split)
        for chunk in chunks:
            all_chunks.append(metadata_prefix + chunk)

    print(f"Всего создано {len(all_chunks)} чанков с метаданными.")
    print(f"Шаг 3: Создание эмбеддингов для чанков (модель: {EMBEDDING_MODEL})...")
    chunk_embeddings = get_embeddings_in_batches(all_chunks, EMBEDDING_MODEL, EMBEDDING_BATCH_SIZE,
                                                 show_progress=True)

    print("Шаг 4: Создание и наполнение индекса FAISS...")
    index = faiss.IndexFlatL2(FAISS_DIMENSION)
    index.add(chunk_embeddings)
    print(f"Индекс FAISS успешно создан. В нем {index.ntotal} векторов.")

    return index, all_chunks

@timed
def expand_question(question: str) -> str:
    """Использует LLM для генерации альтернативных формулировок вопроса."""
    prompt = f"""Ты — AI-ассистент. Твоя задача — сгенерировать 3 альтернативных формулировки для заданного вопроса, чтобы улучшить поиск в базе знаний. Не отвечай на вопрос, а только перефразируй его. Выведи каждый вариант с новой строки, без нумерации.

Оригинальный вопрос: {question}

Альтернативные формулировки:"""
    try:
        response = llm_client.chat.completions.create(
            model=GENERATION_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.8
        )
        expanded_queries = response.choices[0].message.content.strip().split('\n')
        token_logger.log_usage(response.usage, GENERATION_MODEL, "expand_question", f"{question=} {expanded_queries=}")
        return [q.strip() for q in expanded_queries if q.strip()]
    except Exception as e:
        print(f"Ошибка при расширении вопроса: {e}")
        return []

@timed
def generate_hypothetical_answer(question: str) -> str:
    """Генерирует гипотетический ответ на вопрос, не основываясь на базу данных,
    чтобы затем использовать его для поиска по базе данных"""
    prompt = f"""Ты — AI-ассистент. Пожалуйста, сгенерируй короткий, но полный гипотетический ответ на следующий вопрос. Этот ответ будет использован для поиска информации в базе знаний. Не говори, что ты не знаешь ответа. Просто придумай правдоподобный ответ.

Вопрос: {question}

Гипотетический ответ:"""
    try:
        response = llm_client.chat.completions.create(
            model=GENERATION_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0
        )
        hypothetical_answer = response.choices[0].message.content
        token_logger.log_usage(response.usage, GENERATION_MODEL, "generate_hypothetical_answer", f"{question=} {hypothetical_answer=}")
        return hypothetical_answer
    except Exception as e:
        print(f"Ошибка при генерации гипотетического ответа: на вопрос {question}: {e}")
        return question

@timed
def answer_question(question, index, all_chunks):
    """
    Принимает вопрос, РАСШИРЯЕТ его, генерирует гипотетический ответ на вопрос,
    находит релевантный контекст и генерирует ответ.
    """
    all_queries = [question]

    expanded_questions = expand_question(question)
    hypothetical_answer = generate_hypothetical_answer(question)

    all_queries.extend(expanded_questions)
    all_queries.append(hypothetical_answer)

    query_embeddings = get_embeddings_in_batches(all_queries, EMBEDDING_MODEL, 10)

    retrieved_indices = set()
    k_retrieval = RETRIEVAL_K_FOR_RERANK if USE_RERANKER else K_FINAL_CHUNKS
    _, I = index.search(query_embeddings, k_retrieval)
    for indices_per_query in I:
        for idx in indices_per_query:
            retrieved_indices.add(idx)

    retrieved_chunks = [all_chunks[i] for i in retrieved_indices]
    if not USE_RERANKER:
        final_chunks = retrieved_chunks
    else:
        # Переранжирование с помощью RERANKER
        try:
            reranked_response = rerank_docs(
                query=question,
                documents=retrieved_chunks,
                key=EMBEDDER_API_KEY
            )

            results = reranked_response.get('results')
            sorted_results = sorted(results, key=lambda x: x['relevance_score'], reverse=True)
            reranked_docs = [retrieved_chunks[res['index']] for res in sorted_results]
            final_chunks = reranked_docs[:K_FINAL_CHUNKS]
        except Exception as e:
            print(f"Ошибка при переранжировании с помощью RERANKER: {e}")
            print("Использую обычное ранжирование")
            final_chunks = retrieved_chunks[:K_FINAL_CHUNKS]


    context = "\n\n---\n\n".join(final_chunks)

    prompt = f"""Ты — умный и точный финансовый ассистент. Твоя задача — ответить на вопрос пользователя, основываясь на предоставленном ниже контексте. 
    Не используй свои собственные знания и не придумывай информацию. Не говори в ответе, на какие источники ты ссылаешься и вообще никак не упоминай в своём ответе контекст, только используй знания из контекста. 
    Если в контексте нет ответа на вопрос, вежливо сообщи: "В предоставленной базе знаний нет информации по вашему вопросу". 
    Проанализируй все фрагменты контекста. Если информация для ответа содержится в нескольких фрагментах, синтезируй из них единый, полный и связный ответ.

### КОНТЕКСТ ИЗ БАЗЫ ЗНАНИЙ
{context}

### ВОПРОС ПОЛЬЗОВАТЕЛЯ
{question}

### ТВОЙ ОТВЕТ
"""
    try:
        response = llm_client.chat.completions.create(
            model=GENERATION_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0
        )
        final_answer = response.choices[0].message.content
        token_logger.log_usage(response.usage, GENERATION_MODEL, "answer_question",
                               f"{question=} {final_answer=}")
        return final_answer
    except Exception as e:
        print(f"Ошибка при генерации ответа на вопрос '{question}': {e}")
        return "Произошла ошибка при генерации ответа."


# === 3. ОСНОВНОЙ БЛОК ЗАПУСКА ===

if __name__ == "__main__":
    print("--- Запуск пайплайна финансового ассистента ---")

    # Этап I: Подготовка RAG-артефактов (индексация базы знаний)

    if USE_LOCAL_RAG_FILES and os.path.exists(FAISS_INDEX_PATH) and os.path.exists(CHUNKS_PATH):
        # Вариант с локальными файлами (чтобы не жечь токены в ембеддинг-модели зря)
        print(f"Использую сохраненные RAG-артефакты. Загрузка из '{FAISS_INDEX_PATH}' и '{CHUNKS_PATH}'...")
        faiss_index = faiss.read_index(FAISS_INDEX_PATH)
        with open(CHUNKS_PATH, 'rb') as f:
            corpus_chunks = pickle.load(f)
        print("Артефакты RAG успешно загружены.")
    else:
        print("RAG-артефакты будут сгенерированы с нуля.")
        faiss_index, corpus_chunks = create_rag_artifacts('./train_data.csv')
        print(f"Сохранение индекса FAISS в файл '{FAISS_INDEX_PATH}'...")
        faiss.write_index(faiss_index, FAISS_INDEX_PATH)

        print(f"Сохранение чанков в файл '{CHUNKS_PATH}'...")
        with open(CHUNKS_PATH, 'wb') as f:
            pickle.dump(corpus_chunks, f)

    print("\n--- Подготовка завершена. Начинаем генерацию ответов на вопросы. ---")

    # Этап II: Генерация ответов на вопросы из questions.csv
    questions_df = pd.read_csv('./questions.csv')
    questions = questions_df['Вопрос'].tolist()
    answers = [None] * len(questions)

    if not ASYNC_MODE:
        for i, question in tqdm(enumerate(questions), desc="Обработка вопросов"):
            answer = answer_question(question, faiss_index, corpus_chunks)
            answers[i] = answer
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            future_to_question = {
                executor.submit(answer_question, question, faiss_index, corpus_chunks): i
                for i, question in enumerate(questions)
            }

            for future in tqdm(concurrent.futures.as_completed(future_to_question), total=len(questions),
                               desc="Обработка вопросов"):
                question_index = future_to_question[future]
                answer = future.result()
                answers[question_index] = answer

    # Сохранение результатов
    questions_df['Ответы на вопрос'] = answers
    questions_df.to_csv('submission.csv', index=False, encoding='utf-8')
    print("\n--- Все ответы сгенерированы. Файл submission.csv успешно сохранен. ---")

    # Сохранение логов
    token_logger.save_reports()
    time_logger.save_reports()