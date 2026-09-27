import os
import sys
import winreg
import ctypes

from PyQt6.QtCore import QObject
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor
from PyQt6.QtWidgets import (
    QSystemTrayIcon,
    QMenu,
    QApplication
)

SW_HIDE = 0
SW_RESTORE = 9

GWL_EXSTYLE = -20
WS_EX_APPWINDOW = 0x00040000
WS_EX_TOOLWINDOW = 0x00000080

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32 = ctypes.WinDLL("user32", use_last_error=True)


APP_NAME = "AI Screen Assistant"
REGISTRY_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


class TrayManager(QObject):

    def __init__(self, overlay):
        super().__init__()

        self.overlay = overlay
        self.app = QApplication.instance()

        # -----------------------------------------------------
        # CONSOLE
        # -----------------------------------------------------

        self.console_hwnd = None

        self.setup_console()

        # -----------------------------------------------------
        # TRAY
        # -----------------------------------------------------

        self.tray = QSystemTrayIcon(self.app)

        self.tray.setIcon(
            QIcon("logo.ico")
        )

        self.tray.setToolTip(
            APP_NAME
        )

        self.menu = QMenu()

        # Заголовок
        title_action = self.menu.addAction(
            APP_NAME
        )

        title_action.setEnabled(
            False
        )

        self.menu.addSeparator()

        # -----------------------------------------------------
        # CONSOLE CONTROLS
        # -----------------------------------------------------

        self.show_console_action = (
            self.menu.addAction(
                "Показать консоль"
            )
        )

        self.show_console_action.triggered.connect(
            self.show_console
        )

        self.hide_console_action = (
            self.menu.addAction(
                "Скрыть консоль"
            )
        )

        self.hide_console_action.triggered.connect(
            self.hide_console
        )

        self.menu.addSeparator()

        # -----------------------------------------------------
        # AUTOSTART
        # -----------------------------------------------------

        self.autostart_action = (
            self.menu.addAction(
                "Запускать вместе с Windows"
            )
        )

        self.autostart_action.setCheckable(
            True
        )

        self.autostart_action.setChecked(
            self.is_autostart_enabled()
        )

        self.autostart_action.triggered.connect(
            self.toggle_autostart
        )

        self.menu.addSeparator()

        # -----------------------------------------------------
        # EXIT
        # -----------------------------------------------------

        exit_action = self.menu.addAction(
            "Выход"
        )

        exit_action.triggered.connect(
            self.exit_application
        )

        self.tray.setContextMenu(
            self.menu
        )

        self.tray.activated.connect(
            self.on_tray_activated
        )

        self.tray.show()

    # =========================================================
    # CONSOLE SETUP
    # =========================================================

    def setup_console(self):

        # Отцепляемся от PowerShell / старой консоли
        kernel32.FreeConsole()

        # Создаём собственную консоль приложения
        if not kernel32.AllocConsole():
            print("[Tray] Не удалось создать консоль")
            return

        # Перенаправляем стандартные потоки в новую консоль
        sys.stdout = open(
            "CONOUT$",
            "w",
            encoding="utf-8",
            buffering=1
        )

        sys.stderr = open(
            "CONOUT$",
            "w",
            encoding="utf-8",
            buffering=1
        )

        sys.stdin = open(
            "CONIN$",
            "r",
            encoding="utf-8",
            buffering=1
        )

        # Получаем HWND окна консоли
        self.console_hwnd = kernel32.GetConsoleWindow()

        if not self.console_hwnd:
            print("[Tray] Не удалось получить HWND консоли")
            return

        # Убираем консоль из панели задач
        ex_style = user32.GetWindowLongW(
            self.console_hwnd,
            GWL_EXSTYLE
        )

        ex_style &= ~WS_EX_APPWINDOW
        ex_style |= WS_EX_TOOLWINDOW

        user32.SetWindowLongW(
            self.console_hwnd,
            GWL_EXSTYLE,
            ex_style
        )

        # Обновляем стиль окна
        user32.SetWindowPos(
            self.console_hwnd,
            0,
            0,
            0,
            0,
            0,
            0x0001 |  # SWP_NOSIZE
            0x0002 |  # SWP_NOMOVE
            0x0010 |  # SWP_NOACTIVATE
            0x0020    # SWP_FRAMECHANGED
        )
        
        # Сразу скрываем консоль после запуска приложения
        user32.ShowWindow(
            self.console_hwnd,
            SW_HIDE
        )

    # =========================================================
    # SHOW / HIDE CONSOLE
    # =========================================================

    def show_console(self):

        if (
            sys.platform != "win32"
            or not self.console_hwnd
        ):
            return

        try:

            user32.ShowWindow(
                self.console_hwnd,
                SW_RESTORE
            )

            user32.SetForegroundWindow(
                self.console_hwnd
            )

            print(
                "[Console] Консоль показана."
            )

        except Exception as e:

            print(
                f"[Console] Ошибка показа консоли: {e}"
            )

    def hide_console(self):

        if (
            sys.platform != "win32"
            or not self.console_hwnd
        ):
            return

        try:

            user32.ShowWindow(
                self.console_hwnd,
                SW_HIDE
            )

        except Exception as e:

            print(
                f"[Console] Ошибка скрытия консоли: {e}"
            )

    # =========================================================
    # TRAY
    # =========================================================

    def on_tray_activated(self, reason):

        if (
            reason
            == QSystemTrayIcon.ActivationReason.DoubleClick
        ):
            self.show_console()

    # =========================================================
    # AUTOSTART
    # =========================================================

    def get_executable_command(self):

        if getattr(
            sys,
            "frozen",
            False
        ):
            return f'"{sys.executable}"'

        script_path = os.path.abspath(
            sys.argv[0]
        )

        return (
            f'"{sys.executable}" '
            f'"{script_path}"'
        )

    def is_autostart_enabled(self):

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

                    value, _ = winreg.QueryValueEx(
                        key,
                        APP_NAME
                    )

                    return bool(value)

                except FileNotFoundError:

                    return False

        except Exception as e:

            print(
                f"[Tray] Ошибка проверки автозапуска: {e}"
            )

            return False

    def enable_autostart(self):

        if sys.platform != "win32":
            return False

        try:

            command = (
                self.get_executable_command()
            )

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

            print(
                f"[Tray] Автозапуск включен: {command}"
            )

            return True

        except Exception as e:

            print(
                f"[Tray] Не удалось включить автозапуск: {e}"
            )

            return False

    def disable_autostart(self):

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

                    winreg.DeleteValue(
                        key,
                        APP_NAME
                    )

                except FileNotFoundError:
                    pass

            print(
                "[Tray] Автозапуск отключен."
            )

            return True

        except Exception as e:

            print(
                f"[Tray] Не удалось отключить автозапуск: {e}"
            )

            return False

    def toggle_autostart(
        self,
        checked
    ):

        if checked:

            success = (
                self.enable_autostart()
            )

            if not success:

                self.autostart_action.setChecked(
                    False
                )

        else:

            success = (
                self.disable_autostart()
            )

            if not success:

                self.autostart_action.setChecked(
                    True
                )

    # =========================================================
    # EXIT
    # =========================================================

    def exit_application(self):

        self.tray.hide()

        try:
            self.overlay.reset_all()
        except Exception as e:
            print(
                f"[Tray] Ошибка очистки overlay: {e}"
            )

        QApplication.quit()