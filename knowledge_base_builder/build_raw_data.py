import re
import json
from pathlib import Path
from tqdm import tqdm

# --- Конфигурация ---
# Определяем пути относительно текущего файла
BASE_DIR = Path(__file__).parent
SOURCE_DATA_DIR = BASE_DIR / "source_data"
OUTPUT_DIR = BASE_DIR / "output"
RAW_DOCS_PATH = OUTPUT_DIR / "raw_documents.jsonl"

# Определяем метаданные для наших исходных файлов
SOURCE_FILES = [
    {
        "path": SOURCE_DATA_DIR / "nk_part1.txt",
        "source_name": "НК РФ, Часть 1",
        "source_type": "tax_code",
        "source_url": "https://www.consultant.ru/cons/cgi/online.cgi?req=doc&base=LAW&n=511249"
    },
    {
        "path": SOURCE_DATA_DIR / "nk_part2.txt",
        "source_name": "НК РФ, Часть 2",
        "source_type": "tax_code",
        "source_url": "https://www.consultant.ru/cons/cgi/online.cgi?req=doc&base=LAW&n=517473"
    },
    {
        "path": SOURCE_DATA_DIR / "federal_law_54.txt",
        "source_name": "ФЗ-54 О применении ККТ",
        "source_type": "federal_law",
        "source_url": "https://www.consultant.ru/document/cons_doc_LAW_42359/"
    },
    {
        "path": SOURCE_DATA_DIR / "federal_law_422.txt",
        "source_name": "ФЗ-422 О налоге на проф. доход",
        "source_type": "federal_law",
        "source_url": "https://www.consultant.ru/document/cons_doc_LAW_311977/"
    }
]


# --- Логика парсинга ---

def clean_text(text):
    """Очищает текст от лишних пробелов и служебных строк."""
    lines = text.split('\n')
    # Удаляем строки с редакциями и пустые строки
    cleaned_lines = [line for line in lines if not line.strip().startswith('(в ред.') and line.strip()]
    return "\n".join(cleaned_lines).strip()


def parse_text_file(filepath: Path, metadata: dict) -> list[dict]:
    """
    Парсит один текстовый файл, извлекая главы и статьи.
    Работает как конечный автомат.
    """
    # ----- ИЗМЕНЕНИЕ ЗДЕСЬ -----
    with open(filepath, 'r', encoding='cp1251') as f:
        lines = f.readlines()

    all_articles = []
    current_chapter_title = ""
    current_article_data = None

    # Регулярные выражения для поиска заголовков
    chapter_regex = re.compile(r"^\s*Глава\s+([\d\.]+)\s*\.?(.*)", re.IGNORECASE)
    article_regex = re.compile(r"^\s*Статья\s+([\d\.]+)\.?(.*)")

    for line in lines:
        line_strip = line.strip()

        # Ищем заголовок главы
        chapter_match = chapter_regex.match(line_strip)
        if chapter_match:
            # Если нашли новую главу, сбрасываем текущую статью
            if current_article_data:
                current_article_data['content'] = clean_text(current_article_data['content'])
                all_articles.append(current_article_data)
                current_article_data = None
            current_chapter_title = f"Глава {chapter_match.group(1).strip()}. {chapter_match.group(2).strip()}"
            continue

        # Ищем заголовок статьи
        article_match = article_regex.match(line_strip)
        if article_match:
            # Если до этого уже была статья, сохраняем ее
            if current_article_data:
                current_article_data['content'] = clean_text(current_article_data['content'])
                all_articles.append(current_article_data)

            # Начинаем новую статью
            article_number = article_match.group(1).strip()
            article_title = article_match.group(2).strip()

            # Удаляем из заголовка "мусорные" подстроки
            article_title = re.sub(r'\(введена.*?\)', '', article_title).strip()
            article_title = re.sub(r'\(утратила.*?\)', '', article_title).strip()

            current_article_data = {
                "doc_id": f"{metadata['source_name'].replace(' ', '_')}_art_{article_number}",
                "source_type": metadata['source_type'],
                "source_name": metadata['source_name'],
                "url": metadata['source_url'],
                "title": f"Статья {article_number}. {article_title}",
                "content": "",  # Начинаем собирать контент
                "metadata": {
                    "chapter": current_chapter_title,
                    "article_number": article_number
                }
            }
            continue

        # Если мы находимся внутри статьи, добавляем строку к ее контенту
        if current_article_data:
            current_article_data['content'] += line

    # Не забываем сохранить самую последнюю статью в файле
    if current_article_data:
        current_article_data['content'] = clean_text(current_article_data['content'])
        all_articles.append(current_article_data)

    return all_articles


def main():
    """Главная функция для запуска всего процесса."""
    print("--- Начинаю сборку базы знаний из .txt файлов ---")

    # Создаем папку для вывода, если ее нет
    OUTPUT_DIR.mkdir(exist_ok=True)

    all_docs = []

    for file_info in tqdm(SOURCE_FILES, desc="Обработка файлов"):
        filepath = file_info['path']
        if not filepath.exists():
            print(f"ВНИМАНИЕ: Файл не найден, пропускаю: {filepath}")
            continue

        # print(f"\nОбрабатываю файл: {filepath.name}...")
        articles = parse_text_file(filepath, file_info)
        all_docs.extend(articles)
        # print(f"Найдено статей: {len(articles)}")

    print(f"\n--- Всего найдено и обработано статей: {len(all_docs)} ---")

    # Сохраняем все в один .jsonl файл
    with open(RAW_DOCS_PATH, 'w', encoding='utf-8') as f:
        for doc in all_docs:
            f.write(json.dumps(doc, ensure_ascii=False) + '\n')

    print(f"База знаний успешно сохранена в файл: {RAW_DOCS_PATH}")


if __name__ == "__main__":
    main()