import requests
from bs4 import BeautifulSoup
import time


def scrape_article(url: str) -> dict | None:
    """
    Парсит одну статью и возвращает ее заголовок и очищенный текст.
    Возвращает None в случае ошибки.
    """
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()  # Проверка на ошибки HTTP (вроде 404)

        soup = BeautifulSoup(response.text, 'lxml')

        # !!! ВАЖНО: ЭТИ СЕЛЕКТОРЫ НУЖНО БУДЕТ ПОДОБРАТЬ ВРУЧНУЮ !!!
        # Они могут отличаться для klerk.ru и buh.ru и меняться со временем.
        # Как их найти:
        # 1. Откройте статью в браузере.
        # 2. Нажмите F12, чтобы открыть Инструменты разработчика.
        # 3. Выберите инструмент "Inspect" (иконка курсора в квадрате).
        # 4. Кликните на заголовок статьи, а затем на основной текст.
        # 5. Найдите уникальный тег и класс для этих элементов.

        # Примерные селекторы для klerk.ru (нужно проверить актуальность)
        title_tag = soup.find('h1')
        content_div = soup.find(id='article-content')

        # TODO: Добавить сюда логику для buh.ru, если селекторы отличаются
        # if "buh.ru" in url:
        #     title_tag = soup.find(...)
        #     content_div = soup.find(...)

        if not title_tag or not content_div:
            print(f"ПРЕДУПРЕЖДЕНИЕ: Не найден заголовок или контент для URL: {url}")
            return None

        # Очищаем контент от "мусора": рекламы, ссылок, скриптов.
        for tag in content_div.find_all(['script', 'style', 'a', 'nav', 'aside']):
            tag.decompose()

        title = title_tag.get_text(strip=True)
        content = content_div.get_text(separator='\n', strip=True)

        source_name = "klerk.ru" if "klerk.ru" in url else "buh.ru"

        return {
            "source_name": source_name,
            "source_type": "article",
            "url": url,
            "title": title,
            "content": content
        }

    except requests.RequestException as e:
        print(f"ОШИБКА: Не удалось загрузить URL {url}: {e}")
        return None
    except Exception as e:
        print(f"ОШИБКА: Неожиданная проблема при парсинге {url}: {e}")
        return None