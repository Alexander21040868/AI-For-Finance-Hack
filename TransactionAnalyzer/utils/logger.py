# utils/logger.py
import os
import pandas as pd
import threading
import datetime

class TokenUsageLogger:
    def __init__(self):
        self.data = []
        self._lock = threading.Lock()
        self.run_timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    def log(self, model_name: str, task: str, tokens_prompt: int, tokens_completion: int):
        with self._lock:
            self.data.append({
                "timestamp": datetime.datetime.now().isoformat(),
                "model": model_name,
                "task": task,
                "prompt_tokens": tokens_prompt,
                "completion_tokens": tokens_completion,
                "total_tokens": tokens_prompt + tokens_completion
            })

    def save(self, output_dir="logs"):
        if not self.data:
            return
        os.makedirs(output_dir, exist_ok=True)
        filename = f"{output_dir}/transaction_analyzer_{self.run_timestamp}.csv"
        pd.DataFrame(self.data).to_csv(filename, index=False, encoding="utf-8")
        print(f"[LOGGER] Отчёт сохранён: {filename}")


class TimeLogger:
    def __init__(self):
        self.data = []
        self._lock = threading.Lock()
        self.run_timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    def log(self, task_name: str, duration_seconds: float):
        with self._lock:
            self.data.append({
                "timestamp": datetime.datetime.now().isoformat(),
                "task": task_name,
                "duration_sec": round(duration_seconds, 3)
            })

    def save(self, output_dir="logs"):
        if not self.data:
            return
        os.makedirs(output_dir, exist_ok=True)
        filename = f"{output_dir}/time_analyzer_{self.run_timestamp}.csv"
        pd.DataFrame(self.data).to_csv(filename, index=False, encoding="utf-8")
        print(f"[LOGGER] Тайминги сохранены: {filename}")
