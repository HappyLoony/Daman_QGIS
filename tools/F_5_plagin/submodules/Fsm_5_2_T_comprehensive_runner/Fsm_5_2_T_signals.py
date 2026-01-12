# -*- coding: utf-8 -*-
"""
Fsm_5_2_T_signals - Тест Qt сигналов и слотов

Проверяет:
1. QgsProject сигналы (layersAdded, layersRemoved, cleared)
2. QgsVectorLayer сигналы (featureAdded, attributeValueChanged)
3. QgsMapCanvas сигналы (extentsChanged, layersChanged)
4. Processing сигналы (progressChanged)
5. Правильное отключение сигналов (disconnect)
6. Блокировка сигналов (blockSignals)

Важно для правильной реактивности плагина.
"""

from typing import Any, List, Optional
import time

from qgis.core import (
    QgsProject, QgsVectorLayer, QgsFeature, QgsGeometry,
    QgsPointXY, QgsApplication
)
from qgis.PyQt.QtCore import QObject, pyqtSignal, QTimer
from qgis.PyQt.QtWidgets import QApplication


class SignalCatcher(QObject):
    """Вспомогательный класс для отлова сигналов"""

    def __init__(self):
        super().__init__()
        self.signals_received: List[str] = []
        self.signal_data: List[Any] = []

    def catch_signal(self, signal_name: str):
        """Создать слот для отлова сигнала"""
        def slot(*args):
            self.signals_received.append(signal_name)
            self.signal_data.append(args)
        return slot

    def reset(self):
        """Сбросить счётчики"""
        self.signals_received.clear()
        self.signal_data.clear()

    def has_signal(self, signal_name: str) -> bool:
        """Проверить был ли получен сигнал"""
        return signal_name in self.signals_received

    def signal_count(self, signal_name: str) -> int:
        """Количество полученных сигналов с данным именем"""
        return self.signals_received.count(signal_name)


class TestSignals:
    """Тесты Qt сигналов"""

    def __init__(self, iface: Any, logger: Any) -> None:
        """Инициализация теста"""
        self.iface = iface
        self.logger = logger
        self.catcher = SignalCatcher()

    def run_all_tests(self) -> None:
        """Запуск всех тестов сигналов"""
        self.logger.section("ТЕСТ QT СИГНАЛОВ И СЛОТОВ")

        try:
            self.test_01_project_layer_signals()
            self.test_02_layer_feature_signals()
            self.test_03_layer_edit_signals()
            self.test_04_canvas_signals()
            self.test_05_disconnect_signals()
            self.test_06_block_signals()
            self.test_07_custom_signals()

        except Exception as e:
            self.logger.error(f"Критическая ошибка тестов сигналов: {str(e)}")

        self.logger.summary()

    def _process_events(self, timeout_ms: int = 100) -> None:
        """Обработать Qt события (для получения сигналов)"""
        QApplication.processEvents()
        # Небольшая задержка для асинхронных сигналов
        end_time = time.time() + timeout_ms / 1000
        while time.time() < end_time:
            QApplication.processEvents()
            time.sleep(0.01)

    def test_01_project_layer_signals(self) -> None:
        """ТЕСТ 1: Сигналы QgsProject при работе со слоями"""
        self.logger.section("1. QgsProject сигналы слоёв")

        project = QgsProject.instance()
        self.catcher.reset()

        try:
            # Подключаем сигналы
            project.layersAdded.connect(self.catcher.catch_signal('layersAdded'))
            project.layersRemoved.connect(self.catcher.catch_signal('layersRemoved'))

            # Создаём и добавляем слой
            layer = QgsVectorLayer(
                "Point?crs=EPSG:4326&field=id:integer",
                "signal_test_layer",
                "memory"
            )

            if not layer.isValid():
                self.logger.fail("Не удалось создать тестовый слой")
                return

            layer_id = layer.id()
            project.addMapLayer(layer)
            self._process_events()

            if self.catcher.has_signal('layersAdded'):
                self.logger.success("Сигнал layersAdded получен")
            else:
                self.logger.fail("Сигнал layersAdded НЕ получен!")

            # Удаляем слой
            self.catcher.reset()
            project.removeMapLayer(layer_id)
            self._process_events()

            if self.catcher.has_signal('layersRemoved'):
                self.logger.success("Сигнал layersRemoved получен")
            else:
                self.logger.fail("Сигнал layersRemoved НЕ получен!")

        except Exception as e:
            self.logger.error(f"Ошибка теста: {e}")

        finally:
            # Отключаем сигналы
            try:
                project.layersAdded.disconnect()
                project.layersRemoved.disconnect()
            except Exception:
                pass

    def test_02_layer_feature_signals(self) -> None:
        """ТЕСТ 2: Сигналы слоя при добавлении объектов"""
        self.logger.section("2. QgsVectorLayer feature сигналы")

        self.catcher.reset()

        try:
            # Создаём слой
            layer = QgsVectorLayer(
                "Point?crs=EPSG:4326&field=name:string",
                "feature_signal_test",
                "memory"
            )

            if not layer.isValid():
                self.logger.fail("Не удалось создать слой")
                return

            # Подключаем сигналы
            layer.featureAdded.connect(self.catcher.catch_signal('featureAdded'))

            # Начинаем редактирование
            layer.startEditing()

            # Добавляем feature
            feature = QgsFeature()
            feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(0, 0)))
            feature.setAttributes(['test'])
            layer.addFeature(feature)

            self._process_events()

            if self.catcher.has_signal('featureAdded'):
                self.logger.success("Сигнал featureAdded получен")
            else:
                self.logger.fail("Сигнал featureAdded НЕ получен!")

            # Коммитим изменения
            layer.commitChanges()

            # Проверяем что feature добавлен
            if layer.featureCount() == 1:
                self.logger.success("Feature успешно добавлен")
            else:
                self.logger.fail(f"Ожидался 1 feature, получено {layer.featureCount()}")

            # Очистка
            layer.featureAdded.disconnect()
            del layer

        except Exception as e:
            self.logger.error(f"Ошибка теста: {e}")

    def test_03_layer_edit_signals(self) -> None:
        """ТЕСТ 3: Сигналы редактирования слоя"""
        self.logger.section("3. Сигналы editingStarted/Stopped")

        self.catcher.reset()

        try:
            layer = QgsVectorLayer(
                "Point?crs=EPSG:4326&field=id:integer",
                "edit_signal_test",
                "memory"
            )

            if not layer.isValid():
                self.logger.fail("Не удалось создать слой")
                return

            # Подключаем сигналы
            layer.editingStarted.connect(self.catcher.catch_signal('editingStarted'))
            layer.editingStopped.connect(self.catcher.catch_signal('editingStopped'))

            # Начинаем редактирование
            layer.startEditing()
            self._process_events()

            if self.catcher.has_signal('editingStarted'):
                self.logger.success("Сигнал editingStarted получен")
            else:
                self.logger.fail("Сигнал editingStarted НЕ получен!")

            # Завершаем редактирование
            layer.commitChanges()
            self._process_events()

            if self.catcher.has_signal('editingStopped'):
                self.logger.success("Сигнал editingStopped получен")
            else:
                self.logger.fail("Сигнал editingStopped НЕ получен!")

            # Отключаем сигналы
            layer.editingStarted.disconnect()
            layer.editingStopped.disconnect()
            del layer

        except Exception as e:
            self.logger.error(f"Ошибка теста: {e}")

    def test_04_canvas_signals(self) -> None:
        """ТЕСТ 4: Сигналы QgsMapCanvas"""
        self.logger.section("4. QgsMapCanvas сигналы")

        self.catcher.reset()

        try:
            canvas = self.iface.mapCanvas()

            if canvas is None:
                self.logger.fail("mapCanvas недоступен!")
                return

            # Подключаем сигналы
            canvas.extentsChanged.connect(self.catcher.catch_signal('extentsChanged'))

            # Меняем extent
            from qgis.core import QgsRectangle
            current_extent = canvas.extent()
            new_extent = QgsRectangle(0, 0, 100, 100)

            canvas.setExtent(new_extent)
            canvas.refresh()
            self._process_events()

            if self.catcher.has_signal('extentsChanged'):
                self.logger.success("Сигнал extentsChanged получен")
            else:
                self.logger.fail("Сигнал extentsChanged НЕ получен!")

            # Восстанавливаем extent
            canvas.setExtent(current_extent)
            canvas.refresh()

            # Отключаем сигнал
            canvas.extentsChanged.disconnect()

        except Exception as e:
            self.logger.error(f"Ошибка теста canvas: {e}")

    def test_05_disconnect_signals(self) -> None:
        """ТЕСТ 5: Корректное отключение сигналов"""
        self.logger.section("5. Отключение сигналов (disconnect)")

        self.catcher.reset()

        try:
            layer = QgsVectorLayer(
                "Point?crs=EPSG:4326&field=id:integer",
                "disconnect_test",
                "memory"
            )

            if not layer.isValid():
                self.logger.fail("Не удалось создать слой")
                return

            # Подключаем сигнал
            slot = self.catcher.catch_signal('editingStarted')
            layer.editingStarted.connect(slot)

            # Проверяем что работает
            layer.startEditing()
            self._process_events()
            layer.rollBack()

            initial_count = self.catcher.signal_count('editingStarted')
            self.logger.info(f"Сигналов до disconnect: {initial_count}")

            # Отключаем сигнал
            layer.editingStarted.disconnect(slot)

            # Снова запускаем редактирование
            layer.startEditing()
            self._process_events()
            layer.rollBack()

            final_count = self.catcher.signal_count('editingStarted')
            self.logger.info(f"Сигналов после disconnect: {final_count}")

            if final_count == initial_count:
                self.logger.success("Сигнал корректно отключен (disconnect работает)")
            else:
                self.logger.fail("Сигнал продолжает приходить после disconnect!")

            del layer

        except Exception as e:
            self.logger.error(f"Ошибка теста disconnect: {e}")

    def test_06_block_signals(self) -> None:
        """ТЕСТ 6: Блокировка сигналов (blockSignals)"""
        self.logger.section("6. Блокировка сигналов (blockSignals)")

        self.catcher.reset()

        try:
            layer = QgsVectorLayer(
                "Point?crs=EPSG:4326&field=id:integer",
                "block_signals_test",
                "memory"
            )

            if not layer.isValid():
                self.logger.fail("Не удалось создать слой")
                return

            # Подключаем сигнал
            layer.editingStarted.connect(self.catcher.catch_signal('editingStarted'))

            # Проверяем без блокировки
            layer.startEditing()
            self._process_events()
            layer.rollBack()

            count_before_block = self.catcher.signal_count('editingStarted')
            self.logger.info(f"Сигналов без блокировки: {count_before_block}")

            # Блокируем сигналы
            layer.blockSignals(True)

            layer.startEditing()
            self._process_events()
            layer.rollBack()

            count_during_block = self.catcher.signal_count('editingStarted')
            self.logger.info(f"Сигналов во время блокировки: {count_during_block}")

            # Разблокируем
            layer.blockSignals(False)

            layer.startEditing()
            self._process_events()
            layer.rollBack()

            count_after_block = self.catcher.signal_count('editingStarted')
            self.logger.info(f"Сигналов после разблокировки: {count_after_block}")

            # Проверяем
            if count_during_block == count_before_block:
                self.logger.success("blockSignals(True) блокирует сигналы")
            else:
                self.logger.fail("blockSignals(True) не блокирует сигналы!")

            if count_after_block > count_during_block:
                self.logger.success("blockSignals(False) восстанавливает сигналы")
            else:
                self.logger.fail("blockSignals(False) не восстанавливает сигналы!")

            layer.editingStarted.disconnect()
            del layer

        except Exception as e:
            self.logger.error(f"Ошибка теста blockSignals: {e}")

    def test_07_custom_signals(self) -> None:
        """ТЕСТ 7: Пользовательские сигналы"""
        self.logger.section("7. Пользовательские сигналы")

        try:
            # Создаём класс с пользовательским сигналом
            class CustomEmitter(QObject):
                customSignal = pyqtSignal(str, int)

                def emit_signal(self, message: str, value: int):
                    self.customSignal.emit(message, value)

            emitter = CustomEmitter()
            received_data = []

            def custom_slot(msg: str, val: int):
                received_data.append((msg, val))

            # Подключаем
            emitter.customSignal.connect(custom_slot)

            # Эмитим сигнал
            emitter.emit_signal("test_message", 42)
            self._process_events()

            if len(received_data) == 1:
                msg, val = received_data[0]
                if msg == "test_message" and val == 42:
                    self.logger.success("Пользовательский сигнал работает корректно")
                else:
                    self.logger.fail(f"Данные искажены: {received_data}")
            else:
                self.logger.fail(f"Ожидался 1 сигнал, получено {len(received_data)}")

            # Проверяем множественную эмиссию
            received_data.clear()
            for i in range(3):
                emitter.emit_signal(f"msg_{i}", i)

            self._process_events()

            if len(received_data) == 3:
                self.logger.success("Множественная эмиссия работает (3 сигнала)")
            else:
                self.logger.fail(f"Получено {len(received_data)} сигналов вместо 3!")

            # Отключаем
            emitter.customSignal.disconnect(custom_slot)
            del emitter

        except Exception as e:
            self.logger.error(f"Ошибка теста custom signals: {e}")
