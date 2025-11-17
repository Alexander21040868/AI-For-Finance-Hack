# -*- coding: utf-8 -*-
"""
Утилиты для экспорта результатов в различные форматы
"""
import json
from datetime import datetime
from typing import Dict, Any
import pandas as pd
from io import BytesIO
try:
    from reportlab.lib.pagesizes import letter, A4
    from reportlab.lib import colors
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False


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


def export_transactions_to_pdf(result: Dict[str, Any]) -> BytesIO:
    """
    Экспортирует результаты анализа транзакций в PDF
    
    Args:
        result: Результат от transaction_analyzer
    
    Returns:
        BytesIO объект с PDF файлом
    """
    if not REPORTLAB_AVAILABLE:
        raise ImportError("reportlab не установлен. Установите: pip install reportlab")
    
    output = BytesIO()
    doc = SimpleDocTemplate(output, pagesize=A4)
    story = []
    styles = getSampleStyleSheet()
    
    # Заголовок
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=colors.HexColor('#6366f1'),
        spaceAfter=30,
        alignment=TA_CENTER
    )
    story.append(Paragraph("Отчет по анализу транзакций", title_style))
    story.append(Spacer(1, 0.2*inch))
    
    # Сводка
    summary = result.get("summary", {})
    summary_data = [
        ["Показатель", "Значение"],
        ["Режим налогообложения", summary.get("mode", "")],
        ["Количество транзакций", str(summary.get("transactions", 0))],
        ["Налог к уплате", f"{summary.get('tax', 0):.2f} ₽"],
        ["Доходы", f"{summary.get('income', 0):.2f} ₽"],
        ["Расходы", f"{summary.get('expenses', 0):.2f} ₽"]
    ]
    
    summary_table = Table(summary_data, colWidths=[3*inch, 3*inch])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#6366f1')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    story.append(summary_table)
    story.append(Spacer(1, 0.3*inch))
    
    # P&L отчет
    pl_report = result.get("pl_report", {})
    if pl_report:
        story.append(Paragraph("Отчет о прибылях и убытках", styles['Heading2']))
        pl_data = [
            ["Показатель", "Значение"],
            ["Выручка", f"{pl_report.get('revenue', 0):.2f} ₽"],
            ["COGS", f"{pl_report.get('cogs', 0):.2f} ₽"],
            ["Валовая прибыль", f"{pl_report.get('gross_profit', 0):.2f} ₽ ({pl_report.get('gross_margin', 0):.1f}%)"],
            ["Операционные расходы", f"{pl_report.get('operating_expenses', 0):.2f} ₽"],
            ["EBITDA", f"{pl_report.get('operating_profit', 0):.2f} ₽ ({pl_report.get('operating_margin', 0):.1f}%)"]
        ]
        pl_table = Table(pl_data, colWidths=[3*inch, 3*inch])
        pl_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#6366f1')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        story.append(pl_table)
        story.append(Spacer(1, 0.3*inch))
    
    # Детализация транзакций (первые 50)
    detailed = result.get("detailed_transactions", [])
    if detailed:
        story.append(Paragraph("Детализация транзакций", styles['Heading2']))
        story.append(Paragraph(f"(Показано {min(50, len(detailed))} из {len(detailed)} транзакций)", styles['Normal']))
        
        # Подготовка данных для таблицы
        table_data = [["Дата", "Категория", "Сумма", "Контрагент"]]
        for tx in detailed[:50]:
            table_data.append([
                tx.get("Дата", ""),
                tx.get("Категория", ""),
                f"{tx.get('Сумма', 0):.2f} ₽",
                tx.get("Контрагент", "")[:30]  # Ограничиваем длину
            ])
        
        details_table = Table(table_data, colWidths=[1*inch, 1.5*inch, 1*inch, 2.5*inch])
        details_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#6366f1')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.beige])
        ]))
        story.append(details_table)
    
    # Футер
    story.append(Spacer(1, 0.3*inch))
    footer_style = ParagraphStyle(
        'Footer',
        parent=styles['Normal'],
        fontSize=8,
        textColor=colors.grey,
        alignment=TA_CENTER
    )
    story.append(Paragraph(f"Сгенерировано системой ФинПульс {datetime.now().strftime('%d.%m.%Y %H:%M')}", footer_style))
    
    doc.build(story)
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

