from difflib import SequenceMatcher
import ctypes

import numpy as np

from PyQt6.QtCore import (
    QObject,
    QThread,
    QTimer,
    pyqtSignal,
    QRect
)

from PyQt6.QtWidgets import (
    QApplication
)

from processor import (
    AIWorker,
    recognize_text
)


# ============================================================
# WINDOWS SCREEN CAPTURE PROTECTION
# ============================================================

WDA_NONE = 0x00000000

WDA_MONITOR = 0x00000001

WDA_EXCLUDEFROMCAPTURE = 0x00000011


# ============================================================
# WINDOWS API SETUP
# ============================================================

if hasattr(ctypes, "windll"):

    _SetWindowDisplayAffinity = (
        ctypes.windll.user32.SetWindowDisplayAffinity
    )

    _SetWindowDisplayAffinity.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32
    ]

    _SetWindowDisplayAffinity.restype = (
        ctypes.c_bool
    )

else:

    _SetWindowDisplayAffinity = None


# ============================================================
# OCR WORKER
# ============================================================

class GameOCRWorker(QThread):

    result_ready = pyqtSignal(str)

    error = pyqtSignal(str)

    def __init__(
        self,
        image,
        parent=None
    ):
        super().__init__(
            parent
        )

        self.image = image

    def run(self):
        try:
            text = recognize_text(
                self.image,
                preprocess=True
            )

            if self.isInterruptionRequested():
                return

            self.result_ready.emit(
                text
            )

        except Exception as e:

            if not self.isInterruptionRequested():
                self.error.emit(
                    str(e)
                )


# ============================================================
# GAMING TRANSLATION MANAGER
# ============================================================

