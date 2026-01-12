# -*- coding: utf-8 -*-
"""
Субмодуль Fsm_5_2_T_4_1 - Тест функции F_4_1_Картометрия слоев
"""

import tempfile
import os
import shutil


class TestF41:
    """Тесты для F_4_1_Картометрия слоев"""

    def __init__(self, iface, logger):
        self.iface = iface
        self.logger = logger
        self.module = None
        self.test_dir = None

    def run_all_tests(self):
        self.logger.section("ТЕСТ F_4_1: Картометрия слоев")
        self.test_dir = tempfile.mkdtemp(prefix="qgis_test_f41_")

        try:
            self.test_01_init_module()
            self.test_02_check_calculator()
        finally:
            if self.test_dir and os.path.exists(self.test_dir):
                try:
                    shutil.rmtree(self.test_dir)
                except:
                    pass
        self.logger.summary()

    def test_01_init_module(self):
        self.logger.section("1. Инициализация F_4_1_Cartometry")
        try:
            from Daman_QGIS.tools.F_4_cartometry.F_4_1_cartometry import F_4_1_Cartometry
            self.module = F_4_1_Cartometry(self.iface)
            self.logger.success("Модуль загружен")
        except Exception as e:
            self.logger.error(f"Ошибка: {str(e)}")

    def test_02_check_calculator(self):
        self.logger.section("2. Проверка калькулятора")
        if not self.module:
            self.logger.fail("Модуль не инициализирован")
            return

        methods = ['run', 'calculate_area', 'calculate_length']
        for method in methods:
            if hasattr(self.module, method):
                self.logger.success(f"Метод {method} существует")
            else:
                self.logger.warning(f"Метод {method} отсутствует")
