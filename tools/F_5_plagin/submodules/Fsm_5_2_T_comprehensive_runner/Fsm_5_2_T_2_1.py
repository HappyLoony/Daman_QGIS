# -*- coding: utf-8 -*-
"""
Субмодуль Fsm_5_2_T_2_1 - Тест функции F_2_1_Экспорт сводной ведомости
"""

import tempfile
import os
import shutil


class TestF21:
    """Тесты для F_2_1_Экспорт сводной ведомости"""

    def __init__(self, iface, logger):
        self.iface = iface
        self.logger = logger
        self.module = None
        self.test_dir = None

    def run_all_tests(self):
        self.logger.section("ТЕСТ F_2_1: Подбор земельных участков")
        self.test_dir = tempfile.mkdtemp(prefix="qgis_test_f21_")

        try:
            self.test_01_init_module()
            self.test_02_check_export()
        finally:
            if self.test_dir and os.path.exists(self.test_dir):
                try:
                    shutil.rmtree(self.test_dir)
                except:
                    pass
        self.logger.summary()

    def test_01_init_module(self):
        self.logger.section("1. Инициализация F_2_1_LandSelection")
        try:
            from Daman_QGIS.tools.F_2_processing.F_2_1_land_selection import F_2_1_LandSelection
            self.module = F_2_1_LandSelection(self.iface)
            self.logger.success("Модуль загружен")
        except Exception as e:
            self.logger.error(f"Ошибка: {str(e)}")

    def test_02_check_export(self):
        self.logger.section("2. Проверка экспорта")
        if not self.module:
            self.logger.fail("Модуль не инициализирован")
            return

        methods = ['run']
        for method in methods:
            if hasattr(self.module, method):
                self.logger.success(f"Метод {method} существует")
            else:
                self.logger.warning(f"Метод {method} отсутствует")
