# -*- coding: utf-8 -*-

import os
import re
import json
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
from typing import TypedDict, List

# === НОВЫЕ ИМПОРТЫ ДЛЯ LANGGRAPH ===
from langgraph.graph import StateGraph, END

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

# Параметры для обработки данных (из вашего кода)
CHUNK_SIZE = 1024
CHUNK_OVERLAP = 150
EMBEDDING_BATCH_SIZE = 100
FAISS_DIMENSION = 1536
K_FINAL_CHUNKS = 7

# Асинхронная обработка (из вашего кода)
ASYNC_MODE = True
MAX_WORKERS = 10

# Настройки Rerank (из вашего кода)
USE_RERANKER = True
RETRIEVAL_K_FOR_RERANK = 30

# === НОВЫЕ НАСТРОЙКИ ДЛЯ ВЫБОРА РЕЖИМА И УПРАВЛЕНИЯ ЦИКЛАМИ ===

# Переключатель режимов:
# False: RAG с циклом улучшения ОТВЕТА (запрос №1)
# True:  Self-Reflective RAG с циклом улучшения ПОИСКА и ОТВЕТА (запрос №2)
USE_SELF_REFLECTIVE_RAG = True

# Максимальное количество циклов для каждого типа
MAX_ANSWER_REFINEMENT_CYCLES = 3  # Для простого RAG (улучшение ответа)
MIN_SCORE_TO_FINISH = 0.85  # Порог качества ответа для выхода из цикла

MAX_SEARCH_CYCLES = 3  # Для Self-Reflective RAG (улучшение поиска)

# Параметры для режима разработки (из вашего кода)
USE_LOCAL_RAG_FILES = False
SAVE_RAG_FILES = False
LOGGING_TOKEN_USAGE = False
LOGGING_TIME_USAGE = False
FAISS_INDEX_PATH = "faiss_index.bin"
CHUNKS_PATH = "corpus_chunks.pkl"

# Инициализация клиентов для OpenAI API
llm_client = OpenAI(base_url=BASE_URL, api_key=LLM_API_KEY)
embedder_client = OpenAI(base_url=BASE_URL, api_key=EMBEDDER_API_KEY)


# === КЛАССЫ ЛОГИРОВАНИЯ И ДЕКОРАТОР timed (БЕЗ ИЗМЕНЕНИЙ ИЗ ВАШЕГО КОДА) ===
class TokenUsageLogger:
    def __init__(self):
        self.data = []
        self._lock = threading.Lock()
        self.run_timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    def log_usage(self, usage, model_name: str, task: str, task_data: str) -> None:
        if not LOGGING_TOKEN_USAGE: return
        with self._lock: self.data.append({"model_name": model_name, "task": task, "task_data": task_data,
                                           "prompt_tokens": getattr(usage, 'prompt_tokens', 0),
                                           "completion_tokens": getattr(usage, 'completion_tokens', 0),
                                           "total_tokens": getattr(usage, 'total_tokens', 0)})

    def save_reports(self, output_dir="logs"):
        if not LOGGING_TOKEN_USAGE or not self.data: return
        os.makedirs(output_dir, exist_ok=True);
        full_log_df = pd.DataFrame(self.data);
        full_log_path = os.path.join(output_dir, f"{self.run_timestamp}_token_usage_full_log.csv");
        full_log_df.to_csv(full_log_path, index=False, encoding='utf-8');
        print(f"\nПолный лог использования токенов сохранен в: {full_log_path}");
        by_model_task = full_log_df.groupby(['model_name', 'task']).agg(prompt_tokens=('prompt_tokens', 'sum'),
                                                                        completion_tokens=('completion_tokens', 'sum'),
                                                                        total_tokens=('total_tokens', 'sum'),
                                                                        call_count=('model_name',
                                                                                    'size')).reset_index();
        total_tokens_overall = by_model_task['total_tokens'].sum();
        if total_tokens_overall > 0: by_model_task['percentage_of_total'] = (
                    by_model_task['total_tokens'] / total_tokens_overall * 100).round(2)
        by_model_task_path = os.path.join(output_dir, f"{self.run_timestamp}_token_usage_by_model_task.csv");
        by_model_task.to_csv(by_model_task_path, index=False, encoding='utf-8');
        print(f"Агрегированный отчет по задачам сохранен в: {by_model_task_path}");
        print("\n--- Сводный отчет по использованию токенов (Модель + Задача) ---");
        by_model_task_display = by_model_task.copy()
        for col in ['prompt_tokens', 'completion_tokens', 'total_tokens', 'call_count']: by_model_task_display[col] = \
        by_model_task_display[col].apply(lambda x: f"{x:,}")
        if 'percentage_of_total' in by_model_task_display.columns: by_model_task_display['percentage_of_total'] = \
        by_model_task_display['percentage_of_total'].apply(lambda x: f"{x}%")
        print(by_model_task_display.to_string(index=False));
        print("-----------------------------------------------------------------")


