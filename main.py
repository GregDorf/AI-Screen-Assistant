import os
import sys
import signal
import ctypes
import math
import keyboard

# Принудительно устанавливаем CWD в папку с .exe файлом
if getattr(sys, 'frozen', False):
    os.chdir(os.path.dirname(sys.executable))

from PyQt6.QtWidgets import (
    QApplication,
    QWidget,
    QComboBox,
    QLabel,
    QVBoxLayout,
    QPushButton
)

from PyQt6.QtCore import (
    Qt,
    QRect,
    QPoint,
    pyqtSignal,
    QObject,
    QBuffer,
    QIODevice,
    QTimer,
    QEvent
)

from PyQt6.QtGui import (
    QPainter,
    QPen,
    QColor,
    QPixmap,
    QFont,
    QFontMetrics,
    QRegion,
    QPolygon
)

import config
from tray import TrayManager
from processor import AIWorker
from gaming_mode import GamingTranslationManager


class HotkeySignal(QObject):
    triggered = pyqtSignal()


class EscSignal(QObject):
    triggered = pyqtSignal()


class SelectionItem:
    def __init__(
        self,
        rect: QRect,
        category: str,
        answer_rect: QRect,
        snapshot: QPixmap
    ):
        self.rect = rect
        self.category = category
        self.answer = ""
        self.answer_rect = answer_rect
        self.snapshot = snapshot
        self.is_loading = True


