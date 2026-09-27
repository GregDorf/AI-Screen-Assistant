import cv2
import numpy as np
import requests
import easyocr

from PyQt6.QtCore import QThread, pyqtSignal

import config
import os
from difflib import SequenceMatcher


try:
    from openai import OpenAI
except ImportError:
    OpenAI = None


try:
    from google import genai
except ImportError:
    genai = None


# ============================================================
# OCR INITIALIZATION
# ============================================================

print("[System] Инициализация OCR движка...")

model_dir = os.path.expanduser("~/.EasyOCR/model")

if not os.path.exists(model_dir):
    print("[System] Модели EasyOCR не найдены.")
    print("[System] При первом запуске они будут автоматически скачаны (~80 МБ).")
    print("[System] После этого интернет больше не потребуется.")


try:
    GLOBAL_READER = easyocr.Reader(
        ['ru', 'en'],
        gpu=False,
        verbose=False
    )

    print("[System] OCR готов к работе.")

except Exception as e:
    print(f"[System] Не удалось инициализировать OCR: {e}")
    raise


# ============================================================
# IMAGE PREPROCESSING
# ============================================================

def resize_for_ocr(image: np.ndarray) -> np.ndarray:
    """
    Адаптивно увеличивает изображение.

    Маленькие области увеличиваются сильнее.
    Большие области увеличиваются слабее.

    Также существует ограничение максимального размера,
    чтобы EasyOCR не получал чрезмерно большие изображения.
    """

    if image is None:
        return None

    height, width = image.shape[:2]

    if width <= 500 or height <= 300:
        scale = 3.0

    elif width <= 1000 or height <= 600:
        scale = 2.0

    else:
        scale = 1.5

    resized = cv2.resize(
        image,
        None,
        fx=scale,
        fy=scale,
        interpolation=cv2.INTER_CUBIC
    )

    # Ограничиваем итоговый размер.
    max_dimension = 1800

    height, width = resized.shape[:2]

    current_max = max(
        height,
        width
    )

    if current_max > max_dimension:

        reduction = (
            max_dimension /
            current_max
        )

        resized = cv2.resize(
            resized,
            None,
            fx=reduction,
            fy=reduction,
            interpolation=cv2.INTER_AREA
        )

    return resized


def remove_noise(image: np.ndarray) -> np.ndarray:
    """
    Мягкое шумоподавление.

    Не используем сильный blur, поскольку он может уничтожить
    тонкие элементы букв.
    """

    if image is None:
        return None

    return cv2.fastNlMeansDenoisingColored(
        image,
        None,
        3,
        3,
        7,
        21
    )


def improve_contrast(image: np.ndarray) -> np.ndarray:
    """
    Локальное повышение контраста через CLAHE.

    Хорошо помогает, когда текст находится:
    - на градиенте;
    - поверх изображения;
    - на неоднородном фоне;
    - имеет слабый контраст.
    """

    if image is None:
        return None

    lab = cv2.cvtColor(
        image,
        cv2.COLOR_BGR2LAB
    )

    l, a, b = cv2.split(lab)

    clahe = cv2.createCLAHE(
        clipLimit=2.0,
        tileGridSize=(8, 8)
    )

    l = clahe.apply(l)

    result = cv2.merge(
        (l, a, b)
    )

    return cv2.cvtColor(
        result,
        cv2.COLOR_LAB2BGR
    )


def sharpen_image(image: np.ndarray) -> np.ndarray:
    """
    Мягкое повышение резкости.

    Используется unsharp mask.
    """

    if image is None:
        return None

    blurred = cv2.GaussianBlur(
        image,
        (0, 0),
        2.0
    )

    return cv2.addWeighted(
        image,
        1.30,
        blurred,
        -0.30,
        0
    )


def preprocess_image(image: np.ndarray) -> np.ndarray:
    """
    Основной preprocessing OCR.

    Порядок:

        resize
        ↓
        denoise
        ↓
        CLAHE
        ↓
        sharpening

    Важно: здесь НЕ применяется бинаризация.

    Основной OCR получает естественное изображение,
    а дополнительные варианты используются только
    в fallback-режиме.
    """

    if image is None:
        return None

    image = resize_for_ocr(
        image
    )

    image = remove_noise(
        image
    )

    image = improve_contrast(
        image
    )

    image = sharpen_image(
        image
    )

    return image


