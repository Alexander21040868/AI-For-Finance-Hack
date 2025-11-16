# -*- coding: utf-8 -*-
"""
Единый FastAPI бэкенд для проекта ФинПульс
Объединяет три сервиса: TransactionAnalyzer, DocumentAnalyzer, RegulatoryConsultant
"""
import os
import io
import json
from typing import Optional
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
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
        
        return result
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка при анализе транзакций: {str(e)}")


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
        
        return {
            "filename": file.filename,
            "analysis": analysis
        }
        
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
        
        return {
            "question": question,
            "answer": answer
        }
        
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

