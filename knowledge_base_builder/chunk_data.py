import json
import pandas as pd
from pathlib import Path
from tqdm import tqdm

# --- Установите зависимости, если еще не сделали ---
# pip install langchain pandas

try:
    from langchain_text_splitters import RecursiveCharacterTextSplitter
except ImportError:
    print("LangChain не найден. Пожалуйста, установите его:")
    print("pip install langchain")
    exit()

# --- Конфигурация ---
BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "output"
RAW_DOCS_PATH = OUTPUT_DIR / "raw_documents.jsonl"
CHUNKED_DOCS_PATH = OUTPUT_DIR / "knowledge_base_chunks.csv"

# Настройки для разбиения текста
# chunk_size - максимальный размер чанка в символах
# chunk_overlap - сколько символов из предыдущего чанка будет в начале следующего.
#                 Это помогает сохранить контекст на стыках.
CHUNK_SIZE = 1500
CHUNK_OVERLAP = 200


# --- Логика чанкинга ---

def chunk_all_documents() -> pd.DataFrame:
    """
    Читает raw_documents.jsonl, разбивает каждую статью на чанки
    и возвращает DataFrame со всеми чанками.
    """
    print(f"Чтение исходных документов из: {RAW_DOCS_PATH}")

    # 1. Загружаем все документы из .jsonl файла
    all_docs = []
    with open(RAW_DOCS_PATH, 'r', encoding='utf-8') as f:
        for line in f:
            all_docs.append(json.loads(line))

    print(f"Загружено {len(all_docs)} документов.")

    # 2. Инициализируем сплиттер из LangChain
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        length_function=len,
        add_start_index=True,  # Добавляет информацию о том, где начался чанк
    )

    all_chunks = []

    # 3. Проходим по каждому документу и разбиваем его
    for doc in tqdm(all_docs, desc="Разбиение документов на чанки"):
        # LangChain ожидает список текстов для обработки
        chunks = text_splitter.split_text(doc['content'])

        for i, chunk_text in enumerate(chunks):
            all_chunks.append({
                'chunk_id': f"{doc['doc_id']}_chunk_{i + 1}",
                'chunk_text': chunk_text,
                'source_name': doc['source_name'],
                'source_type': doc['source_type'],
                'source_url': doc['url'],
                'original_doc_title': doc['title'],
            })

    return pd.DataFrame(all_chunks)


def main():
    """Главная функция для запуска процесса."""
    df_chunks = chunk_all_documents()

    print(f"\n--- Всего создано чанков: {len(df_chunks)} ---")

    # 4. Сохраняем результат в CSV
    df_chunks.to_csv(CHUNKED_DOCS_PATH, index=False, encoding='utf-8')

    print(f"Файл с чанками успешно сохранен: {CHUNKED_DOCS_PATH}")
    print("\nСтруктура итогового файла:")
    print(df_chunks.head())


if __name__ == "__main__":
    main()