# ============================================================
# OCR UTILITIES
# ============================================================

def normalize_ocr_text(text: str) -> str:
    """
    Убирает лишние пробелы и переносы.
    """

    if not text:
        return ""

    return " ".join(
        text.split()
    ).strip()


def is_valid_ocr_fragment(text: str) -> bool:
    """
    Отбрасывает очевидный OCR-мусор.

    Например:

        ---
        ...
        ;;;
        @@@

    При этом реальные игровые слова не фильтруются.
    """

    if not text:
        return False

    text = text.strip()

    if len(text) < 2:
        return False

    alphanumeric_count = sum(
        char.isalnum()
        for char in text
    )

    if alphanumeric_count == 0:
        return False

    ratio = (
        alphanumeric_count /
        max(len(text), 1)
    )

    if ratio < 0.25:
        return False

    return True


def sort_ocr_results(results):
    """
    Сортирует OCR-блоки сверху вниз,
    а внутри строки — слева направо.
    """

    if not results:
        return []

    prepared = []

    for item in results:

        if len(item) < 3:
            continue

        bbox = item[0]
        text = item[1]
        confidence = item[2]

        if not is_valid_ocr_fragment(
            text
        ):
            continue

        try:

            x = min(
                point[0]
                for point in bbox
            )

            y = min(
                point[1]
                for point in bbox
            )

        except Exception:

            x = 0
            y = 0

        prepared.append(
            (
                y,
                x,
                text,
                confidence
            )
        )

    prepared.sort(
        key=lambda item: (
            item[0],
            item[1]
        )
    )

    return prepared


# ============================================================
# EASY OCR
# ============================================================

def run_easyocr(
    image: np.ndarray
):
    """
    Один проход EasyOCR.

    Параметры ориентированы на экранный текст:
    небольшие буквы, игровые интерфейсы и субтитры.
    """

    if image is None:
        return []

    try:

        return GLOBAL_READER.readtext(

            image,

            detail=1,

            paragraph=False,

            # Позволяем искать маленькие элементы.
            min_size=5,

            # Контраст.
            contrast_ths=0.05,
            adjust_contrast=0.7,

            # Детектор текста.
            text_threshold=0.55,
            low_text=0.25,
            link_threshold=0.35,

            # Ограничиваем внутреннее масштабирование.
            canvas_size=2560,
            mag_ratio=1.0,

            # Геометрия.
            slope_ths=0.15,
            ycenter_ths=0.5,
            height_ths=0.5,
            width_ths=0.6,

            add_margin=0.1,

            # Фильтры.
            threshold=0.2,
            bbox_min_score=0.2,
            bbox_min_size=3
        )

    except Exception as e:

        print(
            f"[OCR] Ошибка EasyOCR: {e}"
        )

        return []


# ============================================================
# RESULT EXTRACTION
# ============================================================

def extract_ocr_text(
    results
) -> str:

    sorted_results = sort_ocr_results(
        results
    )

    if not sorted_results:
        return ""

    text_parts = []

    for (
        _,
        _,
        text,
        confidence
    ) in sorted_results:

        # Базовый фильтр confidence.
        if confidence < 0.30:
            continue

        text = normalize_ocr_text(
            text
        )

        if not text:
            continue

        text_parts.append(
            text
        )

    return normalize_ocr_text(
        " ".join(text_parts)
    )


def calculate_text_quality(
    text: str
) -> float:

    if not text:
        return 0.0

    length = len(text)

    if length < 2:
        return 0.0

    alphanumeric = sum(
        char.isalnum()
        for char in text
    )

    alpha_ratio = (
        alphanumeric /
        max(length, 1)
    )

    if alpha_ratio < 0.30:
        return 0.1

    score = alpha_ratio

    if length >= 5:
        score += 0.15

    if length >= 15:
        score += 0.10

    return min(
        score,
        1.0
    )


def text_similarity(
    text_a: str,
    text_b: str
) -> float:

    a = normalize_ocr_text(
        text_a
    ).casefold()

    b = normalize_ocr_text(
        text_b
    ).casefold()

    if not a or not b:
        return 0.0

    return SequenceMatcher(
        None,
        a,
        b
    ).ratio()


