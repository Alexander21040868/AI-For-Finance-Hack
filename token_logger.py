import datetime
import os
import threading

import pandas as pd

from config import LOGGING_TOKEN_USAGE


class TokenUsageLogger:
    def __init__(self):
        self.data = []
        self._lock = threading.Lock()
        self.run_timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    def log_usage(self, usage, model_name: str, task: str, task_data: str) -> None:
        """Сохраняет данные об использовании токенов моделью"""
        if not LOGGING_TOKEN_USAGE:
            return
        with self._lock:
            log = {
                "model_name": model_name,
                "task": task,
                "task_data": task_data,
                "prompt_tokens": getattr(usage, 'prompt_tokens', 0),
                "completion_tokens": getattr(usage, 'completion_tokens', 0),
                "total_tokens": getattr(usage, 'total_tokens', 0),
            }
            self.data.append(log)

    def save_reports(self, output_dir="logs"):
        if not LOGGING_TOKEN_USAGE:
            pass
        os.makedirs(output_dir, exist_ok=True)

        full_log_df = pd.DataFrame(self.data)
        full_log_path = os.path.join(output_dir, f"{self.run_timestamp}_token_usage_full_log.csv")
        full_log_df.to_csv(full_log_path, index=False, encoding='utf-8')
        print(f"\nПолный лог использования токенов сохранен в: {full_log_path}")

        by_model_task = full_log_df.groupby(['model_name', 'task']).agg(
            prompt_tokens=('prompt_tokens', 'sum'),
            completion_tokens=('completion_tokens', 'sum'),
            total_tokens=('total_tokens', 'sum'),
            call_count=('model_name', 'size')
        ).reset_index()

        total_tokens_overall = by_model_task['total_tokens'].sum()
        if total_tokens_overall > 0:
            by_model_task['percentage_of_total'] = (by_model_task['total_tokens'] / total_tokens_overall * 100).round(2)

        by_model_task_path = os.path.join(output_dir, f"{self.run_timestamp}_token_usage_by_model_task.csv")
        by_model_task.to_csv(by_model_task_path, index=False, encoding='utf-8')
        print(f"Агрегированный отчет по задачам сохранен в: {by_model_task_path}")

        print("\n--- Сводный отчет по использованию токенов (Модель + Задача) ---")
        by_model_task_display = by_model_task.copy()
        for col in ['prompt_tokens', 'completion_tokens', 'total_tokens', 'call_count']:
            by_model_task_display[col] = by_model_task_display[col].apply(lambda x: f"{x:,}")
        if 'percentage_of_total' in by_model_task_display.columns:
            by_model_task_display['percentage_of_total'] = by_model_task_display['percentage_of_total'].apply(
                lambda x: f"{x}%")

        print(by_model_task_display.to_string(index=False))
        print("-----------------------------------------------------------------")


token_logger = TokenUsageLogger()
