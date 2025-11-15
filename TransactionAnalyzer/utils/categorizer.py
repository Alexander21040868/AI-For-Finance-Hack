# -*- coding: utf-8 -*-
import time
from openai import AsyncOpenAI

CATEGORIES = [
    "Аренда", "Зарплата", "Закупка товара", "Хозяйственные нужды",
    "Реклама", "IT-услуги", "Поступление от клиента", "Прочее", "Не принимаемые расходы"
]


async def categorize_transactions(texts, base_url, api_key, model_name, token_logger, time_logger):
    """Отправляет транзакции на классификацию в LLM."""
    client = AsyncOpenAI(base_url=base_url, api_key=api_key)
    results = []

    for text in texts:
        prompt = (
            f"Ты — AI-бухгалтер. Определи категорию транзакции: «{text}».\n"
            f"Категории: {', '.join(CATEGORIES)}.\n"
            f"Если расход нельзя учесть по УСН, выбери 'Не принимаемые расходы'.\n"
            "Ответь только одним словом — названием категории."
        )
        start = time.perf_counter()
        try:
            resp = await client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
            )
            msg = resp.choices[0].message.content.strip()
            results.append(msg)

            if hasattr(resp, "usage"):
                token_logger.log(
                    model_name,
                    "categorize_transaction",
                    resp.usage.prompt_tokens,
                    resp.usage.completion_tokens,
                )

        except Exception as e:
            print(f"[WARN] Ошибка при LLM-запросе: {e}")
            results.append("Прочее")
        finally:
            time_logger.log("categorize_transaction", time.perf_counter() - start)

    return results
