import base64
import os
from PIL import Image
import io
from pdf2image import convert_from_path
from openai import OpenAI
from typing import Dict, List
import docx

from token_logger import token_logger
from time_logger import timed

@timed
def encode_image_to_base64(image: Image.Image) -> str:
    """Кодирует PIL.Image в base64 строку."""
    buffered = io.BytesIO()
    image.convert('RGB').save(buffered, format="JPEG")
    return base64.b64encode(buffered.getvalue()).decode('utf-8')

@timed
def extract_text_from_file(open_router_client: OpenAI,
                           generation_model: str,
                           file_path: str) -> Dict[str, str]:
    """Извлекает текст из одного файла (PDF или изображение) с помощью LLM."""
    print(f"  - Обработка файла: {os.path.basename(file_path)}")

    # === ЛОГИКА ДЛЯ DOCX ===
    if file_path.lower().endswith('.docx'):
        try:
            doc = docx.Document(file_path)
            full_text = []
            for para in doc.paragraphs:
                if para.text.strip():
                    full_text.append(para.text)
            
            text = "\n".join(full_text)
            return {"filename": os.path.basename(file_path), "text": text}
        except Exception as e:
            return {"filename": os.path.basename(file_path), "error": f"Ошибка при обработке DOCX: {e}"}
    
    # === ЛОГИКА ДЛЯ PDF ===
    elif file_path.lower().endswith('.pdf'):
        try:
            # Конвертируем все страницы PDF в изображения
            images = convert_from_path(file_path)
            if not images:
                return {"filename": os.path.basename(file_path), "error": "Пустой или нечитаемый PDF."}

            full_text_from_pdf = ""
            for i, page_image in enumerate(images):
                print(f"    - Обработка страницы {i + 1}/{len(images)}...")
                page_image.thumbnail((2048, 2048))
                base64_image = encode_image_to_base64(page_image)

                # Отправляем каждую страницу на распознавание
                response = open_router_client.chat.completions.create(
                    model=generation_model,
                    messages=[{
                        "role": "user",
                        "content": [
                            {"type": "text",
                             "text": "Извлеки весь текст с этого изображения. Верни только текст, без комментариев."},
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}},
                        ]
                    }],
                )

                page_text = response.choices[0].message.content
                full_text_from_pdf += f"\n--- Страница {i + 1} ---\n" + page_text

            return {"filename": os.path.basename(file_path), "text": full_text_from_pdf}

        except Exception as e:
            return {"filename": os.path.basename(file_path), "error": f"Ошибка при обработке PDF: {e}"}

    # === ЛОГИКА ДЛЯ ИЗОБРАЖЕНИЙ (остается прежней) ===
    else:
        try:
            image = Image.open(file_path)
            image.thumbnail((2048, 2048))
            base64_image = encode_image_to_base64(image)

            response = open_router_client.chat.completions.create(
                model=generation_model,
                messages=[{"role": "user", "content": [
                    {"type": "text",
                     "text": "Извлеки весь текст с этого изображения. Верни только текст, без комментариев."},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}},
                ]
                           }],
                max_tokens=4000
            )
            text = response.choices[0].message.content
            token_logger.log_usage(response.usage, generation_model, "generate_doc_summary",
                                   f"{text=}")
            return {"filename": os.path.basename(file_path), "text": text}
        except Exception as e:
            return {"filename": os.path.basename(file_path), "error": str(e)}

@timed
def batch_extract_text(file_paths: List[str], open_router_client=None, generation_model=None) -> List[Dict[str, str]]:
    """Принимает список путей к файлам и извлекает текст из каждого."""
    print("Запуск извлечения текста из документов...")
    extracted_data = []
    for path in file_paths:
        extracted_data.append(extract_text_from_file(open_router_client, generation_model, path))
    print("Извлечение текста завершено.")
    return extracted_data