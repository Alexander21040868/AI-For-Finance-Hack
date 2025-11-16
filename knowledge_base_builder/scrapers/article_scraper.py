import requests
from bs4 import BeautifulSoup
import time
from urllib.parse import urljoin

def get_relevant_article_urls(base_url="https://www.klerk.ru", limit_per_section=30):
    """
    Собирает URL-адреса статей с сайта klerk.ru из разделов,
    полезных для консультанта малого бизнеса.

    Returns:
        set: Множество уникальных URL-адресов статей.
    """
    # 1. Определяем ключевые разделы для малого бизнеса
    # Эти URL ведут на страницы с лентами статей по конкретным темам
    sections = {
        "УСН": "/rubricator/usn/",
        "АУСН": "/rubricator/483/",
        "Патент (ПСН)": "/rubricator/psn/",
        "Кадры": "/rubricator/kadri/",
        "Зарплата": "/rubricator/zarplata/",
        "Бухучет": "/rubricator/buhgalterskij-uchet/",
        "ИП": "/rubricator/individualniy-predprinimatel/",
        "Бизнес": "/rubricator/malyj-i-srednij-biznes/",
        "ЕНП": "/rubricator/enp/"
    }

    unique_article_urls = set()
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }

    print("Начинаю сбор ссылок по разделам...")

    # 2. Проходим по каждому разделу
    for section_name, section_path in sections.items():
        section_url = urljoin(base_url, section_path)
        print(f"\nОбрабатываю раздел: '{section_name}' ({section_url})")

        try:
            response = requests.get(section_url, headers=headers, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'lxml')

            # 3. Ищем все теги <a>, которые ведут на статьи
            # Эмпирически определено, что ссылки на статьи часто имеют такую структуру.
            # Мы ищем ссылки, которые начинаются с определенных подстрок.
            # Это самый надежный способ отличить их от ссылок на теги или другие разделы.
            found_links = 0
            all_links_on_page = soup.find_all('a', href=True)

            for link in all_links_on_page:
                href = link['href']
                # Фильтруем по характерным для статей путям
                if href.startswith(('/buh/news/', '/blogs/', '/user/')) and href.count('/') >= 3:
                    full_url = urljoin(base_url, href)
                    if full_url not in unique_article_urls:
                        unique_article_urls.add(full_url)
                        found_links += 1
                        if found_links >= limit_per_section:
                            break  # Переходим к следующему разделу, если достигли лимита

            print(f"-> Найдено {found_links} новых ссылок.")

        except requests.RequestException as e:
            print(f"ОШИБКА: Не удалось загрузить раздел {section_name}: {e}")
            continue
        except Exception as e:
            print(f"ОШИБКА: Проблема при парсинге раздела {section_name}: {e}")
            continue

    return unique_article_urls


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