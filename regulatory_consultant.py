import os
import json
import pickle
from pathlib import Path
from datetime import datetime

import faiss
import numpy as np
import pandas as pd
from langchain_text_splitters import RecursiveCharacterTextSplitter
from openai import OpenAI
from tqdm import tqdm

from time_logger import timed
from token_logger import token_logger
from config import RAG_CONFIG, KNOWLEDGE_BASE_BUILDER_CONFIG

# Параметры для обработки данных (из config.py)
# Для разбиения на чанки используем параметры из KNOWLEDGE_BASE_BUILDER_CONFIG (как в chunk_data.py)
CHUNK_SIZE = KNOWLEDGE_BASE_BUILDER_CONFIG["chunk_size"]  # 1500 (из chunk_data.py)
CHUNK_OVERLAP = KNOWLEDGE_BASE_BUILDER_CONFIG["chunk_overlap"]  # 200 (из chunk_data.py)
# Остальные параметры из RAG_CONFIG
EMBEDDING_BATCH_SIZE = RAG_CONFIG["embedding_batch_size"]
FAISS_DIMENSION = RAG_CONFIG["faiss_dimension"]
K_FINAL_CHUNKS = RAG_CONFIG["k_final_chunks"]
USE_RERANKER = RAG_CONFIG["use_reranker"]
RETRIEVAL_K_FOR_RERANK = RAG_CONFIG["retrieval_k_for_rerank"]


