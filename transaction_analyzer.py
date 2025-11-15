import pandas as pd
import io

from openai import OpenAI
from time_logger import timed
from token_logger import token_logger

from pydantic import BaseModel
from typing import List


CATEGORIES = [
    "Аренда", "Зарплата", "Закупка товара", "Хозяйственные нужды",
    "Реклама", "IT-услуги", "Поступление от клиента", "Прочее", "Не принимаемые расходы"
]

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
        """Читает CSV/XLSX и проверяет нужные колонки."""
        if filename.endswith(".csv"):
            df = pd.read_csv(file_bytes)
        elif filename.endswith(".xlsx"):
            df = pd.read_excel(file_bytes)
        else:
            raise ValueError("Поддерживаются только CSV и XLSX файлы")

        required_cols = ["Дата", "Назначение платежа", "Сумма"]
        for col in required_cols:
            if col not in df.columns:
                raise ValueError(f"Отсутствует обязательная колонка: {col}")

        return df

    @timed
    def categorize_transactions(self, texts: list[str]) -> list[str]:
        """Отправляет транзакции на классификацию в LLM."""
        results = []

        for text in texts:
            prompt = (
                f"Ты — AI-бухгалтер. Определи категорию транзакции: «{text}».\n"
                f"Категории: {', '.join(CATEGORIES)}.\n"
                f"Если расход нельзя учесть по УСН, выбери 'Не принимаемые расходы'.\n"
                "Ответь только одним словом — названием категории."
            )

            try:
                response = self.open_router_client.chat.completions.create(
                    model=self.generation_model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.0,
                )
                msg = response.choices[0].message.content.strip()
                results.append(msg)

                if hasattr(response, "usage"):
                    token_logger.log(
                        response.usage,
                        self.generation_model,
                        "categorize_transaction",
                        f"{text=}, {msg=}"
                    )

            except Exception as e:
                print(f"[WARN] Ошибка при LLM-запросе: {e}")
                results.append("Прочее")

        return results

    @timed
    async def analyze_transactions(self, file, tax_mode: str = "УСН_доходы") -> dict | None:
        """Парсинг, классификация, расчёт налогов."""
        try:
            content = await file.read()
            df = self.parse_transactions(io.BytesIO(content), file.filename)

            if "Назначение платежа" not in df.columns:
                raise Exception("Колонка 'Назначение платежа' не найдена")

            df["Категория"] = await self.categorize_transactions(
                df["Назначение платежа"].tolist(),
            )

            total_tax, tax_table = self.calculate_taxes(df, mode=tax_mode)

            return {
                "summary": {"mode": tax_mode, "tax": total_tax, "transactions": len(df)},
                "transactions": tax_table.to_dict(orient="records"),
            }

        except Exception as e:
            print(f"[ERROR] Ошибка при обработке файла: {e}")