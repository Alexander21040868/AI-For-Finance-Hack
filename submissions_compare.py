"""Утилита для сравнения качества получаемых ответов (submission.csv)"""
import os
import pandas as pd

SUBMISSIONS_DIR = "submissions"
ANSWER_COLUMN = "Ответы на вопрос"
NOT_FOUND_ANSWER = "В предоставленной базе знаний нет информации по вашему вопросу."
FOUND_PARTLY_ANSWER = "В предоставленной базе знаний"
PROMPT_LEAKING_ANSWER = "вежливо сообщи"


submission_files = [f for f in os.listdir(SUBMISSIONS_DIR) if f.endswith('.csv')]

for filename in submission_files:
    filepath = os.path.join(SUBMISSIONS_DIR, filename)
    df = pd.read_csv(filepath)

    not_found_count = (df[ANSWER_COLUMN] == NOT_FOUND_ANSWER).sum()
    partly_found_count = (df[ANSWER_COLUMN].str.contains(FOUND_PARTLY_ANSWER, na=False)).sum()
    prompt_leaking_count = (df[ANSWER_COLUMN].str.contains(PROMPT_LEAKING_ANSWER, na=False)).sum()

    print(f"--- Статистика по файлу {filename}: ---")
    print(f"Вопросов, на которые получен ответ 'В предоставленной базе знаний нет информации по вашему вопросу.': {not_found_count}")
    print(f"Вопросов, ответ на которые содержит 'В предоставленной базе знаний' (скорее всего ответ дан лишь частично): {partly_found_count}")
    print(f"Вопросов, ответ на которые содержит 'вежливо сообщи' (скорее всего произошла утечка промпта): {prompt_leaking_count}")
    print("")

