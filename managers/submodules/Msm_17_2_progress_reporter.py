# -*- coding: utf-8 -*-
"""
Msm_17_2: ProgressReporter - отображение прогресса асинхронных задач.

MessageBarReporter показывает прогресс в QgsMessageBar (немодальный, не блокирует UI).
SilentReporter - пустая реализация для тестов и silent режима.

ВАЖНО: Все методы MessageBarReporter вызывать ТОЛЬКО из main thread!
Используйте через сигналы из BaseAsyncTask.finished() или через AsyncTaskManager.
"""

from typing import Optional
from qgis.PyQt.QtWidgets import QProgressBar, QLabel, QHBoxLayout, QWidget, QPushButton
from qgis.core import Qgis
from Daman_QGIS.utils import log_info


class MessageBarReporter:
    """
    Отображение прогресса в QgsMessageBar (немодальный, не блокирует UI).

    Показывает прогресс-бар в верхней части окна QGIS.
    Пользователь может продолжать работу пока задача выполняется.

    ВАЖНО: Все методы вызывать ТОЛЬКО из main thread!
    - show() - при запуске задачи
    - update() - через сигнал progress_updated (автоматически в main thread)
    - close() - в finished() задачи
    - set_completed() - в finished() задачи

    Пример использования (внутри AsyncTaskManager):
        reporter = MessageBarReporter(iface, "Загрузка данных")
        reporter.show()

        # Подключаем к сигналу задачи (сигналы выполняются в main thread)
        task.signals.progress_updated.connect(lambda p, m: reporter.update(p, m))
        task.signals.completed.connect(lambda _: reporter.set_completed(True))
        task.signals.failed.connect(lambda _: reporter.set_completed(False))
    """

    def __init__(self, iface, title: str):
        """
        Инициализация reporter.

        Args:
            iface: QgisInterface
            title: Заголовок операции (отображается рядом с прогресс-баром)
        """
        self.iface = iface
        self.title = title
        self.message_bar_item = None
        self.progress_bar: Optional[QProgressBar] = None
        self.label: Optional[QLabel] = None
        self._is_shown = False

    def show(self):
        """
        Показать прогресс-бар в message bar.

        ВАЖНО: Вызывать только из main thread!
        """
        if self._is_shown:
            return

        # Создаём виджет с прогресс-баром
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # Label с названием операции
        self.label = QLabel(self.title)
        layout.addWidget(self.label)

        # Прогресс-бар
        progress_bar = QProgressBar()
        progress_bar.setMinimum(0)
        progress_bar.setMaximum(100)
        progress_bar.setValue(0)
        progress_bar.setMinimumWidth(150)
        progress_bar.setMaximumWidth(200)
        layout.addWidget(progress_bar)
        self.progress_bar = progress_bar

        # Создаём message bar item
        self.message_bar_item = self.iface.messageBar().createMessage("", "")
        self.message_bar_item.layout().addWidget(widget)

        # Показываем в message bar
        self.iface.messageBar().pushWidget(self.message_bar_item, Qgis.Info)
        self._is_shown = True

        log_info(f"Msm_17_2: MessageBar показан для '{self.title}'")

    def update(self, percent: int, message: str = ""):
        """
        Обновить прогресс.

        ВАЖНО: Вызывать только из main thread!
        Обычно вызывается автоматически через сигнал progress_updated.

        Args:
            percent: Процент выполнения (0-100)
            message: Дополнительное сообщение (опционально)
        """
        if not self._is_shown:
            return

        try:
            if self.progress_bar:
                self.progress_bar.setValue(percent)

            if self.label:
                if message:
                    self.label.setText(f"{self.title}: {message}")
                else:
                    self.label.setText(f"{self.title} ({percent}%)")
        except RuntimeError:
            # Qt C++ объект уже удалён - просто игнорируем
            self._is_shown = False
            self.progress_bar = None
            self.label = None
            self.message_bar_item = None

    def close(self):
        """
        Закрыть прогресс-бар.

        ВАЖНО: Вызывать только из main thread!
        """
        if not self._is_shown:
            return

        try:
            if self.message_bar_item:
                self.iface.messageBar().popWidget(self.message_bar_item)
        except RuntimeError:
            # Qt C++ объект уже удалён - игнорируем
            pass

        self.message_bar_item = None
        self.progress_bar = None
        self.label = None
        self._is_shown = False

        log_info(f"Msm_17_2: MessageBar закрыт для '{self.title}'")

    def set_completed(self, success: bool, message: str = ""):
        """
        Показать сообщение о завершении и закрыть прогресс.

        ВАЖНО: Вызывать только из main thread!

        Args:
            success: True если задача завершена успешно
            message: Кастомное сообщение (опционально)
        """
        self.close()

        # Определяем уровень сообщения и текст
        if success:
            level = Qgis.Success
            text = message if message else f"{self.title}: Завершено"
        else:
            level = Qgis.Warning
            text = message if message else f"{self.title}: Ошибка"

        # Показываем сообщение о завершении (автоматически исчезнет через 5 сек)
        self.iface.messageBar().pushMessage("", text, level, duration=5)

        log_info(f"Msm_17_2: Завершение '{self.title}' (success={success})")


class SilentReporter:
    """
    Пустой reporter для тестов и silent режима.

    Все методы ничего не делают - используется когда
    не нужно показывать прогресс пользователю.
    """

    def __init__(self, iface=None, title: str = ""):
        """
        Инициализация silent reporter.

        Args:
            iface: Игнорируется
            title: Игнорируется
        """
        pass

    def show(self):
        """Ничего не делает."""
        pass

    def update(self, percent: int, message: str = ""):
        """Ничего не делает."""
        pass

    def close(self):
        """Ничего не делает."""
        pass

    def set_completed(self, success: bool, message: str = ""):
        """Ничего не делает."""
        pass
