# -*- coding: utf-8 -*-
"""
Субмодуль Fsm_5_2_T_3_2 - Тест функции F_3_2_Без_Меж

Тестирует функцию переноса ЗУ в слои "Без межевания".
ЗУ Без межевания - существующие участки, не требующие межевых работ.

Проверяет:
- Инициализацию модуля F_3_2_BezMezh
- Маппинг Раздел -> Без_Меж
- Структуру субмодулей (Dialog, Transfer)
- Константы слоёв
"""

import tempfile
import os
import shutil


class TestF32:
    """Тесты для F_3_2_Без_Меж"""

    def __init__(self, iface, logger):
        self.iface = iface
        self.logger = logger
        self.module = None
        self.test_dir = None

    def run_all_tests(self):
        self.logger.section("ТЕСТ F_3_2: Без межевания")
        self.test_dir = tempfile.mkdtemp(prefix="qgis_test_f32_")

        try:
            self.test_01_import_module()
            self.test_02_check_structure()
            self.test_03_check_submodules()
            self.test_04_check_layer_mapping()
            self.test_05_check_constants()
        finally:
            if self.test_dir and os.path.exists(self.test_dir):
                try:
                    shutil.rmtree(self.test_dir)
                except Exception:
                    pass
        self.logger.summary()

    def test_01_import_module(self):
        """ТЕСТ 1: Импорт основного модуля F_3_2"""
        self.logger.section("1. Импорт F_3_2_BezMezh")
        try:
            from Daman_QGIS.tools.F_3_cutting.F_3_2_bez_mezh import F_3_2_BezMezh
            self.module = F_3_2_BezMezh(self.iface)
            self.logger.success("Модуль F_3_2_BezMezh загружен")
        except ImportError as e:
            self.logger.fail(f"Ошибка импорта: {str(e)}")
        except Exception as e:
            self.logger.fail(f"Ошибка инициализации: {str(e)}")

    def test_02_check_structure(self):
        """ТЕСТ 2: Проверка структуры класса"""
        self.logger.section("2. Структура класса F_3_2_BezMezh")

        if not self.module:
            self.logger.fail("Модуль не инициализирован")
            return

        # Проверка обязательных методов
        required_methods = [
            'run',
            'get_name',
            'set_plugin_dir',
            'set_layer_manager',
            '_find_razdel_layers',
            '_show_dialog',
            '_on_transfer',
        ]

        for method in required_methods:
            if hasattr(self.module, method):
                self.logger.success(f"Метод {method}: найден")
            else:
                self.logger.fail(f"Метод {method}: НЕ найден")

        # Проверка атрибутов
        if hasattr(self.module, 'RAZDEL_TO_BEZ_MEZH'):
            mapping = self.module.RAZDEL_TO_BEZ_MEZH
            self.logger.success(f"RAZDEL_TO_BEZ_MEZH: {len(mapping)} маппингов")
        else:
            self.logger.fail("RAZDEL_TO_BEZ_MEZH: НЕ найден")

        if hasattr(self.module, 'WORK_TYPE_BEZ_MEZH'):
            self.logger.success(f"WORK_TYPE_BEZ_MEZH: {self.module.WORK_TYPE_BEZ_MEZH}")
        else:
            self.logger.fail("WORK_TYPE_BEZ_MEZH: НЕ найден")

    def test_03_check_submodules(self):
        """ТЕСТ 3: Проверка импорта субмодулей"""
        self.logger.section("3. Субмодули F_3_2")

        # Fsm_3_2_1_Dialog
        try:
            from Daman_QGIS.tools.F_3_cutting.submodules.Fsm_3_2_1_dialog import (
                Fsm_3_2_1_Dialog
            )
            self.logger.success("Fsm_3_2_1_Dialog: импорт OK")
        except ImportError as e:
            self.logger.fail(f"Fsm_3_2_1_Dialog: ошибка импорта - {e}")

        # Fsm_3_2_2_Transfer
        try:
            from Daman_QGIS.tools.F_3_cutting.submodules.Fsm_3_2_2_transfer import (
                Fsm_3_2_2_Transfer
            )
            self.logger.success("Fsm_3_2_2_Transfer: импорт OK")
        except ImportError as e:
            self.logger.fail(f"Fsm_3_2_2_Transfer: ошибка импорта - {e}")

    def test_04_check_layer_mapping(self):
        """ТЕСТ 4: Проверка маппинга Раздел -> Без_Меж"""
        self.logger.section("4. Маппинг слоёв Раздел -> Без_Меж")

        if not self.module:
            self.logger.fail("Модуль не инициализирован")
            return

        mapping = getattr(self.module, 'RAZDEL_TO_BEZ_MEZH', {})

        if not mapping:
            self.logger.fail("Маппинг пустой")
            return

        for source, target in mapping.items():
            if 'Раздел' in source and 'Без_Меж' in target:
                self.logger.success(f"{source} -> {target}")
            else:
                self.logger.warning(f"Неожиданный маппинг: {source} -> {target}")

    def test_05_check_constants(self):
        """ТЕСТ 5: Проверка констант слоёв"""
        self.logger.section("5. Константы слоёв Раздел и Без_Меж")

        try:
            from Daman_QGIS.constants import (
                # Слои Раздел (источники)
                LAYER_CUTTING_OKS_RAZDEL,
                LAYER_CUTTING_PO_RAZDEL,
                LAYER_CUTTING_VO_RAZDEL,
                # Слои Без_Меж (цели)
                LAYER_CUTTING_OKS_BEZ_MEZH,
                LAYER_CUTTING_PO_BEZ_MEZH,
                LAYER_CUTTING_VO_BEZ_MEZH,
            )

            # Проверка слоёв Раздел
            razdel_layers = [
                ('LAYER_CUTTING_OKS_RAZDEL', LAYER_CUTTING_OKS_RAZDEL),
                ('LAYER_CUTTING_PO_RAZDEL', LAYER_CUTTING_PO_RAZDEL),
                ('LAYER_CUTTING_VO_RAZDEL', LAYER_CUTTING_VO_RAZDEL),
            ]

            for const_name, const_value in razdel_layers:
                if const_value and 'Раздел' in const_value:
                    self.logger.success(f"{const_name}: {const_value}")
                else:
                    self.logger.fail(f"{const_name}: неожиданное значение - {const_value}")

            # Проверка слоёв Без_Меж
            bez_mezh_layers = [
                ('LAYER_CUTTING_OKS_BEZ_MEZH', LAYER_CUTTING_OKS_BEZ_MEZH),
                ('LAYER_CUTTING_PO_BEZ_MEZH', LAYER_CUTTING_PO_BEZ_MEZH),
                ('LAYER_CUTTING_VO_BEZ_MEZH', LAYER_CUTTING_VO_BEZ_MEZH),
            ]

            for const_name, const_value in bez_mezh_layers:
                if const_value and 'Без_Меж' in const_value:
                    self.logger.success(f"{const_name}: {const_value}")
                else:
                    self.logger.fail(f"{const_name}: неожиданное значение - {const_value}")

        except ImportError as e:
            self.logger.fail(f"Ошибка импорта констант: {e}")
