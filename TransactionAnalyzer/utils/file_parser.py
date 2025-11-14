import pandas as pd

def parse_transactions(file_bytes, filename):
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