class TimeUsageLogger:
    def __init__(self):
        self.data = []; self._lock = threading.Lock(); self.run_timestamp = datetime.datetime.now().strftime(
            "%Y%m%d_%H%M%S")

    def log_time(self, task_name: str, duration_seconds: float) -> None:
        if not LOGGING_TIME_USAGE: return
        with self._lock: self.data.append({"task_name": task_name, "duration_seconds": duration_seconds})

    def save_reports(self, output_dir="logs"):
        if not LOGGING_TIME_USAGE or not self.data: return
        os.makedirs(output_dir, exist_ok=True);
        full_log_df = pd.DataFrame(self.data);
        full_log_path = os.path.join(output_dir, f"{self.run_timestamp}_time_usage_full_log.csv");
        full_log_df.to_csv(full_log_path, index=False, encoding='utf-8');
        print(f"\nПолный лог времени выполнения сохранен в: {full_log_path}");
        agg_report = full_log_df.groupby('task_name').agg(total_duration_sec=('duration_seconds', 'sum'),
                                                          call_count=('task_name', 'size'),
                                                          avg_duration_sec=('duration_seconds', 'mean'),
                                                          min_duration_sec=('duration_seconds', 'min'),
                                                          max_duration_sec=('duration_seconds',
                                                                            'max')).reset_index().sort_values(
            by='total_duration_sec', ascending=False);
        total_time_overall = agg_report['total_duration_sec'].sum()
        if total_time_overall > 0: agg_report['percentage_of_total_time'] = (
                    agg_report['total_duration_sec'] / total_time_overall * 100).round(2)
        agg_report_path = os.path.join(output_dir, f"{self.run_timestamp}_time_usage_summary.csv");
        agg_report.to_csv(agg_report_path, index=False, encoding='utf-8');
        print(f"Агрегированный отчет по времени выполнения сохранен в: {agg_report_path}");
        print("\n--- Сводный отчет по времени выполнения (Задача) ---");
        display_df = agg_report.copy()
        for col in ['total_duration_sec', 'avg_duration_sec', 'min_duration_sec', 'max_duration_sec']: display_df[col] = \
        display_df[col].apply(lambda x: f"{x:.3f}s")
        if 'percentage_of_total_time' in display_df.columns: display_df['percentage_of_total_time'] = display_df[
            'percentage_of_total_time'].apply(lambda x: f"{x}%")
        print(display_df.to_string(index=False));
        print("-------------------------------------------------------")


token_logger = TokenUsageLogger();
time_logger = TimeUsageLogger()


