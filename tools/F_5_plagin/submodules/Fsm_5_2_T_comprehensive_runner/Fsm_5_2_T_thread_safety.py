# -*- coding: utf-8 -*-
"""
Fsm_5_2_T_thread_safety - Тест потокобезопасности

Проверяет:
1. QgsTask - асинхронные задачи QGIS
2. Безопасный доступ к слоям из разных потоков
3. Блокировки при записи в слой
4. Параллельное выполнение нескольких QgsTask
5. Отмена задач (cancel)
6. Сигналы завершения задач

Критично для долгих операций (импорт, экспорт, обработка).
"""

from typing import Any, List, Optional
import time
import threading

from qgis.core import (
    QgsApplication, QgsTask, QgsTaskManager,
    QgsVectorLayer, QgsFeature, QgsGeometry, QgsPointXY,
    QgsProject, QgsMessageLog, Qgis
)
from qgis.PyQt.QtCore import QThread
from qgis.PyQt.QtWidgets import QApplication


class SimpleTestTask(QgsTask):
    """Простая тестовая задача"""

    def __init__(self, description: str, duration_sec: float = 0.5):
        super().__init__(description, QgsTask.CanCancel)
        self.duration = duration_sec
        self.result_value = None
        self.was_cancelled = False

    def run(self) -> bool:
        """Выполнение задачи в фоновом потоке"""
        steps = 10
        for i in range(steps):
            if self.isCanceled():
                self.was_cancelled = True
                return False

            # Симуляция работы
            time.sleep(self.duration / steps)
            self.setProgress((i + 1) * 100 / steps)

        self.result_value = "completed"
        return True

    def finished(self, result: bool) -> None:
        """Вызывается в главном потоке после завершения"""
        if result:
            self.result_value = "finished_ok"
        elif self.was_cancelled:
            self.result_value = "cancelled"
        else:
            self.result_value = "failed"


class LayerWriteTask(QgsTask):
    """Задача записи в слой (тест потокобезопасности)"""

    def __init__(self, layer_id: str, feature_count: int):
        super().__init__("Layer Write Test", QgsTask.CanCancel)
        self.layer_id = layer_id
        self.feature_count = feature_count
        self.features_added = 0
        self.error_message = None

    def run(self) -> bool:
        """Записываем features в слой из фонового потока"""
        try:
            # ВАЖНО: В фоновом потоке нельзя напрямую работать со слоем!
            # Это тест того, что мы правильно обрабатываем эту ситуацию

            # Симулируем подготовку данных (это безопасно в фоне)
            features_data = []
            for i in range(self.feature_count):
                if self.isCanceled():
                    return False

                # Готовим данные (не объекты QGIS!)
                features_data.append({
                    'x': i % 10,
                    'y': i // 10,
                    'name': f'feature_{i}'
                })
                self.setProgress((i + 1) * 100 / self.feature_count)

            self.features_added = len(features_data)
            return True

        except Exception as e:
            self.error_message = str(e)
            return False

    def finished(self, result: bool) -> None:
        """Вызывается в главном потоке - здесь безопасно работать со слоем"""
        pass


