# -*- coding: utf-8 -*-

import os
import re
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

# НОВЫЕ ИМПОРТЫ ДЛЯ LANGGRAPH
from typing import TypedDict, List
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

# Параметры для обработки данных
CHUNK_SIZE = 1024
CHUNK_OVERLAP = 150
EMBEDDING_BATCH_SIZE = 100
FAISS_DIMENSION = 1536
K_FINAL_CHUNKS = 7

# NEW:
ASYNC_MODE = True
MAX_WORKERS = 10
USE_LOCAL_RAG_FILES = True
FAISS_INDEX_PATH = "faiss_index.bin"
CHUNKS_PATH = "corpus_chunks.pkl"
LOGGING_TOKEN_USAGE = True
LOGGING_TIME_USAGE = True

# Настройки Rerank:
USE_RERANKER = True
RETRIEVAL_K_FOR_RERANK = 30

### НОВОЕ: Настройки для цикла перепроверки ###
MAX_REFINEMENT_CYCLES = 3       # Максимальное количество циклов улучшения
MIN_SCORE_TO_FINISH = 0.85      # Минимальная оценка ответа для завершения цикла

# Инициализация клиентов для OpenAI API
llm_client = OpenAI(base_url=BASE_URL, api_key=LLM_API_KEY)
embedder_client = OpenAI(base_url=BASE_URL, api_key=EMBEDDER_API_KEY)

# === Классы логирования и декоратор timed (без изменений) ===

class TokenUsageLogger:
    def __init__(self):
        self.data = []
        self._lock = threading.Lock()
        self.run_timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    def log_usage(self, usage, model_name: str, task: str, task_data: str) -> None:
        if not LOGGING_TOKEN_USAGE: return
        with self._lock:
            self.data.append({
                "model_name": model_name, "task": task, "task_data": task_data,
                "prompt_tokens": getattr(usage, 'prompt_tokens', 0),
                "completion_tokens": getattr(usage, 'completion_tokens', 0),
                "total_tokens": getattr(usage, 'total_tokens', 0),
            })

    def save_reports(self, output_dir="logs"):
        if not LOGGING_TOKEN_USAGE or not self.data: return
        os.makedirs(output_dir, exist_ok=True)
        full_log_df = pd.DataFrame(self.data)
        full_log_path = os.path.join(output_dir, f"{self.run_timestamp}_token_usage_full_log.csv")
        full_log_df.to_csv(full_log_path, index=False, encoding='utf-8')
        print(f"\nПолный лог использования токенов сохранен в: {full_log_path}")

        by_model_task = full_log_df.groupby(['model_name', 'task']).agg(
            prompt_tokens=('prompt_tokens', 'sum'), completion_tokens=('completion_tokens', 'sum'),
            total_tokens=('total_tokens', 'sum'), call_count=('model_name', 'size')
        ).reset_index()
        total_tokens_overall = by_model_task['total_tokens'].sum()
        if total_tokens_overall > 0:
            by_model_task['percentage_of_total'] = (by_model_task['total_tokens'] / total_tokens_overall * 100).round(2)
        by_model_task_path = os.path.join(output_dir, f"{self.run_timestamp}_token_usage_by_model_task.csv")
        by_model_task.to_csv(by_model_task_path, index=False, encoding='utf-8')
        print(f"Агрегированный отчет по задачам сохранен в: {by_model_task_path}")
        print("\n--- Сводный отчет по использованию токенов (Модель + Задача) ---")
        display_df = by_model_task.copy()
        for col in ['prompt_tokens', 'completion_tokens', 'total_tokens', 'call_count']:
            display_df[col] = display_df[col].apply(lambda x: f"{x:,}")
        if 'percentage_of_total' in display_df.columns:
            display_df['percentage_of_total'] = display_df['percentage_of_total'].apply(lambda x: f"{x}%")
        print(display_df.to_string(index=False))
        print("-----------------------------------------------------------------")

class TimeUsageLogger:
    def __init__(self):
        self.data = []
        self._lock = threading.Lock()
        self.run_timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    def log_time(self, task_name: str, duration_seconds: float) -> None:
        if not LOGGING_TIME_USAGE: return
        with self._lock:
            self.data.append({"task_name": task_name, "duration_seconds": duration_seconds})

    def save_reports(self, output_dir="logs"):
        if not LOGGING_TIME_USAGE or not self.data: return
        os.makedirs(output_dir, exist_ok=True)
        full_log_df = pd.DataFrame(self.data)
        full_log_path = os.path.join(output_dir, f"{self.run_timestamp}_time_usage_full_log.csv")
        full_log_df.to_csv(full_log_path, index=False, encoding='utf-8')
        print(f"\nПолный лог времени выполнения сохранен в: {full_log_path}")

        agg_report = full_log_df.groupby('task_name').agg(
            total_duration_sec=('duration_seconds', 'sum'), call_count=('task_name', 'size'),
            avg_duration_sec=('duration_seconds', 'mean'), min_duration_sec=('duration_seconds', 'min'),
            max_duration_sec=('duration_seconds', 'max')
        ).reset_index().sort_values(by='total_duration_sec', ascending=False)
        total_time_overall = agg_report['total_duration_sec'].sum()
        if total_time_overall > 0:
            agg_report['percentage_of_total_time'] = (agg_report['total_duration_sec'] / total_time_overall * 100).round(2)
        agg_report_path = os.path.join(output_dir, f"{self.run_timestamp}_time_usage_summary.csv")
        agg_report.to_csv(agg_report_path, index=False, encoding='utf-8')
        print(f"Агрегированный отчет по времени выполнения сохранен в: {agg_report_path}")
        print("\n--- Сводный отчет по времени выполнения (Задача) ---")
        display_df = agg_report.copy()
        for col in ['total_duration_sec', 'avg_duration_sec', 'min_duration_sec', 'max_duration_sec']:
            display_df[col] = display_df[col].apply(lambda x: f"{x:.3f}s")
        if 'percentage_of_total_time' in display_df.columns:
            display_df['percentage_of_total_time'] = display_df['percentage_of_total_time'].apply(lambda x: f"{x}%")
        print(display_df.to_string(index=False))
        print("-------------------------------------------------------")

token_logger = TokenUsageLogger()
time_logger = TimeUsageLogger()

def timed(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        if not LOGGING_TIME_USAGE: return func(*args, **kwargs)
        start_time = time.perf_counter()
        result = func(*args, **kwargs)
        end_time = time.perf_counter()
        duration = end_time - start_time
        time_logger.log_time(func.__name__, duration)
        return result
    return wrapper

@timed
def rerank_docs(query, documents, key):
    response = requests.post(
        "https://ai-for-finance-hack.up.railway.app/rerank",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        json={"model": "deepinfra/Qwen/Qwen3-Reranker-4B", "query": query, "documents": documents}
    )
    return response.json()

# === 2. ФУНКЦИИ ПАЙПЛАЙНА (без изменений) ===
@timed
def get_embeddings_in_batches(texts_list, model, batch_size, show_progress=False):
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
    print("Шаг 1: Загрузка и подготовка данных...")
    df = pd.read_csv(file_path)
    print("Шаг 2: Разбиение документов на чанки...")
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)
    all_chunks = []
    for _, row in df.iterrows():
        metadata_prefix = f"Источник: {row['id']}. Тэги: {row['tags']}. "
        text_to_split = (str(row['annotation'] if pd.notna(row['annotation']) else "") +
                         "\n\n" +
                         str(row['text'] if pd.notna(row['text']) else ""))
        chunks = text_splitter.split_text(text_to_split)
        all_chunks.extend([metadata_prefix + chunk for chunk in chunks])
    print(f"Всего создано {len(all_chunks)} чанков.")
    print(f"Шаг 3: Создание эмбеддингов (модель: {EMBEDDING_MODEL})...")
    chunk_embeddings = get_embeddings_in_batches(all_chunks, EMBEDDING_MODEL, EMBEDDING_BATCH_SIZE, show_progress=True)
    print("Шаг 4: Создание индекса FAISS...")
    index = faiss.IndexFlatL2(FAISS_DIMENSION)
    index.add(chunk_embeddings)
    print(f"Индекс FAISS создан. В нем {index.ntotal} векторов.")
    return index, all_chunks

