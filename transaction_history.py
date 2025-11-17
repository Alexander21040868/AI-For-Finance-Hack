"""
Модуль для хранения и анализа истории транзакций.
Позволяет сравнивать текущие данные с предыдущими периодами.
"""
import json
import os
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from collections import defaultdict
import pandas as pd


class TransactionHistory:
    """Класс для управления историей транзакций."""
    
    def __init__(self, history_file: str = "transaction_history.jsonl"):
        self.history_file = history_file
        self._ensure_history_file()
    
    def _ensure_history_file(self):
        """Создает файл истории, если его нет."""
        if not os.path.exists(self.history_file):
            with open(self.history_file, 'w', encoding='utf-8') as f:
                pass  # Создаем пустой файл
    
    def save_transactions(self, transactions: List[Dict], metadata: Dict = None):
        """
        Сохраняет транзакции в историю.
        
        Args:
            transactions: Список транзакций с полями: Дата, Сумма, Категория, Подкатегория, Контрагент
            metadata: Дополнительные метаданные (режим налогообложения, имя файла и т.д.)
        """
        entry = {
            "timestamp": datetime.now().isoformat(),
            "metadata": metadata or {},
            "transactions": transactions
        }
        
        with open(self.history_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    
    def get_historical_transactions(self, days_back: int = 90) -> List[Dict]:
        """
        Получает транзакции за последние N дней.
        
        Args:
            days_back: Количество дней назад для выборки
            
        Returns:
            Список всех транзакций за период
        """
        cutoff_date = datetime.now() - timedelta(days=days_back)
        all_transactions = []
        
        if not os.path.exists(self.history_file):
            return []
        
        with open(self.history_file, 'r', encoding='utf-8') as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                    entry_date = datetime.fromisoformat(entry["timestamp"])
                    
                    if entry_date >= cutoff_date:
                        # Добавляем метаданные к каждой транзакции
                        for tx in entry.get("transactions", []):
                            tx_copy = tx.copy()
                            tx_copy["_entry_timestamp"] = entry["timestamp"]
                            all_transactions.append(tx_copy)
                except (json.JSONDecodeError, KeyError, ValueError) as e:
                    print(f"[WARN] Ошибка при чтении записи истории: {e}")
                    continue
        
        return all_transactions
    
    def get_counterparty_history(self, counterparty: str, days_back: int = 90) -> List[Dict]:
        """Получает историю транзакций с конкретным контрагентом."""
        all_transactions = self.get_historical_transactions(days_back)
        return [tx for tx in all_transactions if tx.get("Контрагент") == counterparty]
    
    def get_category_statistics(self, category: str, days_back: int = 90) -> Dict:
        """
        Получает статистику по категории за период.
        
        Returns:
            Dict с полями: count, total, mean, std, min, max, monthly_totals
        """
        all_transactions = self.get_historical_transactions(days_back)
        category_transactions = [
            tx for tx in all_transactions 
            if tx.get("Категория") == category
        ]
        
        if not category_transactions:
            return {
                "count": 0,
                "total": 0,
                "mean": 0,
                "std": 0,
                "min": 0,
                "max": 0,
                "monthly_totals": {}
            }
        
        amounts = [abs(float(tx.get("Сумма", 0))) for tx in category_transactions]
        
        # Группировка по месяцам
        monthly_totals = defaultdict(float)
        for tx in category_transactions:
            try:
                date_str = tx.get("Дата", "")
                if isinstance(date_str, str):
                    date = datetime.fromisoformat(date_str.split('T')[0])
                    month_key = date.strftime("%Y-%m")
                    monthly_totals[month_key] += abs(float(tx.get("Сумма", 0)))
            except (ValueError, AttributeError):
                continue
        
        return {
            "count": len(category_transactions),
            "total": sum(amounts),
            "mean": sum(amounts) / len(amounts) if amounts else 0,
            "std": pd.Series(amounts).std() if len(amounts) > 1 else 0,
            "min": min(amounts) if amounts else 0,
            "max": max(amounts) if amounts else 0,
            "monthly_totals": dict(monthly_totals)
        }
    
    def get_known_counterparties(self, days_back: int = 90) -> set:
        """Возвращает множество известных контрагентов за период."""
        all_transactions = self.get_historical_transactions(days_back)
        counterparties = set()
        for tx in all_transactions:
            counterparty = tx.get("Контрагент", "")
            if counterparty and counterparty != "—":
                counterparties.add(counterparty)
        return counterparties
    
    def get_seasonal_patterns(self, category: str, days_back: int = 365) -> Dict:
        """
        Анализирует сезонные паттерны для категории.
        
        Returns:
            Dict с полями: monthly_avg (средние по месяцам), trend (тренд)
        """
        all_transactions = self.get_historical_transactions(days_back)
        category_transactions = [
            tx for tx in all_transactions 
            if tx.get("Категория") == category
        ]
        
        # Группировка по месяцам
        monthly_totals = defaultdict(list)
        for tx in category_transactions:
            try:
                date_str = tx.get("Дата", "")
                if isinstance(date_str, str):
                    date = datetime.fromisoformat(date_str.split('T')[0])
                    month_key = date.strftime("%m")  # Только месяц (01-12)
                    monthly_totals[month_key].append(abs(float(tx.get("Сумма", 0))))
            except (ValueError, AttributeError):
                continue
        
        # Средние по месяцам
        monthly_avg = {
            month: sum(amounts) / len(amounts) if amounts else 0
            for month, amounts in monthly_totals.items()
        }
        
        # Простой тренд (линейная регрессия)
        if len(monthly_avg) >= 2:
            months = sorted([int(m) for m in monthly_avg.keys()])
            values = [monthly_avg[str(m).zfill(2)] for m in months]
            # Простой расчет тренда (рост/падение)
            if len(values) >= 2:
                trend = (values[-1] - values[0]) / len(values) if len(values) > 1 else 0
            else:
                trend = 0
        else:
            trend = 0
        
        return {
            "monthly_avg": monthly_avg,
            "trend": trend
        }
    
    def get_period_comparison(self, current_start: datetime, current_end: datetime, current_transactions_list: list = None) -> Dict:
        """
        Сравнивает текущий период с предыдущим периодом той же длительности.
        
        Args:
            current_start: Начало текущего периода
            current_end: Конец текущего периода
            current_transactions_list: Список транзакций текущего периода (из загруженного файла)
            
        Returns:
            Dict с данными для сравнения: current_period, previous_period, comparison
        """
        period_days = (current_end - current_start).days + 1
        previous_end = current_start - timedelta(days=1)
        previous_start = previous_end - timedelta(days=period_days - 1)
        
        # Получаем транзакции из истории за оба периода
        all_transactions = self.get_historical_transactions(days_back=365)
        
        # Используем переданные транзакции текущего периода или ищем в истории
        if current_transactions_list:
            current_transactions = current_transactions_list
        else:
            current_transactions = []
            for tx in all_transactions:
                try:
                    date_str = tx.get("Дата", "")
                    if not date_str:
                        continue
                        
                    if isinstance(date_str, str):
                        tx_date = datetime.fromisoformat(date_str.split('T')[0])
                        
                        if current_start <= tx_date <= current_end:
                            current_transactions.append(tx)
                except (ValueError, AttributeError):
                    continue
        
        # Ищем предыдущий период в истории
        previous_transactions = []
        for tx in all_transactions:
            try:
                date_str = tx.get("Дата", "")
                if not date_str:
                    continue
                    
                if isinstance(date_str, str):
                    tx_date = datetime.fromisoformat(date_str.split('T')[0])
                    
                    if previous_start <= tx_date <= previous_end:
                        previous_transactions.append(tx)
            except (ValueError, AttributeError):
                continue
        
        # Агрегируем данные
        def aggregate_period(transactions):
            income = sum(abs(float(tx.get("Сумма", 0))) for tx in transactions 
                       if tx.get("Категория") == "Поступление от клиента")
            expenses = sum(abs(float(tx.get("Сумма", 0))) for tx in transactions 
                          if tx.get("Категория") != "Поступление от клиента")
            
            # По категориям
            by_category = defaultdict(float)
            for tx in transactions:
                if tx.get("Категория") != "Поступление от клиента":
                    cat = tx.get("Категория", "Прочее")
                    by_category[cat] += abs(float(tx.get("Сумма", 0)))
            
            return {
                "income": income,
                "expenses": expenses,
                "balance": income - expenses,
                "by_category": dict(by_category),
                "transaction_count": len(transactions)
            }
        
        current_data = aggregate_period(current_transactions)
        previous_data = aggregate_period(previous_transactions)
        
        # Сравнение
        comparison = {}
        if previous_data["income"] > 0:
            comparison["income_change_pct"] = ((current_data["income"] - previous_data["income"]) / previous_data["income"]) * 100
        else:
            comparison["income_change_pct"] = 0 if current_data["income"] == 0 else 100
        
        if previous_data["expenses"] > 0:
            comparison["expenses_change_pct"] = ((current_data["expenses"] - previous_data["expenses"]) / previous_data["expenses"]) * 100
        else:
            comparison["expenses_change_pct"] = 0 if current_data["expenses"] == 0 else 100
        
        if previous_data["balance"] != 0:
            comparison["balance_change_pct"] = ((current_data["balance"] - previous_data["balance"]) / abs(previous_data["balance"])) * 100
        else:
            comparison["balance_change_pct"] = 0 if current_data["balance"] == 0 else (100 if current_data["balance"] > 0 else -100)
        
        return {
            "current_period": {
                "start": current_start.strftime("%Y-%m-%d"),
                "end": current_end.strftime("%Y-%m-%d"),
                **current_data
            },
            "previous_period": {
                "start": previous_start.strftime("%Y-%m-%d"),
                "end": previous_end.strftime("%Y-%m-%d"),
                **previous_data
            },
            "comparison": comparison
        }


# Глобальный экземпляр
transaction_history = TransactionHistory()

