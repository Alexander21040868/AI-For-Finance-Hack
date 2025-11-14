import datetime
import functools
import os
import threading
import time

import pandas as pd

from config import LOGGING_TIME_USAGE


class TimeUsageLogger:
    """Класс для сбора и анализа времени выполнения различных задач."""

    def __init__(self):
        self.data = []
        self._lock = threading.Lock()
        self.run_timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    def log_time(self, task_name: str, duration_seconds: float) -> None:
        """Сохраняет данные о времени выполнения задачи."""
        if not LOGGING_TIME_USAGE:
            return
        with self._lock:
            log_entry = {
                "task_name": task_name,
                "duration_seconds": duration_seconds,
            }
            self.data.append(log_entry)

    def save_reports(self, output_dir="logs"):
        """Сохраняет полный и агрегированный отчеты по времени выполнения."""
        if not LOGGING_TIME_USAGE or not self.data:
            return
        os.makedirs(output_dir, exist_ok=True)

        # 1. Сохранение полного лога
        full_log_df = pd.DataFrame(self.data)
        full_log_path = os.path.join(output_dir, f"{self.run_timestamp}_time_usage_full_log.csv")
        full_log_df.to_csv(full_log_path, index=False, encoding='utf-8')
        print(f"\nПолный лог времени выполнения сохранен в: {full_log_path}")

        # 2. Создание и сохранение агрегированного отчета
        agg_report = full_log_df.groupby('task_name').agg(
            total_duration_sec=('duration_seconds', 'sum'),
            call_count=('task_name', 'size'),
            avg_duration_sec=('duration_seconds', 'mean'),
            min_duration_sec=('duration_seconds', 'min'),
            max_duration_sec=('duration_seconds', 'max')
        ).reset_index()

        agg_report = agg_report.sort_values(by='total_duration_sec', ascending=False)

        # Добавляем процент от общего времени
        total_time_overall = agg_report['total_duration_sec'].sum()
        if total_time_overall > 0:
            agg_report['percentage_of_total_time'] = \
                (agg_report['total_duration_sec'] / total_time_overall * 100).round(2)

        agg_report_path = os.path.join(output_dir, f"{self.run_timestamp}_time_usage_summary.csv")
        agg_report.to_csv(agg_report_path, index=False, encoding='utf-8')
        print(f"Агрегированный отчет по времени выполнения сохранен в: {agg_report_path}")

        # 3. Вывод красивой таблицы в консоль
        print("\n--- Сводный отчет по времени выполнения (Задача) ---")
        display_df = agg_report.copy()
        for col in ['total_duration_sec', 'avg_duration_sec', 'min_duration_sec', 'max_duration_sec']:
            display_df[col] = display_df[col].apply(lambda x: f"{x:.3f}s")
        if 'percentage_of_total_time' in display_df.columns:
            display_df['percentage_of_total_time'] = display_df['percentage_of_total_time'].apply(
                lambda x: f"{x}%")

        print(display_df.to_string(index=False))
        print("-------------------------------------------------------")


time_logger = TimeUsageLogger()


def timed(func):
    """Декоратор для измерения времени выполнения функции."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        if not LOGGING_TIME_USAGE:  # Проверяем флаг в начале
            return func(*args, **kwargs)
        start_time = time.perf_counter()
        result = func(*args, **kwargs)
        end_time = time.perf_counter()
        duration = end_time - start_time
        time_logger.log_time(func.__name__, duration)
        return result

    return wrapper
