# -*- coding: utf-8 -*-
"""
Менеджер истории запросов для сохранения и получения истории использования сервисов
"""
import json
import os
from datetime import datetime
from typing import List, Dict, Optional
import threading

HISTORY_FILE = "history.json"
_history_lock = threading.Lock()


class HistoryManager:
    """Управление историей запросов"""
    
    def __init__(self, history_file: str = HISTORY_FILE):
        self.history_file = history_file
        self._ensure_history_file()
    
    def _ensure_history_file(self):
        """Создает файл истории, если его нет"""
        if not os.path.exists(self.history_file):
            with open(self.history_file, 'w', encoding='utf-8') as f:
                json.dump([], f, ensure_ascii=False, indent=2)
    
    def add_entry(self, service_type: str, input_data: Dict, result: Dict):
        """
        Добавляет запись в историю
        
        Args:
            service_type: Тип сервиса ('transactions', 'documents', 'consultant')
            input_data: Входные данные (файл, вопрос и т.д.)
            result: Результат выполнения
        """
        entry = {
            "timestamp": datetime.now().isoformat(),
            "service_type": service_type,
            "input": input_data,
            "result": result
        }
        
        with _history_lock:
            try:
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    history = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                history = []
            
            history.append(entry)
            
            # Ограничиваем историю последними 100 записями
            if len(history) > 100:
                history = history[-100:]
            
            with open(self.history_file, 'w', encoding='utf-8') as f:
                json.dump(history, f, ensure_ascii=False, indent=2)
    
    def get_history(self, service_type: Optional[str] = None, limit: int = 50) -> List[Dict]:
        """
        Получает историю запросов
        
        Args:
            service_type: Фильтр по типу сервиса (опционально)
            limit: Максимальное количество записей
        
        Returns:
            Список записей истории
        """
        with _history_lock:
            try:
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    history = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                return []
            
            # Фильтруем по типу сервиса, если указан
            if service_type:
                history = [h for h in history if h.get('service_type') == service_type]
            
            # Возвращаем последние N записей
            return history[-limit:]
    
    def clear_history(self):
        """Очищает историю"""
        with _history_lock:
            with open(self.history_file, 'w', encoding='utf-8') as f:
                json.dump([], f, ensure_ascii=False, indent=2)


# Глобальный экземпляр
history_manager = HistoryManager()

