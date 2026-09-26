import os
import sys
import winreg

from PyQt6.QtCore import QObject
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor
from PyQt6.QtWidgets import (
    QSystemTrayIcon,
    QMenu,
    QApplication
)


APP_NAME = "AI Screen Assistant"
REGISTRY_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


class TrayManager(QObject):
    def __init__(self, overlay):
        super().__init__()

        self.overlay = overlay
        self.app = QApplication.instance()

        self.tray = QSystemTrayIcon(self.app)
        self.tray.setIcon(self.create_icon())
        self.tray.setToolTip(APP_NAME)

        self.menu = QMenu()

        # Заголовок
        title_action = self.menu.addAction(APP_NAME)
        title_action.setEnabled(False)

        self.menu.addSeparator()

        # Показать/скрыть
        self.show_action = self.menu.addAction("Показать")
        self.show_action.triggered.connect(self.show_overlay)

        self.hide_action = self.menu.addAction("Скрыть")
        self.hide_action.triggered.connect(self.hide_overlay)

        self.menu.addSeparator()

        # Автозапуск
        self.autostart_action = self.menu.addAction("Запускать вместе с Windows")
        self.autostart_action.setCheckable(True)
        self.autostart_action.setChecked(self.is_autostart_enabled())
        self.autostart_action.triggered.connect(self.toggle_autostart)

        self.menu.addSeparator()

        # Выход
        exit_action = self.menu.addAction("Выход")
        exit_action.triggered.connect(self.exit_application)

        self.tray.setContextMenu(self.menu)

        # Двойной клик по значку
        self.tray.activated.connect(self.on_tray_activated)

        self.tray.show()

    def create_icon(self):
        """
        Создает простую иконку программно.
        Поэтому отдельный .ico файл для работы трея не обязателен.
        """

        pixmap = QPixmap(64, 64)
        pixmap.fill(QColor(30, 30, 30))

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        painter.setPen(QColor(80, 255, 80))
        painter.setBrush(QColor(80, 255, 80))

        # Простая иконка "AI"
        painter.drawEllipse(8, 8, 48, 48)

        painter.setPen(QColor(30, 30, 30))
        painter.drawText(
            pixmap.rect(),
            0x84,  # AlignCenter
            "AI"
        )

        painter.end()

        return QIcon(pixmap)

    # ---------------------------------------------------------
    # ОКНО
    # ---------------------------------------------------------

    def show_overlay(self):
        self.overlay.show()
        self.overlay.raise_()
        self.overlay.activateWindow()

    def hide_overlay(self):
        self.overlay.hide()

    # ---------------------------------------------------------
    # ТРЕЙ
    # ---------------------------------------------------------

    def on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            if self.overlay.isVisible():
                self.hide_overlay()
            else:
                self.show_overlay()

    # ---------------------------------------------------------
    # АВТОЗАПУСК WINDOWS
    # ---------------------------------------------------------

    def get_executable_command(self):
        """
        Возвращает команду, которую Windows должна выполнить.

        Для PyInstaller:
            C:/Program/MyAssistant/MyAssistant.exe

        Для запуска из Python:
            python main.py
        """

        if getattr(sys, "frozen", False):
            # Мы запущены как .exe
            return f'"{sys.executable}"'

        # Работа из исходников
        script_path = os.path.abspath(sys.argv[0])

        return f'"{sys.executable}" "{script_path}"'

    def is_autostart_enabled(self):
        """
        Проверяет наличие программы в реестре Windows.
        """

        if sys.platform != "win32":
            return False

        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                REGISTRY_KEY,
                0,
                winreg.KEY_READ
            ) as key:

                try:
                    value, _ = winreg.QueryValueEx(key, APP_NAME)

                    return bool(value)

                except FileNotFoundError:
                    return False

        except Exception as e:
            print(f"[Tray] Ошибка проверки автозапуска: {e}")
            return False

    def enable_autostart(self):
        """
        Добавляет программу в автозагрузку Windows.
        """

        if sys.platform != "win32":
            return False

        try:
            command = self.get_executable_command()

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                REGISTRY_KEY,
                0,
                winreg.KEY_SET_VALUE
            ) as key:

                winreg.SetValueEx(
                    key,
                    APP_NAME,
                    0,
                    winreg.REG_SZ,
                    command
                )

            print(f"[Tray] Автозапуск включен: {command}")

            return True

        except Exception as e:
            print(f"[Tray] Не удалось включить автозапуск: {e}")
            return False

    def disable_autostart(self):
        """
        Удаляет программу из автозагрузки Windows.
        """

        if sys.platform != "win32":
            return False

        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                REGISTRY_KEY,
                0,
                winreg.KEY_SET_VALUE
            ) as key:

                try:
                    winreg.DeleteValue(key, APP_NAME)
                except FileNotFoundError:
                    pass

            print("[Tray] Автозапуск отключен.")

            return True

        except Exception as e:
            print(f"[Tray] Не удалось отключить автозапуск: {e}")
            return False

    def toggle_autostart(self, checked):
        if checked:
            success = self.enable_autostart()

            if not success:
                self.autostart_action.setChecked(False)

        else:
            success = self.disable_autostart()

            if not success:
                self.autostart_action.setChecked(True)

    # ---------------------------------------------------------
    # ВЫХОД
    # ---------------------------------------------------------

    def exit_application(self):
        """
        Полностью завершает приложение.
        """

        self.tray.hide()

        # Останавливаем приложение через существующий reset_all()
        try:
            self.overlay.reset_all()
        except Exception as e:
            print(f"[Tray] Ошибка очистки overlay: {e}")

        QApplication.quit()