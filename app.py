# -*- coding: utf-8 -*-
"""
Единый FastAPI бэкенд для проекта ФинПульс
Объединяет три сервиса: TransactionAnalyzer, DocumentAnalyzer, RegulatoryConsultant
"""
import os
import io
import json
from typing import Optional
from datetime import datetime
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from openai import OpenAI
from config import BASE_URL, OPEN_ROUTER_API_KEY
from config import REGULATORY_CONSULTANT_CHUNKS_PATH
from config import REGULATORY_CONSULTANT_FAISS_INDEX_PATH
from config import SAVE_RAG_FILES
from config import USE_LOCAL_RAG_FILES

from transaction_analyzer import TransactionAnalyzer
from document_analyzer import DocumentAnalyzer
from regulatory_consultant import RegulatoryConsultant
from document_utils import batch_extract_text
from time_logger import time_logger
from token_logger import token_logger
from history_manager import history_manager
from export_utils import (
    export_transactions_to_excel,
    export_document_analysis_to_pdf,
    export_consultant_to_markdown,
    export_history_to_json,
    export_history_to_excel
)

# === КОНФИГУРАЦИЯ ===
EMBEDDING_MODEL = "openai/text-embedding-3-small"
GENERATION_MODEL = "google/gemini-2.5-flash-lite"

# === ИНИЦИАЛИЗАЦИЯ КЛИЕНТА ===
open_router_client = OpenAI(base_url=BASE_URL, api_key=OPEN_ROUTER_API_KEY)

# === ИНИЦИАЛИЗАЦИЯ СЕРВИСОВ ===
transaction_analyzer = TransactionAnalyzer(
    open_router_client,
    GENERATION_MODEL
)

document_analyzer = DocumentAnalyzer(
    open_router_client,
    GENERATION_MODEL
)

regulatory_consultant = RegulatoryConsultant(
    open_router_client,
    EMBEDDING_MODEL,
    GENERATION_MODEL,
    USE_LOCAL_RAG_FILES,
    SAVE_RAG_FILES,
    REGULATORY_CONSULTANT_FAISS_INDEX_PATH,
    REGULATORY_CONSULTANT_CHUNKS_PATH
)