# === 3. БЛОК LANGGRAPH (Финальная версия с циклом перепроверки) ===

### ИЗМЕНЕНО: Обновляем состояние графа ###
class GraphState(TypedDict):
    """
    Состояние RAG-графа.
    Атрибуты:
        question (str): Исходный вопрос.
        expanded_questions (List[str]): Альтернативные формулировки.
        hypothetical_answer (str): Гипотетический ответ.
        documents (List[str]): Найденные/переранжированные документы.
        is_relevant (bool): Флаг релевантности найденных документов.
        final_answer (str): Финальный ответ.
        num_cycles (int): Счетчик циклов улучшения ответа.
        final_answer_score (float): Оценка качества финального ответа.
    """
    question: str
    expanded_questions: List[str]
    hypothetical_answer: str
    documents: List[str]
    is_relevant: bool
    final_answer: str
    num_cycles: int
    final_answer_score: float

# --- Узлы графа ---

@timed
def expand_question_node(state: GraphState) -> dict:
    question = state['question']
    prompt = f"Сгенерируй 3 альтернативных формулировки для вопроса, чтобы улучшить поиск. Выводи каждую с новой строки, без нумерации.\n\nВопрос: {question}\n\nАльтернативные формулировки:"
    try:
        response = llm_client.chat.completions.create(
            model=GENERATION_MODEL, messages=[{"role": "user", "content": prompt}], temperature=0.8
        )
        expanded_queries = response.choices[0].message.content.strip().split('\n')
        token_logger.log_usage(response.usage, GENERATION_MODEL, "expand_question_node", f"{question=}")
        return {"expanded_questions": [q.strip() for q in expanded_queries if q.strip()]}
    except Exception as e:
        print(f"Ошибка в expand_question_node: {e}")
        return {"expanded_questions": []}

@timed
def hypothetical_answer_node(state: GraphState) -> dict:
    question = state['question']
    prompt = f"Сгенерируй короткий, но полный гипотетический ответ на вопрос. Он будет использован для поиска. Не говори, что не знаешь ответа, просто придумай правдоподобный.\n\nВопрос: {question}\n\nГипотетический ответ:"
    try:
        response = llm_client.chat.completions.create(
            model=GENERATION_MODEL, messages=[{"role": "user", "content": prompt}], temperature=0.0
        )
        hypothetical_answer = response.choices[0].message.content
        token_logger.log_usage(response.usage, GENERATION_MODEL, "hypothetical_answer_node", f"{question=}")
        return {"hypothetical_answer": hypothetical_answer}
    except Exception as e:
        print(f"Ошибка в hypothetical_answer_node: {e}")
        return {"hypothetical_answer": ""}

@timed
def retrieve_node(state: GraphState, index: faiss.Index, all_chunks: List[str]) -> dict:
    all_queries = ([state['question']] + state['expanded_questions'] +
                   ([state['hypothetical_answer']] if state['hypothetical_answer'] else []))
    query_embeddings = get_embeddings_in_batches(all_queries, EMBEDDING_MODEL, 10)
    retrieved_indices = set()
    k_retrieval = RETRIEVAL_K_FOR_RERANK if USE_RERANKER else K_FINAL_CHUNKS
    _, I = index.search(query_embeddings, k_retrieval)
    for indices_per_query in I:
        retrieved_indices.update(idx for idx in indices_per_query if idx != -1)
    return {"documents": [all_chunks[i] for i in retrieved_indices]}

@timed
def rerank_node(state: GraphState) -> dict:
    try:
        reranked_response = rerank_docs(state['question'], state['documents'], EMBEDDER_API_KEY)
        results = sorted(reranked_response.get('results', []), key=lambda x: x['relevance_score'], reverse=True)
        reranked_docs = [state['documents'][res['index']] for res in results]
        return {"documents": reranked_docs[:K_FINAL_CHUNKS]}
    except Exception as e:
        print(f"Ошибка в rerank_node: {e}. Используются результаты без переранжирования.")
        return {"documents": state['documents'][:K_FINAL_CHUNKS]}

