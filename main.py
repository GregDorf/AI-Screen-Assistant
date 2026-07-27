import sys
import ctypes
import math
import keyboard
from PyQt6.QtWidgets import QApplication, QWidget, QComboBox, QLabel, QVBoxLayout, QPushButton
from PyQt6.QtCore import Qt, QRect, QPoint, pyqtSignal, QObject, QBuffer, QIODevice, QTimer, QEvent
from PyQt6.QtGui import QPainter, QPen, QColor, QScreen, QPixmap, QFont, QRegion, QPolygon

import config
from processor import AIWorker


class HotkeySignal(QObject):
    triggered = pyqtSignal()


class EscSignal(QObject):
    triggered = pyqtSignal()


class SelectionItem:
    def __init__(self, rect: QRect, category: str, answer_rect: QRect, snapshot: QPixmap):
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
        # Включаем настоящую прозрачность фона окна на уровне ОС
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        
        #self.hwnd = None
        #if sys.platform == "win32":
        #    try:
        #        self.hwnd = int(self.winId())
        #        ctypes.windll.user32.SetWindowDisplayAffinity(self.hwnd, 0x00000011)
        #    except Exception as e:
        #        print(f"[System Warning] Не удалось установить защиту от захвата окна: {e}")

        self.is_selecting = False
        self.is_choosing_action = False
        self.is_choosing_lang = False
        self.is_capturing = False
        
        self.start_pos = QPoint()
        self.end_pos = QPoint()
        self.screen_pixmap = QPixmap()
        
        self.current_target_rect = QRect()
        self.btn_question_rect = QRect()
        self.btn_term_rect = QRect()
        self.btn_translate_rect = QRect()
        
        self.lang_panel = QWidget(self)
        self.lang_panel.hide()
        
        panel_layout = QVBoxLayout(self.lang_panel)
        panel_layout.setContentsMargins(8, 8, 8, 8)
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
        
        lbl_from = QLabel("Исходный язык:", self.lang_panel)
        lbl_from.setStyleSheet(label_style)
        panel_layout.addWidget(lbl_from)
        
        self.combo_from_lang = QComboBox(self.lang_panel)
        self.combo_from_lang.setStyleSheet(combo_style)
        self.combo_from_lang.installEventFilter(self)
        panel_layout.addWidget(self.combo_from_lang)
        
        lbl_to = QLabel("Перевести на:", self.lang_panel)
        lbl_to.setStyleSheet(label_style)
        panel_layout.addWidget(lbl_to)
        
        self.combo_to_lang = QComboBox(self.lang_panel)
        self.combo_to_lang.setStyleSheet(combo_style)
        self.combo_to_lang.installEventFilter(self)
        panel_layout.addWidget(self.combo_to_lang)
        
        self.btn_confirm_translate = QPushButton("OK", self.lang_panel)
        self.btn_confirm_translate.setStyleSheet("""
            QPushButton {
                background-color: #50ff50;
                color: #1e1e1e;
                border-radius: 6px;
                font-family: 'Segoe UI';
                font-size: 11px;
                font-weight: bold;
                padding: 5px;
            }
            QPushButton:hover {
                background-color: #40e040;
            }
        """)
        self.btn_confirm_translate.installEventFilter(self)
        self.btn_confirm_translate.clicked.connect(self.on_confirm_translation)
        panel_layout.addWidget(self.btn_confirm_translate)
        
        self.lang_panel.setStyleSheet("""
            QWidget {
                background-color: rgba(20, 20, 20, 240);
                border: 1px solid #50ff50;
                border-radius: 8px;
            }
        """)
        self.lang_panel.installEventFilter(self)
        
        self.populate_languages()
        
        self.history_items = []
        self.active_category = "question" 
        self.workers = []
        
        self.dragging_item = None
        self.resizing_item = None
        self.drag_offset = QPoint()
        
        self.angle = 0
        self.anim_timer = QTimer(self)
        self.anim_timer.timeout.connect(self.update_animation)
        self.anim_timer.start(16)
        
        self.hotkey_signal = HotkeySignal()
        self.hotkey_signal.triggered.connect(self.start_capture)
        keyboard.add_hotkey(config.HOTKEY, self.hotkey_signal.triggered.emit)

        self.esc_signal = EscSignal()
        self.esc_signal.triggered.connect(self.reset_all)
        keyboard.add_hotkey('esc', self.esc_signal.triggered.emit)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
            self.reset_all()
            return True
        return super().eventFilter(obj, event)

    def populate_languages(self):
        languages = [
            ("Русский", "русский"), ("Английский", "английский"), ("Испанский", "испанский"),
            ("Немецкий", "немецкий"), ("Французский", "французский"), ("Итальянский", "итальянский"),
            ("Китайский", "китайский"), ("Японский", "японский"), ("Корейский", "корейский"),
            ("Португальский", "португальский"), ("Турецкий", "турецкий"), ("Польский", "польский"),
            ("Украинский", "украинский")
        ]
        
        self.combo_from_lang.addItem("Автоопределение", "auto")
        for name, code in languages:
            self.combo_from_lang.addItem(name, code)
            self.combo_to_lang.addItem(name, code)
            
        self.combo_to_lang.setCurrentIndex(0)

    def update_animation(self):
        if any(item.is_loading for item in self.history_items):
            self.angle = (self.angle + 10) % 360
            for item in self.history_items:
                if item.is_loading:
                    loader_rect = QRect(
                        item.answer_rect.center().x() - 25,
                        item.answer_rect.center().y() - 25,
                        50, 50
                    )
                    self.update(loader_rect)

    def update_interaction_mask(self):
        """
        Динамически пересчитывает маску окна.
        Если мы выбираем область - окно получает клики по всему экрану.
        Если нет - окно прозрачно для кликов везде, кроме самих плашек истории.
        """
        if self.is_selecting or self.is_choosing_action or self.is_choosing_lang:
            self.clearMask()
        else:
            if not self.history_items:
                self.hide()
                return
                
            region = QRegion()
            for item in self.history_items:
                # Добавляем рамку выделения и плашку с ответом в "твердую" зону
                region = region.united(QRegion(item.rect.adjusted(-5, -5, 5, 5)))
                region = region.united(QRegion(item.answer_rect.adjusted(-5, -5, 5, 5)))
                
                # Добавляем соединительную линию в маску (чтобы её не обрезало)
                c1 = item.rect.center()
                c2 = item.answer_rect.center()
                p1 = self.get_rect_intersection_point(item.rect, c2)
                p2 = self.get_rect_intersection_point(item.answer_rect, c1)
                
                dx = p2.x() - p1.x()
                dy = p2.y() - p1.y()
                length = math.hypot(dx, dy)
                if length > 0:
                    nx = int(dy / length * 6)
                    ny = int(-dx / length * 6)
                    poly = QPolygon([
                        QPoint(p1.x() + nx, p1.y() + ny),
                        QPoint(p1.x() - nx, p1.y() - ny),
                        QPoint(p2.x() - nx, p2.y() - ny),
                        QPoint(p2.x() + nx, p2.y() + ny),
                    ])
                    region = region.united(QRegion(poly))
                    
            self.setMask(region)

    def start_capture(self):
        if self.is_selecting or self.is_choosing_action or self.is_choosing_lang or self.is_capturing:
            return

        self.is_capturing = True
        self.lang_panel.hide()
        self.hide()
        QApplication.processEvents()
        
        QTimer.singleShot(150, self._perform_capture)

    def _perform_capture(self):
        screen = QApplication.primaryScreen()
        self.screen_pixmap = screen.grabWindow(0)

        self.setGeometry(screen.geometry())
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        
        self.is_selecting = True
        self.is_choosing_action = False
        self.is_choosing_lang = False

        self.clearMask()  # Очищаем маску для полноэкранного выделения
        self.showMaximized()
        self.raise_()
        self.activateWindow()
        self.setCursor(Qt.CursorShape.CrossCursor)
        
        self.is_capturing = False
        self.repaint()

    def reset_all(self):
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
        self.is_capturing = False
        self.lang_panel.hide()
        
        self.clearMask()
        self.hide()
        self.update()

    def mousePressEvent(self, event):
        pos = event.pos()

        if not self.is_selecting and not self.is_choosing_action and not self.is_choosing_lang:
            for item in self.history_items:
                resize_handle = QRect(item.answer_rect.right() - 15, item.answer_rect.bottom() - 15, 15, 15)
                if resize_handle.contains(pos):
                    self.resizing_item = item
                    return
                elif item.answer_rect.contains(pos):
                    self.dragging_item = item
                    self.drag_offset = pos - item.answer_rect.topLeft()
                    return

        if self.is_selecting and event.button() == Qt.MouseButton.LeftButton:
            self.start_pos = pos
            self.end_pos = self.start_pos
            self.update()
            
        elif self.is_choosing_action and event.button() == Qt.MouseButton.LeftButton:
            if self.btn_question_rect.contains(pos):
                self.start_processing("question")
            elif self.btn_term_rect.contains(pos):
                self.start_processing("term")
            elif self.btn_translate_rect.contains(pos):
                self.setup_language_panel()
            else:
                self.is_choosing_action = False
                self.lang_panel.hide()
                self.update_interaction_mask()  # Переходим в режим плавающих виджетов
                self.update()

    def mouseMoveEvent(self, event):
        pos = event.pos()

        if self.dragging_item:
            self.dragging_item.answer_rect.moveTo(pos - self.drag_offset)
            self.update_interaction_mask()  # Обновляем маску при движении
            self.update()
            return

        if self.resizing_item:
            new_w = max(200, pos.x() - self.resizing_item.answer_rect.left())
            new_h = max(100, pos.y() - self.resizing_item.answer_rect.top())
            self.resizing_item.answer_rect.setWidth(new_w)
            self.resizing_item.answer_rect.setHeight(new_h)
            self.update_interaction_mask()  # Обновляем маску при ресайзе
            self.update()
            return

        if self.is_selecting and bool(event.buttons() & Qt.MouseButton.LeftButton):
            self.end_pos = pos
            self.update()
        elif self.is_choosing_action:
            if (self.btn_question_rect.contains(pos) or 
                self.btn_term_rect.contains(pos) or 
                self.btn_translate_rect.contains(pos)):
                self.setCursor(Qt.CursorShape.PointingHandCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)
        elif not self.is_selecting and not self.is_choosing_lang:
            on_handle = False
            for item in self.history_items:
                handle = QRect(item.answer_rect.right() - 15, item.answer_rect.bottom() - 15, 15, 15)
                if handle.contains(pos):
                    on_handle = True
                    break
            if on_handle:
                self.setCursor(Qt.CursorShape.SizeFDiagCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)

    def mouseReleaseEvent(self, event):
        self.dragging_item = None
        self.resizing_item = None

        if self.is_selecting and event.button() == Qt.MouseButton.LeftButton:
            self.is_selecting = False
            self.current_target_rect = QRect(self.start_pos, self.end_pos).normalized()
            
            if self.current_target_rect.width() > 10 and self.current_target_rect.height() > 10:
                self.setup_action_buttons()
            else:
                self.is_choosing_action = False
                self.is_choosing_lang = False
                self.lang_panel.hide()
                self.update_interaction_mask()
                self.update()

    def setup_action_buttons(self):
        self.is_choosing_action = True
        self.is_choosing_lang = False
        self.lang_panel.hide()
        self.setCursor(Qt.CursorShape.ArrowCursor)
        
        btn_size = 36
        spacing = 8
        total_width = (btn_size * 3) + (spacing * 2)
        
        base_x = self.current_target_rect.right() - total_width
        base_y = self.current_target_rect.bottom() + 10
        
        if base_y + btn_size > self.height():
            base_y = self.current_target_rect.top() - btn_size - 10
            
        if base_x < 0:
            base_x = self.current_target_rect.left()

        self.btn_question_rect = QRect(base_x, base_y, btn_size, btn_size)
        self.btn_term_rect = QRect(base_x + btn_size + spacing, base_y, btn_size, btn_size)
        self.btn_translate_rect = QRect(base_x + (btn_size + spacing) * 2, base_y, btn_size, btn_size)
        self.update()

    def setup_language_panel(self):
        self.is_choosing_action = False
        self.is_choosing_lang = True
        self.setCursor(Qt.CursorShape.ArrowCursor)
        
        panel_width = 200
        panel_height = 160
        
        base_x = self.current_target_rect.right() - panel_width
        base_y = self.current_target_rect.bottom() + 55
        
        if base_y + panel_height > self.height():
            base_y = self.current_target_rect.top() - panel_height - 10
            
        if base_x < 0:
            base_x = self.current_target_rect.left()

        self.lang_panel.setGeometry(base_x, base_y, panel_width, panel_height)
        self.lang_panel.show()
        self.lang_panel.raise_()
        self.lang_panel.activateWindow()

    def on_confirm_translation(self):
        from_lang = self.combo_from_lang.currentData()
        target_lang = self.combo_to_lang.currentData()
        self.lang_panel.hide()
        self.start_processing("translation", target_lang, from_lang)

    def start_processing(self, action: str, target_lang: str = "русский", from_lang: str = "auto"):
        self.is_choosing_action = False
        self.is_choosing_lang = False
        self.lang_panel.hide()
        self.active_category = action
        self.setCursor(Qt.CursorShape.ArrowCursor)
        
        box_width, box_height = 400, 180
        box_x = self.current_target_rect.right() + 40
        box_y = self.current_target_rect.top()
        if box_x + box_width > self.width():
            box_x = self.current_target_rect.left() - box_width - 40
        
        initial_answer_rect = QRect(box_x, box_y, box_width, box_height)
        
        cropped = self.screen_pixmap.copy(self.current_target_rect)
        
        item = SelectionItem(self.current_target_rect, action, initial_answer_rect, cropped)
        self.history_items.append(item)
        
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.ReadWrite)
        cropped.save(buffer, "PNG")
        
        image_bytes_data = bytes(buffer.data())
        worker = AIWorker(image_bytes_data, action, target_lang, from_lang)
        self.workers.append(worker)
        
        def handle_response(answer: str):
            item.answer = answer
            item.is_loading = False
            self.update(item.answer_rect)
            if worker in self.workers:
                self.workers.remove(worker)
            worker.deleteLater()
            
        worker.finished.connect(handle_response)
        worker.start()
        
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        
        # ВАЖНО: Активируем маску, чтобы остальной экран "ожил"
        self.update_interaction_mask()
        
        self.showMaximized()
        self.repaint()

    def get_rect_intersection_point(self, rect: QRect, target_pt: QPoint) -> QPoint:
        center = rect.center()
        cx, cy = center.x(), center.y()
        tx, ty = target_pt.x(), target_pt.y()
        
        dx = tx - cx
        dy = ty - cy
        if dx == 0 and dy == 0:
            return center
            
        left = rect.left() - 2
        right = rect.right() + 2
        top = rect.top() - 2
        bottom = rect.bottom() + 2
        
        best_pt = center
        min_t = float('inf')
        
        if dx != 0:
            t = (left - cx) / dx
            if t > 0:
                y = cy + t * dy
                if top <= y <= bottom and t < min_t:
                    min_t, best_pt = t, QPoint(int(left), int(y))
        if dx != 0:
            t = (right - cx) / dx
            if t > 0:
                y = cy + t * dy
                if top <= y <= bottom and t < min_t:
                    min_t, best_pt = t, QPoint(int(right), int(y))
        if dy != 0:
            t = (top - cy) / dy
            if t > 0:
                x = cx + t * dx
                if left <= x <= right and t < min_t:
                    min_t, best_pt = t, QPoint(int(x), int(top))
        if dy != 0:
            t = (bottom - cy) / dy
            if t > 0:
                x = cx + t * dx
                if left <= x <= right and t < min_t:
                    min_t, best_pt = t, QPoint(int(x), int(bottom))
                        
        return best_pt

    def paintEvent(self, event):
        if getattr(self, 'is_capturing', False):
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Рисуем скриншот ТОЛЬКО если пользователь активно выбирает область
        if self.is_selecting or self.is_choosing_action or self.is_choosing_lang:
            painter.fillRect(self.rect(), Qt.GlobalColor.black)
            if not self.screen_pixmap.isNull():
                painter.drawPixmap(0, 0, self.screen_pixmap)
        else:
            # В "плавающем" режиме фон прозрачный, чтобы был виден живой рабочий стол
            painter.fillRect(self.rect(), Qt.GlobalColor.transparent)

        for item in self.history_items:
            self.draw_result_item(painter, item, draw_snapshot=True)

        if self.is_selecting or self.is_choosing_action or self.is_choosing_lang:
            painter.setBrush(Qt.BrushStyle.NoBrush)

            if self.is_selecting:
                current_rect = QRect(self.start_pos, self.end_pos).normalized()
                painter.save()
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Difference)
                painter.setPen(QPen(QColor(255, 255, 255), 2, Qt.PenStyle.SolidLine))
                painter.drawRect(current_rect)
                painter.restore()
            else:
                current_rect = self.current_target_rect if (self.is_choosing_action or self.is_choosing_lang) else QRect()
                painter.setPen(QPen(QColor(255, 255, 255), 2, Qt.PenStyle.SolidLine))
                painter.drawRect(current_rect)

            if self.is_choosing_action:
                painter.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
                
                painter.setBrush(QColor(52, 152, 219, 230))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawRoundedRect(self.btn_question_rect, 6, 6)
                painter.setPen(QColor(255, 255, 255))
                painter.drawText(self.btn_question_rect, Qt.AlignmentFlag.AlignCenter, "?")
                
                painter.setBrush(QColor(241, 196, 15, 230))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawRoundedRect(self.btn_term_rect, 6, 6)
                painter.setPen(QColor(255, 255, 255))
                painter.drawText(self.btn_term_rect, Qt.AlignmentFlag.AlignCenter, "#")

                painter.setBrush(QColor(80, 255, 80, 230))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawRoundedRect(self.btn_translate_rect, 6, 6)
                painter.setPen(QColor(255, 255, 255))
                painter.drawText(self.btn_translate_rect, Qt.AlignmentFlag.AlignCenter, "T")

    def draw_result_item(self, painter: QPainter, item: SelectionItem, draw_snapshot: bool = True):
        if item.category == "question":
            theme_color = QColor(52, 152, 219)
        elif item.category == "term":
            theme_color = QColor(241, 196, 15)
        else:
            theme_color = QColor(80, 255, 80)
        
        if draw_snapshot and not item.snapshot.isNull():
            painter.drawPixmap(item.rect.topLeft(), item.snapshot)
        
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(theme_color, 3, Qt.PenStyle.DashLine))
        painter.drawRect(item.rect)
        
        painter.setBrush(QColor(30, 30, 30, 245))
        painter.setPen(QPen(theme_color, 1))
        painter.drawRoundedRect(item.answer_rect, 10, 10)
        
        c1 = item.rect.center()
        c2 = item.answer_rect.center()
        
        frame_start_point = self.get_rect_intersection_point(item.rect, c2)
        frame_end_point = self.get_rect_intersection_point(item.answer_rect, c1)
        
        line_pen = QPen(theme_color, 2, Qt.PenStyle.DotLine)
        painter.setPen(line_pen)
        painter.drawLine(frame_start_point, frame_end_point)
        
        if item.is_loading:
            loader_rect = QRect(
                item.answer_rect.center().x() - 20,
                item.answer_rect.center().y() - 20,
                40, 40
            )
            painter.setPen(QPen(theme_color, 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawArc(loader_rect, self.angle * 16, 270 * 16)
        else:
            painter.setPen(QColor(255, 255, 255))
            painter.setFont(QFont("Segoe UI", 11))
            painter.drawText(item.answer_rect.adjusted(15, 15, -20, -20), Qt.TextFlag.TextWordWrap, item.answer)


if __name__ == '__main__':
    app = QApplication(sys.argv)
    overlay = AIOverlay()
    print(f"[System] Ассистент запущен. Провайдер: {config.PROVIDER} | Модель: {config.MODEL_NAME}")
    print(f"[System] Нажми {config.HOTKEY} для выделения. Для очистки экрана нажми Esc.")
    sys.exit(app.exec())