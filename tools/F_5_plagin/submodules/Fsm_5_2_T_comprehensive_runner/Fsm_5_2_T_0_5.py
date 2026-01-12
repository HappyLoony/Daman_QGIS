# -*- coding: utf-8 -*-
"""
Субмодуль Fsm_5_2_T_0_5 - Тест функции F_0_5_Уточнение проекции
"""

import tempfile
import os
import shutil


class TestF05:
    """Тесты для F_0_5_Уточнение проекции"""

    def __init__(self, iface, logger):
        self.iface = iface
        self.logger = logger
        self.module = None
        self.test_dir = None

    def run_all_tests(self):
        self.logger.section("ТЕСТ F_0_5: Уточнение проекции")
        self.test_dir = tempfile.mkdtemp(prefix="qgis_test_f05_")

        try:
            self.test_01_init_module()
            self.test_02_check_dialog()
            self.test_03_check_calculators()
        finally:
            if self.test_dir and os.path.exists(self.test_dir):
                try:
                    shutil.rmtree(self.test_dir)
                except:
                    pass
        self.logger.summary()

    def test_01_init_module(self):
        self.logger.section("1. Инициализация F_0_5_RefineProjection")
        try:
            from Daman_QGIS.tools.F_0_project.F_0_5_refine_projection import F_0_5_RefineProjection
            self.module = F_0_5_RefineProjection(self.iface)
            self.logger.success("Модуль загружен")
        except Exception as e:
            self.logger.error(f"Ошибка: {str(e)}")

    def test_02_check_dialog(self):
        self.logger.section("2. Проверка диалога")
        try:
            from Daman_QGIS.tools.F_0_project.submodules.Fsm_0_5_refine_dialog import RefineProjectionDialog
            self.logger.success("RefineProjectionDialog доступен")
        except Exception as e:
            self.logger.warning(f"Ошибка: {str(e)}")

    def test_03_check_calculators(self):
        self.logger.section("3. Проверка калькуляторов смещения")
        try:
            from Daman_QGIS.external_modules.delta_calculator import delta_calculator
            self.logger.success("delta_calculator доступен")

            from Daman_QGIS.external_modules.VectorBender import vectorbendertransformers
            self.logger.success("VectorBender доступен")
        except Exception as e:
            self.logger.warning(f"Ошибка: {str(e)}")
