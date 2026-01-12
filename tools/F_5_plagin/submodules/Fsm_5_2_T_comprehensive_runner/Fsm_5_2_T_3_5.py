# -*- coding: utf-8 -*-
"""
Субмодуль Fsm_5_2_T_3_5 - Тест функции F_3_5_Изъятие

Тестирует функцию отбора ЗУ для изъятия под гос./муниц. нужды.
Проверяет:
- Инициализацию модуля и субмодулей
- Список слоёв-источников (Раздел + НГС)
- Структуру диалога Fsm_3_5_1_Dialog
- Логику переноса Fsm_3_5_2_Transfer
"""

import tempfile
import os
import shutil


class TestF35:
    """Тесты для F_3_5_Изъятие"""

    def __init__(self, iface, logger):
        self.iface = iface
        self.logger = logger
        self.module = None
        self.test_dir = None

    def run_all_tests(self):
        self.logger.section("ТЕСТ F_3_5: Изъятие ЗУ")
        self.test_dir = tempfile.mkdtemp(prefix="qgis_test_f35_")

        try:
            self.test_01_import_module()
            self.test_02_check_structure()
            self.test_03_check_submodules()
            self.test_04_check_source_layers()
            self.test_05_check_dialog()
            self.test_06_check_transfer()
        finally:
            if self.test_dir and os.path.exists(self.test_dir):
                try:
                    shutil.rmtree(self.test_dir)
                except Exception:
                    pass
        self.logger.summary()

    def test_01_import_module(self):
        """ТЕСТ 1: Импорт основного модуля F_3_5"""
        self.logger.section("1. Импорт F_3_5_Izyatie")
        try:
            from Daman_QGIS.tools.F_3_cutting.F_3_5_izyatie import F_3_5_Izyatie
            self.module = F_3_5_Izyatie(self.iface)
            self.logger.success("Модуль F_3_5_Izyatie загружен")
        except ImportError as e:
            self.logger.fail(f"Ошибка импорта: {str(e)}")
        except Exception as e:
            self.logger.fail(f"Ошибка инициализации: {str(e)}")

    def test_02_check_structure(self):
        """ТЕСТ 2: Проверка структуры класса"""
        self.logger.section("2. Структура класса F_3_5_Izyatie")

        if not self.module:
            self.logger.fail("Модуль не инициализирован")
            return

        # Проверка обязательных методов
        required_methods = [
            'run',
            'get_name',
            'set_plugin_dir',
            'set_layer_manager',
            '_find_source_layers',
            '_show_dialog',
            '_on_transfer',
            '_refresh_layers'
        ]

        for method in required_methods:
            if hasattr(self.module, method):
                self.logger.success(f"Метод {method}: найден")
            else:
                self.logger.fail(f"Метод {method}: НЕ найден")

        # Проверка атрибута SOURCE_LAYERS
        if hasattr(self.module, 'SOURCE_LAYERS'):
            source_layers = self.module.SOURCE_LAYERS
            self.logger.success(f"SOURCE_LAYERS: {len(source_layers)} слоёв")
        else:
            self.logger.fail("SOURCE_LAYERS: НЕ найден")

    def test_03_check_submodules(self):
        """ТЕСТ 3: Проверка импорта субмодулей"""
        self.logger.section("3. Субмодули F_3_5")

        # Fsm_3_5_1_Dialog
        try:
            from Daman_QGIS.tools.F_3_cutting.submodules.Fsm_3_5_1_dialog import (
                Fsm_3_5_1_Dialog
            )
            self.logger.success("Fsm_3_5_1_Dialog: импорт OK")
        except ImportError as e:
            self.logger.fail(f"Fsm_3_5_1_Dialog: ошибка импорта - {e}")

        # Fsm_3_5_2_Transfer
        try:
            from Daman_QGIS.tools.F_3_cutting.submodules.Fsm_3_5_2_transfer import (
                Fsm_3_5_2_Transfer
            )
            self.logger.success("Fsm_3_5_2_Transfer: импорт OK")
        except ImportError as e:
            self.logger.fail(f"Fsm_3_5_2_Transfer: ошибка импорта - {e}")

    def test_04_check_source_layers(self):
        """ТЕСТ 4: Проверка списка слоёв-источников"""
        self.logger.section("4. Слои-источники (Раздел + НГС)")

        try:
            from Daman_QGIS.constants import (
                LAYER_CUTTING_OKS_RAZDEL,
                LAYER_CUTTING_PO_RAZDEL,
                LAYER_CUTTING_VO_RAZDEL,
                LAYER_CUTTING_OKS_NGS,
                LAYER_CUTTING_PO_NGS,
                LAYER_CUTTING_VO_NGS,
                LAYER_IZYATIE_ZU
            )

            # Проверка констант слоёв Раздел
            razdel_layers = [
                ('LAYER_CUTTING_OKS_RAZDEL', LAYER_CUTTING_OKS_RAZDEL),
                ('LAYER_CUTTING_PO_RAZDEL', LAYER_CUTTING_PO_RAZDEL),
                ('LAYER_CUTTING_VO_RAZDEL', LAYER_CUTTING_VO_RAZDEL),
            ]

            for const_name, const_value in razdel_layers:
                if const_value and 'Раздел' in const_value:
                    self.logger.success(f"{const_name}: {const_value}")
                else:
                    self.logger.warning(f"{const_name}: неожиданное значение - {const_value}")

            # Проверка констант слоёв НГС
            ngs_layers = [
                ('LAYER_CUTTING_OKS_NGS', LAYER_CUTTING_OKS_NGS),
                ('LAYER_CUTTING_PO_NGS', LAYER_CUTTING_PO_NGS),
                ('LAYER_CUTTING_VO_NGS', LAYER_CUTTING_VO_NGS),
            ]

            for const_name, const_value in ngs_layers:
                if const_value and 'НГС' in const_value:
                    self.logger.success(f"{const_name}: {const_value}")
                else:
                    self.logger.warning(f"{const_name}: неожиданное значение - {const_value}")

            # Проверка целевого слоя изъятия
            if LAYER_IZYATIE_ZU and 'Изъятие' in LAYER_IZYATIE_ZU:
                self.logger.success(f"LAYER_IZYATIE_ZU: {LAYER_IZYATIE_ZU}")
            else:
                self.logger.fail(f"LAYER_IZYATIE_ZU: неверное значение - {LAYER_IZYATIE_ZU}")

        except ImportError as e:
            self.logger.fail(f"Ошибка импорта констант: {e}")

    def test_05_check_dialog(self):
        """ТЕСТ 5: Проверка структуры диалога Fsm_3_5_1_Dialog"""
        self.logger.section("5. Структура Fsm_3_5_1_Dialog")

        try:
            from Daman_QGIS.tools.F_3_cutting.submodules.Fsm_3_5_1_dialog import (
                Fsm_3_5_1_Dialog
            )

            # Проверка наличия ключевых методов диалога
            dialog_methods = [
                '__init__',
                'exec_',  # Qt метод запуска диалога
            ]

            for method in dialog_methods:
                if hasattr(Fsm_3_5_1_Dialog, method):
                    self.logger.success(f"Метод {method}: найден")
                else:
                    self.logger.warning(f"Метод {method}: не найден")

            # Проверка базового класса
            from qgis.PyQt.QtWidgets import QDialog
            if issubclass(Fsm_3_5_1_Dialog, QDialog):
                self.logger.success("Базовый класс: QDialog")
            else:
                self.logger.warning("Базовый класс: не QDialog")

        except Exception as e:
            self.logger.fail(f"Ошибка проверки диалога: {e}")

    def test_06_check_transfer(self):
        """ТЕСТ 6: Проверка структуры Fsm_3_5_2_Transfer"""
        self.logger.section("6. Структура Fsm_3_5_2_Transfer")

        try:
            from Daman_QGIS.tools.F_3_cutting.submodules.Fsm_3_5_2_transfer import (
                Fsm_3_5_2_Transfer
            )

            # Проверка наличия ключевых методов переноса
            transfer_methods = [
                '__init__',
                'execute',  # Основной метод переноса
            ]

            for method in transfer_methods:
                if hasattr(Fsm_3_5_2_Transfer, method):
                    self.logger.success(f"Метод {method}: найден")
                else:
                    self.logger.fail(f"Метод {method}: НЕ найден")

            # Проверка исходного кода на ключевые паттерны
            import inspect
            source_code = inspect.getsource(Fsm_3_5_2_Transfer)

            patterns = {
                'def execute': 'Метод execute',
                'duplicates': 'Проверка дубликатов',
                'copied': 'Счётчик скопированных',
            }

            for pattern, description in patterns.items():
                if pattern in source_code:
                    self.logger.success(f"{description}: реализован")
                else:
                    self.logger.warning(f"{description}: не найден в коде")

        except Exception as e:
            self.logger.fail(f"Ошибка проверки Transfer: {e}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())