class RegulatoryConsultant:
    def __init__(self,
                 open_router_client: OpenAI,
                 embedding_model: str,
                 generation_model: str,
                 use_local_files: bool,
                 save_local_files: bool,
                 regulatory_consultant_faiss_index_path: str,
                 regulatory_consultant_chunks_path: str
                 ):
        self.open_router_client = open_router_client
        self.embedding_model = embedding_model
        self.generation_model = generation_model
        self.use_local_files = use_local_files
        self.save_local_files = save_local_files
        self.faiss_index_path = regulatory_consultant_faiss_index_path
        self.chunks_path = regulatory_consultant_chunks_path
        self.faiss_index = None
        self.corpus_chunks = None
        self._create_rag_artefacts()

    @timed
    def _should_rebuild_knowledge_base(self, raw_documents_path: str) -> bool:
        """Проверяет, нужно ли пересобирать базу знаний из исходных файлов."""
        try:
            from knowledge_base_builder.build_raw_data import SOURCE_FILES
            
            # Если raw_documents.jsonl не существует, нужно собрать
            if not os.path.exists(raw_documents_path):
                print(f"База знаний не найдена: {raw_documents_path}. Требуется сборка.")
                return True
            
            # Получаем дату модификации raw_documents.jsonl
            raw_docs_mtime = os.path.getmtime(raw_documents_path)
            
            # Проверяем, изменились ли исходные файлы
            for file_info in SOURCE_FILES:
                source_path = file_info['path']
                # Преобразуем Path в строку для os.path.exists
                source_path_str = str(source_path)
                if os.path.exists(source_path_str):
                    source_mtime = os.path.getmtime(source_path_str)
                    if source_mtime > raw_docs_mtime:
                        print(f"Исходный файл '{source_path.name}' изменен. Требуется пересборка базы знаний.")
                        return True
            
            return False
        except Exception as e:
            print(f"Ошибка при проверке необходимости пересборки базы знаний: {e}")
            import traceback
            traceback.print_exc()
            # В случае ошибки не пересобираем
            return False

    @timed
    def _build_knowledge_base(self):
        """Вызывает код из knowledge_base_builder для сборки базы знаний."""
        try:
            print("--- Запуск сборки базы знаний из knowledge_base_builder ---")
            from knowledge_base_builder.build_raw_data import main as build_main
            build_main()
            print("--- База знаний успешно собрана ---")
        except Exception as e:
            print(f"Ошибка при сборке базы знаний: {e}")
            import traceback
            traceback.print_exc()
            raise

    @timed
    def _create_rag_artefacts(self):
        # Проверяем и пересобираем базу знаний при необходимости
        from config import RAW_DOCUMENTS_PATH
        
        if self._should_rebuild_knowledge_base(RAW_DOCUMENTS_PATH):
            self._build_knowledge_base()
        
        if self.use_local_files and os.path.exists(self.faiss_index_path) and os.path.exists(self.chunks_path):
            # Проверяем, не изменился ли raw_documents.jsonl после создания артефактов
            raw_docs_mtime = os.path.getmtime(RAW_DOCUMENTS_PATH) if os.path.exists(RAW_DOCUMENTS_PATH) else 0
            faiss_mtime = os.path.getmtime(self.faiss_index_path) if os.path.exists(self.faiss_index_path) else 0
            
            if raw_docs_mtime > faiss_mtime:
                print(f"База знаний обновлена после создания артефактов. Требуется пересоздание RAG.")
                # Удаляем старые артефакты и пересоздаем
                if os.path.exists(self.faiss_index_path):
                    os.remove(self.faiss_index_path)
                if os.path.exists(self.chunks_path):
                    os.remove(self.chunks_path)
            else:
                print(
                    f"Использую сохраненные RAG-артефакты. Загрузка из '{self.faiss_index_path}' и '{self.chunks_path}'..."
                )
                self.faiss_index = faiss.read_index(self.faiss_index_path)
                with open(self.chunks_path, 'rb') as f:
                    self.corpus_chunks = pickle.load(f)
                print("Артефакты RAG успешно загружены.")
                return
        
        # Если дошли сюда, нужно создать артефакты
        print("RAG-артефакты будут сгенерированы с нуля.")
        faiss_index, corpus_chunks = self._generate_new_rag_artefacts(RAW_DOCUMENTS_PATH)
        self.faiss_index = faiss_index
        self.corpus_chunks = corpus_chunks

        if self.save_local_files:
            print(f"Сохранение индекса FAISS в файл '{self.faiss_index_path}'...")
            faiss.write_index(faiss_index, self.faiss_index_path)

            print(f"Сохранение чанков в файл '{self.chunks_path}'...")
            with open(self.chunks_path, 'wb') as f:
                pickle.dump(corpus_chunks, f)

    @timed
    def _get_embeddings_in_batches(self, texts_list, model, batch_size, show_progress=False):
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
                response = self.open_router_client.embeddings.create(input=batch, model=model)
                embeddings = [item.embedding for item in response.data]
                all_embeddings.extend(embeddings)
            except Exception as e:
                print(f"Ошибка при обработке батча {i // batch_size}: {e}")
                all_embeddings.extend([[0.0] * FAISS_DIMENSION] * len(batch))

        return np.array(all_embeddings).astype('float32')

    @timed
    def _generate_new_rag_artefacts(self, file_path):
        """
        Основная функция для создания артефактов RAG:
        1. Загружает и подготавливает данные из JSONL файла.
        2. Разбивает текст на чанки используя функцию из chunk_data.py.
        3. Создает векторные представления (эмбеддинги) для чанков.
        4. Создает и наполняет поисковый индекс FAISS.
        Возвращает: индекс FAISS и список всех текстовых чанков.
        """
        print("Шаг 1: Загрузка и подготовка данных из JSONL...")
        
        # Используем функцию chunk_all_documents из chunk_data.py для разбиения на чанки
        try:
            import sys
            from pathlib import Path
            # Добавляем корневую директорию проекта в путь для импорта
            project_root = Path(__file__).parent
            if str(project_root) not in sys.path:
                sys.path.insert(0, str(project_root))
            
            from knowledge_base_builder.chunk_data import chunk_all_documents
            
            print("Шаг 2: Разбиение документов на чанки (используя chunk_data.py)...")
            # Используем функцию из chunk_data.py для получения чанков
            chunks_df = chunk_all_documents()
            
            print(f"Загружено {len(chunks_df)} чанков из chunk_data.py")
            
            # Сохраняем чанки в CSV для отладки и других целей (как в chunk_data.py)
            from knowledge_base_builder.chunk_data import CHUNKED_DOCS_PATH
            chunks_df.to_csv(CHUNKED_DOCS_PATH, index=False, encoding='utf-8')
            print(f"Чанки сохранены в CSV: {CHUNKED_DOCS_PATH}")
            
            # Загружаем исходные документы для получения метаданных (глава, статья)
            documents_metadata = {}
            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip():
                        doc = json.loads(line)
                        doc_id = doc.get('doc_id', 'unknown')
                        documents_metadata[doc_id] = doc
            
            # Формируем финальные чанки с метаданными для RAG
            all_chunks = []
            for _, row in chunks_df.iterrows():
                chunk_id = row['chunk_id']
                chunk_text = row['chunk_text']
                source_name = row['source_name']
                source_type = row['source_type']
                title = row['original_doc_title']
                
                # Извлекаем doc_id из chunk_id (формат: "doc_id_chunk_N")
                # Нужно правильно извлечь doc_id, учитывая что он может содержать подчеркивания
                chunk_id_parts = chunk_id.split('_chunk_')
                if len(chunk_id_parts) > 0:
                    doc_id = chunk_id_parts[0]
                else:
                    doc_id = chunk_id
                
                # Получаем дополнительные метаданные из исходного документа
                doc_metadata = documents_metadata.get(doc_id, {})
                metadata_info = doc_metadata.get('metadata', {})
                
                # Формируем префикс с метаданными (как было раньше)
                metadata_prefix = f"Источник: {source_name} ({source_type}). "
                if title:
                    metadata_prefix += f"Название: {title}. "
                if metadata_info:
                    chapter = metadata_info.get('chapter', '')
                    article = metadata_info.get('article_number', '')
                    if chapter:
                        metadata_prefix += f"Глава: {chapter}. "
                    if article:
                        metadata_prefix += f"Статья: {article}. "
                
                all_chunks.append(metadata_prefix + chunk_text)
            
            print(f"Всего создано {len(all_chunks)} чанков с метаданными.")
        except Exception as e:
            print(f"Ошибка при использовании chunk_data.py: {e}")
            import traceback
            traceback.print_exc()
            print("Используем fallback: разбиение на чанки напрямую...")
            # Fallback на старый способ, если chunk_data.py не работает
            documents = []
            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip():
                        documents.append(json.loads(line))
            
            text_splitter = RecursiveCharacterTextSplitter(
                chunk_size=CHUNK_SIZE,
                chunk_overlap=CHUNK_OVERLAP,
                length_function=len,
                add_start_index=True
            )
            all_chunks = []
            
            for doc in documents:
                doc_id = doc.get('doc_id', 'unknown')
                source_name = doc.get('source_name', '')
                source_type = doc.get('source_type', '')
                title = doc.get('title', '')
                metadata_info = doc.get('metadata', {})
                
                metadata_prefix = f"Источник: {source_name} ({source_type}). "
                if title:
                    metadata_prefix += f"Название: {title}. "
                if metadata_info:
                    chapter = metadata_info.get('chapter', '')
                    article = metadata_info.get('article_number', '')
                    if chapter:
                        metadata_prefix += f"Глава: {chapter}. "
                    if article:
                        metadata_prefix += f"Статья: {article}. "
                
                content = doc.get('content', '')
                if not content:
                    continue
                    
                chunks = text_splitter.split_text(content)
                for chunk in chunks:
                    all_chunks.append(metadata_prefix + chunk)
            
            print(f"Всего создано {len(all_chunks)} чанков с метаданными (fallback).")
        print(f"Шаг 3: Создание эмбеддингов для чанков (модель: {self.embedding_model})...")
        chunk_embeddings = self._get_embeddings_in_batches(all_chunks, self.embedding_model, EMBEDDING_BATCH_SIZE,
                                                           show_progress=True)

        print("Шаг 4: Создание и наполнение индекса FAISS...")
        index = faiss.IndexFlatL2(FAISS_DIMENSION)
        index.add(chunk_embeddings)
        print(f"Индекс FAISS успешно создан. В нем {index.ntotal} векторов.")

        return index, all_chunks

    @timed
    def _expand_question(self, question: str) -> list[str]:
        """Использует LLM для генерации альтернативных формулировок вопроса."""
        prompt = f"""Ты — AI-ассистент. Твоя задача — сгенерировать 3 альтернативных формулировки для заданного вопроса, чтобы улучшить поиск в базе знаний. Не отвечай на вопрос, а только перефразируй его. Выведи каждый вариант с новой строки, без нумерации.
    
    Оригинальный вопрос: {question}
    
    Альтернативные формулировки:"""
        try:
            response = self.open_router_client.chat.completions.create(
                model=self.generation_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.8
            )
            expanded_queries = response.choices[0].message.content.strip().split('\n')
            token_logger.log_usage(response.usage, self.generation_model, "expand_question",
                                   f"{question=} {expanded_queries=}")
            return [q.strip() for q in expanded_queries if q.strip()]
        except Exception as e:
            print(f"Ошибка при расширении вопроса: {e}")
            return []

    @timed
    def _generate_hypothetical_answer(self, question: str) -> str:
        """Генерирует гипотетический ответ на вопрос, не основываясь на базу данных,
        чтобы затем использовать его для поиска по базе данных"""
        prompt = f"""Ты — AI-ассистент. Пожалуйста, сгенерируй короткий, но полный гипотетический ответ на следующий вопрос. Этот ответ будет использован для поиска информации в базе знаний. Не говори, что ты не знаешь ответа. Просто придумай правдоподобный ответ.
    
    Вопрос: {question}
    
    Гипотетический ответ:"""
        try:
            response = self.open_router_client.chat.completions.create(
                model=self.generation_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0
            )
            hypothetical_answer = response.choices[0].message.content
            token_logger.log_usage(response.usage, self.generation_model, "generate_hypothetical_answer",
                                   f"{question=} {hypothetical_answer=}")
            return hypothetical_answer
        except Exception as e:
            print(f"Ошибка при генерации гипотетического ответа: на вопрос {question}: {e}")
            return question

    @timed
    def answer_question(self, question):
        """
        Принимает вопрос, РАСШИРЯЕТ его, генерирует гипотетический ответ на вопрос,
        находит релевантный контекст и генерирует ответ.
        """
        all_queries = [question]

        expanded_questions = self._expand_question(question)
        hypothetical_answer = self._generate_hypothetical_answer(question)

        all_queries.extend(expanded_questions)
        all_queries.append(hypothetical_answer)

        query_embeddings = self._get_embeddings_in_batches(all_queries, self.embedding_model, 10)

        retrieved_indices = set()
        k_retrieval = RETRIEVAL_K_FOR_RERANK if USE_RERANKER else K_FINAL_CHUNKS
        _, I = self.faiss_index.search(query_embeddings, k_retrieval)
        for indices_per_query in I:
            for idx in indices_per_query:
                retrieved_indices.add(idx)

        retrieved_chunks = [self.corpus_chunks[i] for i in retrieved_indices]

        # Убрал использование reranker
        final_chunks = retrieved_chunks
        context = "\n\n---\n\n".join(final_chunks)

        prompt = f"""Ты — эмпатичный, но авторитетный финансовый эксперт. Твоя миссия — предоставлять пользователям исчерпывающие, структурированные и практически полезные ответы на сложные финансовые вопросы. Твой язык должен быть профессиональным, но кристально ясным для человека без специальной подготовки.
    
    Твоя задача — проанализировать предоставленный КОНТЕКСТ и на его основе дать полный ответ на ВОПРОС ПОЛЬЗОВАТЕЛЯ.
    
    ### Структура идеального ответа
    
    Твой ответ должен строго следовать этой многоуровневой структуре:
    
    1.  **Введение (необязательно, но желательно для сложных тем):**
        *   Начни с краткого предложения, которое обозначает важность вопроса и основной принцип.
        *   *Пример: "Отзыв лицензии у банка — стрессовая ситуация, но ваши сбережения защищены государством. Главное — действовать правильно. Вот пошаговый план:"*
    
    2.  **Прямой и емкий ответ:**
        *   Сразу дай главный вывод. **Выдели его полужирным.** Это должен быть ответ в 1-2 предложениях, который можно прочитать и сразу понять суть.
        *   *Пример: "**Просрочка по «беспроцентному» займу аннулирует льготные условия и приведет к начислению процентов, пеней и штрафов за весь срок, что значительно увеличит итоговую переплату и полную стоимость кредита (ПСК).**"*
    
    3.  **Детальное объяснение (используй заголовок `### Детали` или `### Как это работает`):**
        *   Разбей сложные темы на логические блоки с **информативными подзаголовками в формате H4** (`#### 1. Как просрочка влияет на переплату`).
        *   Внутри каждого блока используй **маркированные списки** (`*`) для перечисления причин, шагов, последствий или фактов.
        *   **Объясняй сложные термины и аббревиатуры** (например, ПСК, АСВ, ФЗ-353) сразу при первом упоминании, можно в скобках.
        *   Включай **конкретные цифры, сроки и примеры** из контекста, чтобы сделать объяснение наглядным и доказуемым.
        *   Ссылайся на законодательные нормы, если они есть в контексте, чтобы подкрепить авторитетность ответа (например, "согласно ст. 1154 ГК РФ...").
    
    4.  **Практические советы (используй заголовок `### Что делать` или `### Советы`):**
        *   Заверши ответ блоком с **конкретными, действенными шагами**, которые пользователь может предпринять.
        *   Оформляй советы в виде маркированного или нумерованного списка.
        *   *Пример: "- **Проверьте договор:** Найдите разделы о штрафах. - **Свяжитесь с кредитором:** Попытайтесь договориться о реструктуризации."*
    
    ### Стиль и тон: использование эмодзи
    
    Чтобы сделать ответ более живым и понятным, используй эмодзи уместно и дозированно. Они должны служить визуальными акцентами и усиливать эмпатию.
    
    *   **Правила использования:**
        *   Используй эмодзи для выделения пунктов в списках, особенно в разделе "Что делать".
        *   Размещай их в начале или в конце строки для акцента.
        *   Выбирай эмодзи, которые логически связаны с содержанием.
    *   **Что можно использовать:**
        *   Для советов и шагов: ✅, ➡️, ✍️, 📞, 🗓️
        *   Для предупреждений и важных моментов: ⚠️, ❗️, 💡
        *   Для финансовых тем: 💰, 📄, 📈, 🏦, 💳
    *   **Чего следует избегать:**
        *   **Не используй эмодзи** в главном выводе (выделенном полужирным).
        *   Избегай чрезмерного количества эмодзи (не более одного на пункт списка или короткий абзац).
        *   Не используй неуместные или слишком неформальные эмодзи (например, 😂, 🥳, 🤯). Тон должен оставаться профессиональным.
    
    ### Ключевые принципы, которым нужно следовать
    
    *   **100% на основе контекста:** Твой ответ должен быть полностью основан на предоставленном КОНТЕКСТЕ. Не добавляй информацию из своих общих знаний, даже если она кажется верной. Каждое утверждение должно быть подкреплено информацией из источника.
    *   **Исчерпывающе, но без "воды":** Используй ВСЕ релевантные фрагменты из контекста. Синтезируй их в логичный рассказ. Не упускай детали, но избегай повторений.
    *   **Никаких самоссылок:** Никогда не упоминай "контекст", "предоставленную информацию" или "базу знаний" в своем ответе. Говори от лица эксперта, который владеет этой информацией.
    *   **Отказ от ответа:** Если в КОНТЕКСТЕ абсолютно нет информации для ответа на вопрос, напиши только одну фразу: `К сожалению, в моей базе знаний нет информации по вашему вопросу.`
    
    ---
    
    ### КОНТЕКСТ ИЗ БАЗЫ ЗНАНИЙ
    {context}
    
    ### ВОПРОС ПОЛЬЗОВАТЕЛЯ
    {question}
    
    ### ТВОЙ ОТВЕТ
    """
        try:
            response = self.open_router_client.chat.completions.create(
                model=self.generation_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0
            )
            final_answer = response.choices[0].message.content
            token_logger.log_usage(response.usage, self.generation_model, "answer_question",
                                   f"{question=} {final_answer=}")
            return final_answer
        except Exception as e:
            print(f"Ошибка при генерации ответа на вопрос '{question}': {e}")
            return "Произошла ошибка при генерации ответа."