def timed(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        if not LOGGING_TIME_USAGE: return func(*args, **kwargs)
        start_time = time.perf_counter();
        result = func(*args, **kwargs);
        end_time = time.perf_counter();
        duration = end_time - start_time;
        time_logger.log_time(func.__name__, duration);
        return result

    return wrapper


# === ФУНКЦИИ ИЗ ВАШЕГО КОДА (rerank_docs, get_embeddings_in_batches, create_rag_artifacts) БЕЗ ИЗМЕНЕНИЙ ===
@timed
def rerank_docs(query, documents, key):
    response = requests.post("https://ai-for-finance-hack.up.railway.app/rerank",
                             headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
                             json={"model": "deepinfra/Qwen/Qwen3-Reranker-4B", "query": query,
                                   "documents": documents});
    return response.json()


@timed
def get_embeddings_in_batches(texts_list, model, batch_size, show_progress=False):
    all_embeddings = [];
    iterator = range(0, len(texts_list), batch_size)
    if show_progress: iterator = tqdm(iterator, desc="Создание эмбеддингов")
    for i in iterator:
        batch = texts_list[i:i + batch_size]
        try:
            response = embedder_client.embeddings.create(input=batch, model=model); embeddings = [item.embedding for
                                                                                                  item in
                                                                                                  response.data]; all_embeddings.extend(
                embeddings)
        except Exception as e:
            print(f"Ошибка при обработке батча {i // batch_size}: {e}"); all_embeddings.extend(
                [[0.0] * FAISS_DIMENSION] * len(batch))
    return np.array(all_embeddings).astype('float32')


@timed
def create_rag_artifacts(file_path):
    print("Шаг 1: Загрузка и подготовка данных...");
    df = pd.read_csv(file_path);
    print("Шаг 2: Разбиение документов на чанки...");
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP);
    all_chunks = []
    for _, row in df.iterrows(): metadata_prefix = f"Источник: {row['id']}. Тэги: {row['tags']}. "; text_to_split = (
                str(row['annotation'] if pd.notna(row['annotation']) else "") + "\n\n" + str(
            row['text'] if pd.notna(row['text']) else "")); chunks = text_splitter.split_text(
        text_to_split); all_chunks.extend([metadata_prefix + chunk for chunk in chunks])
    print(f"Всего создано {len(all_chunks)} чанков с метаданными.");
    print(f"Шаг 3: Создание эмбеддингов для чанков (модель: {EMBEDDING_MODEL})...");
    chunk_embeddings = get_embeddings_in_batches(all_chunks, EMBEDDING_MODEL, EMBEDDING_BATCH_SIZE, show_progress=True);
    print("Шаг 4: Создание и наполнение индекса FAISS...");
    index = faiss.IndexFlatL2(FAISS_DIMENSION);
    index.add(chunk_embeddings);
    print(f"Индекс FAISS успешно создан. В нем {index.ntotal} векторов.");
    return index, all_chunks


# === 2. БЛОК LANGGRAPH: СОСТОЯНИЕ И УЗЛЫ ===

# Определяем состояние графа, которое будет передаваться между узлами
class GraphState(TypedDict):
    question: str
    generation_prompt: str  # Ваш оригинальный промпт для генерации
    all_queries: List[str]  # Все поисковые запросы (для Self-Reflective RAG)
    documents: List[str]  # Все найденные чанки
    final_answer: str  # Текущий/финальный ответ
    # Счетчики циклов
    answer_refinement_cycles: int
    search_cycles: int
    # Поля для оценки и рефлексии
    answer_score: float
    reflection: dict


# --- Узлы графа (Nodes) ---
# Мы берем ваши оригинальные функции и превращаем их в узлы графа

@timed
def expand_question_node(state: GraphState) -> dict:
    """Узел для генерации альтернативных формулировок вопроса."""
    print("--- УЗЕЛ: Расширение вопроса ---")
    question = state['question']
    # ВАШ ОРИГИНАЛЬНЫЙ ПРОМПТ
    prompt = f"""Ты — AI-ассистент. Твоя задача — сгенерировать 3 альтернативных формулировки для заданного вопроса, чтобы улучшить поиск в базе знаний. Не отвечай на вопрос, а только перефразируй его. Выведи каждый вариант с новой строки, без нумерации.

Оригинальный вопрос: {question}

Альтернативные формулировки:"""
    try:
        response = llm_client.chat.completions.create(model=GENERATION_MODEL,
                                                      messages=[{"role": "user", "content": prompt}], temperature=0.8)
        expanded_queries = [q.strip() for q in response.choices[0].message.content.strip().split('\n') if q.strip()]
        token_logger.log_usage(response.usage, GENERATION_MODEL, "expand_question_node", f"{question=}")
        # Инициализируем all_queries
        return {"all_queries": [question] + expanded_queries}
    except Exception as e:
        print(f"Ошибка при расширении вопроса: {e}")
        return {"all_queries": [question]}


