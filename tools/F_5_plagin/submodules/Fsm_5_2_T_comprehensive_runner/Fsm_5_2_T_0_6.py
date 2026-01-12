# -*- coding: utf-8 -*-
"""
Субмодуль Fsm_5_2_T_0_6 - Тест функции F_0_6_Экспорт в DXF
"""

import tempfile
import os
import shutil


class TestF06:
    """Тесты для F_0_6_Экспорт в DXF"""

    def __init__(self, iface, logger):
        self.iface = iface
        self.logger = logger
        self.module = None
        self.test_dir = None

    def run_all_tests(self):
        self.logger.section("ТЕСТ F_0_6: Экспорт в DXF")
        self.test_dir = tempfile.mkdtemp(prefix="qgis_test_f06_")

        try:
            self.test_01_init_module()
            self.test_02_check_exporter()
        finally:
            if self.test_dir and os.path.exists(self.test_dir):
                try:
                    shutil.rmtree(self.test_dir)
                except:
                    pass
        self.logger.summary()

    def test_01_init_module(self):
        self.logger.section("1. Инициализация F_0_6_ExportDxf")
        self.logger.warning("F_0_6 не существует: экспорт DXF реализован через F_1_5_UniversalExport")
        self.logger.info("Используйте тест F_1_5 для проверки экспорта в DXF")

    def test_02_check_exporter(self):
        self.logger.section("2. Проверка экспортера DXF")
        self.logger.info("Тест пропущен: F_0_6 не существует")
        self.logger.success("Используйте F_1_5_UniversalExport для экспорта в DXF")