class GamingTranslationManager(QObject):

    translation_started = pyqtSignal()

    translation_finished = pyqtSignal(str)

    status_changed = pyqtSignal(str)

    def __init__(
        self,
        parent=None,
        overlay_window=None
    ):
        super().__init__(
            parent
        )

        # ----------------------------------------------------
        # РЕАЛЬНЫЙ TOP-LEVEL OVERLAY
        # ----------------------------------------------------

        self.overlay_window = overlay_window

        self.overlay_capture_protected = False

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
        # WORKERS
        # ----------------------------------------------------

        self.ocr_worker = None

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
    # SET OVERLAY WINDOW
    # ========================================================

    def set_overlay_window(
        self,
        overlay_window
    ):
        self.overlay_window = (
            overlay_window
        )

        print(
            "[Gaming] Overlay window установлен"
        )

    # ========================================================
    # PROTECT OVERLAY FROM CAPTURE
    # ========================================================

    def _protect_overlay_from_capture(
        self
    ):
        self.overlay_capture_protected = False

        if _SetWindowDisplayAffinity is None:
            print(
                "[Gaming] "
                "SetWindowDisplayAffinity недоступен"
            )

            return False

        overlay = self.overlay_window

        if overlay is None:
            print(
                "[Gaming] "
                "Overlay window не задан"
            )

            return False

        try:
            # ------------------------------------------------
            # Получаем HWND именно AIOverlay.
            # ------------------------------------------------

            hwnd = int(
                overlay.winId()
            )

            if hwnd == 0:
                print(
                    "[Gaming] "
                    "Не удалось получить HWND overlay"
                )

                return False

            print(
                "[Gaming] "
                f"HWND overlay: {hwnd}"
            )

            # ------------------------------------------------
            # Исключаем окно из поддерживаемого Windows
            # screen capture.
            # ------------------------------------------------

            result = (
                _SetWindowDisplayAffinity(
                    ctypes.c_void_p(hwnd),
                    WDA_EXCLUDEFROMCAPTURE
                )
            )

            if not result:
                error_code = (
                    ctypes.get_last_error()
                )

                print(
                    "[Gaming] "
                    "Не удалось установить "
                    "WDA_EXCLUDEFROMCAPTURE. "
                    f"Windows error: {error_code}"
                )

                return False

            self.overlay_capture_protected = True

            print(
                "[Gaming] "
                "Overlay исключён из screen capture"
            )

            return True

        except Exception as e:

            print(
                "[Gaming] "
                "Ошибка установки capture protection: "
                f"{e}"
            )

            return False

    # ========================================================
    # REMOVE CAPTURE PROTECTION
    # ========================================================

    def _remove_overlay_capture_protection(
        self
    ):
        if not self.overlay_capture_protected:
            return

        if _SetWindowDisplayAffinity is None:
            return

        overlay = self.overlay_window

        if overlay is None:
            return

        try:
            hwnd = int(
                overlay.winId()
            )

            if hwnd == 0:
                return

            _SetWindowDisplayAffinity(
                ctypes.c_void_p(hwnd),
                WDA_NONE
            )

            print(
                "[Gaming] "
                "Защита overlay от screen capture снята"
            )

        except Exception as e:

            print(
                "[Gaming] "
                "Ошибка снятия capture protection: "
                f"{e}"
            )

        finally:
            self.overlay_capture_protected = False

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
        # Старый OCR
        # ----------------------------------------------------

        self._wait_for_ocr_worker()

        # ----------------------------------------------------
        # Старый перевод
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
        # CAPTURE PROTECTION
        #
        # Overlay уже показан из main.py.
        # Сейчас получаем его реальный HWND и исключаем
        # его из поддерживаемого Windows capture.
        # ----------------------------------------------------

        protected = (
            self._protect_overlay_from_capture()
        )

        if not protected:
            print(
                "[Gaming] "
                "ВНИМАНИЕ: Overlay НЕ был исключён "
                "из screen capture"
            )

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

    def _wait_for_ocr_worker(
        self
    ):
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

        if worker.isFinished():
            worker.deleteLater()

        self.ocr_worker = None

    # ========================================================
    # WAIT FOR TRANSLATION
    # ========================================================

    def _wait_for_translation_worker(
        self
    ):
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
        self.is_running = False

        self.ocr_timer.stop()

        self._wait_for_ocr_worker()

        self._wait_for_translation_worker()

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

        # После выхода из Gaming Mode
        # снова разрешаем обычный capture этого окна.
        self._remove_overlay_capture_protection()

    # ========================================================
    # OCR CAPTURE
    # ========================================================

    def capture_and_ocr(
        self
    ):
        if not self.is_running:
            return

        if self.target_rect.isNull():
            return

        if (
            self.ocr_worker is not None
            and self.ocr_worker.isRunning()
        ):
            return

        try:
            screen = (
                QApplication.primaryScreen()
            )

            if screen is None:
                return

            rect = self.target_rect

            # ------------------------------------------------
            # ВАЖНО:
            #
            # Overlay НЕ скрываем.
            #
            # Windows получает отдельный HWND overlay
            # с WDA_EXCLUDEFROMCAPTURE.
            #
            # Здесь захватывается экран как раньше.
            # ------------------------------------------------

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

            # Qt RGB -> OpenCV BGR
            image_array = (
                image_array[:, :, ::-1]
                .copy()
            )

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

    def on_ocr_finished(
        self
    ):
        worker = self.ocr_worker

        if worker is None:
            return

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

        char_similarity = SequenceMatcher(
            None,
            a,
            b
        ).ratio()

        words_a = a.split()

        words_b = b.split()

        if not words_a or not words_b:
            return char_similarity

        word_similarity = SequenceMatcher(
            None,
            words_a,
            words_b
        ).ratio()

        set_a = set(
            words_a
        )

        set_b = set(
            words_b
        )

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

        len_a = len(a)

        len_b = len(b)

        max_len = max(
            len_a,
            len_b
        )

        if max_len > 0:
            length_similarity = (
                1.0
                - abs(len_a - len_b)
                / max_len
            )

        else:
            length_similarity = 0.0

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
                similarity
                >= self.similarity_threshold
            ):
                self.candidate_text = ""

                self.candidate_count = 0

                return

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

        if (
            similarity
            >= self.similarity_threshold
        ):
            self.candidate_count += 1

            print(
                "[Gaming] "
                f"OCR кандидат "
                f"({self.candidate_count}/"
                f"{self.required_candidate_count})"
            )

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

        if (
            self.candidate_count
            < self.required_candidate_count
        ):
            return

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

        if self.last_text:

            similarity = (
                self.text_similarity(
                    text,
                    self.last_text
                )
            )

            if (
                similarity
                >= self.similarity_threshold
            ):
                return

        self.last_text = text

        if (
            self.translation_worker is not None
            and self.translation_worker.isRunning()
        ):
            self.pending_text = text

            self.status_changed.emit(
                "Обнаружен новый игровой текст"
            )

            return

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
            target_lang=self.target_lang,
            from_lang=self.from_lang,
            extracted_text=text
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