@timed
def hypothetical_answer_node(state: GraphState) -> dict:
    """Узел для генерации гипотетического ответа."""
    print("--- УЗЕЛ: Генерация гипотетического ответа ---")
    question = state['question']
    # ВАШ ОРИГИНАЛЬНЫЙ ПРОМПТ
    prompt = f"""Ты — AI-ассистент. Пожалуйста, сгенерируй короткий, но полный гипотетический ответ на следующий вопрос. Этот ответ будет использован для поиска информации в базе знаний. Не говори, что ты не знаешь ответа. Просто придумай правдоподобный ответ.

Вопрос: {question}

Гипотетический ответ:"""
    try:
        response = llm_client.chat.completions.create(model=GENERATION_MODEL,
                                                      messages=[{"role": "user", "content": prompt}], temperature=0.0)
        hypothetical_answer = response.choices[0].message.content
        token_logger.log_usage(response.usage, GENERATION_MODEL, "hypothetical_answer_node", f"{question=}")
        # Добавляем гипотетический ответ к списку запросов
        all_queries = state.get('all_queries', []) + [hypothetical_answer]
        return {"all_queries": all_queries}
    except Exception as e:
        print(f"Ошибка при генерации гипотетического ответа: {e}")
        return {}  # Не меняем состояние


@timed
def retrieve_and_rerank_node(state: GraphState, index: faiss.Index, all_chunks: List[str]) -> dict:
    """Узел для поиска в FAISS и переранжирования."""
    search_cycle = state.get('search_cycles', 1)
    print(f"--- УЗЕЛ: Поиск и Ранжирование (Итерация {search_cycle}) ---")

    # В Self-Reflective режиме мы используем все накопленные запросы
    queries_to_search = state.get('all_queries', [state['question']])

    query_embeddings = get_embeddings_in_batches(queries_to_search, EMBEDDING_MODEL, 10)

    # Находим индексы
    k_retrieval = RETRIEVAL_K_FOR_RERANK if USE_RERANKER else K_FINAL_CHUNKS
    _, I = index.search(query_embeddings, k_retrieval)

    # Собираем уникальные индексы из всех запросов
    retrieved_indices = set(idx for indices_per_query in I for idx in indices_per_query if idx != -1)

    # В Self-Reflective режиме добавляем новые чанки к уже найденным
    if USE_SELF_REFLECTIVE_RAG and state.get('documents'):
        # Это сложнее, т.к. документы - это тексты, а не индексы.
        # Для простоты и эффективности будем каждый раз искать заново по всем запросам и объединять.
        # Это гарантирует, что мы не потеряем контекст.
        current_docs_set = set(state['documents'])
        new_docs = [all_chunks[i] for i in retrieved_indices if all_chunks[i] not in current_docs_set]
        all_found_docs = state['documents'] + new_docs
        print(f"Найдено {len(new_docs)} новых чанков. Всего чанков: {len(all_found_docs)}")
    else:
        all_found_docs = [all_chunks[i] for i in retrieved_indices]

    if not all_found_docs:
        return {"documents": []}

    if not USE_RERANKER:
        final_chunks = all_found_docs[:K_FINAL_CHUNKS]
    else:
        try:
            reranked_response = rerank_docs(query=state['question'], documents=all_found_docs, key=EMBEDDER_API_KEY)
            sorted_results = sorted(reranked_response.get('results', []), key=lambda x: x['relevance_score'],
                                    reverse=True)
            reranked_docs = [all_found_docs[res['index']] for res in sorted_results]
            final_chunks = reranked_docs[:K_FINAL_CHUNKS]
        except Exception as e:
            print(f"Ошибка при переранжировании: {e}. Использую первые {K_FINAL_CHUNKS} чанков.")
            final_chunks = all_found_docs[:K_FINAL_CHUNKS]

    return {"documents": final_chunks}


