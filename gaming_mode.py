from difflib import SequenceMatcher

import numpy as np

from PyQt6.QtCore import (
    QObject,
    QThread,
    QTimer,
    pyqtSignal,
    QRect
)

from PyQt6.QtWidgets import QApplication

from processor import (
    AIWorker,
    recognize_text
)


# ============================================================
# OCR WORKER
# ============================================================

class GameOCRWorker(QThread):

    result_ready = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, image, parent=None):
        super().__init__(parent)

        self.image = image

    def run(self):

        try:

            text = recognize_text(
                self.image,
                preprocess=True
            )

            if self.isInterruptionRequested():
                return

            self.result_ready.emit(text)

        except Exception as e:

            if not self.isInterruptionRequested():
                self.error.emit(str(e))


# ============================================================
# GAMING TRANSLATION MANAGER
# ============================================================

class GamingTranslationManager(QObject):

    translation_started = pyqtSignal()

    translation_finished = pyqtSignal(str)

    status_changed = pyqtSignal(str)

    def __init__(
        self,
        parent=None
    ):

        super().__init__(
            parent
        )

        # ----------------------------------------------------
        # TARGET REGION
        # ----------------------------------------------------

        self.target_rect = QRect()

        # ----------------------------------------------------
        # OCR STATE
        # ----------------------------------------------------

        self.last_text = ""

        self.translating_text = ""

        self.pending_text = ""

        self.candidate_text = ""

        self.candidate_count = 0

        self.required_candidate_count = 2

        self.similarity_threshold = 0.90

        # ----------------------------------------------------
        # LANGUAGE
        # ----------------------------------------------------

        self.target_lang = "русский"

        self.from_lang = "auto"

        # ----------------------------------------------------
        # RUNNING
        # ----------------------------------------------------

        self.is_running = False

        # ----------------------------------------------------
        # OCR WORKER
        # ----------------------------------------------------

        self.ocr_worker = None

        # ----------------------------------------------------
        # TRANSLATION WORKER
        # ----------------------------------------------------

        self.translation_worker = None

        # ----------------------------------------------------
        # OCR TIMER
        # ----------------------------------------------------

        self.ocr_timer = QTimer(
            self
        )

        self.ocr_timer.setInterval(
            300
        )

        self.ocr_timer.timeout.connect(
            self.capture_and_ocr
        )

    # ========================================================
    # START
    # ========================================================

    def start(
        self,
        target_rect: QRect,
        target_lang="русский",
        from_lang="auto"
    ):

        # ----------------------------------------------------
        # На всякий случай гарантируем,
        # что старый OCR полностью завершён.
        # ----------------------------------------------------

        self._wait_for_ocr_worker()

        # ----------------------------------------------------
        # Старый перевод также не должен оставаться
        # бесхозным.
        # ----------------------------------------------------

        self._wait_for_translation_worker()

        # ----------------------------------------------------
        # CONFIGURATION
        # ----------------------------------------------------

        self.target_rect = QRect(
            target_rect
        )

        self.target_lang = target_lang

        self.from_lang = from_lang

        # ----------------------------------------------------
        # RESET STATE
        # ----------------------------------------------------

        self.last_text = ""

        self.translating_text = ""

        self.pending_text = ""

        self.candidate_text = ""

        self.candidate_count = 0

        self.is_running = True

        # ----------------------------------------------------
        # START
        # ----------------------------------------------------

        self.status_changed.emit(
            "Игровой режим запущен"
        )

        print(
            "[Gaming] Игровой режим запущен"
        )

        self.ocr_timer.start()

        # Первый OCR сразу.
        self.capture_and_ocr()

    # ========================================================
    # WAIT FOR OCR
    # ========================================================

    def _wait_for_ocr_worker(self):

        worker = self.ocr_worker

        if worker is None:
            return

        if worker.isRunning():

            print(
                "[Gaming] "
                "Ожидание завершения OCR..."
            )

            worker.requestInterruption()

            worker.wait()

        # ----------------------------------------------------
        # После wait() поток гарантированно остановлен.
        # ----------------------------------------------------

        if worker.isFinished():

            worker.deleteLater()

        self.ocr_worker = None

    # ========================================================
    # WAIT FOR TRANSLATION
    # ========================================================

    def _wait_for_translation_worker(self):

        worker = self.translation_worker

        if worker is None:
            return

        if worker.isRunning():

            print(
                "[Gaming] "
                "Ожидание завершения перевода..."
            )

            worker.requestInterruption()

            worker.wait()

        if worker.isFinished():

            worker.deleteLater()

        self.translation_worker = None

    # ========================================================
    # STOP
    # ========================================================

    def stop(self):

        # ----------------------------------------------------
        # Сначала запрещаем новые задачи.
        # ----------------------------------------------------

        self.is_running = False

        # ----------------------------------------------------
        # Останавливаем таймер.
        # ----------------------------------------------------

        self.ocr_timer.stop()

        # ----------------------------------------------------
        # OCR
        # ----------------------------------------------------

        self._wait_for_ocr_worker()

        # ----------------------------------------------------
        # TRANSLATION
        # ----------------------------------------------------

        self._wait_for_translation_worker()

        # ----------------------------------------------------
        # RESET STATE
        # ----------------------------------------------------

        self.last_text = ""

        self.translating_text = ""

        self.pending_text = ""

        self.candidate_text = ""

        self.candidate_count = 0

        self.status_changed.emit(
            "Игровой режим остановлен"
        )

        print(
            "[Gaming] Игровой режим остановлен"
        )

    # ========================================================
    # OCR
    # ========================================================

    def capture_and_ocr(self):

        if not self.is_running:
            return

        if self.target_rect.isNull():
            return

        # ----------------------------------------------------
        # Предыдущий OCR ещё работает.
        # Просто ждём следующего тика таймера.
        # ----------------------------------------------------

        if (
            self.ocr_worker is not None
            and self.ocr_worker.isRunning()
        ):

            return

        try:

            screen = QApplication.primaryScreen()

            if screen is None:
                return

            rect = self.target_rect

            pixmap = screen.grabWindow(
                0,
                rect.x(),
                rect.y(),
                rect.width(),
                rect.height()
            )

            if pixmap.isNull():
                return

            image = pixmap.toImage()

            image = image.convertToFormat(
                image.Format.Format_RGB888
            )

            width = image.width()

            height = image.height()

            bytes_per_line = (
                image.bytesPerLine()
            )

            ptr = image.bits()

            ptr.setsize(
                image.sizeInBytes()
            )

            buffer = np.frombuffer(
                ptr,
                dtype=np.uint8
            )

            image_array = buffer.reshape(
                (
                    height,
                    bytes_per_line
                )
            )[:, :width * 3]

            image_array = image_array.reshape(
                (
                    height,
                    width,
                    3
                )
            )

            # ------------------------------------------------
            # Qt RGB -> OpenCV BGR
            # ------------------------------------------------

            image_array = (
                image_array[:, :, ::-1]
                .copy()
            )

            # ------------------------------------------------
            # Создаём worker.
            #
            # Передаём self как parent.
            # Это дополнительно защищает от случайного
            # уничтожения объекта раньше времени.
            # ------------------------------------------------

            worker = GameOCRWorker(
                image_array,
                self
            )

            self.ocr_worker = worker

            worker.result_ready.connect(
                self.on_ocr_result
            )

            worker.error.connect(
                self.on_ocr_error
            )

            worker.finished.connect(
                self.on_ocr_finished
            )

            worker.start()

        except Exception as e:

            print(
                f"[Gaming] Ошибка захвата: {e}"
            )

    # ========================================================
    # OCR FINISHED
    # ========================================================

    def on_ocr_finished(self):

        worker = self.ocr_worker

        if worker is None:
            return

        # ----------------------------------------------------
        # finished() означает, что run() уже завершился.
        # Теперь поток можно удалить.
        # ----------------------------------------------------

        self.ocr_worker = None

        worker.deleteLater()

    # ========================================================
    # OCR ERROR
    # ========================================================

    def on_ocr_error(
        self,
        error
    ):

        print(
            f"[Gaming] OCR ошибка: {error}"
        )

    # ========================================================
    # NORMALIZATION
    # ========================================================

    def normalize_text(
        self,
        text
    ):

        if not text:
            return ""

        return (
            " ".join(
                text.split()
            )
            .casefold()
        )

    # ========================================================
    # SIMILARITY
    # ========================================================

    def text_similarity(
        self,
        text_a,
        text_b
    ):

        a = self.normalize_text(
            text_a
        )

        b = self.normalize_text(
            text_b
        )

        if not a or not b:
            return 0.0

        if a == b:
            return 1.0

        # ----------------------------------------------------
        # Символьное сходство
        # ----------------------------------------------------

        char_similarity = SequenceMatcher(
            None,
            a,
            b
        ).ratio()

        # ----------------------------------------------------
        # Слова
        # ----------------------------------------------------

        words_a = a.split()

        words_b = b.split()

        if not words_a or not words_b:
            return char_similarity

        word_similarity = SequenceMatcher(
            None,
            words_a,
            words_b
        ).ratio()

        # ----------------------------------------------------
        # Пересечение слов
        # ----------------------------------------------------

        set_a = set(words_a)

        set_b = set(words_b)

        intersection = len(
            set_a & set_b
        )

        union = len(
            set_a | set_b
        )

        if union > 0:

            word_overlap = (
                intersection / union
            )

        else:

            word_overlap = 0.0

        # ----------------------------------------------------
        # Сходство длины
        # ----------------------------------------------------

        len_a = len(a)

        len_b = len(b)

        max_len = max(
            len_a,
            len_b
        )

        if max_len > 0:

            length_similarity = (
                1.0
                - abs(len_a - len_b) / max_len
            )

        else:

            length_similarity = 0.0

        # ----------------------------------------------------
        # Итог
        # ----------------------------------------------------

        similarity = (
            char_similarity * 0.35
            + word_similarity * 0.30
            + word_overlap * 0.20
            + length_similarity * 0.15
        )

        return similarity

    # ========================================================
    # OCR RESULT
    # ========================================================

    def on_ocr_result(
        self,
        text
    ):

        if not self.is_running:
            return

        text = text.strip()

        if not text:
            return

        if not self.normalize_text(
            text
        ):

            return

        # ----------------------------------------------------
        # COMPARE WITH CURRENT TEXT
        # ----------------------------------------------------

        if self.last_text:

            similarity = (
                self.text_similarity(
                    text,
                    self.last_text
                )
            )

            similarity_percent = (
                similarity * 100
            )

            print(
                "[Gaming] "
                "Сходство с текущим текстом: "
                f"{similarity_percent:.1f}%"
            )

            if (
                similarity >=
                self.similarity_threshold
            ):

                self.candidate_text = ""

                self.candidate_count = 0

                return

        # ----------------------------------------------------
        # FIRST CANDIDATE
        # ----------------------------------------------------

        if not self.candidate_text:

            self.candidate_text = text

            self.candidate_count = 1

            print(
                "[Gaming] "
                f"OCR кандидат "
                f"(1/{self.required_candidate_count}): "
                f"{text}"
            )

            return

        # ----------------------------------------------------
        # COMPARE WITH CANDIDATE
        # ----------------------------------------------------

        similarity = (
            self.text_similarity(
                text,
                self.candidate_text
            )
        )

        similarity_percent = (
            similarity * 100
        )

        print(
            "[Gaming] "
            "Сходство с кандидатом: "
            f"{similarity_percent:.1f}%"
        )

        # ----------------------------------------------------
        # SAME CANDIDATE
        # ----------------------------------------------------

        if (
            similarity >=
            self.similarity_threshold
        ):

            self.candidate_count += 1

            print(
                "[Gaming] "
                f"OCR кандидат "
                f"({self.candidate_count}/"
                f"{self.required_candidate_count})"
            )

        # ----------------------------------------------------
        # NEW CANDIDATE
        # ----------------------------------------------------

        else:

            self.candidate_text = text

            self.candidate_count = 1

            print(
                "[Gaming] "
                f"Новый OCR кандидат "
                f"(1/{self.required_candidate_count}): "
                f"{text}"
            )

            return

        # ----------------------------------------------------
        # NOT ENOUGH CONFIRMATIONS
        # ----------------------------------------------------

        if (
            self.candidate_count <
            self.required_candidate_count
        ):

            return

        # ----------------------------------------------------
        # CONFIRMED
        # ----------------------------------------------------

        stable_text = (
            self.candidate_text
        )

        self.candidate_text = ""

        self.candidate_count = 0

        print(
            "[Gaming] "
            "Новый игровой текст подтверждён"
        )

        self.accept_new_text(
            stable_text
        )

    # ========================================================
    # ACCEPT NEW TEXT
    # ========================================================

    def accept_new_text(
        self,
        text
    ):

        if not self.is_running:
            return

        text = text.strip()

        if not text:
            return

        # ----------------------------------------------------
        # DUPLICATE PROTECTION
        # ----------------------------------------------------

        if self.last_text:

            similarity = (
                self.text_similarity(
                    text,
                    self.last_text
                )
            )

            if (
                similarity >=
                self.similarity_threshold
            ):

                return

        # ----------------------------------------------------
        # SAVE CURRENT TEXT
        # ----------------------------------------------------

        self.last_text = text

        # ----------------------------------------------------
        # TRANSLATION BUSY
        # ----------------------------------------------------

        if (
            self.translation_worker is not None
            and self.translation_worker.isRunning()
        ):

            self.pending_text = text

            self.status_changed.emit(
                "Обнаружен новый игровой текст"
            )

            return

        # ----------------------------------------------------
        # TRANSLATE
        # ----------------------------------------------------

        self.start_translation(
            text
        )

    # ========================================================
    # TRANSLATION
    # ========================================================

    def start_translation(
        self,
        text
    ):

        if not self.is_running:
            return

        # ----------------------------------------------------
        # Не создаём несколько переводчиков.
        # ----------------------------------------------------

        if (
            self.translation_worker is not None
            and self.translation_worker.isRunning()
        ):

            self.pending_text = text

            return

        self.translating_text = text

        self.translation_started.emit()

        self.status_changed.emit(
            "Перевод..."
        )

        print(
            "[Gaming] Перевод..."
        )

        worker = AIWorker(

            image_bytes=b"",

            action="game_translation",

            target_lang=
                self.target_lang,

            from_lang=
                self.from_lang,

            extracted_text=
                text
        )

        self.translation_worker = worker

        worker.finished.connect(
            self.on_translation_finished
        )

        worker.start()

    # ========================================================
    # TRANSLATION FINISHED
    # ========================================================

    def on_translation_finished(
        self,
        answer
    ):

        if not self.is_running:
            return

        print(
            "[Gaming] Перевод: "
            f"{answer}"
        )

        self.translation_finished.emit(
            answer
        )

        worker = (
            self.translation_worker
        )

        self.translation_worker = None

        if worker is not None:

            worker.deleteLater()

        # ----------------------------------------------------
        # Новый текст появился во время перевода.
        # ----------------------------------------------------

        if self.pending_text:

            pending = (
                self.pending_text
            )

            self.pending_text = ""

            if (
                self.text_similarity(
                    pending,
                    self.translating_text
                )
                < self.similarity_threshold
            ):

                self.start_translation(
                    pending
                )