@timed
def grade_documents_node(state: GraphState) -> dict:
    if not state["documents"]: return {"is_relevant": False}
    context = "\n\n---\n\n".join(state["documents"])
    prompt = f"Определи, содержит ли контекст ответ на вопрос. Ответь одним словом: 'yes' или 'no'.\n\n### КОНТЕКСТ\n{context}\n\n### ВОПРОС\n{state['question']}\n\n### Содержит ответ? (yes/no)"
    try:
        response = llm_client.chat.completions.create(
            model=GENERATION_MODEL, messages=[{"role": "user", "content": prompt}], temperature=0.0, max_tokens=10
        )
        decision = response.choices[0].message.content.strip().lower()
        token_logger.log_usage(response.usage, GENERATION_MODEL, "grade_documents_node", f"question={state['question']}")
        return {"is_relevant": "yes" in decision}
    except Exception as e:
        print(f"Ошибка в grade_documents_node: {e}")
        return {"is_relevant": False}

### ИЗМЕНЕНО: Первая генерация ответа, инициализирует счетчик циклов ###
@timed
def generate_answer_node(state: GraphState) -> dict:
    context = "\n\n---\n\n".join(state["documents"])
    prompt = f"""Ты — умный и точный финансовый ассистент. Ответь на вопрос пользователя, основываясь ИСКЛЮЧИТЕЛЬНО на предоставленном контексте.
- Проанализируй запрос.
- Найди все релевантные фрагменты в контексте.
- Синтезируй единый, исчерпывающий и user-friendly ответ.
- Не выдумывай информацию и не ссылайся на "контекст".
Если в контексте нет ответа, сообщи: "В предоставленной базе знаний нет информации по вашему вопросу".

### КОНТЕКСТ
{context}

### ВОПРОС
{state['question']}

### ТВОЙ ОТВЕТ
"""
    try:
        response = llm_client.chat.completions.create(
            model=GENERATION_MODEL, messages=[{"role": "user", "content": prompt}], temperature=0.0
        )
        token_logger.log_usage(response.usage, GENERATION_MODEL, "generate_answer_node", f"question={state['question']}")
        # Инициализируем счетчик циклов
        return {"final_answer": response.choices[0].message.content, "num_cycles": 1}
    except Exception as e:
        print(f"Ошибка в generate_answer_node: {e}")
        return {"final_answer": "Произошла ошибка при генерации ответа.", "num_cycles": 1}

### НОВОЕ: Узел для оценки качества ответа ###
@timed
def grade_answer_node(state: GraphState) -> dict:
    context = "\n\n---\n\n".join(state["documents"])
    prompt = f"""Оцени, насколько полно и точно сгенерированный ответ соответствует вопросу, основываясь на предоставленном контексте.
Выведи оценку в виде числа с плавающей точкой от 0.0 (ужасно) до 1.0 (идеально).
0.0: Ответ полностью нерелевантен или не основан на контексте.
0.5: Ответ частично релевантен, но упускает важные детали или содержит неточности.
1.0: Ответ полностью релевантен, точен, исчерпывающ и полностью основан на контексте.

### КОНТЕКСТ
{context}

### ВОПРОС
{state['question']}

### СГЕНЕРИРОВАННЫЙ ОТВЕТ
{state['final_answer']}

### ТВОЯ ОЦЕНКА (ТОЛЬКО ЧИСЛО ОТ 0.0 ДО 1.0):
"""
    try:
        response = llm_client.chat.completions.create(
            model=GENERATION_MODEL, messages=[{"role": "user", "content": prompt}], temperature=0.0, max_tokens=5
        )
        score_text = response.choices[0].message.content.strip()
        # Используем re для надежного извлечения числа
        match = re.search(r"(\d\.\d+)", score_text)
        if match:
            score = float(match.group(1))
        else:
            score = float(score_text) # Попытка прямого преобразования
        token_logger.log_usage(response.usage, GENERATION_MODEL, "grade_answer_node", f"question={state['question']}")
        print(f"  - Оценка ответа: {score:.2f} (цикл {state.get('num_cycles', 1)})")
        return {"final_answer_score": score}
    except Exception as e:
        print(f"Ошибка в grade_answer_node: {e}. Присвоена оценка 0.0.")
        return {"final_answer_score": 0.0}