@timed
def generate_answer_node(state: GraphState) -> dict:
    """Узел для генерации ответа на основе найденных чанков."""
    print("--- УЗЕЛ: Генерация ответа ---")
    context = "\n\n---\n\n".join(state["documents"])

    # ВАШ ОРИГИНАЛЬНЫЙ ПРОМПТ ДЛЯ ГЕНЕРАЦИИ
    prompt = f"""Ты — умный и точный финансовый ассистент. Твоя задача — ответить на вопрос пользователя, основываясь на предоставленном ниже контексте.

Действуй по следующему плану:
1.  Анализ запроса: Внимательно прочти вопрос пользователя и определи ключевые аспекты, которые нужно осветить.
2.  Поиск в контексте: Просканируй ВЕСЬ предоставленный контекст и найди все фрагменты, относящиеся к каждому аспекту вопроса.
3.  Синтез ответа: Собери найденную информацию в единый, логичный, исчерпывающий и user-friendly ответ.
4.  Финальная проверка: Убедись, что твой ответ полностью основан на контексте, не содержит выдуманной информации и не ссылается на "предоставленный контекст" (то есть не говори пользователю, что ты используешь контекст), и не содержит утечки промпта.

Если в контексте нет информации для ответа, вежливо сообщи: "В предоставленной базе знаний нет информации по вашему вопросу".

### КОНТЕКСТ ИЗ БАЗЫ ЗНАНИЙ
{context}

### ВОПРОС ПОЛЬЗОВАТЕЛЯ
{state['question']}

### ТВОЙ ОТВЕТ
"""
    try:
        response = llm_client.chat.completions.create(model=GENERATION_MODEL,
                                                      messages=[{"role": "user", "content": prompt}], temperature=0.0)
        final_answer = response.choices[0].message.content
        token_logger.log_usage(response.usage, GENERATION_MODEL, "generate_answer_node",
                               f"question={state['question']}")
        # Сохраняем и промпт, и ответ, и инициализируем счетчики
        return {"final_answer": final_answer, "generation_prompt": prompt, "answer_refinement_cycles": 1,
                "search_cycles": state.get("search_cycles", 1)}
    except Exception as e:
        print(f"Ошибка при генерации ответа: {e}")
        return {"final_answer": "Произошла ошибка при генерации ответа."}


# --- Новые узлы для циклов ---

@timed
def grade_answer_node(state: GraphState) -> dict:
    """Узел для оценки качества сгенерированного ответа."""
    print("--- УЗЕЛ: Оценка качества ответа ---")
    # Этот промпт новый, он необходим для цикла улучшения
    prompt = f"""Оцени, насколько полно и точно сгенерированный ответ соответствует вопросу. Выведи оценку в виде числа с плавающей точкой от 0.0 до 1.0.
0.0: Ответ нерелевантен. 0.5: Ответ частичный. 1.0: Ответ идеален.

### ВОПРОС\n{state['question']}\n\n### СГЕНЕРИРОВАННЫЙ ОТВЕТ\n{state['final_answer']}\n\n### ТВОЯ ОЦЕНКА (ТОЛЬКО ЧИСЛО ОТ 0.0 ДО 1.0):"""
    try:
        response = llm_client.chat.completions.create(model=GENERATION_MODEL,
                                                      messages=[{"role": "user", "content": prompt}], temperature=0.0,
                                                      max_tokens=5)
        score = float(re.search(r"(\d\.\d+)", response.choices[0].message.content).group(1))
        token_logger.log_usage(response.usage, GENERATION_MODEL, "grade_answer_node", f"question={state['question']}")
        print(f"  - Оценка ответа: {score:.2f}")
        return {"answer_score": score}
    except Exception as e:
        print(f"Ошибка при оценке ответа: {e}. Присвоена оценка 0.0.")
        return {"answer_score": 0.0}


@timed
def refine_answer_node(state: GraphState) -> dict:
    """Узел для улучшения ответа, если он получил низкую оценку."""
    print(f"--- УЗЕЛ: Улучшение ответа (Итерация {state.get('answer_refinement_cycles', 1) + 1}) ---")
    # Этот промпт тоже новый
    prompt = f"""Ты — эксперт по улучшению текстов. Тебе дан вопрос, контекст и предыдущая, неидеальная попытка ответа. Твоя задача — сгенерировать НОВУЮ, УЛУЧШЕННУЮ версию ответа, используя ИСКЛЮЧИТЕЛЬНО информацию из контекста.

### КОНТЕКСТ\n{state['documents']}\n\n### ВОПРОС\n{state['question']}\n\n### ПРЕДЫДУЩИЙ НЕИДЕАЛЬНЫЙ ОТВЕТ\n{state['final_answer']}\n\n### ТВОЙ НОВЫЙ, УЛУЧШЕННЫЙ ОТВЕТ:"""
    try:
        response = llm_client.chat.completions.create(model=GENERATION_MODEL,
                                                      messages=[{"role": "user", "content": prompt}], temperature=0.1)
        new_answer = response.choices[0].message.content
        token_logger.log_usage(response.usage, GENERATION_MODEL, "refine_answer_node", f"question={state['question']}")
        return {"final_answer": new_answer, "answer_refinement_cycles": state.get('answer_refinement_cycles', 1) + 1}
    except Exception as e:
        print(f"Ошибка при улучшении ответа: {e}")
        return {}


