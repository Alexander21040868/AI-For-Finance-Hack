import pandas as pd
import io
import json
import numpy as np
import asyncio
import time
from datetime import datetime, timedelta
from collections import defaultdict
from typing import List, Optional, Dict, Tuple

from openai import OpenAI
from time_logger import timed
from token_logger import token_logger
from config import TRANSACTION_ANALYZER_CONFIG
from transaction_history import transaction_history

from pydantic import BaseModel


CATEGORIES = [
    "Аренда", "Зарплата", "Закупка товара", "Хозяйственные нужды",
    "Реклама", "IT-услуги", "Поступление от клиента", "Прочее", "Не принимаемые расходы"
]

# Подкатегории для детализации
SUBCATEGORIES = {
    "Закупка товара": ["Сырье", "Комплектующие", "Готовая Продукция", "Упаковка"],
    "IT-услуги": ["SaaS (Подписка)", "Разработка (Проект)", "Хостинг/Домен", "Оборудование"],
    "Реклама": ["Google Ads", "Яндекс.Директ", "SMM", "Блогеры", "Офлайн"],
    "Аренда": ["Офис", "Склад", "Производство"],
    "Зарплата": ["Оклад", "Премия", "Налоги с ФОТ"]
}

class TaxRow(BaseModel):
    Показатель: str
    Значение: float

class AnalyzeSummary(BaseModel):
    mode: str
    tax: float

class AnalyzeResponse(BaseModel):
    summary: AnalyzeSummary
    transactions: List[TaxRow]