def choose_best_ocr_result(
    results
) -> str:

    valid_results = [
        result
        for result in results
        if result
    ]

    if not valid_results:
        return ""

    if len(valid_results) == 1:
        return valid_results[0]

    best_text = valid_results[0]

    best_score = calculate_text_quality(
        best_text
    )

    for candidate in valid_results[1:]:

        candidate_score = (
            calculate_text_quality(
                candidate
            )
        )

        similarity = text_similarity(
            candidate,
            best_text
        )

        if similarity >= 0.65:

            if candidate_score > best_score:

                best_text = candidate
                best_score = candidate_score

        elif candidate_score > (
            best_score + 0.15
        ):

            best_text = candidate
            best_score = candidate_score

    return best_text


# ============================================================
# MAIN OCR FUNCTION
# ============================================================

def recognize_text(
    image: np.ndarray,
    preprocess: bool = True
) -> str:
    """
    Главная функция OCR.

    ВАЖНАЯ ОПТИМИЗАЦИЯ:

    Первый проход всегда является основным.

    Дополнительные OCR-проходы запускаются только тогда,
    когда первый результат выглядит подозрительно.

    Поэтому нормальный игровой текст обычно требует
    только одного запуска EasyOCR.
    """

    if image is None:
        return ""

    # --------------------------------------------------------
    # PRIMARY PASS
    # --------------------------------------------------------

    if preprocess:

        processed = preprocess_image(
            image
        )

    else:

        processed = image

    primary_results = run_easyocr(
        processed
    )

    primary_text = extract_ocr_text(
        primary_results
    )

    # --------------------------------------------------------
    # Если результат достаточно хороший,
    # сразу возвращаем его.
    # --------------------------------------------------------

    primary_quality = calculate_text_quality(
        primary_text
    )

    if primary_text and primary_quality >= 0.65:

        return primary_text

    # --------------------------------------------------------
    # FALLBACK PASS #1
    #
    # Grayscale
    # --------------------------------------------------------

    fallback_results = []

    try:

        gray = cv2.cvtColor(
            processed,
            cv2.COLOR_BGR2GRAY
        )

        gray = cv2.normalize(
            gray,
            None,
            0,
            255,
            cv2.NORM_MINMAX
        )

        gray_text = extract_ocr_text(
            run_easyocr(gray)
        )

        if gray_text:

            fallback_results.append(
                gray_text
            )

    except Exception as e:

        print(
            f"[OCR] Ошибка grayscale: {e}"
        )

    # --------------------------------------------------------
    # FALLBACK PASS #2
    #
    # Adaptive threshold
    #
    # Запускается только если первый проход
    # и grayscale не дали хорошего результата.
    # --------------------------------------------------------

    if (
        not primary_text
        or primary_quality < 0.50
    ):

        try:

            threshold = cv2.adaptiveThreshold(

                gray,

                255,

                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,

                cv2.THRESH_BINARY,

                31,

                11
            )

            threshold_text = extract_ocr_text(
                run_easyocr(threshold)
            )

            if threshold_text:

                fallback_results.append(
                    threshold_text
                )

        except Exception as e:

            print(
                f"[OCR] Ошибка threshold: {e}"
            )

    # --------------------------------------------------------
    # FALLBACK PASS #3
    #
    # Inverted threshold
    #
    # Используется только в крайнем случае.
    # --------------------------------------------------------

    if (
        not primary_text
        or primary_quality < 0.35
    ):

        try:

            inverted = cv2.adaptiveThreshold(

                gray,

                255,

                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,

                cv2.THRESH_BINARY_INV,

                31,

                11
            )

            inverted_text = extract_ocr_text(
                run_easyocr(inverted)
            )

            if inverted_text:

                fallback_results.append(
                    inverted_text
                )

        except Exception as e:

            print(
                f"[OCR] Ошибка inverted threshold: {e}"
            )

    # --------------------------------------------------------
    # FINAL SELECTION
    # --------------------------------------------------------

    all_results = []

    if primary_text:
        all_results.append(
            primary_text
        )

    all_results.extend(
        fallback_results
    )

    return choose_best_ocr_result(
        all_results
    )


