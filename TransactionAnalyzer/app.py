# -*- coding: utf-8 -*-
import io
import os
import pandas as pd
from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile, Form, HTTPException
from TransactionAnalyzer.utils.file_parser import parse_transactions
from TransactionAnalyzer.utils.categorizer import categorize_transactions
from TransactionAnalyzer.utils.logger import TokenUsageLogger, TimeLogger
from TransactionAnalyzer.utils.models import AnalyzeResponse
from TransactionAnalyzer.tax_calc import calculate_taxes

# === Загрузка конфигурации ===
load_dotenv()
BASE_URL = os.getenv("BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
LLM_MODEL = os.getenv("LLM_MODEL", "openai/gpt-5")

# === Инициализация приложения ===
app = FastAPI(title="TransactionAnalyzer")
token_logger = TokenUsageLogger()
time_logger = TimeLogger()


@app.get("/health")
def health_check():
    """Проверка статуса микросервиса."""
    return {"status": "ok", "model": LLM_MODEL, "service": "TransactionAnalyzer"}


@app.post("/analyze", response_model=AnalyzeResponse)
async def analyze_transactions(file: UploadFile, tax_mode: str = Form("УСН_доходы")):
    """Главный эндпоинт: парсинг, классификация, расчёт налогов."""
    try:
        content = await file.read()
        df = parse_transactions(io.BytesIO(content), file.filename)

        if "Назначение платежа" not in df.columns:
            raise HTTPException(status_code=400, detail="Колонка 'Назначение платежа' не найдена")

        df["Категория"] = await categorize_transactions(
            df["Назначение платежа"].tolist(),
            base_url=BASE_URL,
            api_key=OPENROUTER_API_KEY,
            model_name=LLM_MODEL,
            token_logger=token_logger,
            time_logger=time_logger,
        )

        total_tax, tax_table = calculate_taxes(df, mode=tax_mode)
        token_logger.save()
        time_logger.save()

        return {
            "summary": {"mode": tax_mode, "tax": total_tax, "transactions": len(df)},
            "transactions": tax_table.to_dict(orient="records"),
        }

    except HTTPException as e:
        raise e
    except Exception as e:
        print(f"[ERROR] Ошибка при обработке файла: {e}")
        raise HTTPException(status_code=500, detail=str(e))