### НОВОЕ: Узел для улучшения ответа ###
@timed
def refine_answer_node(state: GraphState) -> dict:
    print(f"  - Улучшение ответа (цикл {state.get('num_cycles', 1) + 1})...")
    context = "\n\n---\n\n".join(state["documents"])
    prompt = f"""Ты — эксперт по улучшению текстов. Тебе дан вопрос, контекст и предыдущая, неидеальная попытка ответа.
Твоя задача — сгенерировать НОВУЮ, УЛУЧШЕННУЮ версию ответа.
- Новый ответ должен быть более полным, точным и лучше структурированным.
- Используй ИСКЛЮЧИТЕЛЬНО информацию из предоставленного контекста.
- Не ссылайся на "предыдущий ответ" или "неидеальную попытку". Просто дай новый, качественный ответ.

### КОНТЕКСТ
{context}

### ВОПРОС
{state['question']}

### ПРЕДЫДУЩИЙ НЕИДЕАЛЬНЫЙ ОТВЕТ
{state['final_answer']}

### ТВОЙ НОВЫЙ, УЛУЧШЕННЫЙ ОТВЕТ:
"""
    try:
        response = llm_client.chat.completions.create(
            model=GENERATION_MODEL, messages=[{"role": "user", "content": prompt}], temperature=0.1
        )
        new_answer = response.choices[0].message.content
        current_cycles = state.get('num_cycles', 1)
        token_logger.log_usage(response.usage, GENERATION_MODEL, "refine_answer_node", f"question={state['question']}")
        return {"final_answer": new_answer, "num_cycles": current_cycles + 1}
    except Exception as e:
        print(f"Ошибка в refine_answer_node: {e}")
        # Возвращаем старый ответ, чтобы не прерывать граф
        return {"final_answer": state['final_answer'], "num_cycles": state.get('num_cycles', 1) + 1}

@timed
def no_info_found_node(state: GraphState) -> dict:
    return {"final_answer": "В предоставленной базе знаний нет информации по вашему вопросу."}

# --- Условные переходы ---
def should_rerank(state: GraphState) -> str:
    return "rerank_node" if USE_RERANKER and state['documents'] else "grade_documents_node"

def decide_to_generate(state: GraphState) -> str:
    return "generate_answer_node" if state.get("is_relevant") else "no_info_found_node"

### НОВОЕ: Условие для цикла улучшения ###
def should_refine_or_finish(state: GraphState) -> str:
    """
    Решает, нужно ли улучшать ответ или можно завершать работу.
    """
    score = state.get("final_answer_score", 0.0)
    cycles = state.get("num_cycles", 1)

    if score >= MIN_SCORE_TO_FINISH:
        print("  - Ответ достаточно качественный. Завершение.")
        return END
    if cycles >= MAX_REFINEMENT_CYCLES:
        print("  - Достигнут лимит циклов улучшения. Завершение.")
        return END

    return "refine_answer_node"

# --- Сборка графа ---
def create_rag_graph(index: faiss.Index, all_chunks: List[str]):
    workflow = StateGraph(GraphState)
    retrieve_with_context = functools.partial(retrieve_node, index=index, all_chunks=all_chunks)

    # Добавляем все узлы
    workflow.add_node("expand_question_node", expand_question_node)
    workflow.add_node("hypothetical_answer_node", hypothetical_answer_node)
    workflow.add_node("retrieve_node", retrieve_with_context)
    workflow.add_node("rerank_node", rerank_node)
    workflow.add_node("grade_documents_node", grade_documents_node)
    workflow.add_node("generate_answer_node", generate_answer_node)
    workflow.add_node("no_info_found_node", no_info_found_node)
    ### НОВОЕ: Добавляем узлы цикла ###
    workflow.add_node("grade_answer_node", grade_answer_node)
    workflow.add_node("refine_answer_node", refine_answer_node)

    # Строим связи
    workflow.set_entry_point("expand_question_node")
    workflow.add_edge("expand_question_node", "hypothetical_answer_node")
    workflow.add_edge("hypothetical_answer_node", "retrieve_node")
    workflow.add_conditional_edges("retrieve_node", should_rerank, {"rerank_node": "rerank_node", "grade_documents_node": "grade_documents_node"})
    workflow.add_edge("rerank_node", "grade_documents_node")
    workflow.add_conditional_edges("grade_documents_node", decide_to_generate, {"generate_answer_node": "generate_answer_node", "no_info_found_node": "no_info_found_node"})

    ### ИЗМЕНЕНО: Запускаем цикл улучшения после первой генерации ###
    workflow.add_edge("generate_answer_node", "grade_answer_node")
    # Добавляем условный переход для цикла
    workflow.add_conditional_edges(
        "grade_answer_node",
        should_refine_or_finish,
        {
            "refine_answer_node": "refine_answer_node",
            END: END
        }
    )
    # Замыкаем цикл: после улучшения снова оцениваем
    workflow.add_edge("refine_answer_node", "grade_answer_node")

    # Узел "нет информации" сразу ведет к концу
    workflow.add_edge("no_info_found_node", END)

    return workflow.compile()

