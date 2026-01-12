# -*- coding: utf-8 -*-
"""
Субмодуль Fsm_5_2_T_0_3 - Тест функции F_0_3_Редактирование свойств проекта
"""

import os
import tempfile
import shutil


class TestF03:
    """Тесты для функции F_0_3_Редактирование свойств проекта"""

    def __init__(self, iface, logger):
        self.iface = iface
        self.logger = logger
        self.module = None
        self.project_manager = None
        self.test_dir = None

    def run_all_tests(self):
        self.logger.section("ТЕСТ F_0_3: Редактирование свойств проекта")
        self.test_dir = tempfile.mkdtemp(prefix="qgis_test_f03_")

        try:
            self.test_01_init_module()
            self.test_02_check_dialog()
            self.test_03_check_methods()
        finally:
            if self.test_dir and os.path.exists(self.test_dir):
                try:
                    shutil.rmtree(self.test_dir)
                except:
                    pass
        self.logger.summary()

    def test_01_init_module(self):
        self.logger.section("1. Инициализация F_0_3_EditProjectProperties")
        try:
            from Daman_QGIS.tools.F_0_project.F_0_3_edit_project_properties import F_0_3_EditProjectProperties
            self.module = F_0_3_EditProjectProperties(self.iface)
            self.logger.success("Модуль загружен")

            from Daman_QGIS.managers import ProjectManager
            self.project_manager = ProjectManager(self.iface, os.path.dirname(os.path.dirname(__file__)))
            self.module.set_project_manager(self.project_manager)
            self.logger.success("ProjectManager установлен")
        except Exception as e:
            self.logger.error(f"Ошибка: {str(e)}")

    def test_02_check_dialog(self):
        self.logger.section("2. Проверка диалога")
        try:
            from Daman_QGIS.tools.F_0_project.submodules.Fsm_0_3_1_edit_project_dialog import EditProjectDialog
            self.logger.success("EditProjectDialog доступен")
        except Exception as e:
            self.logger.warning(f"Ошибка: {str(e)}")

    def test_03_check_methods(self):
        self.logger.section("3. Проверка методов")
        if not self.module:
            self.logger.fail("Модуль не инициализирован")
            return

        methods = ['run', 'set_project_manager']
        for method in methods:
            self.logger.check(
                hasattr(self.module, method),
                f"Метод {method} существует",
                f"Метод {method} отсутствует!"
            )