@timed
def reflect_node(state: GraphState) -> dict:
    """Узел 'мозгового центра' для Self-Reflective RAG. Анализирует ситуацию и решает, что делать дальше."""
    print(f"--- УЗЕЛ: Рефлексия (Итерация поиска {state.get('search_cycles', 1)}) ---")

    # === УСИЛЕННЫЙ ПРОМПТ С ПРИМЕРАМИ (FEW-SHOT) ===
    # 1. Создаем переменную с объединенным контекстом для чистоты
    context_str = "\n\n---\n\n".join(state['documents'])

    prompt = f"""Ты — эксперт-аналитик RAG-систем. Твоя задача — проанализировать текущее состояние и решить, что делать дальше.
Твой ответ должен быть СТРОГО в формате JSON без какого-либо дополнительного текста до или после.

### ПРИМЕР 1 (Нужен дополнительный поиск):
Исходный вопрос: "Расскажи всё про вклад 'Накопительный'".
Контекст: "По вкладу 'Накопительный' ставка 15% годовых."
Сгенерированный ответ: "Ставка по вкладу 'Накопительный' составляет 15% годовых."
Твой JSON ответ:
{{
  "critique": "Ответ правильный, но неполный. В вопросе было слово 'всё', а в ответе нет информации о сроках и минимальной сумме.",
  "next_action": "SEARCH",
  "new_query": "условия и сроки по вкладу Накопительный"
}}

### ПРИМЕР 2 (Ответ полный, завершаем):
Исходный вопрос: "Какая ставка по вкладу 'Накопительный'?"
Контекст: "Процентная ставка по вкладу 'Накопительный' составляет 15% годовых."
Сгенерированный ответ: "Процентная ставка по вкладу 'Накопительный' составляет 15% годовых."
Твой JSON ответ:
{{
  "critique": "Ответ точный и полностью соответствует вопросу.",
  "next_action": "FINISH",
  "new_query": ""
}}

### ТЕКУЩАЯ ЗАДАЧА:

### ИСХОДНЫЙ ВОПРОС:
{state['question']}

### КОНТЕКСТ (Найденные чанки):
{context_str}

### СГЕНЕРИРОВАННЫЙ ОТВЕТ:
{state['final_answer']}

### ТВОЙ JSON ОТВЕТ:
"""
    try:
        response = llm_client.chat.completions.create(
            model=GENERATION_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0
        )
        raw_response = response.choices[0].message.content

        # === УМНЫЙ ПАРСЕР JSON ===
        reflection_json = {}
        try:
            # Ищем JSON объект в тексте, так как модель может добавить лишний текст
            json_match = re.search(r'\{.*\}', raw_response, re.DOTALL)
            if json_match:
                reflection_json = json.loads(json_match.group(0))
            else:
                # Если JSON не найден, считаем это ошибкой
                raise json.JSONDecodeError("JSON объект не найден в ответе модели.", raw_response, 0)
        except json.JSONDecodeError as json_e:
            # Если парсинг не удался, выводим ошибку и завершаем
            print(
                f"Ошибка при рефлексии (не удалось распарсить JSON): {json_e}. Ответ модели: '{raw_response}'. Принимаем решение завершить.")
            return {"reflection": {"next_action": "FINISH"}}

        token_logger.log_usage(response.usage, GENERATION_MODEL, "reflect_node", f"question={state['question']}")
        print(
            f"  - Решение рефлексии: {reflection_json.get('next_action')}. Критика: {reflection_json.get('critique')}")
        return {"reflection": reflection_json}

    except Exception as e:
        # Ловим ошибки API и другие непредвиденные сбои
        print(f"Критическая ошибка в reflect_node (вероятно, API): {e}. Принимаем решение завершить.")
        return {"reflection": {"next_action": "FINISH"}}


