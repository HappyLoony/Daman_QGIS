# -*- coding: utf-8 -*-
"""
Msm_17_1: BaseAsyncTask - базовый класс для асинхронных задач плагина.

Использует QgsTask для фоновой обработки без блокировки UI.
Наследники реализуют execute() с основной логикой.

CRITICAL RULES:
1. В execute() НЕЛЬЗЯ обращаться к QgsVectorLayer напрямую - передавать layer_id
2. В execute() НЕЛЬЗЯ изменять GUI
3. В execute() НЕЛЬЗЯ использовать print()
4. Исключения в execute() ловятся в run() и передаются через signals.failed
"""

from abc import abstractmethod
from typing import Any, Optional
from qgis.PyQt.QtCore import pyqtSignal, QObject
from qgis.core import QgsTask
from Daman_QGIS.utils import log_info, log_error


class AsyncTaskSignals(QObject):
    """
    Сигналы для передачи результатов из background thread в main thread.

    Все сигналы thread-safe и могут безопасно emit из background thread.
    Slots подключенные к этим сигналам выполняются в main thread.
    """
    progress_updated = pyqtSignal(int, str)  # percent (0-100), message
    completed = pyqtSignal(object)  # result (Any)
    failed = pyqtSignal(str)  # error message
    cancelled = pyqtSignal()


class BaseAsyncTask(QgsTask):
    """
    Базовый класс для асинхронных задач плагина.

    Наследники должны реализовать execute() с основной логикой.
    run() и finished() НЕ переопределять - они обеспечивают безопасность.

    CRITICAL - В execute() НЕЛЬЗЯ:
    - Обращаться к QgsVectorLayer напрямую (передавать layer_id, получать через QgsProject.instance().mapLayer())
    - Изменять GUI (widgets, dialogs)
    - Использовать print() (crash в background thread)
    - Бросать исключения наружу (ловятся в run())

    Пример использования:
        class MyTask(BaseAsyncTask):
            def __init__(self, layer_id: str):
                super().__init__("Моя задача")
                self.layer_id = layer_id

            def execute(self):
                from qgis.core import QgsProject
                layer = QgsProject.instance().mapLayer(self.layer_id)
                if not layer:
                    raise ValueError(f"Layer {self.layer_id} not found")

                # Обработка...
                for i in range(100):
                    if self.is_cancelled():
                        return None
                    self.report_progress(i, f"Шаг {i}/100")

                return {"result": "success"}
    """

    def __init__(self, description: str, can_cancel: bool = True):
        """
        Инициализация задачи.

        Args:
            description: Описание задачи (отображается в TaskManager QGIS)
            can_cancel: Разрешить ли отмену задачи пользователем
        """
        flags = QgsTask.CanCancel if can_cancel else QgsTask.Flags()
        super().__init__(description, flags)

        self.signals = AsyncTaskSignals()
        self.result: Any = None
        self.error: Optional[str] = None

    @abstractmethod
    def execute(self) -> Any:
        """
        Основная логика задачи. Реализуется в наследниках.

        Выполняется в background thread.

        Returns:
            Результат выполнения (передаётся в signals.completed)

        Raises:
            Exception: Любые исключения ловятся в run() и передаются в signals.failed

        ВАЖНО:
        - Периодически проверять is_cancelled() и выходить если True
        - Вызывать report_progress() для обновления прогресса
        - Получать слои через QgsProject.instance().mapLayer(layer_id)
        """
        pass

    def run(self) -> bool:
        """
        Выполняется в background thread. НЕ переопределять в наследниках.

        Вызывает execute() и ловит все исключения.

        Returns:
            True если execute() завершился успешно, False при ошибке
        """
        try:
            log_info(f"Msm_17_1: Запуск задачи '{self.description()}'")
            self.result = self.execute()
            return True
        except Exception as e:
            # CRITICAL: Никогда не бросаем исключения наружу - crash QGIS!
            import traceback
            self.error = f"{str(e)}\n{traceback.format_exc()}"
            log_error(f"Msm_17_1: Ошибка в задаче '{self.description()}': {self.error}")
            return False

    def finished(self, result: bool):
        """
        Вызывается в main thread после завершения run().
        НЕ переопределять в наследниках.

        Безопасно для GUI операций - выполняется в main thread.

        Args:
            result: Возвращаемое значение run() (True/False)
        """
        if self.isCanceled():
            log_info(f"Msm_17_1: Задача отменена '{self.description()}'")
            self.signals.cancelled.emit()
        elif result:
            log_info(f"Msm_17_1: Задача завершена '{self.description()}'")
            self.signals.completed.emit(self.result)
        else:
            log_error(f"Msm_17_1: Задача завершена с ошибкой '{self.description()}': {self.error}")
            self.signals.failed.emit(self.error or "Unknown error")

    def report_progress(self, percent: int, message: str = ""):
        """
        Безопасный способ сообщить о прогрессе.

        Можно вызывать из execute(). Thread-safe.

        Args:
            percent: Процент выполнения (0-100)
            message: Текстовое сообщение о текущем этапе
        """
        if not self.isCanceled():
            # setProgress() встроен в QgsTask и thread-safe
            self.setProgress(percent)
            # emit сигнала тоже thread-safe
            self.signals.progress_updated.emit(percent, message)

    def is_cancelled(self) -> bool:
        """
        Проверка отмены задачи.

        Вызывать периодически в execute() и выходить если True.

        Returns:
            True если пользователь отменил задачу
        """
        return self.isCanceled()
