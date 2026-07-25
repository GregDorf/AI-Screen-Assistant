import cv2
import numpy as np
import requests
import easyocr
from PyQt6.QtCore import QThread, pyqtSignal
import config

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

try:
    from google import genai
except ImportError:
    genai = None

print("[System] Инициализация OCR движка...")
GLOBAL_READER = easyocr.Reader(['ru', 'en'], gpu=False, verbose=False)
print("[System] OCR готов к работе.")


class AIWorker(QThread):
    finished = pyqtSignal(str)

    def __init__(self, image_bytes: bytes, action: str, target_lang: str = "русский", from_lang: str = "auto"):
        super().__init__()
        self.image_bytes = image_bytes
        self.action = action
        self.target_lang = target_lang
        self.from_lang = from_lang
        self.reader = GLOBAL_READER

    def run(self):
        try:
            clean_img = self.clean_image(self.image_bytes)
            result = self.reader.readtext(clean_img)
            
            if not result:
                self.finished.emit("Текст не найден.")
                return

            extracted_text = " ".join([
                item[1] for item in result 
                if item[2] > 0.3
            ]).strip()
            
            if not extracted_text:
                self.finished.emit("Текст не распознан или содержит слишком много шума.")
                return

            print(f"[OCR] Распознано ({self.action}): {extracted_text}")

            if self.action == "translation":
                from_str = f"с языка '{self.from_lang}'" if self.from_lang != "auto" else "с автоопределением исходного языка"
                prompt = (
                    f"Выполни буквальный, точный перевод следующего текста {from_str} на {self.target_lang} язык. "
                    f"Строго сохраняй исходную структуру текста, абзацы, все знаки препинания и списки. "
                    f"Не допускай вольных трактовок, переводи максимально точно и полно. Выдай исключительно готовый перевод:\n\n{extracted_text}"
                )
            elif self.action == "term":
                prompt = (
                    f"Найдите главный термин или понятие в следующем тексте и дайте его четкое, академическое определение:\n\n{extracted_text}"
                )
            else:
                prompt = (
                    f"Проанализируй следующий текст. Если там вопрос, задача или код — дай четкий, емкий и понятный ответ:\n\n{extracted_text}"
                )

            answer = self.call_ai(prompt)
            self.finished.emit(answer)

        except Exception as e:
            self.finished.emit(f"Ошибка выполнения: {str(e)}")

    def clean_image(self, image_bytes: bytes) -> np.ndarray:
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        img = cv2.resize(img, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
        return img

    def call_ai(self, prompt: str) -> str:
        provider = config.PROVIDER.lower()

        if provider == "ollama":
            payload = {
                "model": config.MODEL_NAME, 
                "prompt": prompt, 
                "stream": False,
                "options": {
                    "num_predict": 1000,
                    "temperature": 0.2
                }
            }
            try:
                ollama_endpoint = getattr(config, "OLLAMA_URL", "http://localhost:11434/api/generate")
                res = requests.post(ollama_endpoint, json=payload, timeout=120)
                if res.status_code == 200:
                    return res.json().get("response", "Пустой ответ.")
                return f"Ошибка Ollama: {res.status_code}"
            except Exception as e:
                return f"Ошибка подключения к Ollama: {e}"

        elif provider == "openai":
            if not OpenAI:
                return "Ошибка: библиотека 'openai' не установлена."
            try:
                client = OpenAI(api_key=config.API_KEY)
                response = client.chat.completions.create(
                    model=config.MODEL_NAME,
                    messages=[{"role": "user", "content": prompt}]
                )
                return response.choices[0].message.content.strip()
            except Exception as e:
                return f"Ошибка OpenAI API: {e}"
                
        elif provider == "deepseek":
            if not OpenAI:
                return "Ошибка: библиотека 'openai' не установлена (требуется для DeepSeek API)."
            try:
                # DeepSeek использует полностью совместимый с OpenAI формат запросов
                client = OpenAI(api_key=config.API_KEY, base_url="https://api.deepseek.com")
                response = client.chat.completions.create(
                    model=config.MODEL_NAME,
                    messages=[{"role": "user", "content": prompt}]
                )
                return response.choices[0].message.content.strip()
            except Exception as e:
                return f"Ошибка DeepSeek API: {e}"

        elif provider == "gemini":
            if not genai:
                return "Ошибка: библиотека 'google-genai' не установлена."
            try:
                client = genai.Client(api_key=config.API_KEY)
                response = client.models.generate_content(
                    model=config.MODEL_NAME,
                    contents=prompt,
                )
                return response.text.strip()
            except Exception as e:
                return f"Ошибка Gemini API: {e}"

        return f"Неизвестный провайдер: {provider}"