class AIOverlay(QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Tool |
            Qt.WindowType.WindowStaysOnTopHint
        )

        # Настоящая прозрачность окна на уровне ОС.
        self.setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground,
            True
        )

        self.setAutoFillBackground(False)

        self.is_selecting = False
        self.is_choosing_action = False
        self.is_choosing_lang = False
        self.language_panel_for_gaming = False
        self.is_capturing = False
        self.is_gaming_mode = False

        self.start_pos = QPoint()
        self.end_pos = QPoint()

        self.screen_pixmap = QPixmap()

        # Обычная область выделения.
        self.current_target_rect = QRect()

        # Фиксированная область игрового режима.
        self.gaming_rect = QRect()

        self.btn_question_rect = QRect()
        self.btn_term_rect = QRect()
        self.btn_translate_rect = QRect()
        self.btn_gaming_rect = QRect()

        # -----------------------------------------------------
        # LANGUAGE PANEL
        # -----------------------------------------------------

        self.lang_panel = QWidget(self)
        self.lang_panel.hide()

        panel_layout = QVBoxLayout(
            self.lang_panel
        )

        panel_layout.setContentsMargins(
            8,
            8,
            8,
            8
        )

        panel_layout.setSpacing(6)

        combo_style = """
            QComboBox {
                background-color: rgba(30, 30, 30, 240);
                color: white;
                border: 1px solid #50ff50;
                border-radius: 6px;
                padding: 4px 8px;
                font-family: 'Segoe UI';
                font-size: 11px;
                font-weight: bold;
            }

            QComboBox::drop-down {
                border: 0px;
            }

            QComboBox QAbstractItemView {
                background-color: #1e1e1e;
                color: white;
                selection-background-color: #3498db;
                selection-color: white;
                border: 1px solid #50ff50;
            }
        """

        label_style = """
            color: #b0ffb0;
            font-family: 'Segoe UI';
            font-size: 10px;
            font-weight: bold;
        """

        lbl_from = QLabel(
            "Исходный язык:",
            self.lang_panel
        )

        lbl_from.setStyleSheet(
            label_style
        )

        panel_layout.addWidget(
            lbl_from
        )

        self.combo_from_lang = QComboBox(
            self.lang_panel
        )

        self.combo_from_lang.installEventFilter(
            self
        )

        panel_layout.addWidget(
            self.combo_from_lang
        )

        lbl_to = QLabel(
            "Перевести на:",
            self.lang_panel
        )

        lbl_to.setStyleSheet(
            label_style
        )

        panel_layout.addWidget(
            lbl_to
        )

        self.combo_to_lang = QComboBox(
            self.lang_panel
        )

        self.combo_to_lang.installEventFilter(
            self
        )

        panel_layout.addWidget(
            self.combo_to_lang
        )

        self.btn_confirm_translate = QPushButton(
            "OK",
            self.lang_panel
        )

        self.btn_confirm_translate.installEventFilter(
            self
        )

        self.btn_confirm_translate.clicked.connect(
            self.on_confirm_translation
        )

        panel_layout.addWidget(
            self.btn_confirm_translate
        )

        self.lang_panel.installEventFilter(
            self
        )

        self.set_language_panel_style(
            gaming=False
        )

        self.populate_languages()

        # -----------------------------------------------------
        # NORMAL MODE DATA
        # -----------------------------------------------------

        self.history_items = []

        self.active_category = "question"

        self.workers = []

        # -----------------------------------------------------
        # GAMING MODE DATA
        # -----------------------------------------------------

        self.gaming_translation = ""

        self.gaming_translation_loading = False

        # ВАЖНО:
        # Передаём САМ AIOverlay как overlay_window.
        #
        # Именно этот top-level QWidget рисует Gaming Mode
        # и именно его HWND нужно исключить из capture.
        self.gaming_manager = GamingTranslationManager(
            self,
            overlay_window=self
        )

        self.gaming_manager.translation_started.connect(
            self.on_gaming_translation_started
        )

        self.gaming_manager.translation_finished.connect(
            self.on_gaming_translation_finished
        )

        self.gaming_manager.status_changed.connect(
            self.on_gaming_status_changed
        )

        # -----------------------------------------------------
        # NORMAL MODE INTERACTION
        # -----------------------------------------------------

        self.dragging_item = None

        self.resizing_item = None

        self.drag_offset = QPoint()

        # -----------------------------------------------------
        # ANIMATION
        # -----------------------------------------------------

        self.angle = 0

        self.anim_timer = QTimer(self)

        self.anim_timer.timeout.connect(
            self.update_animation
        )

        self.anim_timer.start(33)

        # -----------------------------------------------------
        # HOTKEYS
        # -----------------------------------------------------

        self.hotkey_signal = HotkeySignal()

        self.hotkey_signal.triggered.connect(
            self.start_capture
        )

        self.esc_signal = EscSignal()

        self.esc_signal.triggered.connect(
            self.reset_all
        )

        QTimer.singleShot(
            3000,
            self.init_hotkeys
        )

    # =========================================================
    # HOTKEYS
    # =========================================================

    def init_hotkeys(self):
        try:
            keyboard.add_hotkey(
                config.HOTKEY,
                self.hotkey_signal.triggered.emit
            )

            keyboard.add_hotkey(
                "esc",
                self.esc_signal.triggered.emit
            )

            print(
                "[System] Глобальные горячие клавиши успешно зарегистрированы"
            )

        except Exception as e:
            print(
                f"[Error] Не удалось зарегистрировать хоткеи: {e}"
            )

    # =========================================================
    # LANGUAGE PANEL STYLE
    # =========================================================

    def set_language_panel_style(
        self,
        gaming=False
    ):
        if gaming:
            border_color = "#dc2828"
            background_color = "rgba(35, 15, 15, 245)"
            accent_color = "#dc2828"
            hover_color = "#c82020"
            label_color = "#ffb0b0"

        else:
            border_color = "#50ff50"
            background_color = "rgba(20, 20, 20, 240)"
            accent_color = "#50ff50"
            hover_color = "#40e040"
            label_color = "#b0ffb0"

        self.lang_panel.setStyleSheet(
            f"""
            QWidget {{
                background-color: {background_color};
                border: 1px solid {border_color};
                border-radius: 8px;
            }}
            """
        )

        self.combo_from_lang.setStyleSheet(
            f"""
            QComboBox {{
                background-color: rgba(30, 30, 30, 240);
                color: white;
                border: 1px solid {border_color};
                border-radius: 6px;
                padding: 4px 8px;
                font-family: 'Segoe UI';
                font-size: 11px;
                font-weight: bold;
            }}

            QComboBox::drop-down {{
                border: 0px;
            }}

            QComboBox QAbstractItemView {{
                background-color: #1e1e1e;
                color: white;
                selection-background-color: {accent_color};
                selection-color: white;
                border: 1px solid {border_color};
            }}
            """
        )

        self.combo_to_lang.setStyleSheet(
            f"""
            QComboBox {{
                background-color: rgba(30, 30, 30, 240);
                color: white;
                border: 1px solid {border_color};
                border-radius: 6px;
                padding: 4px 8px;
                font-family: 'Segoe UI';
                font-size: 11px;
                font-weight: bold;
            }}

            QComboBox::drop-down {{
                border: 0px;
            }}

            QComboBox QAbstractItemView {{
                background-color: #1e1e1e;
                color: white;
                selection-background-color: {accent_color};
                selection-color: white;
                border: 1px solid {border_color};
            }}
            """
        )

        label_style = f"""
            color: {label_color};
            font-family: 'Segoe UI';
            font-size: 10px;
            font-weight: bold;
            background-color: transparent;
            border: none;
        """

        for widget in self.lang_panel.findChildren(QLabel):
            widget.setStyleSheet(
                label_style
            )

        self.btn_confirm_translate.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {accent_color};
                color: #1e1e1e;
                border: none;
                border-radius: 6px;
                font-family: 'Segoe UI';
                font-size: 11px;
                font-weight: bold;
                padding: 5px;
            }}

            QPushButton:hover {{
                background-color: {hover_color};
            }}

            QPushButton:pressed {{
                background-color: {border_color};
            }}
            """
        )

    # =========================================================
    # GAMING MODE SIGNALS
    # =========================================================

    def on_gaming_translation_started(self):
        self.gaming_translation_loading = False

        self.update()

    def on_gaming_translation_finished(
        self,
        answer: str
    ):
        self.gaming_translation_loading = False

        self.gaming_translation = answer

        self.update()

    def on_gaming_status_changed(
        self,
        status: str
    ):
        print(
            f"[Gaming] {status}"
        )

    # =========================================================
    # EVENT FILTER
    # =========================================================

    def eventFilter(
        self,
        obj,
        event
    ):
        if (
            event.type()
            == QEvent.Type.KeyPress
            and event.key()
            == Qt.Key.Key_Escape
        ):
            self.reset_all()

            return True

        return super().eventFilter(
            obj,
            event
        )

    # =========================================================
    # LANGUAGES
    # =========================================================

    def populate_languages(self):
        languages = [
            ("Русский", "русский"),
            ("Английский", "английский"),
            ("Испанский", "испанский"),
            ("Немецкий", "немецкий"),
            ("Французский", "французский"),
            ("Итальянский", "итальянский"),
            ("Китайский", "китайский"),
            ("Японский", "японский"),
            ("Корейский", "корейский"),
            ("Португальский", "португальский"),
            ("Турецкий", "турецкий"),
            ("Польский", "польский"),
            ("Украинский", "украинский")
        ]

        self.combo_from_lang.addItem(
            "Автоопределение",
            "auto"
        )

        for name, code in languages:
            self.combo_from_lang.addItem(
                name,
                code
            )

            self.combo_to_lang.addItem(
                name,
                code
            )

        self.combo_to_lang.setCurrentIndex(
            0
        )

    # =========================================================
    # ANIMATION
    # =========================================================

    def update_animation(self):
        normal_loading = any(
            item.is_loading
            for item in self.history_items
        )

        gaming_loading = (
            self.is_gaming_mode
            and self.gaming_translation_loading
        )

        if normal_loading or gaming_loading:
            self.angle = (
                self.angle + 10
            ) % 360

            if normal_loading:
                for item in self.history_items:
                    if item.is_loading:
                        loader_rect = QRect(
                            item.answer_rect.center().x() - 25,
                            item.answer_rect.center().y() - 25,
                            50,
                            50
                        )

                        self.update(
                            loader_rect
                        )

            if gaming_loading:
                self.update(
                    self.gaming_rect
                )

    # =========================================================
    # INTERACTION MASK
    # =========================================================

    def update_interaction_mask(self):
        if self.is_gaming_mode:
            self.clearMask()
            return

        if (
            self.is_selecting
            or self.is_choosing_action
            or self.is_choosing_lang
        ):
            self.clearMask()

        else:
            if not self.history_items:
                self.hide()
                return

            region = QRegion()

            for item in self.history_items:
                region = region.united(
                    QRegion(
                        item.rect.adjusted(
                            -5,
                            -5,
                            5,
                            5
                        )
                    )
                )

                region = region.united(
                    QRegion(
                        item.answer_rect.adjusted(
                            -5,
                            -5,
                            5,
                            5
                        )
                    )
                )

                c1 = item.rect.center()

                c2 = item.answer_rect.center()

                p1 = self.get_rect_intersection_point(
                    item.rect,
                    c2
                )

                p2 = self.get_rect_intersection_point(
                    item.answer_rect,
                    c1
                )

                dx = p2.x() - p1.x()

                dy = p2.y() - p1.y()

                length = math.hypot(
                    dx,
                    dy
                )

                if length > 0:
                    nx = int(
                        dy / length * 6
                    )

                    ny = int(
                        -dx / length * 6
                    )

                    poly = QPolygon([
                        QPoint(
                            p1.x() + nx,
                            p1.y() + ny
                        ),
                        QPoint(
                            p1.x() - nx,
                            p1.y() - ny
                        ),
                        QPoint(
                            p2.x() - nx,
                            p2.y() - ny
                        ),
                        QPoint(
                            p2.x() + nx,
                            p2.y() + ny
                        )
                    ])

                    region = region.united(
                        QRegion(poly)
                    )

            self.setMask(
                region
            )

    # =========================================================
    # CAPTURE
    # =========================================================

    def start_capture(self):
        if (
            self.is_selecting
            or self.is_choosing_action
            or self.is_choosing_lang
            or self.is_capturing
        ):
            return

        self.is_capturing = True

        self.lang_panel.hide()

        self.hide()

        QApplication.processEvents()

        QTimer.singleShot(
            150,
            self._perform_capture
        )

    def _perform_capture(self):
        screen = QApplication.primaryScreen()

        self.screen_pixmap = screen.grabWindow(
            0
        )

        self.setGeometry(
            screen.geometry()
        )

        self.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents,
            False
        )

        self.is_selecting = True

        self.is_choosing_action = False

        self.is_choosing_lang = False

        self.start_pos = QPoint()

        self.end_pos = QPoint()

        self.current_target_rect = QRect()

        self.clearMask()

        self.showMaximized()

        self.raise_()

        self.activateWindow()

        self.setCursor(
            Qt.CursorShape.CrossCursor
        )

        self.is_capturing = False

        self.repaint()

    # =========================================================
    # RESET
    # =========================================================

    def reset_all(self):
        if self.is_gaming_mode:
            self.gaming_manager.stop()

        self.is_gaming_mode = False

        self.gaming_rect = QRect()

        self.gaming_translation = ""

        self.gaming_translation_loading = False

        self.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents,
            False
        )

        for worker in self.workers:
            if worker.isRunning():
                worker.terminate()
                worker.wait()

        self.workers.clear()

        self.history_items.clear()

        self.screen_pixmap = QPixmap()

        self.is_selecting = False

        self.is_choosing_action = False

        self.is_choosing_lang = False

        self.language_panel_for_gaming = False

        self.is_capturing = False

        self.lang_panel.hide()

        self.current_target_rect = QRect()

        self.clearMask()

        self.hide()

        self.update()

    # =========================================================
    # MOUSE PRESS
    # =========================================================

    def mousePressEvent(self, event):
        pos = event.pos()

        if (
            self.is_selecting
            and event.button()
            == Qt.MouseButton.LeftButton
        ):
            self.start_pos = pos

            self.end_pos = pos

            self.update()

            return

        if (
            not self.is_selecting
            and not self.is_choosing_action
            and not self.is_choosing_lang
            and not self.is_gaming_mode
        ):
            for item in self.history_items:
                resize_handle = QRect(
                    item.answer_rect.right() - 15,
                    item.answer_rect.bottom() - 15,
                    15,
                    15
                )

                if resize_handle.contains(pos):
                    self.resizing_item = item

                    self.clearMask()

                    return

                elif item.answer_rect.contains(pos):
                    self.dragging_item = item

                    self.drag_offset = (
                        pos
                        - item.answer_rect.topLeft()
                    )

                    self.clearMask()

                    return

        elif (
            self.is_choosing_action
            and event.button()
            == Qt.MouseButton.LeftButton
        ):
            if self.btn_question_rect.contains(pos):
                self.start_processing(
                    "question"
                )

            elif self.btn_term_rect.contains(pos):
                self.start_processing(
                    "term"
                )

            elif self.btn_translate_rect.contains(pos):
                self.language_panel_for_gaming = False

                self.setup_language_panel()

            elif self.btn_gaming_rect.contains(pos):
                self.language_panel_for_gaming = True

                self.setup_language_panel()

            else:
                self.is_choosing_action = False

                self.lang_panel.hide()

                self.update_interaction_mask()

                self.update()

    # =========================================================
    # MOUSE MOVE
    # =========================================================

    def mouseMoveEvent(self, event):
        pos = event.pos()

        if self.dragging_item:
            self.dragging_item.answer_rect.moveTo(
                pos - self.drag_offset
            )

            self.update()

            return

        if self.resizing_item:
            new_w = max(
                200,
                pos.x()
                - self.resizing_item.answer_rect.left()
            )

            new_h = max(
                100,
                pos.y()
                - self.resizing_item.answer_rect.top()
            )

            self.resizing_item.answer_rect.setWidth(
                new_w
            )

            self.resizing_item.answer_rect.setHeight(
                new_h
            )

            self.update()

            return

        if (
            self.is_selecting
            and bool(
                event.buttons()
                & Qt.MouseButton.LeftButton
            )
        ):
            self.end_pos = pos

            self.update()

        elif self.is_choosing_action:
            if (
                self.btn_question_rect.contains(pos)
                or self.btn_term_rect.contains(pos)
                or self.btn_translate_rect.contains(pos)
                or self.btn_gaming_rect.contains(pos)
            ):
                self.setCursor(
                    Qt.CursorShape.PointingHandCursor
                )

            else:
                self.setCursor(
                    Qt.CursorShape.ArrowCursor
                )

        elif (
            not self.is_selecting
            and not self.is_choosing_lang
            and not self.is_gaming_mode
        ):
            on_handle = False

            for item in self.history_items:
                handle = QRect(
                    item.answer_rect.right() - 15,
                    item.answer_rect.bottom() - 15,
                    15,
                    15
                )

                if handle.contains(pos):
                    on_handle = True
                    break

            if on_handle:
                self.setCursor(
                    Qt.CursorShape.SizeFDiagCursor
                )

            else:
                self.setCursor(
                    Qt.CursorShape.ArrowCursor
                )

    # =========================================================
    # MOUSE RELEASE
    # =========================================================

    def mouseReleaseEvent(self, event):
        if (
            self.dragging_item
            or self.resizing_item
        ):
            self.dragging_item = None

            self.resizing_item = None

            self.update_interaction_mask()

            return

        self.dragging_item = None

        self.resizing_item = None

        if (
            self.is_selecting
            and event.button()
            == Qt.MouseButton.LeftButton
        ):
            self.is_selecting = False

            self.current_target_rect = QRect(
                self.start_pos,
                self.end_pos
            ).normalized()

            if (
                self.current_target_rect.width() > 10
                and self.current_target_rect.height() > 10
            ):
                self.setup_action_buttons()

            else:
                self.is_choosing_action = False

                self.is_choosing_lang = False

                self.lang_panel.hide()

                self.update_interaction_mask()

                self.update()

    # =========================================================
    # ACTION BUTTONS
    # =========================================================

    def setup_action_buttons(self):
        self.is_choosing_action = True

        self.is_choosing_lang = False

        self.lang_panel.hide()

        self.setCursor(
            Qt.CursorShape.ArrowCursor
        )

        btn_size = 36

        spacing = 8

        total_width = (
            btn_size * 4
            + spacing * 3
        )

        base_x = (
            self.current_target_rect.right()
            - total_width
        )

        base_y = (
            self.current_target_rect.bottom()
            + 10
        )

        if (
            base_y + btn_size
            > self.height()
        ):
            base_y = (
                self.current_target_rect.top()
                - btn_size
                - 10
            )

        if base_x < 0:
            base_x = (
                self.current_target_rect.left()
            )

        self.btn_question_rect = QRect(
            base_x,
            base_y,
            btn_size,
            btn_size
        )

        self.btn_term_rect = QRect(
            base_x + btn_size + spacing,
            base_y,
            btn_size,
            btn_size
        )

        self.btn_translate_rect = QRect(
            base_x
            + (btn_size + spacing) * 2,
            base_y,
            btn_size,
            btn_size
        )

        self.btn_gaming_rect = QRect(
            base_x
            + (btn_size + spacing) * 3,
            base_y,
            btn_size,
            btn_size
        )

        self.update()

    # =========================================================
    # LANGUAGE PANEL
    # =========================================================

    def setup_language_panel(self):
        self.is_choosing_action = False

        self.is_choosing_lang = True

        self.setCursor(
            Qt.CursorShape.ArrowCursor
        )

        self.set_language_panel_style(
            gaming=self.language_panel_for_gaming
        )

        panel_width = 200

        panel_height = 160

        base_x = (
            self.current_target_rect.right()
            - panel_width
        )

        base_y = (
            self.current_target_rect.bottom()
            + 55
        )

        if base_y + panel_height > self.height():
            base_y = (
                self.current_target_rect.top()
                - panel_height
                - 10
            )

        if base_x < 0:
            base_x = self.current_target_rect.left()

        self.lang_panel.setGeometry(
            base_x,
            base_y,
            panel_width,
            panel_height
        )

        self.lang_panel.show()

        self.lang_panel.raise_()

        self.lang_panel.activateWindow()

    # =========================================================
    # CONFIRM TRANSLATION
    # =========================================================

    def on_confirm_translation(self):
        from_lang = (
            self.combo_from_lang.currentData()
        )

        target_lang = (
            self.combo_to_lang.currentData()
        )

        self.lang_panel.hide()

        self.is_choosing_lang = False

        if self.language_panel_for_gaming:
            self.language_panel_for_gaming = False

            self.start_gaming_mode(
                target_lang,
                from_lang
            )

            return

        self.start_processing(
            "translation",
            target_lang,
            from_lang
        )

    # =========================================================
    # NORMAL PROCESSING
    # =========================================================

    def start_processing(
        self,
        action: str,
        target_lang: str = "русский",
        from_lang: str = "auto"
    ):
        self.is_choosing_action = False

        self.is_choosing_lang = False

        self.lang_panel.hide()

        self.active_category = action

        self.setCursor(
            Qt.CursorShape.ArrowCursor
        )

        box_width = 400

        box_height = 180

        box_x = (
            self.current_target_rect.right()
            + 40
        )

        box_y = (
            self.current_target_rect.top()
        )

        if (
            box_x + box_width
            > self.width()
        ):
            box_x = (
                self.current_target_rect.left()
                - box_width
                - 40
            )

        initial_answer_rect = QRect(
            box_x,
            box_y,
            box_width,
            box_height
        )

        cropped = self.screen_pixmap.copy(
            self.current_target_rect
        )

        item = SelectionItem(
            self.current_target_rect,
            action,
            initial_answer_rect,
            cropped
        )

        self.history_items.append(
            item
        )

        buffer = QBuffer()

        buffer.open(
            QIODevice.OpenModeFlag.ReadWrite
        )

        cropped.save(
            buffer,
            "PNG"
        )

        image_bytes_data = bytes(
            buffer.data()
        )

        worker = AIWorker(
            image_bytes_data,
            action,
            target_lang,
            from_lang
        )

        self.workers.append(
            worker
        )

        def handle_response(answer: str):
            item.answer = answer

            item.is_loading = False

            self.update(
                item.answer_rect
            )

            if worker in self.workers:
                self.workers.remove(
                    worker
                )

            worker.deleteLater()

        worker.finished.connect(
            handle_response
        )

        worker.start()

        self.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents,
            False
        )

        self.update_interaction_mask()

        self.showMaximized()

        self.repaint()

    # =========================================================
    # RECT INTERSECTION
    # =========================================================

    def get_rect_intersection_point(
        self,
        rect: QRect,
        target_pt: QPoint
    ) -> QPoint:
        center = rect.center()

        cx = center.x()
        cy = center.y()

        tx = target_pt.x()
        ty = target_pt.y()

        dx = tx - cx
        dy = ty - cy

        if dx == 0 and dy == 0:
            return center

        left = rect.left() - 2
        right = rect.right() + 2
        top = rect.top() - 2
        bottom = rect.bottom() + 2

        best_pt = center

        min_t = float("inf")

        if dx != 0:
            t = (
                left - cx
            ) / dx

            if t > 0:
                y = cy + t * dy

                if (
                    top <= y <= bottom
                    and t < min_t
                ):
                    min_t = t

                    best_pt = QPoint(
                        int(left),
                        int(y)
                    )

        if dx != 0:
            t = (
                right - cx
            ) / dx

            if t > 0:
                y = cy + t * dy

                if (
                    top <= y <= bottom
                    and t < min_t
                ):
                    min_t = t

                    best_pt = QPoint(
                        int(right),
                        int(y)
                    )

        if dy != 0:
            t = (
                top - cy
            ) / dy

            if t > 0:
                x = cx + t * dx

                if (
                    left <= x <= right
                    and t < min_t
                ):
                    min_t = t

                    best_pt = QPoint(
                        int(x),
                        int(top)
                    )

        if dy != 0:
            t = (
                bottom - cy
            ) / dy

            if t > 0:
                x = cx + t * dx

                if (
                    left <= x <= right
                    and t < min_t
                ):
                    min_t = t

                    best_pt = QPoint(
                        int(x),
                        int(bottom)
                    )

        return best_pt

    # =========================================================
    # CLOSE
    # =========================================================

    def closeEvent(self, event):
        if self.is_gaming_mode:
            self.gaming_manager.stop()

        event.ignore()

        self.hide()

    # =========================================================
    # PAINT
    # =========================================================

    def paintEvent(self, event):
        if getattr(
            self,
            "is_capturing",
            False
        ):
            return

        painter = QPainter(self)

        painter.setRenderHint(
            QPainter.RenderHint.Antialiasing
        )

        clip_rect = event.rect()

        # -----------------------------------------------------
        # SCREENSHOT DURING AREA SELECTION
        # -----------------------------------------------------

        if (
            self.is_selecting
            or self.is_choosing_action
            or self.is_choosing_lang
        ):
            painter.fillRect(
                self.rect(),
                Qt.GlobalColor.black
            )

            if not self.screen_pixmap.isNull():
                painter.drawPixmap(
                    0,
                    0,
                    self.screen_pixmap
                )

        # -----------------------------------------------------
        # NORMAL MODE
        # -----------------------------------------------------

        if not self.is_gaming_mode:
            for item in self.history_items:
                item_full_rect = (
                    item.rect.united(
                        item.answer_rect
                    )
                )

                if clip_rect.intersects(
                    item_full_rect.adjusted(
                        -20,
                        -20,
                        20,
                        20
                    )
                ):
                    self.draw_result_item(
                        painter,
                        item,
                        draw_snapshot=True
                    )

        # -----------------------------------------------------
        # GAMING MODE
        # -----------------------------------------------------

        if self.is_gaming_mode:
            self.draw_gaming_mode(
                painter
            )

        # -----------------------------------------------------
        # AREA SELECTION / ACTION BUTTONS
        # -----------------------------------------------------

        if (
            self.is_selecting
            or self.is_choosing_action
            or self.is_choosing_lang
        ):
            painter.setBrush(
                Qt.BrushStyle.NoBrush
            )

            if self.is_selecting:
                current_rect = QRect(
                    self.start_pos,
                    self.end_pos
                ).normalized()

            else:
                current_rect = (
                    self.current_target_rect
                    if (
                        self.is_choosing_action
                        or self.is_choosing_lang
                    )
                    else QRect()
                )

            if (
                not current_rect.isNull()
                and current_rect.width() > 0
                and current_rect.height() > 0
            ):
                painter.save()

                painter.setCompositionMode(
                    QPainter.CompositionMode.CompositionMode_Difference
                )

                painter.setBrush(
                    Qt.BrushStyle.NoBrush
                )

                painter.setPen(
                    QPen(
                        QColor(
                            255,
                            255,
                            255
                        ),
                        2,
                        Qt.PenStyle.SolidLine
                    )
                )

                painter.drawRect(
                    current_rect
                )

                painter.restore()

            # -------------------------------------------------
            # ACTION BUTTONS
            # -------------------------------------------------

            if self.is_choosing_action:
                painter.setFont(
                    QFont(
                        "Segoe UI",
                        13,
                        QFont.Weight.Bold
                    )
                )

                # Question
                painter.setBrush(
                    QColor(
                        52,
                        152,
                        219,
                        230
                    )
                )

                painter.setPen(
                    Qt.PenStyle.NoPen
                )

                painter.drawRoundedRect(
                    self.btn_question_rect,
                    6,
                    6
                )

                painter.setPen(
                    QColor(
                        255,
                        255,
                        255
                    )
                )

                painter.drawText(
                    self.btn_question_rect,
                    Qt.AlignmentFlag.AlignCenter,
                    "?"
                )

                # Term
                painter.setBrush(
                    QColor(
                        241,
                        196,
                        15,
                        230
                    )
                )

                painter.setPen(
                    Qt.PenStyle.NoPen
                )

                painter.drawRoundedRect(
                    self.btn_term_rect,
                    6,
                    6
                )

                painter.setPen(
                    QColor(
                        255,
                        255,
                        255
                    )
                )

                painter.drawText(
                    self.btn_term_rect,
                    Qt.AlignmentFlag.AlignCenter,
                    "#"
                )

                # Translation
                painter.setBrush(
                    QColor(
                        80,
                        255,
                        80,
                        230
                    )
                )

                painter.setPen(
                    Qt.PenStyle.NoPen
                )

                painter.drawRoundedRect(
                    self.btn_translate_rect,
                    6,
                    6
                )

                painter.setPen(
                    QColor(
                        255,
                        255,
                        255
                    )
                )

                painter.drawText(
                    self.btn_translate_rect,
                    Qt.AlignmentFlag.AlignCenter,
                    "T"
                )

                # Gaming
                painter.setBrush(
                    QColor(
                        220,
                        40,
                        40,
                        240
                    )
                )

                painter.setPen(
                    Qt.PenStyle.NoPen
                )

                painter.drawRoundedRect(
                    self.btn_gaming_rect,
                    6,
                    6
                )

                # Белый геймпад
                painter.setBrush(
                    QColor(
                        255,
                        255,
                        255
                    )
                )

                painter.setPen(
                    Qt.PenStyle.NoPen
                )

                gamepad = self.btn_gaming_rect.adjusted(
                    7,
                    10,
                    -7,
                    -10
                )

                painter.drawRoundedRect(
                    gamepad,
                    8,
                    8
                )

                left_handle = QPolygon([
                    QPoint(
                        gamepad.left(),
                        gamepad.top() + 7
                    ),
                    QPoint(
                        gamepad.left() - 2,
                        gamepad.bottom() - 2
                    ),
                    QPoint(
                        gamepad.left() + 6,
                        gamepad.bottom()
                    ),
                    QPoint(
                        gamepad.left() + 10,
                        gamepad.top() + 5
                    )
                ])

                right_handle = QPolygon([
                    QPoint(
                        gamepad.right(),
                        gamepad.top() + 7
                    ),
                    QPoint(
                        gamepad.right() + 2,
                        gamepad.bottom() - 2
                    ),
                    QPoint(
                        gamepad.right() - 6,
                        gamepad.bottom()
                    ),
                    QPoint(
                        gamepad.right() - 10,
                        gamepad.top() + 5
                    )
                ])

                painter.drawPolygon(
                    left_handle
                )

                painter.drawPolygon(
                    right_handle
                )

                painter.setBrush(
                    QColor(
                        220,
                        40,
                        40
                    )
                )

                center_x = (
                    gamepad.center().x()
                )

                center_y = (
                    gamepad.center().y()
                )

                painter.drawRect(
                    center_x - 7,
                    center_y - 2,
                    14,
                    4
                )

                painter.drawRect(
                    center_x - 2,
                    center_y - 7,
                    4,
                    14
                )

                painter.drawEllipse(
                    gamepad.right() - 12,
                    gamepad.center().y() - 5,
                    4,
                    4
                )

                painter.drawEllipse(
                    gamepad.right() - 6,
                    gamepad.center().y() - 9,
                    4,
                    4
                )

    # =========================================================
    # NORMAL RESULT ITEM
    # =========================================================

    def draw_result_item(
        self,
        painter: QPainter,
        item: SelectionItem,
        draw_snapshot: bool = True
    ):
        if item.category == "question":
            theme_color = QColor(
                52,
                152,
                219
            )

        elif item.category == "term":
            theme_color = QColor(
                241,
                196,
                15
            )

        else:
            theme_color = QColor(
                80,
                255,
                80
            )

        if (
            draw_snapshot
            and not item.snapshot.isNull()
        ):
            painter.drawPixmap(
                item.rect.topLeft(),
                item.snapshot
            )

        painter.setBrush(
            Qt.BrushStyle.NoBrush
        )

        painter.setPen(
            QPen(
                theme_color,
                3,
                Qt.PenStyle.DashLine
            )
        )

        painter.drawRect(
            item.rect
        )

        painter.setBrush(
            QColor(
                30,
                30,
                30,
                245
            )
        )

        painter.setPen(
            QPen(
                theme_color,
                1
            )
        )

        painter.drawRoundedRect(
            item.answer_rect,
            10,
            10
        )

        c1 = item.rect.center()

        c2 = item.answer_rect.center()

        frame_start_point = (
            self.get_rect_intersection_point(
                item.rect,
                c2
            )
        )

        frame_end_point = (
            self.get_rect_intersection_point(
                item.answer_rect,
                c1
            )
        )

        line_pen = QPen(
            theme_color,
            2,
            Qt.PenStyle.DotLine
        )

        painter.setPen(
            line_pen
        )

        painter.drawLine(
            frame_start_point,
            frame_end_point
        )

        if item.is_loading:
            loader_rect = QRect(
                item.answer_rect.center().x() - 20,
                item.answer_rect.center().y() - 20,
                40,
                40
            )

            painter.setPen(
                QPen(
                    theme_color,
                    4,
                    Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap
                )
            )

            painter.setBrush(
                Qt.BrushStyle.NoBrush
            )

            painter.drawArc(
                loader_rect,
                self.angle * 16,
                270 * 16
            )

        else:
            painter.setPen(
                QColor(
                    255,
                    255,
                    255
                )
            )

            painter.setFont(
                QFont(
                    "Segoe UI",
                    11
                )
            )

            painter.drawText(
                item.answer_rect.adjusted(
                    15,
                    15,
                    -20,
                    -20
                ),
                Qt.TextFlag.TextWordWrap,
                item.answer
            )

    # =========================================================
    # START GAMING MODE
    # =========================================================

    def start_gaming_mode(
        self,
        target_lang="русский",
        from_lang="auto"
    ):
        if self.current_target_rect.isNull():
            return

        self.is_choosing_action = False

        self.is_choosing_lang = False

        self.lang_panel.hide()

        self.is_gaming_mode = True

        self.history_items.clear()

        self.gaming_translation = ""

        self.gaming_translation_loading = False

        self.setCursor(
            Qt.CursorShape.ArrowCursor
        )

        gaming_rect = QRect(
            self.current_target_rect
        )

        self.gaming_rect = QRect(
            gaming_rect
        )

        self.screen_pixmap = QPixmap()

        self.clearMask()

        # -----------------------------------------------------
        # СНАЧАЛА создаём/показываем реальное top-level окно.
        # -----------------------------------------------------

        self.showMaximized()

        self.raise_()

        # -----------------------------------------------------
        # Весь Overlay пропускает мышь.
        # -----------------------------------------------------

        self.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents,
            True
        )

        # -----------------------------------------------------
        # ВАЖНО:
        # Передаём именно этот AIOverlay в менеджер.
        # Менеджер использует его HWND для
        # SetWindowDisplayAffinity.
        # -----------------------------------------------------

        self.gaming_manager.set_overlay_window(
            self
        )

        # -----------------------------------------------------
        # Запускаем OCR.
        # Защита capture будет установлена внутри start()
        # ДО первого capture_and_ocr().
        # -----------------------------------------------------

        self.gaming_manager.start(
            self.gaming_rect,
            target_lang,
            from_lang
        )

        self.update()

        self.repaint()

    # =========================================================
    # DRAW GAMING MODE
    # =========================================================

    def draw_gaming_mode(
        self,
        painter
    ):
        rect = self.gaming_rect

        if (
            rect.isNull()
            or rect.width() <= 0
            or rect.height() <= 0
        ):
            return

        painter.save()

        painter.setCompositionMode(
            QPainter.CompositionMode.CompositionMode_SourceOver
        )

        # -----------------------------------------------------
        # Затемнение игровой области
        # -----------------------------------------------------

        painter.setPen(
            Qt.PenStyle.NoPen
        )

        painter.setBrush(
            QColor(
                15,
                15,
                15,
                200
            )
        )

        painter.fillRect(
            rect,
            painter.brush()
        )

        # -----------------------------------------------------
        # Красная рамка
        # -----------------------------------------------------

        painter.setBrush(
            Qt.BrushStyle.NoBrush
        )

        painter.setPen(
            QPen(
                QColor(
                    220,
                    40,
                    40
                ),
                3,
                Qt.PenStyle.SolidLine
            )
        )

        painter.drawRect(
            rect.adjusted(
                1,
                1,
                -1,
                -1
            )
        )

        # -----------------------------------------------------
        # ПЕРЕВОД
        # -----------------------------------------------------

        if self.gaming_translation:
            text = self.gaming_translation.strip()

            padding_x = min(
                25,
                max(
                    5,
                    rect.width() // 20
                )
            )

            padding_y = min(
                25,
                max(
                    3,
                    rect.height() // 10
                )
            )

            text_rect = rect.adjusted(
                padding_x,
                padding_y,
                -padding_x,
                -padding_y
            )

            min_font_size = 6

            max_font_size = 32

            best_font = QFont(
                "Segoe UI",
                min_font_size,
                QFont.Weight.Bold
            )

            low = min_font_size

            high = max_font_size

            while low <= high:
                font_size = (
                    low + high
                ) // 2

                test_font = QFont(
                    "Segoe UI",
                    font_size,
                    QFont.Weight.Bold
                )

                metrics = QFontMetrics(
                    test_font
                )

                bounding_rect = (
                    metrics.boundingRect(
                        text_rect,
                        Qt.TextFlag.TextWordWrap,
                        text
                    )
                )

                fits_width = (
                    bounding_rect.width()
                    <= text_rect.width()
                )

                fits_height = (
                    bounding_rect.height()
                    <= text_rect.height()
                )

                if fits_width and fits_height:
                    best_font = test_font

                    low = font_size + 1

                else:
                    high = font_size - 1

            painter.setFont(
                best_font
            )

            painter.setPen(
                QColor(
                    255,
                    255,
                    255
                )
            )

            painter.drawText(
                text_rect,
                Qt.AlignmentFlag.AlignCenter
                | Qt.TextFlag.TextWordWrap,
                text
            )

        # -----------------------------------------------------
        # ЗАГРУЗКА
        # -----------------------------------------------------

        if self.gaming_translation_loading:
            loader_size = 42

            loader_rect = QRect(
                rect.center().x()
                - loader_size // 2,
                rect.center().y()
                - loader_size // 2,
                loader_size,
                loader_size
            )

            painter.setBrush(
                Qt.BrushStyle.NoBrush
            )

            painter.setPen(
                QPen(
                    QColor(
                        220,
                        40,
                        40
                    ),
                    4,
                    Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap
                )
            )

            painter.drawArc(
                loader_rect,
                self.angle * 16,
                270 * 16
            )

        painter.restore()


if __name__ == "__main__":
    app = QApplication(
        sys.argv
    )

    app.setQuitOnLastWindowClosed(
        False
    )

    overlay = AIOverlay()

    tray = TrayManager(
        overlay
    )

    signal.signal(
        signal.SIGINT,
        lambda signum, frame:
            tray.exit_application()
    )

    print(
        f"[System] Ассистент запущен. "
        f"Провайдер: {config.PROVIDER} | "
        f"Модель: {config.MODEL_NAME}"
    )

    print(
        f"[System] Нажми {config.HOTKEY} "
        f"для выделения. "
        f"Для очистки экрана нажми Esc."
    )

    sys.exit(
        app.exec()
    )