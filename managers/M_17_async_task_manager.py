# -*- coding: utf-8 -*-
"""
M_17: AsyncTaskManager - централизованное управление асинхронными задачами.

Использует QgsTask для фоновой обработки,
QgsMessageBar для отображения прогресса (не блокирует UI).

Основные возможности:
- Запуск задач в фоновом потоке (не блокирует QGIS)
- Автоматическое управление жизненным циклом задач
- Прогресс в MessageBar (немодальный)
- Поддержка отмены задач
- Callbacks для обработки результатов

Пример использования:
    from Daman_QGIS.managers import get_async_manager

    manager = get_async_manager(self.iface)
    task = MyTask(layer.id())
    task_id = manager.run(
        task,
        on_completed=lambda result: handle_result(result),
        on_failed=lambda error: handle_error(error)
    )

    # Отмена если нужно
    manager.cancel(task_id)
"""

from typing import Dict, Optional, Callable, Any
from qgis.core import QgsApplication
from Daman_QGIS.utils import log_info, log_warning, log_error
from .submodules.Msm_17_1_base_task import BaseAsyncTask
from .submodules.Msm_17_2_progress_reporter import MessageBarReporter, SilentReporter


class AsyncTaskManager:
    """
    Менеджер асинхронных задач.

    Управляет жизненным циклом QgsTask:
    - Хранит ссылки на активные задачи (CRITICAL: предотвращает garbage collection)
    - Управляет MessageBar reporters для отображения прогресса
    - Обеспечивает cleanup после завершения задач
    - Подключает callbacks для обработки результатов
    - Поддерживает последовательное выполнение задач (очередь)
    """

    def __init__(self, iface):
        """
        Инициализация менеджера.

        Args:
            iface: QgisInterface
        """
        self.iface = iface
        # CRITICAL: Храним ссылки на задачи, иначе GC удалит их и QGIS упадёт
        self._active_tasks: Dict[str, BaseAsyncTask] = {}
        self._reporters: Dict[str, MessageBarReporter] = {}
        self._task_counter = 0

        # Очередь для последовательного выполнения задач
        self._sequential_queue: list = []
        self._sequential_running: bool = False
        self._sequential_callbacks: Dict[str, dict] = {}

    def run(self,
            task: BaseAsyncTask,
            show_progress: bool = True,
            silent_completion: bool = False,
            on_completed: Optional[Callable[[Any], None]] = None,
            on_failed: Optional[Callable[[str], None]] = None,
            on_cancelled: Optional[Callable[[], None]] = None) -> str:
        """
        Запуск асинхронной задачи.

        Args:
            task: Экземпляр BaseAsyncTask (или наследника)
            show_progress: Показывать ли прогресс в MessageBar (default: True)
            silent_completion: Не показывать сообщение о завершении (default: False).
                              Используйте True при запуске множества задач, чтобы
                              показать одно общее сообщение в конце.
            on_completed: Callback при успешном завершении, получает result
            on_failed: Callback при ошибке, получает error message
            on_cancelled: Callback при отмене пользователем

        Returns:
            task_id: Уникальный идентификатор задачи для отслеживания/отмены

        Note:
            Все callbacks выполняются в main thread, безопасно для GUI операций.
        """
        # Генерируем уникальный ID
        self._task_counter += 1
        task_id = f"task_{self._task_counter}_{task.description()}"

        # CRITICAL: Сохраняем ссылку на task
        # Без этого Python GC удалит task после выхода из функции,
        # а QGIS попытается обратиться к удалённому объекту = crash
        self._active_tasks[task_id] = task

        # Сохраняем флаг silent_completion для использования в _cleanup
        if not hasattr(self, '_silent_tasks'):
            self._silent_tasks = set()
        if silent_completion:
            self._silent_tasks.add(task_id)

        # Создаём reporter для отображения прогресса
        if show_progress:
            reporter = MessageBarReporter(self.iface, task.description())
            self._reporters[task_id] = reporter
            reporter.show()

            # Подключаем обновление прогресса через сигнал
            # Сигнал thread-safe, slot выполняется в main thread
            task.signals.progress_updated.connect(
                lambda p, m: self._on_progress(task_id, p, m)
            )

        # Подключаем пользовательские callbacks
        if on_completed:
            task.signals.completed.connect(on_completed)
        if on_failed:
            task.signals.failed.connect(on_failed)
        if on_cancelled:
            task.signals.cancelled.connect(on_cancelled)

        # Подключаем внутренний cleanup
        # lambda с default argument для захвата текущего значения task_id
        task.signals.completed.connect(
            lambda _, tid=task_id: self._cleanup(tid, success=True)
        )
        task.signals.failed.connect(
            lambda _, tid=task_id: self._cleanup(tid, success=False)
        )
        task.signals.cancelled.connect(
            lambda tid=task_id: self._cleanup(tid, success=False, cancelled=True)
        )

        # Добавляем в глобальный TaskManager QGIS
        # После этого QGIS берёт ownership и запускает task.run() в background thread
        QgsApplication.taskManager().addTask(task)

        log_info(f"M_17: Запущена задача '{task_id}'")
        return task_id

    def cancel(self, task_id: str) -> bool:
        """
        Отменить задачу по ID.

        Args:
            task_id: ID задачи (возвращается из run())

        Returns:
            True если задача была найдена и отменена, False если не найдена
        """
        if task_id in self._active_tasks:
            task = self._active_tasks[task_id]
            task.cancel()
            log_info(f"M_17: Запрошена отмена задачи '{task_id}'")
            return True

        log_warning(f"M_17: Задача '{task_id}' не найдена для отмены")
        return False

    def cancel_all(self):
        """Отменить все активные задачи."""
        task_ids = list(self._active_tasks.keys())
        for task_id in task_ids:
            self.cancel(task_id)

        if task_ids:
            log_info(f"M_17: Отменено {len(task_ids)} задач")

    def is_running(self, task_id: str) -> bool:
        """
        Проверить, выполняется ли задача.

        Args:
            task_id: ID задачи

        Returns:
            True если задача активна
        """
        return task_id in self._active_tasks

    def get_active_count(self) -> int:
        """
        Получить количество активных задач.

        Returns:
            Количество выполняющихся задач
        """
        return len(self._active_tasks)

    def get_active_tasks(self) -> Dict[str, str]:
        """
        Получить список активных задач.

        Returns:
            Dict[task_id, description]
        """
        return {
            task_id: task.description()
            for task_id, task in self._active_tasks.items()
        }

    def _on_progress(self, task_id: str, percent: int, message: str):
        """
        Callback для обновления прогресса (вызывается в main thread).

        Args:
            task_id: ID задачи
            percent: Процент выполнения
            message: Сообщение о текущем этапе
        """
        if task_id in self._reporters:
            self._reporters[task_id].update(percent, message)

    def _cleanup(self, task_id: str, success: bool, cancelled: bool = False):
        """
        Очистка после завершения задачи.

        Вызывается автоматически через сигналы (в main thread).

        Args:
            task_id: ID задачи
            success: True если задача завершена успешно
            cancelled: True если задача была отменена
        """
        # Проверяем флаг silent_completion
        is_silent = hasattr(self, '_silent_tasks') and task_id in self._silent_tasks

        # Закрываем reporter
        if task_id in self._reporters:
            reporter = self._reporters[task_id]
            if is_silent:
                # Просто закрываем без сообщения о завершении
                reporter.close()
            elif cancelled:
                reporter.set_completed(False, "Отменено")
            else:
                reporter.set_completed(success)
            del self._reporters[task_id]

        # Удаляем ссылку на task (теперь GC может его удалить)
        if task_id in self._active_tasks:
            del self._active_tasks[task_id]

        # Удаляем из silent_tasks
        if hasattr(self, '_silent_tasks') and task_id in self._silent_tasks:
            self._silent_tasks.discard(task_id)

        status = "cancelled" if cancelled else ("success" if success else "failed")
        log_info(f"M_17: Cleanup задачи '{task_id}' (status={status}, silent={is_silent})")

    def run_sequential(self,
                       tasks: list,
                       show_progress: bool = True,
                       silent_completion: bool = True,
                       on_each_completed: Optional[Callable[[str, Any], None]] = None,
                       on_each_failed: Optional[Callable[[str, str], None]] = None,
                       on_each_cancelled: Optional[Callable[[str], None]] = None,
                       on_all_completed: Optional[Callable[[], None]] = None):
        """
        Запуск задач ПОСЛЕДОВАТЕЛЬНО (одна за другой).

        ВАЖНО: Используйте этот метод вместо run() когда задачи используют
        processing.run() или другие не thread-safe операции QGIS.

        Args:
            tasks: Список экземпляров BaseAsyncTask
            show_progress: Показывать ли прогресс в MessageBar
            silent_completion: Не показывать сообщение для каждой задачи
            on_each_completed: Callback при завершении каждой задачи (task_id, result)
            on_each_failed: Callback при ошибке каждой задачи (task_id, error)
            on_each_cancelled: Callback при отмене каждой задачи (task_id)
            on_all_completed: Callback когда ВСЕ задачи завершены

        Note:
            - Следующая задача стартует только после завершения предыдущей
            - Это предотвращает access violation от параллельных processing.run()
        """
        if not tasks:
            if on_all_completed:
                on_all_completed()
            return

        log_info(f"M_17: Запуск последовательной очереди из {len(tasks)} задач")

        # Сохраняем общий callback
        self._sequential_all_completed = on_all_completed
        self._sequential_total = len(tasks)
        self._sequential_completed = 0

        # Добавляем задачи в очередь
        for task in tasks:
            task_info = {
                'task': task,
                'show_progress': show_progress,
                'silent_completion': silent_completion,
                'on_completed': on_each_completed,
                'on_failed': on_each_failed,
                'on_cancelled': on_each_cancelled
            }
            self._sequential_queue.append(task_info)

        # Запускаем первую задачу
        self._run_next_sequential()

    def _run_next_sequential(self):
        """Запуск следующей задачи из очереди."""
        if not self._sequential_queue:
            # Очередь пуста - все задачи выполнены
            self._sequential_running = False
            log_info(f"M_17: Последовательная очередь завершена "
                    f"({self._sequential_completed}/{self._sequential_total})")
            if hasattr(self, '_sequential_all_completed') and self._sequential_all_completed:
                self._sequential_all_completed()
            return

        self._sequential_running = True
        task_info = self._sequential_queue.pop(0)
        task = task_info['task']

        # Создаём обёртки для callbacks чтобы запустить следующую задачу
        original_on_completed = task_info['on_completed']
        original_on_failed = task_info['on_failed']
        original_on_cancelled = task_info['on_cancelled']

        def on_completed_wrapper(result, tid=None):
            self._sequential_completed += 1
            if original_on_completed and tid:
                original_on_completed(tid, result)
            # Запускаем следующую задачу
            self._run_next_sequential()

        def on_failed_wrapper(error, tid=None):
            self._sequential_completed += 1
            if original_on_failed and tid:
                original_on_failed(tid, error)
            # Продолжаем очередь даже при ошибке
            self._run_next_sequential()

        def on_cancelled_wrapper(tid=None):
            self._sequential_completed += 1
            if original_on_cancelled and tid:
                original_on_cancelled(tid)
            # Продолжаем очередь даже при отмене
            self._run_next_sequential()

        # Запускаем через стандартный run() но с нашими обёртками
        task_id = self.run(
            task,
            show_progress=task_info['show_progress'],
            silent_completion=task_info['silent_completion'],
            on_completed=lambda result, tid=task.description(): on_completed_wrapper(result, tid),
            on_failed=lambda error, tid=task.description(): on_failed_wrapper(error, tid),
            on_cancelled=lambda tid=task.description(): on_cancelled_wrapper(tid)
        )

        log_info(f"M_17: Запущена задача {self._sequential_completed + 1}/{self._sequential_total}: {task_id}")

    def clear_sequential_queue(self):
        """Очистить очередь последовательных задач (не отменяет текущую)."""
        cleared = len(self._sequential_queue)
        self._sequential_queue.clear()
        if cleared > 0:
            log_info(f"M_17: Очищена очередь из {cleared} задач")


# Singleton instance
_async_manager: Optional[AsyncTaskManager] = None


def get_async_manager(iface=None) -> AsyncTaskManager:
    """
    Получить singleton экземпляр AsyncTaskManager.

    Args:
        iface: QgisInterface (обязателен при первом вызове)

    Returns:
        AsyncTaskManager instance

    Raises:
        ValueError: Если iface не передан при первом вызове

    Example:
        # При инициализации плагина (первый вызов)
        manager = get_async_manager(self.iface)

        # В других местах (iface уже сохранён)
        manager = get_async_manager()
    """
    global _async_manager

    if _async_manager is None:
        if iface is None:
            raise ValueError(
                "M_17: iface required for first call to get_async_manager(). "
                "Call get_async_manager(iface) during plugin initialization."
            )
        _async_manager = AsyncTaskManager(iface)
        log_info("M_17: Singleton AsyncTaskManager создан")

    return _async_manager


def reset_async_manager():
    """
    Сброс singleton экземпляра.

    Используется для тестов и при выгрузке плагина.
    Отменяет все активные задачи перед сбросом.
    """
    global _async_manager

    if _async_manager is not None:
        _async_manager.cancel_all()
        log_info("M_17: Singleton AsyncTaskManager сброшен")

    _async_manager = None
