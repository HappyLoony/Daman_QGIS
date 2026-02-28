# -*- coding: utf-8 -*-
"""
Субмодуль Fsm_4_2_T_3_2 - Тест функции F_2_2_Без_Меж

Тестирует функцию переноса ЗУ в слои "Без межевания".
ЗУ Без межевания - существующие участки, не требующие межевых работ.

Проверяет:
- Инициализацию модуля F_2_2_BezMezh
- Двухступенчатый маппинг слой -> тип ЗПР -> Без_Меж
- Структуру субмодулей (Dialog, Transfer)
- Константы слоёв
- Метод _finalize_layer
- Использование safe_refresh
- Поле Точки = '-' в Fsm_2_2_2_Transfer
"""

import tempfile
import os
import shutil


class TestF32:
    """Тесты для F_2_2_Без_Меж"""

    def __init__(self, iface, logger):
        self.iface = iface
        self.logger = logger
        self.module = None
        self.test_dir = None

    def run_all_tests(self):
        self.logger.section("ТЕСТ F_2_2: Без межевания")
        self.test_dir = tempfile.mkdtemp(prefix="qgis_test_f32_")

        try:
            self.test_01_import_module()
            self.test_02_check_structure()
            self.test_03_check_submodules()
            self.test_04_check_layer_mapping()
            self.test_05_check_constants()
            # Новые тесты
            self.test_06_finalize_layer_method()
            self.test_07_refresh_layers_uses_safe_refresh()
            self.test_08_transfer_tochki_field()
            self.test_09_transfer_fid_diagnostics()
        finally:
            if self.test_dir and os.path.exists(self.test_dir):
                try:
                    shutil.rmtree(self.test_dir)
                except Exception:
                    pass
        self.logger.summary()

    def test_01_import_module(self):
        """ТЕСТ 1: Импорт основного модуля F_2_2"""
        self.logger.section("1. Импорт F_2_2_BezMezh")
        try:
            from Daman_QGIS.tools.F_2_cutting.F_2_2_bez_mezh import F_2_2_BezMezh
            self.module = F_2_2_BezMezh(self.iface)
            self.logger.success("Модуль F_2_2_BezMezh загружен")
        except ImportError as e:
            self.logger.fail(f"Ошибка импорта: {str(e)}")
        except Exception as e:
            self.logger.fail(f"Ошибка инициализации: {str(e)}")

    def test_02_check_structure(self):
        """ТЕСТ 2: Проверка структуры класса"""
        self.logger.section("2. Структура класса F_2_2_BezMezh")

        if not self.module:
            self.logger.fail("Модуль не инициализирован")
            return

        # Проверка обязательных методов
        required_methods = [
            'run',
            'get_name',
            'set_plugin_dir',
            'set_layer_manager',
            '_find_cutting_layers',
            '_show_dialog',
            '_on_transfer',
        ]

        for method in required_methods:
            if hasattr(self.module, method):
                self.logger.success(f"Метод {method}: найден")
            else:
                self.logger.fail(f"Метод {method}: НЕ найден")

        # Проверка атрибутов двухступенчатого маппинга
        if hasattr(self.module, 'LAYER_TO_ZPR_TYPE'):
            mapping = self.module.LAYER_TO_ZPR_TYPE
            self.logger.success(f"LAYER_TO_ZPR_TYPE: {len(mapping)} маппингов")
        else:
            self.logger.fail("LAYER_TO_ZPR_TYPE: НЕ найден")

        if hasattr(self.module, 'ZPR_TYPE_TO_BEZ_MEZH'):
            mapping = self.module.ZPR_TYPE_TO_BEZ_MEZH
            self.logger.success(f"ZPR_TYPE_TO_BEZ_MEZH: {len(mapping)} маппингов")
        else:
            self.logger.fail("ZPR_TYPE_TO_BEZ_MEZH: НЕ найден")

        if hasattr(self.module, 'WORK_TYPE_BEZ_MEZH'):
            self.logger.success(f"WORK_TYPE_BEZ_MEZH: {self.module.WORK_TYPE_BEZ_MEZH}")
        else:
            self.logger.fail("WORK_TYPE_BEZ_MEZH: НЕ найден")

    def test_03_check_submodules(self):
        """ТЕСТ 3: Проверка импорта субмодулей"""
        self.logger.section("3. Субмодули F_2_2")

        # Fsm_2_2_1_Dialog
        try:
            from Daman_QGIS.tools.F_2_cutting.submodules.Fsm_2_2_1_dialog import (
                Fsm_2_2_1_Dialog
            )
            self.logger.success("Fsm_2_2_1_Dialog: импорт OK")
        except ImportError as e:
            self.logger.fail(f"Fsm_2_2_1_Dialog: ошибка импорта - {e}")

        # Fsm_2_2_2_Transfer
        try:
            from Daman_QGIS.tools.F_2_cutting.submodules.Fsm_2_2_2_transfer import (
                Fsm_2_2_2_Transfer
            )
            self.logger.success("Fsm_2_2_2_Transfer: импорт OK")
        except ImportError as e:
            self.logger.fail(f"Fsm_2_2_2_Transfer: ошибка импорта - {e}")

    def test_04_check_layer_mapping(self):
        """ТЕСТ 4: Проверка двухступенчатого маппинга слой -> ЗПР -> Без_Меж"""
        self.logger.section("4. Маппинг слоёв -> ЗПР тип -> Без_Меж")

        if not self.module:
            self.logger.fail("Модуль не инициализирован")
            return

        layer_to_zpr = getattr(self.module, 'LAYER_TO_ZPR_TYPE', {})
        zpr_to_bez = getattr(self.module, 'ZPR_TYPE_TO_BEZ_MEZH', {})

        if not layer_to_zpr:
            self.logger.fail("LAYER_TO_ZPR_TYPE пустой")
            return

        if not zpr_to_bez:
            self.logger.fail("ZPR_TYPE_TO_BEZ_MEZH пустой")
            return

        # Проверяем цепочку маппинга для каждого типа ЗПР
        for zpr_type, bez_mezh_layer in zpr_to_bez.items():
            if 'Без_Меж' in bez_mezh_layer:
                self.logger.success(f"ЗПР '{zpr_type}' -> {bez_mezh_layer}")
            else:
                self.logger.warning(f"Неожиданный маппинг ЗПР: {zpr_type} -> {bez_mezh_layer}")

        # Проверяем что все слои Раздел/Изм имеют тип ЗПР
        for layer_name, zpr_type in layer_to_zpr.items():
            if zpr_type in zpr_to_bez:
                self.logger.success(f"{layer_name} -> '{zpr_type}' -> {zpr_to_bez[zpr_type]}")
            else:
                self.logger.fail(f"Тип ЗПР '{zpr_type}' не найден в ZPR_TYPE_TO_BEZ_MEZH")

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

    def test_06_finalize_layer_method(self):
        """ТЕСТ 6: Проверка метода _finalize_layer"""
        self.logger.section("6. Метод _finalize_layer")

        if not self.module:
            self.logger.fail("Модуль не инициализирован")
            return

        if hasattr(self.module, '_finalize_layer'):
            self.logger.success("Метод _finalize_layer: найден")

            # Проверяем исходный код метода
            import inspect
            source = inspect.getsource(self.module._finalize_layer)

            if 'AttributeProcessor' in source:
                self.logger.success("_finalize_layer использует AttributeProcessor")
            else:
                self.logger.warning("_finalize_layer НЕ использует AttributeProcessor")

            if 'finalize_layer_processing' in source:
                self.logger.success("_finalize_layer вызывает finalize_layer_processing")
            else:
                self.logger.warning("_finalize_layer НЕ вызывает finalize_layer_processing")
        else:
            self.logger.fail("Метод _finalize_layer: НЕ найден")

    def test_07_refresh_layers_uses_safe_refresh(self):
        """ТЕСТ 7: _refresh_all_layers использует safe_refresh"""
        self.logger.section("7. _refresh_all_layers использует safe_refresh")

        if not self.module:
            self.logger.fail("Модуль не инициализирован")
            return

        if hasattr(self.module, '_refresh_all_layers'):
            self.logger.success("Метод _refresh_all_layers: найден")

            import inspect
            source = inspect.getsource(self.module._refresh_all_layers)

            if 'safe_refresh_layer' in source:
                self.logger.success("_refresh_all_layers использует safe_refresh_layer")
            else:
                self.logger.warning("_refresh_all_layers НЕ использует safe_refresh_layer")

            if 'safe_refresh_canvas' in source:
                self.logger.success("_refresh_all_layers использует safe_refresh_canvas")
            else:
                self.logger.warning("_refresh_all_layers НЕ использует safe_refresh_canvas")
        else:
            self.logger.fail("Метод _refresh_all_layers: НЕ найден")

    def test_08_transfer_tochki_field(self):
        """ТЕСТ 8: Fsm_2_2_2_Transfer устанавливает Точки = '-'"""
        self.logger.section("8. Fsm_2_2_2_Transfer: Точки = '-'")

        try:
            import inspect
            from Daman_QGIS.tools.F_2_cutting.submodules.Fsm_2_2_2_transfer import (
                Fsm_2_2_2_Transfer
            )

            # Проверяем исходный код метода _set_bez_mezh_attributes
            source = inspect.getsource(Fsm_2_2_2_Transfer._set_bez_mezh_attributes)

            # Поле Точки должно быть '-', а не ''
            if "'Точки', '-'" in source or '"Точки", "-"' in source:
                self.logger.success("Точки устанавливается в '-'")
            elif "'Точки', ''" in source or '"Точки", ""' in source:
                self.logger.fail("Точки устанавливается в '' (пустую строку)!")
            else:
                self.logger.warning("Не удалось определить значение Точки")

        except Exception as e:
            self.logger.fail(f"Ошибка проверки Точки: {e}")

    def test_09_transfer_fid_diagnostics(self):
        """ТЕСТ 9: Fsm_2_2_2_Transfer имеет диагностику fid"""
        self.logger.section("9. Fsm_2_2_2_Transfer: диагностика fid")

        try:
            import inspect
            from Daman_QGIS.tools.F_2_cutting.submodules.Fsm_2_2_2_transfer import (
                Fsm_2_2_2_Transfer
            )

            source = inspect.getsource(Fsm_2_2_2_Transfer.execute)

            # Проверяем наличие диагностики
            checks = [
                ('isEditable', 'Проверка isEditable'),
                ('missing_fids', 'Отслеживание missing_fids'),
                ('commitChanges', 'Коммит изменений перед переносом'),
            ]

            for check, desc in checks:
                if check in source:
                    self.logger.success(f"{desc}: найдено")
                else:
                    self.logger.warning(f"{desc}: НЕ найдено")

        except Exception as e:
            self.logger.fail(f"Ошибка проверки диагностики: {e}")


def run_tests(iface, logger):
    """Точка входа для запуска тестов"""
    test = TestF32(iface, logger)
    test.run_all_tests()
    return test