# === СОЗДАНИЕ FASTAPI ПРИЛОЖЕНИЯ ===
app = FastAPI(
    title="ФинПульс API",
    description="Единый API для анализа транзакций, документов и консультаций по налогам",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Создаём папку static, если её нет
os.makedirs("static", exist_ok=True)
os.makedirs("uploads", exist_ok=True)

# Монтируем статические файлы
app.mount("/static", StaticFiles(directory="static"), name="static")


# === ЭНДПОИНТЫ ===

@app.get("/", response_class=HTMLResponse)
async def root():
    """Главная страница - отдаём фронтенд"""
    try:
        with open("static/index.html", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return """
        <html>
            <body>
                <h1>ФинПульс API</h1>
                <p>Фронтенд не найден. Создайте файл static/index.html</p>
                <p>API документация: <a href="/docs">/docs</a></p>
            </body>
        </html>
        """


@app.get("/health")
async def health_check():
    """Проверка работоспособности сервиса"""
    return {
        "status": "ok",
        "services": {
            "transaction_analyzer": "ready",
            "document_analyzer": "ready",
            "regulatory_consultant": "ready"
        }
    }


@app.post("/api/analyze-transactions")
async def analyze_transactions_endpoint(
    file: UploadFile = File(...),
    tax_mode: str = Form("УСН_доходы")
):
    """
    Анализ банковской выписки
    
    - **file**: CSV или XLSX файл с транзакциями
    - **tax_mode**: Режим налогообложения ("УСН_доходы" или "УСН_доходы_минус_расходы")
    """
    try:
        # Читаем содержимое файла
        content = await file.read()
        
        # Сохраняем файл временно
        file_path = f"uploads/{file.filename}"
        with open(file_path, "wb") as f:
            f.write(content)
        
        # Перематываем файл назад для анализа
        file.file.seek(0)
        
        # Анализируем
        result = await transaction_analyzer.analyze_transactions(
            file=file,
            tax_mode=tax_mode
        )
        
        # Удаляем временный файл
        if os.path.exists(file_path):
            os.remove(file_path)
        
        # Сохраняем логи
        time_logger.save_reports()
        token_logger.save_reports()
        
        # Сохраняем в историю
        history_manager.add_entry(
            service_type="transactions",
            input_data={"filename": file.filename, "tax_mode": tax_mode},
            result=result
        )
        
        return result
        
    except Exception as e:
        import traceback
        error_detail = f"Ошибка при анализе транзакций: {str(e)}"
        print(f"[ERROR] {error_detail}")
        print(f"[DEBUG] Traceback:\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=error_detail)


@app.post("/api/analyze-document")
async def analyze_document_endpoint(
    file: UploadFile = File(...)
):
    """
    Анализ юридического документа
    
    - **file**: PDF, DOCX или JPG файл с документом
    """
    try:
        # Сохраняем файл временно
        file_path = f"uploads/{file.filename}"
        with open(file_path, "wb") as f:
            content = await file.read()
            f.write(content)
        
        # Извлекаем текст
        extracted_documents = batch_extract_text(
            [file_path],
            open_router_client,
            GENERATION_MODEL
        )
        
        if not extracted_documents or "error" in extracted_documents[0]:
            raise HTTPException(
                status_code=400,
                detail=extracted_documents[0].get("error", "Не удалось извлечь текст из документа")
            )
        
        # Генерируем анализ
        document_text = extracted_documents[0].get("text", "")
        analysis = document_analyzer.generate_summary(document_text)
        
        # Удаляем временный файл
        if os.path.exists(file_path):
            os.remove(file_path)
        
        # Сохраняем логи
        time_logger.save_reports()
        token_logger.save_reports()
        
        result = {
            "filename": file.filename,
            "analysis": analysis
        }
        
        # Сохраняем в историю
        history_manager.add_entry(
            service_type="documents",
            input_data={"filename": file.filename},
            result=result
        )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка при анализе документа: {str(e)}")


@app.post("/api/ask-question")
async def ask_question_endpoint(
    question: str = Form(...)
):
    """
    Консультация по налогам и законодательству
    
    - **question**: Вопрос пользователя
    """
    try:
        if not question or len(question.strip()) == 0:
            raise HTTPException(status_code=400, detail="Вопрос не может быть пустым")
        
        # Получаем ответ от консультанта
        answer = regulatory_consultant.answer_question(question)
        
        # Сохраняем логи
        time_logger.save_reports()
        token_logger.save_reports()
        
        result = {
            "question": question,
            "answer": answer
        }
        
        # Сохраняем в историю
        history_manager.add_entry(
            service_type="consultant",
            input_data={"question": question},
            result=result
        )
        
        return result
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка при обработке вопроса: {str(e)}")


@app.get("/api/logs/tokens")
async def get_token_logs():
    """Получить статистику использования токенов"""
    try:
        logs_dir = "logs"
        if not os.path.exists(logs_dir):
            return {"logs": []}
        
        log_files = [f for f in os.listdir(logs_dir) if f.startswith("token_logger_")]
        return {"files": log_files}
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/logs/time")
async def get_time_logs():
    """Получить статистику времени выполнения"""
    try:
        logs_dir = "logs"
        if not os.path.exists(logs_dir):
            return {"logs": []}
        
        log_files = [f for f in os.listdir(logs_dir) if f.startswith("time_analyzer_")]
        return {"files": log_files}
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/history")
async def get_history(service_type: Optional[str] = None, limit: int = 50):
    """
    Получить историю запросов
    
    - **service_type**: Фильтр по типу ('transactions', 'documents', 'consultant')
    - **limit**: Максимальное количество записей (по умолчанию 50)
    """
    try:
        history = history_manager.get_history(service_type=service_type, limit=limit)
        return {"history": history, "count": len(history)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка при получении истории: {str(e)}")


@app.delete("/api/history")
async def clear_history():
    """Очистить историю запросов"""
    try:
        history_manager.clear_history()
        return {"message": "История очищена"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка при очистке истории: {str(e)}")


@app.post("/api/export/transactions")
async def export_transactions(result_data: str = Form(...)):
    """
    Экспортировать результаты анализа транзакций в Excel
    
    - **result_data**: JSON строка с результатами анализа
    """
    try:
        result = json.loads(result_data)
        excel_file = export_transactions_to_excel(result)
        
        filename = f"transactions_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        excel_file.seek(0)
        return StreamingResponse(
            excel_file,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка при экспорте: {str(e)}")


@app.post("/api/export/document")
async def export_document(result_data: str = Form(...)):
    """
    Экспортировать результаты анализа документа в текстовый формат
    
    - **result_data**: JSON строка с результатами анализа
    """
    try:
        result = json.loads(result_data)
        markdown = export_document_analysis_to_pdf(result)
        
        from fastapi.responses import Response
        filename = f"document_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        return Response(
            content=markdown,
            media_type="text/markdown",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка при экспорте: {str(e)}")


@app.post("/api/export/consultant")
async def export_consultant(result_data: str = Form(...)):
    """
    Экспортировать ответ консультанта в markdown
    
    - **result_data**: JSON строка с результатами
    """
    try:
        result = json.loads(result_data)
        markdown = export_consultant_to_markdown(result)
        
        from fastapi.responses import Response
        filename = f"consultant_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        return Response(
            content=markdown,
            media_type="text/markdown",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка при экспорте: {str(e)}")


@app.get("/api/export/history")
async def export_history(format: str = "json", service_type: Optional[str] = None):
    """
    Экспортировать историю запросов
    
    - **format**: Формат экспорта ('json' или 'excel')
    - **service_type**: Фильтр по типу сервиса (опционально)
    """
    try:
        history = history_manager.get_history(service_type=service_type, limit=1000)
        
        if format == "excel":
            excel_file = export_history_to_excel(history)
            filename = f"history_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
            excel_file.seek(0)
            return StreamingResponse(
                excel_file,
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                headers={"Content-Disposition": f"attachment; filename={filename}"}
            )
        else:
            json_data = export_history_to_json(history)
            from fastapi.responses import Response
            filename = f"history_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            return Response(
                content=json_data,
                media_type="application/json",
                headers={"Content-Disposition": f"attachment; filename={filename}"}
            )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка при экспорте истории: {str(e)}")


if __name__ == "__main__":
    print("""
    ╔═══════════════════════════════════════════════════════╗
    ║                 🚀 ФинПульс API                       ║
    ║                                                       ║
    ║  Сервер запущен!                                     ║
    ║  Веб-интерфейс: http://localhost:8000                ║
    ║  API документация: http://localhost:8000/docs        ║
    ╚═══════════════════════════════════════════════════════╝
    """)
    
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )

