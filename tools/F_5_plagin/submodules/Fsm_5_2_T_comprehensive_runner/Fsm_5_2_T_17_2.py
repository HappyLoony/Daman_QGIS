# -*- coding: utf-8 -*-
"""
Fsm_5_2_T_17_2 - Тест Msm_17_2_progress_reporter

Проверяет корректную обработку RuntimeError при удалении Qt C++ объектов.
Это критическая проверка для асинхронных операций, когда Qt виджеты
(QProgressBar, QLabel, QgsMessageBarItem) могут быть удалены до завершения callback.

СЦЕНАРИЙ ОШИБКИ:
  1. MessageBarReporter создаёт progress_bar и label
  2. Пользователь закрывает message bar вручную (или QGIS очищает его)
  3. C++ объекты удаляются, но Python ссылки остаются
  4. Callback вызывает progress_bar.setValue() → RuntimeError

РЕШЕНИЕ (в Msm_17_2):
  try/except RuntimeError вокруг всех обращений к Qt виджетам
"""

from unittest.mock import MagicMock, PropertyMock


class TestProgressReporterRuntimeError:
    """Тест обработки RuntimeError в MessageBarReporter"""

    def __init__(self, iface, logger):
        """Инициализация теста"""
        self.iface = iface
        self.logger = logger

    def run_all_tests(self):
        """Запуск всех тестов"""
        self.logger.section("ТЕСТ Msm_17_2: ProgressReporter RuntimeError handling")

        self.test_01_import()
        self.test_02_update_with_deleted_widget()
        self.test_03_close_with_deleted_widget()
        self.test_04_silent_reporter()

        self.logger.summary()

    def test_01_import(self):
        """ТЕСТ 1: Импорт модуля"""
        self.logger.info("1. Проверка импорта Msm_17_2_progress_reporter")

        try:
            from Daman_QGIS.managers.submodules.Msm_17_2_progress_reporter import (
                MessageBarReporter,
                SilentReporter
            )
            self.logger.success("Импорт OK")
        except ImportError as e:
            self.logger.fail(f"Ошибка импорта: {e}")

    def test_02_update_with_deleted_widget(self):
        """ТЕСТ 2: update() с удалённым QProgressBar"""
        self.logger.info("2. Проверка update() с удалённым Qt объектом")

        try:
            from Daman_QGIS.managers.submodules.Msm_17_2_progress_reporter import MessageBarReporter

            # Создаём mock iface
            mock_iface = MagicMock()
            mock_message_bar = MagicMock()
            mock_iface.messageBar.return_value = mock_message_bar

            reporter = MessageBarReporter(mock_iface, "Test Operation")

            # Симулируем показанный reporter
            reporter._is_shown = True

            # Создаём mock progress_bar который выбрасывает RuntimeError
            mock_progress_bar = MagicMock()
            mock_progress_bar.setValue.side_effect = RuntimeError(
                "wrapped C/C++ object of type QProgressBar has been deleted"
            )
            reporter.progress_bar = mock_progress_bar

            # Создаём mock label
            mock_label = MagicMock()
            reporter.label = mock_label

            # Вызываем update() - НЕ должен падать!
            try:
                reporter.update(50, "Testing...")
                self.logger.success("update() корректно обработал RuntimeError")

                # Проверяем что состояние сброшено (update() должен был сбросить в None)
                if not reporter._is_shown and reporter.progress_bar is None:  # type: ignore[comparison-overlap]
                    self.logger.success("Состояние reporter сброшено после RuntimeError")
                else:
                    self.logger.fail("Состояние reporter НЕ сброшено после RuntimeError")

            except RuntimeError as e:
                self.logger.fail(f"update() НЕ обработал RuntimeError: {e}")

        except Exception as e:
            self.logger.fail(f"Ошибка теста: {e}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_03_close_with_deleted_widget(self):
        """ТЕСТ 3: close() с удалённым QgsMessageBarItem"""
        self.logger.info("3. Проверка close() с удалённым Qt объектом")

        try:
            from Daman_QGIS.managers.submodules.Msm_17_2_progress_reporter import MessageBarReporter

            # Создаём mock iface
            mock_iface = MagicMock()
            mock_message_bar = MagicMock()
            # popWidget выбрасывает RuntimeError (виджет уже удалён)
            mock_message_bar.popWidget.side_effect = RuntimeError(
                "wrapped C/C++ object of type QgsMessageBarItem has been deleted"
            )
            mock_iface.messageBar.return_value = mock_message_bar

            reporter = MessageBarReporter(mock_iface, "Test Operation")

            # Симулируем показанный reporter
            reporter._is_shown = True
            reporter.message_bar_item = MagicMock()
            reporter.progress_bar = MagicMock()
            reporter.label = MagicMock()

            # Вызываем close() - НЕ должен падать!
            try:
                reporter.close()
                self.logger.success("close() корректно обработал RuntimeError")

                # Проверяем что состояние сброшено (close() должен был сбросить в None)
                if not reporter._is_shown and reporter.message_bar_item is None:  # type: ignore[comparison-overlap]
                    self.logger.success("Состояние reporter сброшено после close()")
                else:
                    self.logger.fail("Состояние reporter НЕ сброшено после close()")

            except RuntimeError as e:
                self.logger.fail(f"close() НЕ обработал RuntimeError: {e}")

        except Exception as e:
            self.logger.fail(f"Ошибка теста: {e}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_04_silent_reporter(self):
        """ТЕСТ 4: SilentReporter (no-op реализация)"""
        self.logger.info("4. Проверка SilentReporter (no-op)")

        try:
            from Daman_QGIS.managers.submodules.Msm_17_2_progress_reporter import SilentReporter

            reporter = SilentReporter()

            # Все методы должны работать без ошибок
            reporter.show()
            reporter.update(50, "Test")
            reporter.close()
            reporter.set_completed(True, "Done")

            self.logger.success("SilentReporter работает корректно")

        except Exception as e:
            self.logger.fail(f"Ошибка SilentReporter: {e}")
