# -*- coding: utf-8 -*-
"""
Утилиты для экспорта результатов в различные форматы
"""
import json
from datetime import datetime
from typing import Dict, Any
import pandas as pd
from io import BytesIO


def export_transactions_to_excel(result: Dict[str, Any]) -> BytesIO:
    """
    Экспортирует результаты анализа транзакций в Excel
    
    Args:
        result: Результат от transaction_analyzer
    
    Returns:
        BytesIO объект с Excel файлом
    """
    output = BytesIO()
    
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        # Лист 1: Сводка
        summary_data = {
            "Показатель": ["Режим налогообложения", "Количество транзакций", "Налог к уплате"],
            "Значение": [
                result.get("summary", {}).get("mode", ""),
                result.get("summary", {}).get("transactions", 0),
                f"{result.get('summary', {}).get('tax', 0):.2f} ₽"
            ]
        }
        df_summary = pd.DataFrame(summary_data)
        df_summary.to_excel(writer, sheet_name="Сводка", index=False)
        
        # Лист 2: Детализация
        if result.get("transactions"):
            df_details = pd.DataFrame(result["transactions"])
            df_details.to_excel(writer, sheet_name="Детализация", index=False)
    
    output.seek(0)
    return output


def export_document_analysis_to_pdf(result: Dict[str, Any]) -> str:
    """
    Экспортирует результаты анализа документа в текстовый формат
    (PDF требует дополнительных библиотек, возвращаем markdown для простоты)
    
    Args:
        result: Результат от document_analyzer
    
    Returns:
        Markdown строка (можно конвертировать в PDF позже)
    """
    filename = result.get("filename", "Документ")
    analysis = result.get("analysis", "")
    
    markdown = f"""# Анализ документа: {filename}

**Дата анализа:** {datetime.now().strftime("%d.%m.%Y %H:%M")}

---

{analysis}

---
*Сгенерировано системой ФинПульс*
"""
    return markdown


def export_consultant_to_markdown(result: Dict[str, Any]) -> str:
    """
    Экспортирует ответ консультанта в markdown
    
    Args:
        result: Результат от regulatory_consultant
    
    Returns:
        Markdown строка
    """
    question = result.get("question", "")
    answer = result.get("answer", "")
    
    markdown = f"""# Вопрос юридическому консультанту

**Дата:** {datetime.now().strftime("%d.%m.%Y %H:%M")}

## Вопрос

{question}

---

## Ответ

{answer}

---
*Сгенерировано системой ФинПульс*
"""
    return markdown


def export_history_to_json(history: list) -> str:
    """
    Экспортирует историю в JSON
    
    Args:
        history: Список записей истории
    
    Returns:
        JSON строка
    """
    return json.dumps(history, ensure_ascii=False, indent=2)


def export_history_to_excel(history: list) -> BytesIO:
    """
    Экспортирует историю в Excel
    
    Args:
        history: Список записей истории
    
    Returns:
        BytesIO объект с Excel файлом
    """
    output = BytesIO()
    
    # Подготовка данных
    rows = []
    for entry in history:
        service_type = entry.get("service_type", "")
        timestamp = entry.get("timestamp", "")
        input_data = entry.get("input", {})
        result = entry.get("result", {})
        
        # Формируем строку
        row = {
            "Дата и время": timestamp,
            "Сервис": service_type,
            "Входные данные": json.dumps(input_data, ensure_ascii=False),
            "Результат": json.dumps(result, ensure_ascii=False)[:500]  # Ограничиваем длину
        }
        rows.append(row)
    
    df = pd.DataFrame(rows)
    df.to_excel(output, index=False, engine='openpyxl')
    output.seek(0)
    
    return output