@timed
def update_search_query_node(state: GraphState) -> dict:
    """Узел для обновления счетчика и списка запросов перед новым поиском."""
    print("--- УЗЕЛ: Обновление перед новым поиском ---")
    reflection = state.get("reflection", {})
    new_query = reflection.get("new_query", "")

    all_queries = state.get('all_queries', [])
    if new_query and new_query not in all_queries:
        all_queries.append(new_query)

    # Правильно обновляем состояние
    return {
        "all_queries": all_queries,
        "search_cycles": state.get("search_cycles", 1) + 1
    }

# === 3. СБОРКА ГРАФОВ И УСЛОВНЫЕ ПЕРЕХОДЫ ===

# --- Условные переходы (Conditional Edges) ---

def decide_to_refine_answer(state: GraphState) -> str:
    """Решает, нужно ли улучшать ответ в простом RAG."""
    if state.get("answer_score", 0.0) >= MIN_SCORE_TO_FINISH or state.get("answer_refinement_cycles",
                                                                          0) >= MAX_ANSWER_REFINEMENT_CYCLES:
        return END
    return "refine_answer_node"


def decide_next_step_in_self_reflection(state: GraphState) -> str:
    """Решает, что делать в Self-Reflective RAG: искать или завершать."""
    reflection = state.get("reflection", {})
    next_action = reflection.get("next_action", "FINISH")

    # Теперь условие чистое, без изменения состояния
    if next_action == "SEARCH" and state.get('search_cycles', 1) < MAX_SEARCH_CYCLES:
        print("  - Решение: нужен новый поиск.")
        return "update_search_query_node"  # Переходим на новый узел

    print("  - Решение: завершить.")
    return END


# --- Функции для создания графов ---

def create_answer_refinement_graph(index: faiss.Index, all_chunks: List[str]):
    """ЗАПРОС №1: Создает граф для RAG с циклом улучшения ОТВЕТА."""
    print("Компиляция графа: Улучшение ОТВЕТА...")
    workflow = StateGraph(GraphState)

    # Привязываем контекст (индекс и чанки) к узлу
    retrieve_with_context = functools.partial(retrieve_and_rerank_node, index=index, all_chunks=all_chunks)

    workflow.add_node("expand_question_node", expand_question_node)
    workflow.add_node("hypothetical_answer_node", hypothetical_answer_node)
    workflow.add_node("retrieve_and_rerank_node", retrieve_with_context)
    workflow.add_node("generate_answer_node", generate_answer_node)
    workflow.add_node("grade_answer_node", grade_answer_node)
    workflow.add_node("refine_answer_node", refine_answer_node)

    workflow.set_entry_point("expand_question_node")
    workflow.add_edge("expand_question_node", "hypothetical_answer_node")
    workflow.add_edge("hypothetical_answer_node", "retrieve_and_rerank_node")
    workflow.add_edge("retrieve_and_rerank_node", "generate_answer_node")

    # Цикл улучшения ответа
    workflow.add_edge("generate_answer_node", "grade_answer_node")
    workflow.add_conditional_edges("grade_answer_node", decide_to_refine_answer,
                                   {END: END, "refine_answer_node": "refine_answer_node"})
    workflow.add_edge("refine_answer_node", "grade_answer_node")

    return workflow.compile()


def create_self_reflective_graph(index: faiss.Index, all_chunks: List[str]):
    """ЗАПРОС №2: Создает граф для Self-Reflective RAG с циклом улучшения ПОИСКА."""
    print("Компиляция графа: Self-Reflective RAG (улучшение ПОИСКА)...")
    workflow = StateGraph(GraphState)

    retrieve_with_context = functools.partial(retrieve_and_rerank_node, index=index, all_chunks=all_chunks)

    # Добавляем ВСЕ узлы, включая новый
    workflow.add_node("expand_question_node", expand_question_node)
    workflow.add_node("hypothetical_answer_node", hypothetical_answer_node)
    workflow.add_node("retrieve_and_rerank_node", retrieve_with_context)
    workflow.add_node("generate_answer_node", generate_answer_node)
    workflow.add_node("reflect_node", reflect_node)
    workflow.add_node("update_search_query_node", update_search_query_node)  # <-- НОВЫЙ УЗЕЛ

    workflow.set_entry_point("expand_question_node")
    workflow.add_edge("expand_question_node", "hypothetical_answer_node")
    workflow.add_edge("hypothetical_answer_node", "retrieve_and_rerank_node")
    workflow.add_edge("retrieve_and_rerank_node", "generate_answer_node")
    workflow.add_edge("generate_answer_node", "reflect_node")

    # Главный цикл рефлексии
    workflow.add_conditional_edges(
        "reflect_node",
        decide_next_step_in_self_reflection,
        {
            "update_search_query_node": "update_search_query_node",  # <-- Идем на новый узел
            END: END
        }
    )

    # Замыкаем цикл: после обновления идем на новый поиск
    workflow.add_edge("update_search_query_node", "retrieve_and_rerank_node")

    return workflow.compile()