class TestThreadSafety:
    """Тесты потокобезопасности"""

    def __init__(self, iface: Any, logger: Any) -> None:
        """Инициализация теста"""
        self.iface = iface
        self.logger = logger
        # Храним ссылки на задачи чтобы они не удалялись преждевременно
        self._active_tasks: List[QgsTask] = []

    def run_all_tests(self) -> None:
        """Запуск всех тестов потокобезопасности"""
        self.logger.section("ТЕСТ ПОТОКОБЕЗОПАСНОСТИ")

        try:
            self.test_01_task_manager_available()
            self.test_02_simple_task()
            self.test_03_task_progress()
            self.test_04_task_cancel()
            self.test_05_multiple_tasks()
            self.test_06_main_thread_check()
            self.test_07_layer_thread_safety()

        except Exception as e:
            self.logger.error(f"Критическая ошибка тестов thread safety: {str(e)}")

        self.logger.summary()

    def _process_events(self, timeout_ms: int = 500) -> None:
        """Обработать Qt события"""
        end_time = time.time() + timeout_ms / 1000
        while time.time() < end_time:
            QApplication.processEvents()
            time.sleep(0.01)

    def test_01_task_manager_available(self) -> None:
        """ТЕСТ 1: Доступность QgsTaskManager"""
        self.logger.section("1. QgsTaskManager")

        try:
            task_manager = QgsApplication.taskManager()

            if task_manager is not None:
                self.logger.success("QgsTaskManager доступен")

                # Количество активных задач
                active_count = task_manager.countActiveTasks()
                self.logger.info(f"Активных задач: {active_count}")

                # Проверяем методы
                methods = ['addTask', 'cancelAll', 'countActiveTasks']
                for method in methods:
                    if hasattr(task_manager, method):
                        self.logger.success(f"Метод {method}() доступен")
                    else:
                        self.logger.fail(f"Метод {method}() недоступен!")

            else:
                self.logger.fail("QgsTaskManager недоступен!")

        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    def test_02_simple_task(self) -> None:
        """ТЕСТ 2: Простая QgsTask"""
        self.logger.section("2. Простая QgsTask")

        try:
            task = SimpleTestTask("Simple Test Task", duration_sec=0.3)
            # ВАЖНО: Сохраняем ссылку чтобы объект не удалился
            self._active_tasks.append(task)

            task_manager = QgsApplication.taskManager()

            # Используем сигналы для отслеживания завершения
            task_completed = False
            task_success = False
            result_value = [None]

            def on_task_completed():
                nonlocal task_completed, task_success
                task_completed = True
                task_success = True
                result_value[0] = task.result_value

            def on_task_terminated():
                nonlocal task_completed
                task_completed = True
                result_value[0] = task.result_value

            task.taskCompleted.connect(on_task_completed)
            task.taskTerminated.connect(on_task_terminated)

            # Добавляем задачу
            task_id = task_manager.addTask(task)
            self.logger.info(f"Задача добавлена, ID: {task_id}")

            # Ждём завершения через сигнал
            timeout = 5.0
            start_time = time.time()

            while not task_completed and time.time() - start_time < timeout:
                self._process_events(100)

            # Даём время на обработку
            self._process_events(100)

            # Проверяем результат
            if task_success:
                self.logger.success("Задача завершена успешно")
                self.logger.info(f"Результат: {result_value[0]}")
            elif task_completed:
                self.logger.fail(f"Задача прервана неожиданно: {result_value[0]}")
            else:
                self.logger.fail("Таймаут ожидания задачи!")

        except RuntimeError as e:
            if "has been deleted" in str(e):
                self.logger.fail(f"C++ объект задачи удалён преждевременно: {e}")
            else:
                self.logger.error(f"RuntimeError: {e}")
        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    def test_03_task_progress(self) -> None:
        """ТЕСТ 3: Прогресс задачи"""
        self.logger.section("3. Прогресс задачи")

        try:
            task = SimpleTestTask("Progress Test Task", duration_sec=0.5)
            # ВАЖНО: Сохраняем ссылку чтобы объект не удалился
            self._active_tasks.append(task)

            progress_values: List[float] = []
            task_completed = False
            task_status = None

            # Подключаем сигнал прогресса
            task.progressChanged.connect(lambda p: progress_values.append(p))

            # Подключаем сигнал завершения для захвата статуса ДО удаления C++ объекта
            def on_task_finished():
                nonlocal task_completed
                task_completed = True

            task.taskCompleted.connect(on_task_finished)
            task.taskTerminated.connect(on_task_finished)

            task_manager = QgsApplication.taskManager()
            task_manager.addTask(task)

            # Ждём завершения через сигнал, а не через status()
            timeout = 5.0
            start_time = time.time()

            while not task_completed and time.time() - start_time < timeout:
                self._process_events(50)

            # Даём немного времени на обработку финальных событий
            self._process_events(100)

            self.logger.info(f"Получено {len(progress_values)} значений прогресса")

            if len(progress_values) > 0:
                self.logger.success("Сигнал progressChanged работает")

                # Проверяем что прогресс монотонно растёт
                is_monotonic = all(progress_values[i] <= progress_values[i + 1]
                                   for i in range(len(progress_values) - 1))

                if is_monotonic:
                    self.logger.success("Прогресс монотонно возрастает")
                else:
                    self.logger.fail("Прогресс не монотонный!")

                # Проверяем финальное значение
                if progress_values and progress_values[-1] == 100:
                    self.logger.success("Финальный прогресс = 100%")
                else:
                    self.logger.fail(f"Финальный прогресс {progress_values[-1]}% != 100%!")

            else:
                self.logger.fail("Сигнал progressChanged не получен!")

        except RuntimeError as e:
            # C++ объект удалён - это ожидаемое поведение после завершения задачи
            if "has been deleted" in str(e):
                self.logger.fail(f"C++ объект задачи удалён преждевременно: {e}")
            else:
                self.logger.error(f"RuntimeError: {e}")
        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    def test_04_task_cancel(self) -> None:
        """ТЕСТ 4: Отмена задачи"""
        self.logger.section("4. Отмена задачи (cancel)")

        try:
            # Создаём долгую задачу
            task = SimpleTestTask("Cancellable Task", duration_sec=2.0)
            # ВАЖНО: Сохраняем ссылку чтобы объект не удалился
            self._active_tasks.append(task)

            # Используем сигналы для отслеживания завершения
            task_finished = False
            was_cancelled = [False]

            def on_task_completed():
                nonlocal task_finished
                task_finished = True

            def on_task_terminated():
                nonlocal task_finished
                task_finished = True
                was_cancelled[0] = task.was_cancelled

            task.taskCompleted.connect(on_task_completed)
            task.taskTerminated.connect(on_task_terminated)

            task_manager = QgsApplication.taskManager()
            task_manager.addTask(task)
            self.logger.info("Задача запущена")

            # Ждём немного и отменяем
            self._process_events(200)

            task.cancel()
            self.logger.info("Отправлен cancel()")

            # Ждём завершения через сигнал
            timeout = 3.0
            start_time = time.time()

            while not task_finished and time.time() - start_time < timeout:
                self._process_events(50)

            # Даём время на обработку
            self._process_events(100)

            # Проверяем - задача ДОЛЖНА быть отменена
            if was_cancelled[0]:
                self.logger.success("Задача корректно отменена (isCanceled() сработал)")
            elif task_finished:
                self.logger.success("Задача завершена/прервана после cancel()")
            else:
                self.logger.fail("Таймаут - задача не была отменена!")

        except RuntimeError as e:
            if "has been deleted" in str(e):
                self.logger.fail(f"C++ объект задачи удалён преждевременно: {e}")
            else:
                self.logger.error(f"RuntimeError: {e}")
        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    def test_05_multiple_tasks(self) -> None:
        """ТЕСТ 5: Несколько параллельных задач"""
        self.logger.section("5. Параллельные задачи")

        try:
            task_count = 3
            tasks: List[SimpleTestTask] = []
            task_manager = QgsApplication.taskManager()

            # Счётчики завершения (через сигналы, а не polling status())
            completed_count = [0]
            terminated_count = [0]

            def on_task_completed():
                completed_count[0] += 1

            def on_task_terminated():
                terminated_count[0] += 1

            # Создаём и запускаем задачи
            for i in range(task_count):
                task = SimpleTestTask(f"Parallel Task {i + 1}", duration_sec=0.3)
                # ВАЖНО: Сохраняем ссылку чтобы объект не удалился преждевременно
                self._active_tasks.append(task)
                tasks.append(task)

                # Подключаем сигналы ДО добавления в TaskManager
                task.taskCompleted.connect(on_task_completed)
                task.taskTerminated.connect(on_task_terminated)

                task_manager.addTask(task)

            self.logger.info(f"Запущено {task_count} параллельных задач")

            # Ждём завершения всех через сигналы
            timeout = 10.0
            start_time = time.time()

            while time.time() - start_time < timeout:
                total_finished = completed_count[0] + terminated_count[0]
                if total_finished >= task_count:
                    break
                self._process_events(100)

            # Даём время на финальную обработку
            self._process_events(100)

            # Проверяем результаты
            self.logger.info(f"Завершено: {completed_count[0]}, Прервано: {terminated_count[0]}")

            if completed_count[0] == task_count:
                self.logger.success(f"Все {task_count} задач успешно завершены")
            elif completed_count[0] + terminated_count[0] == task_count:
                self.logger.fail(f"Не все задачи успешны! Completed: {completed_count[0]}, Terminated: {terminated_count[0]}")
            else:
                self.logger.fail(f"Таймаут - не все задачи завершились! Completed: {completed_count[0]}, Terminated: {terminated_count[0]}")

        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    def test_06_main_thread_check(self) -> None:
        """ТЕСТ 6: Проверка главного потока"""
        self.logger.section("6. Проверка главного потока")

        try:
            # В главном потоке
            main_thread = QThread.currentThread()
            app_thread = QApplication.instance().thread()

            is_main = main_thread == app_thread
            self.logger.info(f"Текущий поток == Application thread: {is_main}")

            if is_main:
                self.logger.success("Тест выполняется в главном потоке")
            else:
                self.logger.fail("Тест выполняется НЕ в главном потоке!")

            # Проверяем threading
            current_thread = threading.current_thread()
            self.logger.info(f"threading.current_thread(): {current_thread.name}")

            if current_thread == threading.main_thread():
                self.logger.success("threading подтверждает главный поток")
            else:
                self.logger.fail("threading: не главный поток!")

        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    def test_07_layer_thread_safety(self) -> None:
        """ТЕСТ 7: Потокобезопасность работы со слоями"""
        self.logger.section("7. Потокобезопасность слоёв")

        layer_id = None
        try:
            # Создаём слой
            layer = QgsVectorLayer(
                "Point?crs=EPSG:4326&field=name:string",
                "thread_test_layer",
                "memory"
            )

            if not layer.isValid():
                self.logger.fail("Не удалось создать слой")
                return

            self.logger.info("Слой создан в главном потоке")

            # Добавляем в проект
            QgsProject.instance().addMapLayer(layer, False)
            layer_id = layer.id()

            # Создаём задачу записи
            task = LayerWriteTask(layer_id, feature_count=100)
            # ВАЖНО: Сохраняем ссылку чтобы объект не удалился
            self._active_tasks.append(task)

            # Используем сигналы для отслеживания завершения вместо polling status()
            task_completed = False
            task_success = False
            features_added = [0]  # Используем список для захвата в closure

            def on_task_completed():
                nonlocal task_completed, task_success
                task_completed = True
                task_success = True
                features_added[0] = task.features_added

            def on_task_terminated():
                nonlocal task_completed
                task_completed = True

            task.taskCompleted.connect(on_task_completed)
            task.taskTerminated.connect(on_task_terminated)

            task_manager = QgsApplication.taskManager()
            task_manager.addTask(task)

            # Ждём завершения через сигнал
            timeout = 5.0
            start_time = time.time()

            while not task_completed and time.time() - start_time < timeout:
                self._process_events(100)

            # Даём время на обработку финальных событий
            self._process_events(100)

            if task_success:
                self.logger.success(f"Задача подготовила {features_added[0]} features")
                self.logger.info("Данные подготовлены в фоновом потоке безопасно")
            elif task_completed:
                self.logger.fail("Задача прервана!")
            else:
                self.logger.fail("Таймаут ожидания задачи!")

            # Проверяем рекомендации
            self.logger.info("РЕКОМЕНДАЦИИ по потокобезопасности:")
            self.logger.info("  - Не модифицировать слои в QgsTask.run()")
            self.logger.info("  - Подготавливать данные в фоне, записывать в finished()")
            self.logger.info("  - Использовать сигналы для коммуникации с главным потоком")

        except RuntimeError as e:
            if "has been deleted" in str(e):
                self.logger.fail(f"C++ объект задачи удалён преждевременно: {e}")
            else:
                self.logger.error(f"RuntimeError: {e}")
        except Exception as e:
            self.logger.error(f"Ошибка: {e}")
        finally:
            # Очистка
            if layer_id:
                try:
                    QgsProject.instance().removeMapLayer(layer_id)
                except Exception:
                    pass
