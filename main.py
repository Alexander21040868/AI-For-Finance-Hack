# -*- coding: utf-8 -*-

import os
import pandas as pd
import numpy as np
import faiss
from tqdm import tqdm
from dotenv import load_dotenv
from openai import OpenAI
from langchain_text_splitters import RecursiveCharacterTextSplitter
import concurrent.futures
import pickle

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
TOP_K_RETRIEVAL = 7  # Количество наиболее релевантных чанков для поиска

# NEW:
ASYNC_MODE = True # Обрабатывать вопросы пользователей в асинхронном (True) либо синхронном (False) режиме
MAX_WORKERS = 10 # Число параллельных обработчиков
USE_LOCAL_RAG_FILES = True # Использовать RAG-артефакты, которые уже сохранены в директории
FAISS_INDEX_PATH = "faiss_index.bin"
CHUNKS_PATH = "corpus_chunks.pkl"

# Инициализация клиентов для OpenAI API
# Один клиент для генерации ответов, другой для создания эмбеддингов
llm_client = OpenAI(base_url=BASE_URL, api_key=LLM_API_KEY)
embedder_client = OpenAI(base_url=BASE_URL, api_key=EMBEDDER_API_KEY)


# === 2. ФУНКЦИИ ПАЙПЛАЙНА ===

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


def expand_question(question):
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
        return [q.strip() for q in expanded_queries if q.strip()]
    except Exception as e:
        print(f"Ошибка при расширении вопроса: {e}")
        return []

def generate_hypothetical_answer(question: str) -> str:
    """Генерирует гипотетический ответ на вопрос, не основываясь на базу данных,
    чтобы затем использовать его для поиска по базе данных

    Возвращает сгенерированный ответ на вопрос"""
    prompt = f"""Ты — AI-ассистент. Пожалуйста, сгенерируй короткий, но полный гипотетический ответ на следующий вопрос. Этот ответ будет использован для поиска информации в базе знаний. Не говори, что ты не знаешь ответа. Просто придумай правдоподобный ответ.

Вопрос: {question}

Гипотетический ответ:"""
    try:
        response = llm_client.chat.completions.create(
            model=GENERATION_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"Ошибка при генерации гипотетического ответа: {e}")
        return question


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
    _, I = index.search(query_embeddings, TOP_K_RETRIEVAL)
    for indices_per_query in I:
        for idx in indices_per_query:
            retrieved_indices.add(idx)

    retrieved_chunks = [all_chunks[i] for i in retrieved_indices]
    context = "\n\n---\n\n".join(retrieved_chunks)

    prompt = f"""Ты — умный и точный финансовый ассистент. Твоя задача — ответить на вопрос пользователя, основываясь на предоставленном ниже контексте. Не используй свои собственные знания и не придумывай информацию. Если в контексте нет прямого ответа на вопрос, вежливо сообщи: "В предоставленной базе знаний нет информации по вашему вопросу".

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
        return response.choices[0].message.content
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