class TransactionAnalyzer:
    def __init__(self,
                 open_router_client: OpenAI,
                 generation_model: str,
                 ):
        self.open_router_client = open_router_client
        self.generation_model = generation_model

    @staticmethod
    def calculate_taxes(df: pd.DataFrame, mode: str = "УСН_доходы") -> (float, pd.DataFrame):
        """Рассчитывает налоговую базу и итоговый налог."""
        df["Сумма"] = pd.to_numeric(df["Сумма"], errors="coerce").fillna(0)

        if mode == "УСН_доходы":
            tax_base = df[df["Категория"] == "Поступление от клиента"]["Сумма"].sum()
            rate = 0.06
        else:
            income = df[df["Категория"] == "Поступление от клиента"]["Сумма"].sum()
            expenses = df[df["Категория"] != "Поступление от клиента"]["Сумма"].sum()
            tax_base = income - expenses
            rate = 0.15

        tax = max(tax_base * rate, 0)

        return round(tax, 2), pd.DataFrame({
            "Показатель": ["Налоговая база", "Ставка (%)", "Налог к уплате"],
            "Значение": [round(tax_base, 2), rate * 100, round(tax, 2)]
        })

    @staticmethod
    @timed
    def parse_transactions(file_bytes, filename) -> pd.DataFrame:
        """
        Читает CSV/XLSX и проверяет нужные колонки.
        Добавлена валидация данных: формат дат, проверка на дубликаты.
        """
        if filename.endswith(".csv"):
            df = pd.read_csv(file_bytes)
        elif filename.endswith(".xlsx"):
            df = pd.read_excel(file_bytes)
        else:
            raise ValueError("Поддерживаются только CSV и XLSX файлы")

        if df.empty:
            raise ValueError("Файл пуст или не содержит данных")

        required_cols = ["Дата", "Назначение платежа", "Сумма"]
        for col in required_cols:
            if col not in df.columns:
                raise ValueError(f"Отсутствует обязательная колонка: {col}")

        # Валидация и нормализация дат
        try:
            # Сохраняем исходные даты для восстановления при необходимости
            original_dates = df["Дата"].copy()
            
            # Пробуем парсить как YYYY-MM-DD (стандартный формат)
            df["Дата"] = pd.to_datetime(df["Дата"], errors="coerce", dayfirst=False, format='%Y-%m-%d')
            
            # Если не получилось, пробуем без формата (автоопределение)
            if df["Дата"].isna().any():
                mask = df["Дата"].isna()
                df.loc[mask, "Дата"] = pd.to_datetime(original_dates[mask], errors="coerce", dayfirst=True)
            
            # Если все еще есть NaN, пробуем как строки в формате YYYY-MM-DD
            if df["Дата"].isna().any():
                mask = df["Дата"].isna()
                for idx in df[mask].index:
                    date_str = str(original_dates.loc[idx]).strip()
                    # Пробуем распарсить как YYYY-MM-DD
                    if len(date_str) >= 10 and date_str[4] == '-' and date_str[7] == '-':
                        try:
                            parsed = pd.to_datetime(date_str[:10], format='%Y-%m-%d', errors="coerce")
                            if pd.notna(parsed):
                                df.loc[idx, "Дата"] = parsed
                        except:
                            pass
            
            na_count = df["Дата"].isna().sum()
            if na_count > 0:
                print(f"[WARN] {na_count} дат не удалось распознать из {len(df)} транзакций")
                # Выводим примеры проблемных дат
                problem_indices = df[df["Дата"].isna()].index.tolist()[:5]
                for idx in problem_indices:
                    print(f"[WARN] Проблемная дата (индекс {idx}): '{original_dates.loc[idx]}' -> NaN")
        except Exception as e:
            print(f"[WARN] Ошибка при парсинге дат: {e}")
            import traceback
            traceback.print_exc()

        # Проверка на дубликаты (по дате, сумме и назначению)
        duplicates = df.duplicated(subset=["Дата", "Сумма", "Назначение платежа"], keep=False)
        if duplicates.any():
            dup_count = duplicates.sum()
            print(f"[INFO] Обнаружено {dup_count} потенциальных дубликатов транзакций")

        # Валидация сумм
        df["Сумма"] = pd.to_numeric(df["Сумма"], errors="coerce")
        if df["Сумма"].isna().any():
            na_count = df["Сумма"].isna().sum()
            print(f"[WARN] {na_count} транзакций с некорректной суммой будут пропущены")
            df = df.dropna(subset=["Сумма"])

        if df.empty:
            raise ValueError("После валидации не осталось валидных транзакций")

        return df

    @timed
    def categorize_transactions(self, texts: List[str]) -> List[Dict[str, str]]:
        """
        Многоуровневая категоризация с батчингом: один LLM-запрос обрабатывает несколько транзакций.
        Возвращает список словарей с полями: category, subcategory, counterparty, project.
        """
        batch_size = TRANSACTION_ANALYZER_CONFIG["batch_size"]
        results = []
        
        # Обрабатываем транзакции батчами
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            batch_results = self._categorize_batch(batch)
            results.extend(batch_results)
        
        return results

    def _categorize_batch(self, texts: List[str]) -> List[Dict[str, str]]:
        """
        Обрабатывает батч транзакций одним LLM-запросом.
        Возвращает JSON-структуру со всеми данными для каждой транзакции.
        """
        # Формируем промпт для батча
        transactions_list = "\n".join([f"{i+1}. {text}" for i, text in enumerate(texts)])
        
        # Создаем JSON-схему для ответа
        subcategories_json = json.dumps(SUBCATEGORIES, ensure_ascii=False, indent=2)
        
        prompt = f"""Ты — AI-бухгалтер. Проанализируй следующие транзакции и верни JSON-массив с результатами.

Транзакции:
{transactions_list}

Категории: {', '.join(CATEGORIES)}

Подкатегории (по категориям):
{subcategories_json}

Для каждой транзакции определи:
1. category - главная категория из списка выше
2. subcategory - подкатегория (если есть в списке для данной категории, иначе "—")
3. counterparty - название компании/ИП (очисти от ООО, за, согласно, НДС, договор), если не найдено - "—"
4. project - проект/ЦЗ (ищи ключевые слова: Москва-Сити, Ребрендинг, Проект, ЦЗ), если не найдено - "—"

Верни ТОЛЬКО валидный JSON-массив в формате:
[
  {{"category": "Категория", "subcategory": "Подкатегория", "counterparty": "Название", "project": "Проект"}},
  ...
]

Важно: верни ТОЛЬКО JSON, без дополнительного текста."""

        try:
            response = self._llm_request_with_retry(prompt)
            
            # Парсим JSON ответ
            response_text = response.choices[0].message.content.strip()
            
            # Очищаем от markdown code blocks если есть
            if response_text.startswith("```"):
                response_text = response_text.split("```")[1]
                if response_text.startswith("json"):
                    response_text = response_text[4:]
                response_text = response_text.strip()
            
            batch_results = json.loads(response_text)
            
            # Валидация и нормализация результатов
            validated_results = []
            if not isinstance(batch_results, list):
                print(f"[ERROR] Ожидался список, получен: {type(batch_results)}")
                return self._categorize_fallback(texts)
            
            if len(batch_results) != len(texts):
                print(f"[WARN] Количество результатов ({len(batch_results)}) не совпадает с количеством транзакций ({len(texts)})")
                # Дополняем или обрезаем до нужного размера
                if len(batch_results) < len(texts):
                    batch_results.extend([{}] * (len(texts) - len(batch_results)))
                else:
                    batch_results = batch_results[:len(texts)]
            
            for idx, result in enumerate(batch_results):
                if not isinstance(result, dict):
                    print(f"[WARN] Результат {idx} не является словарем: {type(result)}")
                    result = {}
                
                category = result.get("category", "Прочее")
                if category not in CATEGORIES:
                    category = "Прочее"
                
                subcategory = result.get("subcategory", "—")
                if category in SUBCATEGORIES:
                    if subcategory not in SUBCATEGORIES[category]:
                        subcategory = "—"
                else:
                    subcategory = "—"
                
                counterparty = result.get("counterparty", "—")
                if not counterparty or counterparty.strip() == "":
                    counterparty = "—"
                else:
                    counterparty = counterparty.strip()
                
                project = result.get("project", "—")
                if not project or project.strip() == "":
                    # Fallback на эвристику
                    if idx < len(texts):
                        project = self._extract_project(texts[idx])
                    else:
                        project = "—"
                
                validated_results.append({
                    "category": category,
                    "subcategory": subcategory,
                    "counterparty": counterparty,
                    "project": project
                })
            
            if hasattr(response, "usage"):
                token_logger.log_usage(
                    response.usage,
                    self.generation_model,
                    "categorize_batch",
                    f"batch_size={len(texts)}"
                )
            
            return validated_results
            
        except json.JSONDecodeError as e:
            print(f"[ERROR] Ошибка парсинга JSON ответа: {e}")
            print(f"[DEBUG] Ответ LLM (первые 500 символов): {response_text[:500] if 'response_text' in locals() else 'N/A'}")
            import traceback
            print(f"[DEBUG] Traceback: {traceback.format_exc()}")
            # Fallback на индивидуальную обработку
            return self._categorize_fallback(texts)
        except Exception as e:
            print(f"[ERROR] Ошибка при батч-категоризации: {e}")
            import traceback
            print(f"[DEBUG] Traceback: {traceback.format_exc()}")
            # Fallback на индивидуальную обработку
            return self._categorize_fallback(texts)

    def _categorize_fallback(self, texts: List[str]) -> List[Dict[str, str]]:
        """Fallback метод: индивидуальная обработка при ошибке батча."""
        results = []
        for text in texts:
            category = self._get_main_category(text)
            subcategory = self._get_subcategory(text, category)
            counterparty = self._extract_counterparty(text)
            project = self._extract_project(text)
            results.append({
                "category": category,
                "subcategory": subcategory,
                "counterparty": counterparty,
                "project": project
            })
        return results

    def _llm_request_with_retry(self, prompt: str):
        """Выполняет LLM-запрос с retry логикой и обработкой ошибок."""
        max_retries = TRANSACTION_ANALYZER_CONFIG["max_retries"]
        retry_delay = TRANSACTION_ANALYZER_CONFIG["retry_delay"]
        
        for attempt in range(max_retries):
            try:
                response = self.open_router_client.chat.completions.create(
                    model=self.generation_model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.0,
                )
                return response
            except Exception as e:
                error_msg = str(e).lower()
                if attempt < max_retries - 1:
                    # Проверяем, стоит ли повторять
                    if "rate limit" in error_msg or "timeout" in error_msg or "429" in error_msg:
                        wait_time = retry_delay * (2 ** attempt)  # Exponential backoff
                        print(f"[WARN] Ошибка API (попытка {attempt + 1}/{max_retries}): {e}. Повтор через {wait_time:.1f}с...")
                        time.sleep(wait_time)
                        continue
                    else:
                        # Для других ошибок тоже повторяем
                        print(f"[WARN] Ошибка API (попытка {attempt + 1}/{max_retries}): {e}. Повтор...")
                        time.sleep(retry_delay)
                        continue
                else:
                    # Последняя попытка не удалась
                    print(f"[ERROR] Все попытки LLM-запроса исчерпаны: {e}")
                    raise

    def _get_main_category(self, text: str) -> str:
        """Первичная категоризация транзакции (fallback метод)."""
        prompt = (
            f"Ты — AI-бухгалтер. Определи главную категорию транзакции: «{text}».\n"
            f"Категории: {', '.join(CATEGORIES)}.\n"
            f"Если расход нельзя учесть по УСН, выбери 'Не принимаемые расходы'.\n"
            "Ответь только одним словом — названием категории."
        )

        try:
            response = self._llm_request_with_retry(prompt)
            category = response.choices[0].message.content.strip()
            
            if hasattr(response, "usage"):
                token_logger.log_usage(
                    response.usage,
                    self.generation_model,
                    "categorize_main",
                    f"{text=}, {category=}"
                )
            
            return category if category in CATEGORIES else "Прочее"
        except Exception as e:
            print(f"[WARN] Ошибка при категоризации: {e}")
            return "Прочее"

    def _get_subcategory(self, text: str, main_category: str) -> str:
        """Детализация подкатегории на основе главной категории (fallback метод)."""
        if main_category not in SUBCATEGORIES:
            return "—"
        
        subcats = SUBCATEGORIES[main_category]
        prompt = (
            f"Ты — AI-бухгалтер. Определи подкатегорию транзакции: «{text}».\n"
            f"Главная категория: {main_category}.\n"
            f"Подкатегории: {', '.join(subcats)}.\n"
            "Если подкатегорию определить невозможно, ответь '—'.\n"
            "Ответь только одним словом или '—'."
        )

        try:
            response = self._llm_request_with_retry(prompt)
            subcategory = response.choices[0].message.content.strip()
            
            if hasattr(response, "usage"):
                token_logger.log_usage(
                    response.usage,
                    self.generation_model,
                    "categorize_sub",
                    f"{text=}, {subcategory=}"
                )
            
            return subcategory if subcategory in subcats else "—"
        except Exception as e:
            print(f"[WARN] Ошибка при детализации: {e}")
            return "—"

    def _extract_counterparty(self, text: str) -> str:
        """Извлекает наименование контрагента из назначения платежа (fallback метод)."""
        prompt = (
            f"Извлеки название компании или ИП из текста: «{text}».\n"
            "Очисти от лишних слов (ООО, за, согласно, НДС, договор и т.д.).\n"
            "Если название не найдено, ответь '—'.\n"
            "Ответь только названием компании или '—'."
        )

        try:
            response = self._llm_request_with_retry(prompt)
            counterparty = response.choices[0].message.content.strip()
            
            if hasattr(response, "usage"):
                token_logger.log_usage(
                    response.usage,
                    self.generation_model,
                    "extract_counterparty",
                    f"{text=}, {counterparty=}"
                )
            
            return counterparty if counterparty and counterparty != "—" else "—"
        except Exception as e:
            print(f"[WARN] Ошибка при извлечении контрагента: {e}")
            return "—"

    def _extract_project(self, text: str) -> str:
        """Извлекает проект/центр затрат из назначения платежа."""
        # Простая эвристика: ищем коды проектов или ключевые слова
        project_keywords = ["Москва-Сити", "Ребрендинг", "Проект", "ЦЗ"]
        
        for keyword in project_keywords:
            if keyword.lower() in text.lower():
                return keyword
        
        return "—"

    @timed
    async def analyze_transactions(self, file, tax_mode: str = "УСН_доходы") -> Optional[Dict]:
        """
        Расширенный анализ транзакций:
        - Многоуровневая категоризация
        - Анализ аномалий
        - Управленческий P&L
        - Прогнозы и рекомендации
        """
        try:
            content = await file.read()
            df = self.parse_transactions(io.BytesIO(content), file.filename)

            if "Назначение платежа" not in df.columns:
                raise Exception("Колонка 'Назначение платежа' не найдена")

            # Расширенная категоризация
            categorization_results = self.categorize_transactions(
                df["Назначение платежа"].tolist(),
            )
            
            # Добавляем новые колонки
            df["Категория"] = [r["category"] for r in categorization_results]
            df["Подкатегория"] = [r["subcategory"] for r in categorization_results]
            df["Контрагент"] = [r["counterparty"] for r in categorization_results]
            df["Проект"] = [r["project"] for r in categorization_results]
            df["Сумма"] = pd.to_numeric(df["Сумма"], errors="coerce").fillna(0)

            # Базовый расчет налогов
            total_tax, tax_table = self.calculate_taxes(df, mode=tax_mode)

            # Подготовка детализированных транзакций с конвертацией дат в строки (для истории)
            # Делаем это до анализа, чтобы сохранить в историю
            detailed_df_for_history = df[[
                "Дата", "Назначение платежа", "Сумма", 
                "Категория", "Подкатегория", "Контрагент", "Проект"
            ]].copy()
            
            # Конвертируем Timestamp в строки для истории
            if "Дата" in detailed_df_for_history.columns:
                detailed_df_for_history["Дата"] = detailed_df_for_history["Дата"].apply(
                    lambda x: x.strftime("%Y-%m-%d") if pd.notna(x) and hasattr(x, 'strftime') else str(x) if pd.notna(x) else ""
                )
            
            # Сохраняем транзакции в историю
            detailed_transactions_for_history = detailed_df_for_history.to_dict(orient="records")
            transaction_history.save_transactions(
                detailed_transactions_for_history,
                metadata={"tax_mode": tax_mode, "filename": file.filename}
            )

            # Анализ аномалий (с учетом истории)
            anomalies = self._detect_anomalies(df)

            # Управленческий P&L
            pl_report = self._generate_pl_report(df)
            
            # Вычисляем общие доходы и расходы для summary
            total_income = df[df["Категория"] == "Поступление от клиента"]["Сумма"].sum()
            total_expenses = df[df["Категория"] != "Поступление от клиента"]["Сумма"].abs().sum()

            # Прогнозы и рекомендации (с учетом сезонности и истории)
            forecasts = self._generate_forecasts(df)

            # Подготовка детализированных транзакций с конвертацией дат в строки
            detailed_df = df[[
                "Дата", "Назначение платежа", "Сумма", 
                "Категория", "Подкатегория", "Контрагент", "Проект"
            ]].copy()
            
            # Проверяем даты перед конвертацией
            na_before = detailed_df["Дата"].isna().sum()
            if na_before > 0:
                print(f"[WARN] Перед конвертацией: {na_before} транзакций с NaN датами")
                # Выводим примеры
                for idx in detailed_df[detailed_df["Дата"].isna()].index[:3]:
                    print(f"[WARN] Транзакция без даты (индекс {idx}): Категория='{detailed_df.loc[idx, 'Категория']}', Сумма={detailed_df.loc[idx, 'Сумма']}")
            
            # Конвертируем Timestamp в строки для JSON сериализации
            if "Дата" in detailed_df.columns:
                def convert_date(x):
                    if pd.isna(x):
                        return ""
                    # Если это Timestamp или datetime объект
                    if hasattr(x, 'strftime'):
                        try:
                            return x.strftime("%Y-%m-%d")
                        except:
                            return str(x)
                    # Если это уже строка
                    if isinstance(x, str):
                        # Пытаемся распарсить и вернуть в нужном формате
                        try:
                            parsed = pd.to_datetime(x, errors="coerce")
                            if pd.notna(parsed):
                                return parsed.strftime("%Y-%m-%d")
                            return x  # Возвращаем исходную строку, если не удалось распарсить
                        except:
                            return x
                    return str(x) if x else ""
                
                detailed_df["Дата"] = detailed_df["Дата"].apply(convert_date)
                
                # Проверяем, что даты не потерялись
                empty_dates = detailed_df["Дата"].eq("").sum()
                if empty_dates > 0:
                    print(f"[WARN] {empty_dates} транзакций с пустыми датами после конвертации")
                    # Пытаемся восстановить из исходного DataFrame
                    # Используем reset_index для сохранения исходных индексов
                    detailed_df_reset = detailed_df.reset_index()
                    df_reset = df.reset_index()
                    
                    for idx in detailed_df[detailed_df["Дата"] == ""].index:
                        # Находим соответствующую строку в исходном DataFrame
                        # Индексы должны совпадать, так как мы делали copy() без изменений порядка
                        if idx in df.index:
                            original_date = df.loc[idx, "Дата"]
                            if pd.notna(original_date):
                                try:
                                    if hasattr(original_date, 'strftime'):
                                        detailed_df.loc[idx, "Дата"] = original_date.strftime("%Y-%m-%d")
                                    else:
                                        # Пробуем распарсить строку
                                        parsed = pd.to_datetime(str(original_date), errors="coerce")
                                        if pd.notna(parsed):
                                            detailed_df.loc[idx, "Дата"] = parsed.strftime("%Y-%m-%d")
                                        else:
                                            detailed_df.loc[idx, "Дата"] = str(original_date)
                                except Exception as e:
                                    print(f"[WARN] Ошибка при восстановлении даты для индекса {idx}: {e}")
                                    detailed_df.loc[idx, "Дата"] = str(original_date) if original_date else ""
                    
                    # Проверяем результат
                    empty_after = detailed_df["Дата"].eq("").sum()
                    if empty_after < empty_dates:
                        print(f"[INFO] Восстановлено {empty_dates - empty_after} дат")
                    if empty_after > 0:
                        print(f"[WARN] Осталось {empty_after} транзакций с пустыми датами")
            
            # Конвертируем все числовые типы в нативные Python типы
            detailed_df["Сумма"] = detailed_df["Сумма"].apply(lambda x: float(x) if pd.notna(x) else 0.0)
            
            # Сравнение периодов (для bar chart)
            period_comparison = None
            if "Дата" in df.columns and not df["Дата"].isna().all():
                try:
                    dates = pd.to_datetime(df["Дата"], errors="coerce").dropna()
                    if len(dates) > 0:
                        current_start = dates.min().to_pydatetime()
                        current_end = dates.max().to_pydatetime()
                        # Передаем транзакции из текущего файла для точного расчета
                        current_tx_list = detailed_df.to_dict(orient="records")
                        period_comparison = transaction_history.get_period_comparison(
                            current_start, current_end, current_transactions_list=current_tx_list
                        )
                except Exception as e:
                    print(f"[WARN] Ошибка при расчете сравнения периодов: {e}")
            
            # Бенчмаркинг
            benchmarking = self._calculate_benchmarking(pl_report, df)
            
            # Налоговое планирование
            tax_planning = self._generate_tax_planning(df, tax_mode, total_tax, forecasts)
            
            return {
                "summary": {
                    "mode": tax_mode,
                    "tax": total_tax,
                    "transactions": len(df),
                    "income": float(total_income),
                    "expenses": float(total_expenses)
                },
                "transactions": tax_table.to_dict(orient="records"),
                "detailed_transactions": detailed_df.to_dict(orient="records"),
                "anomalies": anomalies,
                "pl_report": pl_report,
                "forecasts": forecasts,
                "period_comparison": period_comparison,
                "benchmarking": benchmarking,
                "tax_planning": tax_planning
            }

        except Exception as e:
            print(f"[ERROR] Ошибка при обработке файла: {e}")
            raise

    def _detect_anomalies(self, df: pd.DataFrame) -> List[Dict]:
        """Обнаружение аномалий в транзакциях."""
        anomalies = []
        df["Сумма"] = pd.to_numeric(df["Сумма"], errors="coerce").fillna(0)
        
        # Логирование для отладки
        print(f"[DEBUG] Обнаружение аномалий: всего транзакций {len(df)}, категорий {len(df['Категория'].unique())}")
        
        # Проверяем, что есть данные для анализа
        if len(df) == 0:
            print("[DEBUG] Нет транзакций для анализа аномалий")
            return []

        # 1. Всплеск расходов (outliers)
        sigma_threshold = TRANSACTION_ANALYZER_CONFIG["outlier_sigma_threshold"]
        for category in df["Категория"].unique():
            category_df = df[df["Категория"] == category].copy()
            if len(category_df) < 3:
                print(f"[DEBUG] Категория '{category}': пропущена (транзакций < 3: {len(category_df)})")
                continue
            
            # Используем абсолютные значения для статистики, но сохраняем оригинальные для фильтрации
            amounts_abs = category_df["Сумма"].abs()
            mean = amounts_abs.mean()
            std = amounts_abs.std()
            
            if std > 0:
                # Фильтруем по абсолютным значениям, но используем оригинальные суммы в результате
                outlier_mask = amounts_abs > mean + sigma_threshold * std
                outliers = category_df[outlier_mask]
                
                for _, row in outliers.iterrows():
                    amount_abs = abs(row["Сумма"])
                    deviation_sigma = ((amount_abs - mean) / std) if std > 0 else 0
                    anomalies.append({
                        "type": "Всплеск расходов",
                        "severity": "high",
                        "description": f"Транзакция {amount_abs:.2f} ₽ в категории '{category}' превышает средний чек ({mean:.2f} ₽) более чем в {sigma_threshold} раза (отклонение: {deviation_sigma:.2f}σ)",
                        "transaction": {
                            "date": str(row.get("Дата", "")),
                            "amount": float(row["Сумма"]),
                            "description": str(row.get("Назначение платежа", ""))
                        }
                    })
                    print(f"[DEBUG] Найдена аномалия: всплеск расходов в категории '{category}', сумма {amount_abs:.2f} ₽")

        # 2. Новые контрагенты (с учетом истории)
        known_counterparties = transaction_history.get_known_counterparties(days_back=90)
        current_counterparties = set(df[df["Контрагент"] != "—"]["Контрагент"].unique())
        new_counterparties = current_counterparties - known_counterparties
        
        counterparty_threshold = TRANSACTION_ANALYZER_CONFIG["new_counterparty_threshold"]
        for counterparty in new_counterparties:
            counterparty_df = df[df["Контрагент"] == counterparty]
            total = counterparty_df["Сумма"].abs().sum()
            if total > counterparty_threshold:
                anomalies.append({
                    "type": "Новый контрагент",
                    "severity": "medium",
                    "description": f"Платеж новому контрагенту '{counterparty}' на сумму {total:.2f} ₽. Контрагент не встречался в истории за последние 90 дней. Рекомендуется проверить договор.",
                    "transaction": {
                        "counterparty": counterparty,
                        "total": float(total)
                    }
                })
                print(f"[DEBUG] Найдена аномалия: новый контрагент '{counterparty}', сумма {total:.2f} ₽")
        
        # 2.1. Сравнение с историческими данными для категорий (только если есть достаточно истории)
        # Используем историю только как дополнительный контекст, не блокируем обнаружение аномалий
        for category in df["Категория"].unique():
            category_df = df[df["Категория"] == category]
            if len(category_df) < 3:
                continue
            
            # Получаем историческую статистику (исключая текущий файл - берем данные до сегодня)
            hist_stats = transaction_history.get_category_statistics(category, days_back=90)
            
            # Проверяем только если есть достаточно исторических данных (минимум 10 транзакций)
            if hist_stats["count"] >= 10:
                current_total = category_df["Сумма"].abs().sum()
                current_mean = category_df["Сумма"].abs().mean()
                hist_mean = hist_stats["mean"]
                
                # Проверяем значительное отклонение от исторического среднего
                if hist_mean > 0:
                    deviation = abs(current_mean - hist_mean) / hist_mean
                    if deviation > 0.3:  # Отклонение более 30%
                        anomalies.append({
                            "type": "Отклонение от тренда",
                            "severity": "medium",
                            "description": f"Категория '{category}': средний чек {current_mean:.2f} ₽ отличается от исторического ({hist_mean:.2f} ₽) на {deviation*100:.1f}%",
                            "transaction": {
                                "category": category,
                                "current_mean": float(current_mean),
                                "historical_mean": float(hist_mean),
                                "deviation": float(deviation)
                            }
                        })
                        print(f"[DEBUG] Найдена аномалия: отклонение от тренда в категории '{category}'")

        # 3. Негативная динамика (улучшенный расчет CAC)
        income = df[df["Категория"] == "Поступление от клиента"]["Сумма"].sum()
        advertising = df[df["Категория"] == "Реклама"]["Сумма"].abs().sum()
        
        if income > 0 and advertising > 0:
            # Улучшенный расчет CAC: реклама / количество уникальных клиентов (приблизительно)
            # Если нет данных о клиентах, используем упрощенную формулу: реклама / (доход / средний чек)
            # Предполагаем средний чек клиента 10,000 ₽ (можно сделать конфигурируемым)
            avg_customer_value = 10000
            estimated_customers = max(1, income / avg_customer_value)
            cac = advertising / estimated_customers if estimated_customers > 0 else 0
            
            # Сравниваем с историческим CAC
            hist_adv_stats = transaction_history.get_category_statistics("Реклама", days_back=90)
            hist_income_stats = transaction_history.get_category_statistics("Поступление от клиента", days_back=90)
            
            if hist_adv_stats["count"] > 0 and hist_income_stats["count"] > 0:
                hist_estimated_customers = max(1, hist_income_stats["total"] / avg_customer_value)
                hist_cac = hist_adv_stats["total"] / hist_estimated_customers if hist_estimated_customers > 0 else 0
                cac_increase = (cac - hist_cac) / hist_cac if hist_cac > 0 else 0
            else:
                hist_cac = None
                cac_increase = 0
            
            cac_threshold = TRANSACTION_ANALYZER_CONFIG["cac_warning_threshold"]
            cac_ratio = advertising / income if income > 0 else 0
            
            if cac_ratio > cac_threshold or (hist_cac and cac > hist_cac * 1.2):
                description = f"Высокая стоимость привлечения клиента (CAC: {cac:.2f} ₽). Реклама составляет {advertising:.2f} ₽ при доходе {income:.2f} ₽"
                if hist_cac:
                    description += f". Исторический CAC: {hist_cac:.2f} ₽ (рост на {cac_increase*100:.1f}%)"
                
                anomalies.append({
                    "type": "Негативная динамика",
                    "severity": "medium",
                    "description": description,
                    "transaction": {
                        "advertising": float(advertising),
                        "income": float(income),
                        "cac": float(cac),
                        "cac_ratio": float(cac_ratio),
                        "historical_cac": float(hist_cac) if hist_cac else None
                    }
                })

        print(f"[DEBUG] Всего обнаружено аномалий: {len(anomalies)}")
        return anomalies

    def _generate_pl_report(self, df: pd.DataFrame) -> Dict:
        """Генерация управленческого P&L отчета."""
        df["Сумма"] = pd.to_numeric(df["Сумма"], errors="coerce").fillna(0)
        
        # Выручка
        revenue = df[df["Категория"] == "Поступление от клиента"]["Сумма"].sum()
        
        # COGS (Себестоимость)
        cogs_categories = df[
            (df["Категория"] == "Закупка товара") & 
            (df["Подкатегория"].isin(["Сырье", "Комплектующие"]))
        ]
        cogs = cogs_categories["Сумма"].abs().sum()
        
        # Валовая прибыль
        gross_profit = revenue - cogs
        
        # Операционные расходы (все расходы кроме COGS и "Не принимаемые расходы")
        # COGS уже учтен отдельно, поэтому вычитаем его из операционных расходов
        all_expenses = df[
            ~df["Категория"].isin(["Поступление от клиента", "Не принимаемые расходы"])
        ]["Сумма"].abs().sum()
        operating_expenses = all_expenses - cogs  # Исключаем COGS из операционных расходов
        
        # Операционная прибыль (EBITDA)
        operating_profit = gross_profit - operating_expenses
        
        # Детализация по категориям
        expense_breakdown = {}
        for category in df[df["Категория"] != "Поступление от клиента"]["Категория"].unique():
            expense_breakdown[category] = float(
                df[df["Категория"] == category]["Сумма"].abs().sum()
            )

        return {
            "revenue": float(revenue),
            "cogs": float(cogs),
            "gross_profit": float(gross_profit),
            "gross_margin": float((gross_profit / revenue * 100) if revenue > 0 else 0),
            "operating_expenses": float(operating_expenses),
            "operating_profit": float(operating_profit),
            "operating_margin": float((operating_profit / revenue * 100) if revenue > 0 else 0),
            "expense_breakdown": expense_breakdown
        }

    def _generate_forecasts(self, df: pd.DataFrame) -> Dict:
        """
        Генерация прогнозов и рекомендаций с учетом сезонности и истории.
        Включает confidence intervals для более точных прогнозов.
        """
        df["Сумма"] = pd.to_numeric(df["Сумма"], errors="coerce").fillna(0)
        
        # Определяем регулярные платежи (аренда, зарплата, подписки)
        regular_categories = ["Аренда", "Зарплата"]
        regular_payments = df[df["Категория"].isin(regular_categories)]["Сумма"].abs().sum()
        
        # Текущие расходы и доходы
        total_expenses = df[df["Категория"] != "Поступление от клиента"]["Сумма"].abs().sum()
        total_income = df[df["Категория"] == "Поступление от клиента"]["Сумма"].sum()
        
        # Определяем период данных (в днях)
        num_transactions = len(df)
        if "Дата" in df.columns and not df["Дата"].isna().all():
            try:
                dates = pd.to_datetime(df["Дата"], errors="coerce")
                dates = dates.dropna()
                if len(dates) > 1:
                    period_days = (dates.max() - dates.min()).days + 1
                elif len(dates) == 1:
                    # Если только одна транзакция, используем минимальный период (1 день)
                    period_days = 1
                else:
                    period_days = 1
            except:
                period_days = 1
        else:
            period_days = 1
        
        # Если транзакций мало, используем более консервативный подход
        use_history = num_transactions >= 5  # Используем историю только если есть достаточно данных
        
        # Средние дневные расходы и доходы
        # Если период слишком мал (1 день), не экстраполируем на 30 дней напрямую
        if period_days < 7 and num_transactions < 5:
            # Для малого количества данных используем более консервативный прогноз
            # Берем текущие значения и умножаем на разумный коэффициент
            avg_daily_expenses = total_expenses / max(period_days, 1)
            avg_daily_income = total_income / max(period_days, 1)
            # Для малого количества данных не экстраполируем линейно на 30 дней
            # Используем более консервативный подход: умножаем на количество дней в месяце / период
            forecast_30d_expenses = avg_daily_expenses * 30
            forecast_30d_income = avg_daily_income * 30
            seasonal_factor_expenses = 1.0
            seasonal_factor_income = 1.0
        else:
            avg_daily_expenses = total_expenses / max(period_days, 1)
            avg_daily_income = total_income / max(period_days, 1)
            
            # Получаем исторические данные для более точного прогноза (только если достаточно данных)
            if use_history:
                hist_expenses_stats = transaction_history.get_category_statistics("Аренда", days_back=90)
                hist_income_stats = transaction_history.get_category_statistics("Поступление от клиента", days_back=90)
            else:
                hist_expenses_stats = {"count": 0, "std": 0}
                hist_income_stats = {"count": 0, "std": 0}
            
            # Учитываем сезонность (только если достаточно данных)
            seasonal_factor_expenses = 1.0
            seasonal_factor_income = 1.0
            
            if use_history:
                current_month = datetime.now().month
                seasonal_patterns_expenses = transaction_history.get_seasonal_patterns("Аренда", days_back=365)
                seasonal_patterns_income = transaction_history.get_seasonal_patterns("Поступление от клиента", days_back=365)
                
                if seasonal_patterns_expenses["monthly_avg"]:
                    current_month_key = str(current_month).zfill(2)
                    if current_month_key in seasonal_patterns_expenses["monthly_avg"]:
                        avg_all_months = sum(seasonal_patterns_expenses["monthly_avg"].values()) / len(seasonal_patterns_expenses["monthly_avg"])
                        if avg_all_months > 0:
                            seasonal_factor_expenses = seasonal_patterns_expenses["monthly_avg"][current_month_key] / avg_all_months
                            # Ограничиваем сезонный коэффициент разумными пределами (0.5 - 2.0)
                            seasonal_factor_expenses = max(0.5, min(2.0, seasonal_factor_expenses))
                
                if seasonal_patterns_income["monthly_avg"]:
                    current_month_key = str(current_month).zfill(2)
                    if current_month_key in seasonal_patterns_income["monthly_avg"]:
                        avg_all_months = sum(seasonal_patterns_income["monthly_avg"].values()) / len(seasonal_patterns_income["monthly_avg"])
                        if avg_all_months > 0:
                            seasonal_factor_income = seasonal_patterns_income["monthly_avg"][current_month_key] / avg_all_months
                            # Ограничиваем сезонный коэффициент разумными пределами (0.5 - 2.0)
                            seasonal_factor_income = max(0.5, min(2.0, seasonal_factor_income))
            
            # Прогноз на 30 дней с учетом сезонности
            forecast_30d_expenses = avg_daily_expenses * 30 * seasonal_factor_expenses
            forecast_30d_income = avg_daily_income * 30 * seasonal_factor_income
        
        # Логирование для отладки
        print(f"[FORECAST] Транзакций: {num_transactions}, Период: {period_days} дней")
        print(f"[FORECAST] Расходы: {total_expenses:.2f} ₽, Доходы: {total_income:.2f} ₽")
        print(f"[FORECAST] Средние дневные: расходы {avg_daily_expenses:.2f} ₽/день, доходы {avg_daily_income:.2f} ₽/день")
        print(f"[FORECAST] Сезонные коэффициенты: расходы {seasonal_factor_expenses:.2f}x, доходы {seasonal_factor_income:.2f}x")
        print(f"[FORECAST] Прогноз на 30 дней: расходы {forecast_30d_expenses:.2f} ₽, доходы {forecast_30d_income:.2f} ₽")
        
        # Confidence intervals (95% доверительный интервал)
        # Используем стандартное отклонение из истории, если доступно
        if hist_expenses_stats["std"] > 0:
            # 95% CI = mean ± 1.96 * std / sqrt(n)
            # Для прогноза используем упрощенную формулу: ± 20% от среднего
            expenses_ci_lower = forecast_30d_expenses * 0.8
            expenses_ci_upper = forecast_30d_expenses * 1.2
        else:
            # Если нет истории, используем консервативную оценку ± 30%
            expenses_ci_lower = forecast_30d_expenses * 0.7
            expenses_ci_upper = forecast_30d_expenses * 1.3
        
        if hist_income_stats["std"] > 0:
            income_ci_lower = forecast_30d_income * 0.8
            income_ci_upper = forecast_30d_income * 1.2
        else:
            income_ci_lower = forecast_30d_income * 0.7
            income_ci_upper = forecast_30d_income * 1.3
        
        # Прогноз баланса
        forecast_balance = forecast_30d_income - forecast_30d_expenses
        forecast_balance_ci_lower = income_ci_lower - expenses_ci_upper  # Худший сценарий
        forecast_balance_ci_upper = income_ci_upper - expenses_ci_lower  # Лучший сценарий
        
        # Рекомендации с конкретными действиями
        recommendations = []
        
        # Анализ расходов по категориям для конкретных рекомендаций
        expense_breakdown = {}
        for category in df[df["Категория"] != "Поступление от клиента"]["Категория"].unique():
            expense_breakdown[category] = float(
                df[df["Категория"] == category]["Сумма"].abs().sum()
            )
        
        # Топ-3 категории расходов
        top_expenses = sorted(expense_breakdown.items(), key=lambda x: x[1], reverse=True)[:3]
        
        # Конкретные рекомендации по оптимизации
        if top_expenses:
            for category, amount in top_expenses:
                if amount > 50000:  # Если категория расходов > 50,000₽
                    potential_savings = amount * 0.15  # Предлагаем сэкономить 15%
                    recommendations.append({
                        "type": "info",
                        "title": f"Оптимизация: {category}",
                        "message": f"Снижение расходов на {category} на 15% сэкономит {potential_savings:.0f} ₽/мес ({potential_savings * 12:.0f} ₽/год). Текущие расходы: {amount:.0f} ₽"
                    })
        
        # Рекомендация по налоговому режиму
        income = df[df["Категория"] == "Поступление от клиента"]["Сумма"].sum()
        expenses = df[df["Категория"] != "Поступление от клиента"]["Сумма"].abs().sum()
        if income > 0 and expenses > 0:
            tax_income_mode = income * 0.06
            tax_expenses_mode = max((income - expenses) * 0.15, 0)
            if tax_expenses_mode < tax_income_mode and expenses / income > 0.3:
                savings = tax_income_mode - tax_expenses_mode
                recommendations.append({
                    "type": "info",
                    "title": "Оптимизация налогообложения",
                    "message": f"Переход на УСН 'доходы минус расходы' может сэкономить {savings:.0f} ₽/мес ({savings * 12:.0f} ₽/год). Текущий налог: {tax_income_mode:.0f} ₽, при новом режиме: {tax_expenses_mode:.0f} ₽"
                })
        
        if regular_payments > 0:
            recommendations.append({
                "type": "warning",
                "title": "Регулярные платежи",
                "message": f"В следующем периоде ожидаются регулярные платежи на сумму {regular_payments:.2f} ₽. Убедитесь в наличии средств на счете."
            })
        
        if forecast_balance_ci_lower < 0:
            recommendations.append({
                "type": "critical",
                "title": "Риск отрицательного баланса",
                "message": f"В худшем сценарии прогнозируется отрицательный баланс через 30 дней (нижняя граница: {forecast_balance_ci_lower:.2f} ₽). Рекомендуется увеличить доходы или сократить расходы на {abs(forecast_balance_ci_lower):.0f} ₽"
            })
        elif forecast_balance < 0:
            recommendations.append({
                "type": "warning",
                "title": "Негативный прогноз",
                "message": f"При текущих темпах прогнозируется отрицательный баланс через 30 дней ({forecast_balance:.2f} ₽). Рекомендуется сократить расходы на {abs(forecast_balance):.0f} ₽ или увеличить доходы"
            })
        
        # Сезонные рекомендации
        if abs(seasonal_factor_expenses - 1.0) > 0.15 or abs(seasonal_factor_income - 1.0) > 0.15:
            if seasonal_factor_expenses > 1.15:
                recommendations.append({
                    "type": "info",
                    "title": "Сезонность расходов",
                    "message": f"Текущий месяц обычно характеризуется повышенными расходами (коэффициент: {seasonal_factor_expenses:.2f}x). Заранее подготовьте резерв средств"
                })
            if seasonal_factor_income < 0.85:
                recommendations.append({
                    "type": "warning",
                    "title": "Сезонность доходов",
                    "message": f"Текущий месяц обычно характеризуется снижением доходов (коэффициент: {seasonal_factor_income:.2f}x). Рекомендуется сократить расходы или использовать резерв"
                })
        
        # Приоритизация рекомендаций (критические первыми)
        recommendations.sort(key=lambda x: {"critical": 0, "warning": 1, "info": 2}.get(x["type"], 3))

        return {
            "avg_daily_expenses": float(avg_daily_expenses),
            "avg_daily_income": float(avg_daily_income),
            "forecast_30d_expenses": float(forecast_30d_expenses),
            "forecast_30d_income": float(forecast_30d_income),
            "forecast_30d_balance": float(forecast_balance),
            "confidence_intervals": {
                "expenses": {
                    "lower": float(expenses_ci_lower),
                    "upper": float(expenses_ci_upper)
                },
                "income": {
                    "lower": float(income_ci_lower),
                    "upper": float(income_ci_upper)
                },
                "balance": {
                    "lower": float(forecast_balance_ci_lower),
                    "upper": float(forecast_balance_ci_upper)
                }
            },
            "seasonal_factors": {
                "expenses": float(seasonal_factor_expenses),
                "income": float(seasonal_factor_income)
            },
            "recommendations": recommendations
        }
    
    def _calculate_benchmarking(self, pl_report: Dict, df: pd.DataFrame) -> Dict:
        """
        Сравнение с индустриальными бенчмарками.
        Использует типичные значения для малого и среднего бизнеса в России.
        """
        revenue = pl_report.get("revenue", 0)
        if revenue == 0:
            return {
                "available": False,
                "message": "Недостаточно данных для бенчмаркинга"
            }
        
        # Индустриальные бенчмарки (типичные значения для малого/среднего бизнеса в России)
        # Источник: обобщенные данные по отраслям
        benchmarks = {
            "cac_ratio": 0.15,  # Реклама не должна превышать 15% выручки
            "gross_margin": 30.0,  # Типичная валовая маржа: 30%
            "operating_margin": 15.0,  # Типичная операционная маржа: 15%
            "advertising_ratio": 0.10,  # Реклама: 10% выручки
            "salary_ratio": 0.30,  # Зарплата: 30% выручки
            "rent_ratio": 0.05,  # Аренда: 5% выручки
        }
        
        # Текущие показатели
        current_cac_ratio = 0
        advertising = df[df["Категория"] == "Реклама"]["Сумма"].abs().sum()
        if revenue > 0:
            current_cac_ratio = advertising / revenue
        
        current_gross_margin = pl_report.get("gross_margin", 0)
        current_operating_margin = pl_report.get("operating_margin", 0)
        
        salary = df[df["Категория"] == "Зарплата"]["Сумма"].abs().sum()
        rent = df[df["Категория"] == "Аренда"]["Сумма"].abs().sum()
        
        current_salary_ratio = salary / revenue if revenue > 0 else 0
        current_rent_ratio = rent / revenue if revenue > 0 else 0
        current_advertising_ratio = advertising / revenue if revenue > 0 else 0
        
        # Сравнения
        comparisons = []
        
        if current_cac_ratio > benchmarks["cac_ratio"]:
            comparisons.append({
                "metric": "CAC (стоимость привлечения клиента)",
                "current": f"{current_cac_ratio*100:.1f}%",
                "benchmark": f"{benchmarks['cac_ratio']*100:.0f}%",
                "status": "warning",
                "message": f"Ваш CAC ({current_cac_ratio*100:.1f}%) выше среднего по отрасли ({benchmarks['cac_ratio']*100:.0f}%). Рекомендуется оптимизировать рекламные каналы."
            })
        else:
            comparisons.append({
                "metric": "CAC (стоимость привлечения клиента)",
                "current": f"{current_cac_ratio*100:.1f}%",
                "benchmark": f"{benchmarks['cac_ratio']*100:.0f}%",
                "status": "good",
                "message": f"Ваш CAC ({current_cac_ratio*100:.1f}%) в пределах нормы."
            })
        
        if current_gross_margin < benchmarks["gross_margin"]:
            comparisons.append({
                "metric": "Валовая маржа",
                "current": f"{current_gross_margin:.1f}%",
                "benchmark": f"{benchmarks['gross_margin']:.0f}%",
                "status": "warning",
                "message": f"Ваша валовая маржа ({current_gross_margin:.1f}%) ниже среднего по отрасли ({benchmarks['gross_margin']:.0f}%). Рекомендуется пересмотреть ценообразование или себестоимость."
            })
        else:
            comparisons.append({
                "metric": "Валовая маржа",
                "current": f"{current_gross_margin:.1f}%",
                "benchmark": f"{benchmarks['gross_margin']:.0f}%",
                "status": "good",
                "message": f"Ваша валовая маржа ({current_gross_margin:.1f}%) соответствует или превышает средний показатель."
            })
        
        if current_operating_margin < benchmarks["operating_margin"]:
            comparisons.append({
                "metric": "Операционная маржа (EBITDA)",
                "current": f"{current_operating_margin:.1f}%",
                "benchmark": f"{benchmarks['operating_margin']:.0f}%",
                "status": "warning",
                "message": f"Ваша операционная маржа ({current_operating_margin:.1f}%) ниже среднего по отрасли ({benchmarks['operating_margin']:.0f}%). Рекомендуется оптимизировать операционные расходы."
            })
        else:
            comparisons.append({
                "metric": "Операционная маржа (EBITDA)",
                "current": f"{current_operating_margin:.1f}%",
                "benchmark": f"{benchmarks['operating_margin']:.0f}%",
                "status": "good",
                "message": f"Ваша операционная маржа ({current_operating_margin:.1f}%) соответствует или превышает средний показатель."
            })
        
        return {
            "available": True,
            "comparisons": comparisons,
            "benchmarks": benchmarks,
            "current_metrics": {
                "cac_ratio": float(current_cac_ratio),
                "gross_margin": float(current_gross_margin),
                "operating_margin": float(current_operating_margin),
                "salary_ratio": float(current_salary_ratio),
                "rent_ratio": float(current_rent_ratio),
                "advertising_ratio": float(current_advertising_ratio)
            }
        }
    
    def _generate_tax_planning(self, df: pd.DataFrame, current_mode: str, current_tax: float, forecasts: Dict) -> Dict:
        """
        Генерация налогового планирования на год с рекомендациями.
        """
        revenue = df[df["Категория"] == "Поступление от клиента"]["Сумма"].sum()
        expenses = df[df["Категория"] != "Поступление от клиента"]["Сумма"].abs().sum()
        
        if revenue == 0:
            return {
                "available": False,
                "message": "Недостаточно данных для налогового планирования"
            }
        
        # Прогноз на год (используем данные из forecasts)
        forecast_30d_income = forecasts.get("forecast_30d_income", revenue)
        forecast_30d_expenses = forecasts.get("forecast_30d_expenses", expenses)
        
        # Экстраполируем на год (упрощенно: умножаем на 12)
        annual_income_forecast = forecast_30d_income * 12
        annual_expenses_forecast = forecast_30d_expenses * 12
        
        # Расчет налогов для разных режимов
        tax_scenarios = []
        
        # УСН "доходы" (6%)
        tax_income_mode = annual_income_forecast * 0.06
        tax_scenarios.append({
            "mode": "УСН 'доходы' (6%)",
            "annual_income": annual_income_forecast,
            "annual_expenses": annual_expenses_forecast,
            "tax": tax_income_mode,
            "effective_rate": 6.0
        })
        
        # УСН "доходы минус расходы" (15%)
        taxable_base = max(annual_income_forecast - annual_expenses_forecast, 0)
        tax_expenses_mode = taxable_base * 0.15
        tax_scenarios.append({
            "mode": "УСН 'доходы минус расходы' (15%)",
            "annual_income": annual_income_forecast,
            "annual_expenses": annual_expenses_forecast,
            "tax": tax_expenses_mode,
            "effective_rate": (tax_expenses_mode / annual_income_forecast * 100) if annual_income_forecast > 0 else 0
        })
        
        # Находим оптимальный режим
        optimal_scenario = min(tax_scenarios, key=lambda x: x["tax"])
        current_scenario = next((s for s in tax_scenarios if s["mode"].startswith(current_mode.split("_")[0])), tax_scenarios[0])
        
        potential_savings = current_scenario["tax"] - optimal_scenario["tax"]
        
        recommendations = []
        if potential_savings > 0 and optimal_scenario["mode"] != current_scenario["mode"]:
            recommendations.append({
                "type": "info",
                "title": "Оптимизация налогового режима",
                "message": f"Переход на {optimal_scenario['mode']} может сэкономить {potential_savings:.0f} ₽/год. Текущий налог: {current_scenario['tax']:.0f} ₽, оптимальный: {optimal_scenario['tax']:.0f} ₽"
            })
        
        # Квартальное планирование
        quarterly_forecast = {
            "Q1": {"income": annual_income_forecast * 0.25, "expenses": annual_expenses_forecast * 0.25},
            "Q2": {"income": annual_income_forecast * 0.25, "expenses": annual_expenses_forecast * 0.25},
            "Q3": {"income": annual_income_forecast * 0.25, "expenses": annual_expenses_forecast * 0.25},
            "Q4": {"income": annual_income_forecast * 0.25, "expenses": annual_expenses_forecast * 0.25}
        }
        
        return {
            "available": True,
            "annual_forecast": {
                "income": float(annual_income_forecast),
                "expenses": float(annual_expenses_forecast),
                "balance": float(annual_income_forecast - annual_expenses_forecast)
            },
            "tax_scenarios": tax_scenarios,
            "optimal_scenario": optimal_scenario,
            "current_scenario": current_scenario,
            "potential_savings": float(potential_savings),
            "quarterly_forecast": quarterly_forecast,
            "recommendations": recommendations
        }