# === 4. ОСНОВНОЙ БЛОК ЗАПУСКА ===

def answer_question_graph(question: str, rag_app):
    """Общая функция-обертка для запуска любого скомпилированного графа."""
    try:
        initial_state = {"question": question, "search_cycles": 1}
        # === ИЗМЕНЕНИЕ ЗДЕСЬ ===
        # Увеличиваем лимит рекурсии
        config = {"recursion_limit": 50}
        final_state = rag_app.invoke(initial_state, config=config)
        return final_state.get("final_answer", "Не удалось получить финальный ответ от графа.")
    except Exception as e:
        print(f"Критическая ошибка при выполнении графа для вопроса '{question}': {e}")
        return "Произошла критическая ошибка при обработке вашего запроса."

if __name__ == "__main__":
    print("--- Запуск пайплайна финансового ассистента ---")

    # Этап I: Подготовка RAG-артефактов (как в вашем коде)
    if USE_LOCAL_RAG_FILES and os.path.exists(FAISS_INDEX_PATH) and os.path.exists(CHUNKS_PATH):
        print(f"Использую сохраненные RAG-артефакты...")
        faiss_index = faiss.read_index(FAISS_INDEX_PATH)
        with open(CHUNKS_PATH, 'rb') as f:
            corpus_chunks = pickle.load(f)
        print("Артефакты RAG успешно загружены.")
    else:
        print("RAG-артефакты будут сгенерированы с нуля.")
        faiss_index, corpus_chunks = create_rag_artifacts('./train_data.csv')
        if SAVE_RAG_FILES:
            print(f"Сохранение индекса FAISS в '{FAISS_INDEX_PATH}'...");
            faiss.write_index(faiss_index, FAISS_INDEX_PATH)
            print(f"Сохранение чанков в '{CHUNKS_PATH}'...");
            with open(CHUNKS_PATH, 'wb') as f: pickle.dump(corpus_chunks, f)

    # Этап II: Компиляция выбранного графа
    if USE_SELF_REFLECTIVE_RAG:
        rag_app = create_self_reflective_graph(faiss_index, corpus_chunks)
    else:
        rag_app = create_answer_refinement_graph(faiss_index, corpus_chunks)
    print("RAG-граф успешно скомпилирован.")

    # Этап III: Генерация ответов на вопросы
    print("\n--- Подготовка завершена. Начинаем генерацию ответов. ---")
    questions_df = pd.read_csv('./questions.csv')
    questions = questions_df['Вопрос'].tolist()
    answers = [None] * len(questions)

    # Запускаем асинхронную или синхронную обработку
    if not ASYNC_MODE:
        for i, question in tqdm(enumerate(questions), desc="Обработка вопросов (синхронно)"):
            answers[i] = answer_question_graph(question, rag_app)
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            future_to_index = {executor.submit(answer_question_graph, q, rag_app): i for i, q in enumerate(questions)}
            for future in tqdm(concurrent.futures.as_completed(future_to_index), total=len(questions),
                               desc="Обработка вопросов (асинхронно)"):
                idx = future_to_index[future]
                try:
                    answers[idx] = future.result()
                except Exception as exc:
                    print(f"Вопрос с индексом {idx} сгенерировал исключение: {exc}"); answers[
                        idx] = "Произошла ошибка при обработке."

    # Сохранение результатов и логов
    questions_df['Ответы на вопрос'] = answers
    questions_df.to_csv('10_SelfReflectiveRAG_update.csv', index=False, encoding='utf-8')
    print("\n--- Все ответы сгенерированы. Файл 10_SelfReflectiveRAG_update.csv успешно сохранен. ---")

    token_logger.save_reports()
    time_logger.save_reports()
