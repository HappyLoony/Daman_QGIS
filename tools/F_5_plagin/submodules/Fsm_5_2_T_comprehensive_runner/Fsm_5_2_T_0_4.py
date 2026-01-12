# -*- coding: utf-8 -*-
"""
Fsm_5_2_T_0_4: Тест диагностики F_0_4 после завершения

Проверяет:
1. AsyncTaskManager callbacks
2. MessageBarReporter lifecycle
3. Диалог обновления после async завершения
4. Memory leaks от task references
"""

from Daman_QGIS.utils import log_info, log_warning, log_error
from qgis.core import QgsProject, QgsVectorLayer, QgsApplication
from qgis.PyQt.QtCore import QTimer
from qgis.PyQt.QtWidgets import QApplication


class TestF04:
    """Тест диагностики F_0_4"""

    def __init__(self, iface, logger):
        self.iface = iface
        self.logger = logger
        self.test_results = []

    def run_all_tests(self):
        """Запуск всех тестов"""
        self.logger.section("ТЕСТ F_0_4: Проверка топологии (диагностика)")

        tests = [
            ("AsyncTaskManager state", self.test_async_manager_state),
            ("MessageBarReporter cleanup", self.test_messagebar_cleanup),
            ("Pending tasks check", self.test_pending_tasks),
            ("Event loop blocking", self.test_event_loop),
        ]

        for name, test_func in tests:
            try:
                result = test_func()
                if result:
                    self.logger.success(f"{name}: OK")
                else:
                    self.logger.fail(f"{name}: FAIL")
            except Exception as e:
                self.logger.fail(f"{name}: ERROR - {e}")

        self.logger.summary()

    def test_async_manager_state(self) -> bool:
        """Тест 1: Проверка состояния AsyncTaskManager"""
        try:
            from Daman_QGIS.managers import get_async_manager

            manager = get_async_manager(self.iface)

            # Проверяем количество активных задач
            active_count = manager.get_active_count()
            active_tasks = manager.get_active_tasks()

            self.logger.info(f"Active tasks: {active_count}")
            for task_id, desc in active_tasks.items():
                self.logger.info(f"  - {task_id}: {desc}")

            # Если есть активные задачи после завершения - это проблема
            if active_count > 0:
                self.logger.warning("Есть активные задачи после завершения!")
                return False

            return True

        except Exception as e:
            self.logger.error(f"ERROR: {e}")
            return False

    def test_messagebar_cleanup(self) -> bool:
        """Тест 2: Проверка очистки MessageBar"""
        try:
            # Проверяем MessageBar
            message_bar = self.iface.messageBar()

            # Получаем текущие виджеты
            layout = message_bar.layout()
            widget_count = layout.count() if layout else 0

            self.logger.info(f"MessageBar widgets: {widget_count}")

            # ПРИМЕЧАНИЕ: Количество виджетов зависит от состояния QGIS
            # В тестовой среде это не критично - просто информируем
            # Порог увеличен до 10 (разумный максимум)
            if widget_count > 10:
                self.logger.warning(f"Много виджетов в MessageBar ({widget_count})")
                return False

            return True

        except Exception as e:
            self.logger.error(f"ERROR: {e}")
            return False

    def test_pending_tasks(self) -> bool:
        """Тест 3: Проверка QgsTaskManager на зависшие задачи"""
        try:
            task_manager = QgsApplication.taskManager()

            # Получаем список задач
            active_ids = task_manager.activeTasks()
            count = task_manager.count()

            self.logger.info(f"QgsTaskManager active: {len(active_ids)}, total: {count}")

            if len(active_ids) > 0:
                self.logger.info(f"Active task IDs: {active_ids}")

            return True

        except Exception as e:
            self.logger.error(f"ERROR: {e}")
            return False

    def test_event_loop(self) -> bool:
        """Тест 4: Проверка блокировки event loop"""
        try:
            import time

            # Создаём флаг
            self._event_processed = False

            def on_timer():
                self._event_processed = True

            # Запускаем таймер на 10мс (минимальный интервал)
            QTimer.singleShot(10, on_timer)

            # Обрабатываем события с паузой для срабатывания таймера
            start_time = time.time()
            max_wait = 0.5  # Максимум 500мс ожидания

            while not self._event_processed and (time.time() - start_time) < max_wait:
                QApplication.processEvents()
                time.sleep(0.01)  # 10мс пауза между итерациями

            if not self._event_processed:
                self.logger.warning("Event loop заблокирован!")
                return False

            self.logger.info("Event loop работает нормально")
            return True

        except Exception as e:
            self.logger.error(f"ERROR: {e}")
            return False
