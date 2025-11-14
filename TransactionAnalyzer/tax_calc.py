import pandas as pd

def calculate_taxes(df: pd.DataFrame, mode: str = "УСН_доходы"):
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
