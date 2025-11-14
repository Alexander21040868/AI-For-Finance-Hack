from pydantic import BaseModel
from typing import List, Optional

class TaxRow(BaseModel):
    Показатель: str
    Значение: float

class AnalyzeSummary(BaseModel):
    mode: str
    tax: float

class AnalyzeResponse(BaseModel):
    summary: AnalyzeSummary
    transactions: List[TaxRow]

