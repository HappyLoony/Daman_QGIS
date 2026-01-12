# -*- coding: utf-8 -*-
"""
Субмодуль Fsm_5_2_T_3_1 - Тест функции F_3_1_Нарезка_ЗПР

Тестирует функцию нарезки зон планируемого размещения (ЗПР).
Нарезка выполняется по границам ЗУ и других слоёв (НП, МО, Лес, Вода).

Проверяет:
- Инициализацию модуля F_3_1_NarezkaZPR
- Структуру класса и наличие методов
- Делегирование в M_26_CuttingManager
- Константы слоёв (источники и цели)
"""

import tempfile
import os
import shutil


class TestF31:
    """Тесты для F_3_1_Нарезка_ЗПР"""

    def __init__(self, iface, logger):
        self.iface = iface
        self.logger = logger
        self.module = None
        self.test_dir = None

    def run_all_tests(self):
        self.logger.section("ТЕСТ F_3_1: Нарезка ЗПР")
        self.test_dir = tempfile.mkdtemp(prefix="qgis_test_f31_")

        try:
            self.test_01_import_module()
            self.test_02_check_structure()
            self.test_03_check_constants()
            self.test_04_check_cutting_manager()
        finally:
            if self.test_dir and os.path.exists(self.test_dir):
                try:
                    shutil.rmtree(self.test_dir)
                except Exception:
                    pass
        self.logger.summary()

    def test_01_import_module(self):
        """ТЕСТ 1: Импорт основного модуля F_3_1"""
        self.logger.section("1. Импорт F_3_1_NarezkaZPR")
        try:
            from Daman_QGIS.tools.F_3_cutting.F_3_1_narezka_zpr import F_3_1_NarezkaZPR
            self.module = F_3_1_NarezkaZPR(self.iface)
            self.logger.success("Модуль F_3_1_NarezkaZPR загружен")
        except ImportError as e:
            self.logger.fail(f"Ошибка импорта: {str(e)}")
        except Exception as e:
            self.logger.fail(f"Ошибка инициализации: {str(e)}")

    def test_02_check_structure(self):
        """ТЕСТ 2: Проверка структуры класса"""
        self.logger.section("2. Структура класса F_3_1_NarezkaZPR")

        if not self.module:
            self.logger.fail("Модуль не инициализирован")
            return

        # Проверка обязательных методов
        required_methods = [
            'run',
            'get_name',
            'set_plugin_dir',
            'set_layer_manager',
            'set_project_manager',
            '_execute_via_m26'
        ]

        for method in required_methods:
            if hasattr(self.module, method):
                self.logger.success(f"Метод {method}: найден")
            else:
                self.logger.fail(f"Метод {method}: НЕ найден")

    def test_03_check_constants(self):
        """ТЕСТ 3: Проверка констант слоёв"""
        self.logger.section("3. Константы слоёв нарезки")

        try:
            from Daman_QGIS.constants import (
                # Слои ЗПР (источники)
                LAYER_ZPR_OKS, LAYER_ZPR_PO, LAYER_ZPR_VO,
                # Слои выборки (границы нарезки)
                LAYER_SELECTION_ZU, LAYER_SELECTION_ZU_10M,
                # Выходные слои Раздел
                LAYER_CUTTING_OKS_RAZDEL, LAYER_CUTTING_PO_RAZDEL, LAYER_CUTTING_VO_RAZDEL,
                # Выходные слои НГС
                LAYER_CUTTING_OKS_NGS, LAYER_CUTTING_PO_NGS, LAYER_CUTTING_VO_NGS,
            )

            # Проверка слоёв ЗПР
            zpr_layers = [
                ('LAYER_ZPR_OKS', LAYER_ZPR_OKS),
                ('LAYER_ZPR_PO', LAYER_ZPR_PO),
                ('LAYER_ZPR_VO', LAYER_ZPR_VO),
            ]

            for const_name, const_value in zpr_layers:
                if const_value:
                    self.logger.success(f"{const_name}: {const_value}")
                else:
                    self.logger.fail(f"{const_name}: пустое значение")

            # Проверка слоёв выборки
            if LAYER_SELECTION_ZU:
                self.logger.success(f"LAYER_SELECTION_ZU: {LAYER_SELECTION_ZU}")
            else:
                self.logger.fail("LAYER_SELECTION_ZU: пустое значение")

            # Проверка выходных слоёв Раздел
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

            # Проверка выходных слоёв НГС
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

        except ImportError as e:
            self.logger.fail(f"Ошибка импорта констант: {e}")

    def test_04_check_cutting_manager(self):
        """ТЕСТ 4: Проверка M_26_CuttingManager"""
        self.logger.section("4. M_26_CuttingManager (делегирование)")

        try:
            from Daman_QGIS.managers import get_cutting_manager

            # Проверка функции получения менеджера
            self.logger.success("get_cutting_manager: импорт OK")

            # Проверка структуры CuttingManager
            from Daman_QGIS.managers.M_26_cutting_manager import CuttingManager

            required_methods = [
                'cut_all_zpr_types',
                'cut_zpr_layer',
            ]

            for method in required_methods:
                if hasattr(CuttingManager, method):
                    self.logger.success(f"CuttingManager.{method}: найден")
                else:
                    self.logger.warning(f"CuttingManager.{method}: не найден")

        except ImportError as e:
            self.logger.fail(f"Ошибка импорта CuttingManager: {e}")
        except Exception as e:
            self.logger.fail(f"Ошибка проверки CuttingManager: {e}")