# ============================================================
# AI WORKER
# ============================================================

class AIWorker(QThread):

    finished = pyqtSignal(str)

    def __init__(
        self,
        image_bytes: bytes,
        action: str,
        target_lang: str = "русский",
        from_lang: str = "auto",
        extracted_text: str = None
    ):

        super().__init__()

        self.image_bytes = image_bytes

        self.action = action

        self.target_lang = target_lang

        self.from_lang = from_lang

        self.extracted_text = extracted_text

        self.reader = GLOBAL_READER

    def run(self):

        try:

            # ------------------------------------------------
            # OCR
            # ------------------------------------------------

            if self.extracted_text is not None:

                extracted_text = (
                    self.extracted_text
                )

            else:

                clean_img = self.clean_image(
                    self.image_bytes
                )

                if clean_img is None:

                    self.finished.emit(
                        "Не удалось обработать изображение."
                    )

                    return

                # clean_image уже сделал preprocessing,
                # поэтому повторно его не выполняем.
                extracted_text = recognize_text(
                    clean_img,
                    preprocess=False
                )

                if not extracted_text:

                    self.finished.emit(
                        "Текст не найден."
                    )

                    return

            extracted_text = normalize_ocr_text(
                extracted_text
            )

            if not extracted_text:

                self.finished.emit(
                    "Текст не распознан."
                )

                return

            print(
                f"[OCR] Распознано ({self.action}): "
                f"{extracted_text}"
            )

            # ------------------------------------------------
            # TRANSLATION
            # ------------------------------------------------

            if self.action == "translation":

                from_str = (

                    f"с языка '{self.from_lang}'"

                    if self.from_lang != "auto"

                    else
                    "с автоопределением исходного языка"
                )

                prompt = (
                        "ЗАДАЧА: перевод текста.\n\n"

                        f"Переведи входной текст {from_str} "
                        f"на {self.target_lang}.\n\n"

                        "СТРОГИЕ ПРАВИЛА:\n"
                        "1. Твой ответ должен содержать ТОЛЬКО перевод.\n"
                        "2. Никаких пояснений, комментариев, вступлений или заключений.\n"
                        "3. Запрещено писать фразы вроде: "
                        "\"Вот перевод\", \"Перевод:\", \"Конечно\", "
                        "\"Разумеется\", \"Ниже перевод\" и любые аналогичные фразы.\n"
                        "4. Не добавляй информацию, которой нет в исходном тексте.\n"
                        "5. Не объясняй смысл исходного текста.\n"
                        "6. Не пересказывай текст.\n"
                        "7. Не сокращай текст.\n"
                        "8. Не дополняй текст от себя.\n"
                        "9. Сохраняй исходный смысл максимально точно.\n"
                        "10. Сохраняй имена, числа, названия и специальные обозначения.\n"
                        "11. Сохраняй структуру текста настолько, насколько это возможно.\n"
                        "12. Если исходный текст содержит только одно слово или короткую фразу, "
                        "переведи только это слово или фразу.\n\n"

                        "ФОРМАТ ОТВЕТА:\n"
                        "Только готовый перевод. Никакого другого текста.\n\n"

                        "ИСХОДНЫЙ ТЕКСТ:\n"
                        f"{extracted_text}"
                    )

            # ------------------------------------------------
            # GAME TRANSLATION
            # ------------------------------------------------

            elif self.action == "game_translation":

                prompt = (
                    "ЗАДАЧА: перевод текста из видеоигры.\n\n"

                    f"Переведи текст на {self.target_lang}.\n\n"

                    "СТРОГИЕ ПРАВИЛА:\n"
                    "1. Верни ТОЛЬКО перевод.\n"
                    "2. Не пиши никаких пояснений.\n"
                    "3. Не добавляй вступление или заключение.\n"
                    "4. Запрещены фразы: "
                    "\"Вот перевод\", \"Перевод:\", \"Конечно\", "
                    "\"Разумеется\", \"Вот ваш перевод\" и любые подобные фразы.\n"
                    "5. Не пересказывай содержание.\n"
                    "6. Не сокращай реплики.\n"
                    "7. Не добавляй реплики, которых нет в оригинале.\n"
                    "8. Не добавляй контекст от себя.\n"
                    "9. Не объясняй игровые термины отдельно от перевода.\n"
                    "10. Сохраняй имена персонажей.\n"
                    "11. Сохраняй названия предметов, локаций и способностей, "
                    "если их перевод не очевиден из контекста.\n"
                    "12. Сохраняй смысл, эмоциональный тон и стиль реплик.\n"
                    "13. Если текст содержит несколько реплик, сохрани их порядок.\n"
                    "14. Если исходный текст содержит только одно слово или короткую фразу, "
                    "переведи только это слово или фразу.\n"
                    "15. Не отвечай на вопросы, содержащиеся в игровом тексте. "
                    "Текст нужно именно ПЕРЕВЕСТИ.\n\n"

                    "ФОРМАТ ОТВЕТА:\n"
                    "Только готовый перевод. Никакого другого текста.\n\n"

                    "ИСХОДНЫЙ ТЕКСТ:\n"
                    f"{extracted_text}"
                )

            # ------------------------------------------------
            # TERM
            # ------------------------------------------------

            elif self.action == "term":

                prompt = (
                    "ЗАДАЧА: определить и объяснить термин.\n\n"

                    "Входной текст содержит термин или понятие. "
                    "Найди главное понятие и дай его точное определение.\n\n"

                    "СТРОГИЕ ПРАВИЛА:\n"
                    "1. Определи именно термин или понятие, а не тему текста в целом.\n"
                    "2. Дай краткое и точное определение этого термина.\n"
                    "3. Объясняй именно значение термина.\n"
                    "4. Не пересказывай исходный текст.\n"
                    "5. Не анализируй намерения автора.\n"
                    "6. Не добавляй информацию, не относящуюся непосредственно к термину.\n"
                    "7. Не придумывай значения, которых у термина нет.\n"
                    "8. Если термин многозначный, укажи только значение, "
                    "которое соответствует контексту входного текста.\n"
                    "9. Если контекста недостаточно, укажи наиболее распространенное "
                    "значение термина и не выдумывай дополнительный контекст.\n"
                    "10. Не используй вступления вроде "
                    "\"Этот термин означает\", \"Конечно\", \"Разумеется\" и т.п.\n\n"

                    "ФОРМАТ ОТВЕТА:\n"
                    "Термин: краткое определение.\n"
                    "Никаких дополнительных комментариев.\n\n"

                    "ВХОДНОЙ ТЕКСТ:\n"
                    f"{extracted_text}"
                )

            # ------------------------------------------------
            # DEFAULT / QUESTION
            # ------------------------------------------------

            else:

                prompt = (
                    "ЗАДАЧА: ответить на вопрос или решить поставленную задачу.\n\n"

                    "Входной текст может содержать вопрос, задачу или фрагмент, "
                    "требующий ответа.\n\n"

                    "СТРОГИЕ ПРАВИЛА:\n"
                    "1. Если во входном тексте есть вопрос — дай ТОЛЬКО ответ на этот вопрос.\n"
                    "2. Не пересказывай вопрос.\n"
                    "3. Не добавляй вступления вроде "
                    "\"Ответ:\", \"Конечно\", \"Разумеется\", "
                    "\"Давайте разберем\", \"Вот решение\" и т.п.\n"
                    "4. Не добавляй заключений или дополнительных рассуждений, "
                    "если они не нужны для ответа.\n"
                    "5. Не уходи от поставленного вопроса.\n"
                    "6. Не меняй задачу на другую.\n"
                    "7. Не придумывай отсутствующие в тексте факты.\n"
                    "8. Если данных недостаточно для однозначного ответа, "
                    "скажи только об этом кратко.\n"
                    "9. Если вопрос требует вычисления — дай результат и только "
                    "минимально необходимое объяснение.\n"
                    "10. Если вопрос требует объяснения — дай краткое объяснение "
                    "непосредственно по сути вопроса.\n\n"

                    "ФОРМАТ ОТВЕТА:\n"
                    "Только ответ на поставленный вопрос.\n\n"

                    "ВХОДНОЙ ТЕКСТ:\n"
                    f"{extracted_text}"
                )

            # ------------------------------------------------
            # AI
            # ------------------------------------------------

            answer = self.call_ai(
                prompt
            )

            self.finished.emit(
                answer
            )

        except Exception as e:

            self.finished.emit(
                f"Ошибка выполнения: {str(e)}"
            )

    # ========================================================
    # IMAGE DECODING
    # ========================================================

    def clean_image(
        self,
        image_bytes: bytes
    ) -> np.ndarray:

        nparr = np.frombuffer(
            image_bytes,
            np.uint8
        )

        img = cv2.imdecode(
            nparr,
            cv2.IMREAD_COLOR
        )

        if img is None:
            return None

        return preprocess_image(
            img
        )

    # ========================================================
    # AI
    # ========================================================

    def call_ai(
        self,
        prompt: str
    ) -> str:

        provider = (
            config.PROVIDER
            .lower()
        )

        # ----------------------------------------------------
        # OLLAMA
        # ----------------------------------------------------

        if provider == "ollama":

            payload = {

                "model":
                    config.MODEL_NAME,

                "prompt":
                    prompt,

                "stream":
                    False,

                "options": {

                    "num_predict":
                        1000,

                    "temperature":
                        0.2
                }
            }

            try:

                ollama_endpoint = getattr(

                    config,

                    "OLLAMA_URL",

                    "http://localhost:11434/api/generate"
                )

                res = requests.post(

                    ollama_endpoint,

                    json=payload,

                    timeout=120
                )

                if res.status_code == 200:

                    return res.json().get(

                        "response",

                        "Пустой ответ."
                    )

                return (
                    f"Ошибка Ollama: "
                    f"{res.status_code}"
                )

            except Exception as e:

                return (
                    f"Ошибка подключения к Ollama: "
                    f"{e}"
                )

        # ----------------------------------------------------
        # OPENAI
        # ----------------------------------------------------

        elif provider == "openai":

            if not OpenAI:

                return (
                    "Ошибка: библиотека 'openai' "
                    "не установлена."
                )

            try:

                client = OpenAI(
                    api_key=config.API_KEY
                )

                response = (
                    client
                    .chat
                    .completions
                    .create(

                        model=
                            config.MODEL_NAME,

                        messages=[
                            {
                                "role":
                                    "user",

                                "content":
                                    prompt
                            }
                        ]
                    )
                )

                return (
                    response
                    .choices[0]
                    .message
                    .content
                    .strip()
                )

            except Exception as e:

                return (
                    f"Ошибка OpenAI API: "
                    f"{e}"
                )

        # ----------------------------------------------------
        # DEEPSEEK
        # ----------------------------------------------------

        elif provider == "deepseek":

            if not OpenAI:

                return (
                    "Ошибка: библиотека 'openai' "
                    "не установлена "
                    "(требуется для DeepSeek API)."
                )

            try:

                client = OpenAI(

                    api_key=
                        config.API_KEY,

                    base_url=
                        "https://api.deepseek.com"
                )

                response = (
                    client
                    .chat
                    .completions
                    .create(

                        model=
                            config.MODEL_NAME,

                        messages=[
                            {
                                "role":
                                    "user",

                                "content":
                                    prompt
                            }
                        ]
                    )
                )

                return (
                    response
                    .choices[0]
                    .message
                    .content
                    .strip()
                )

            except Exception as e:

                return (
                    f"Ошибка DeepSeek API: "
                    f"{e}"
                )

        # ----------------------------------------------------
        # GEMINI
        # ----------------------------------------------------

        elif provider == "gemini":

            if not genai:

                return (
                    "Ошибка: библиотека 'google-genai' "
                    "не установлена."
                )

            try:

                client = genai.Client(
                    api_key=config.API_KEY
                )

                response = (
                    client
                    .models
                    .generate_content(

                        model=
                            config.MODEL_NAME,

                        contents=
                            prompt
                    )
                )

                return (
                    response
                    .text
                    .strip()
                )

            except Exception as e:

                return (
                    f"Ошибка Gemini API: "
                    f"{e}"
                )

        return (
            f"Неизвестный провайдер: "
            f"{provider}"
        )