# === 4. ФУНКЦИЯ-ОБЕРТКА И ОСНОВНОЙ БЛОК ЗАПУСКА (без изменений) ===
def answer_question(question: str, rag_app):
    """Запускает RAG-граф для получения ответа на вопрос."""
    try:
        print(f"\n[Обработка вопроса]: {question}")
        final_state = rag_app.invoke({"question": question})
        return final_state.get("final_answer", "Не удалось получить финальный ответ от графа.")
    except Exception as e:
        print(f"Критическая ошибка при выполнении графа для вопроса '{question}': {e}")
        return "Произошла критическая ошибка при обработке вашего запроса."

if __name__ == "__main__":
    print("--- Запуск пайплайна финансового ассистента ---")

    if USE_LOCAL_RAG_FILES and os.path.exists(FAISS_INDEX_PATH) and os.path.exists(CHUNKS_PATH):
        print(f"Загрузка RAG-артефактов из '{FAISS_INDEX_PATH}' и '{CHUNKS_PATH}'...")
        faiss_index = faiss.read_index(FAISS_INDEX_PATH)
        with open(CHUNKS_PATH, 'rb') as f:
            corpus_chunks = pickle.load(f)
        print("Артефакты RAG успешно загружены.")
    else:
        print("Генерация RAG-артефактов с нуля...")
        faiss_index, corpus_chunks = create_rag_artifacts('./train_data.csv')
        print(f"Сохранение индекса FAISS в '{FAISS_INDEX_PATH}'...")
        faiss.write_index(faiss_index, FAISS_INDEX_PATH)
        print(f"Сохранение чанков в '{CHUNKS_PATH}'...")
        with open(CHUNKS_PATH, 'wb') as f:
            pickle.dump(corpus_chunks, f)

    print("\nСоздание и компиляция RAG-графа...")
    rag_app = create_rag_graph(faiss_index, corpus_chunks)
    print("RAG-граф успешно скомпилирован.")

    print("\n--- Подготовка завершена. Генерация ответов... ---")
    questions_df = pd.read_csv('./questions.csv')
    questions = questions_df['Вопрос'].tolist()
    answers = [None] * len(questions)

    if not ASYNC_MODE:
        for i, question in tqdm(enumerate(questions), desc="Обработка вопросов (синхронно)"):
            answers[i] = answer_question(question, rag_app)
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            future_to_index = {executor.submit(answer_question, q, rag_app): i for i, q in enumerate(questions)}
            for future in tqdm(concurrent.futures.as_completed(future_to_index), total=len(questions), desc="Обработка вопросов (асинхронно)"):
                idx = future_to_index[future]
                try:
                    answers[idx] = future.result()
                except Exception as exc:
                    print(f"Вопрос с индексом {idx} сгенерировал исключение: {exc}")
                    answers[idx] = "Произошла ошибка при обработке."

    questions_df['Ответы на вопрос'] = answers
    questions_df.to_csv('submission.csv', index=False, encoding='utf-8')
    print("\n--- Все ответы сгенерированы. Файл submission.csv сохранен. ---")

    token_logger.save_reports()
    time_logger.save_reports()
