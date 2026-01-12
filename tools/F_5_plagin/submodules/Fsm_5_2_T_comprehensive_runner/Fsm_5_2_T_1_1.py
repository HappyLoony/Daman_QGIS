# -*- coding: utf-8 -*-
"""
Субмодуль Fsm_5_2_T_1_1 - Тест функции F_1_1_Универсальный импорт
Проверка импорта данных в форматах XML, DXF, TAB
"""

import os
import tempfile
import shutil
from qgis.core import QgsVectorLayer, QgsProject


class TestF11:
    """Тесты для функции F_1_1_Универсальный импорт"""

    def __init__(self, iface, logger):
        """Инициализация теста"""
        self.iface = iface
        self.logger = logger
        self.module = None
        self.project_manager = None
        self.layer_manager = None
        self.test_dir = None

    def run_all_tests(self):
        """Запуск всех тестов F_1_1"""
        self.logger.section("ТЕСТ F_1_1: Универсальный импорт данных")

        self.test_dir = tempfile.mkdtemp(prefix="qgis_test_f11_")
        self.logger.info(f"Временная директория: {self.test_dir}")
        assert self.test_dir is not None  # tempfile.mkdtemp всегда возвращает строку

        try:
            self.test_01_init_module()
            self.test_02_check_dependencies()
            self.test_03_check_submodules()
            self.test_04_format_validation()
            self.test_05_xml_submodule()
            self.test_06_dxf_submodule()
            self.test_07_tab_submodule()
            self.test_08_real_import()

        finally:
            if self.test_dir and os.path.exists(self.test_dir):
                try:
                    shutil.rmtree(self.test_dir)
                    self.logger.info("Временные файлы очищены")
                except Exception as e:
                    self.logger.warning(f"Не удалось удалить временные файлы: {str(e)}")

        self.logger.summary()

    def test_01_init_module(self):
        """ТЕСТ 1: Инициализация модуля F_1_1"""
        self.logger.section("1. Инициализация модуля F_1_1_UniversalImport")

        try:
            from Daman_QGIS.tools.F_1_data.F_1_1_universal_import import F_1_1_UniversalImport

            self.module = F_1_1_UniversalImport(self.iface)
            self.logger.success("Модуль F_1_1_UniversalImport загружен успешно")

            self.logger.check(
                hasattr(self.module, 'run'),
                "Метод run существует",
                "Метод run отсутствует!"
            )

            self.logger.check(
                hasattr(self.module, 'import_with_options'),
                "Метод import_with_options существует",
                "Метод import_with_options отсутствует!"
            )

            self.logger.check(
                hasattr(self.module, 'FORMAT_SUBMODULES'),
                "Словарь FORMAT_SUBMODULES существует",
                "FORMAT_SUBMODULES отсутствует!"
            )

            if hasattr(self.module, 'FORMAT_SUBMODULES'):
                formats = list(self.module.FORMAT_SUBMODULES.keys())
                self.logger.data("Поддерживаемые форматы", ", ".join(formats))

                self.logger.check(
                    'XML' in formats,
                    "Формат XML поддерживается",
                    "Формат XML не поддерживается!"
                )

                self.logger.check(
                    'DXF' in formats,
                    "Формат DXF поддерживается",
                    "Формат DXF не поддерживается!"
                )

                self.logger.check(
                    'TAB' in formats,
                    "Формат TAB поддерживается",
                    "Формат TAB не поддерживается!"
                )

        except Exception as e:
            self.logger.error(f"Ошибка инициализации: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())
            self.module = None

    def test_02_check_dependencies(self):
        """ТЕСТ 2: Проверка зависимостей"""
        self.logger.section("2. Проверка зависимостей модуля")

        if not self.module:
            self.logger.fail("Модуль не инициализирован, пропускаем тест")
            return

        try:
            from Daman_QGIS.managers import ProjectManager
            self.project_manager = ProjectManager(self.iface, os.path.dirname(os.path.dirname(__file__)))
            self.logger.success("ProjectManager доступен")

            self.module.set_project_manager(self.project_manager)
            self.logger.success("ProjectManager установлен в F_1_1")

            from Daman_QGIS.managers import LayerManager
            self.layer_manager = LayerManager(self.iface, self.project_manager)
            self.logger.success("LayerManager доступен")

            self.module.set_layer_manager(self.layer_manager)
            self.logger.success("LayerManager установлен в F_1_1")

            from Daman_QGIS.tools.F_1_data.ui.universal_import_dialog import UniversalImportDialog
            self.logger.success("UniversalImportDialog доступен")

        except Exception as e:
            self.logger.error(f"Ошибка проверки зависимостей: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_03_check_submodules(self):
        """ТЕСТ 3: Проверка сабмодулей импорта"""
        self.logger.section("3. Проверка сабмодулей импорта")

        if not self.module:
            self.logger.fail("Модуль не инициализирован, пропускаем тест")
            return

        try:
            from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_1_1_xml import XmlImportSubmodule
            self.logger.success("XmlImportSubmodule доступен")

            self.logger.check(
                hasattr(XmlImportSubmodule, 'import_file'),
                "XmlImportSubmodule имеет метод import_file",
                "Метод import_file отсутствует в XmlImportSubmodule!"
            )

        except Exception as e:
            self.logger.warning(f"XmlImportSubmodule недоступен: {str(e)}")

        try:
            from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_1_2_dxf import DxfImportSubmodule
            self.logger.success("DxfImportSubmodule доступен")

            self.logger.check(
                hasattr(DxfImportSubmodule, 'import_file'),
                "DxfImportSubmodule имеет метод import_file",
                "Метод import_file отсутствует в DxfImportSubmodule!"
            )

        except Exception as e:
            self.logger.warning(f"DxfImportSubmodule недоступен: {str(e)}")

        try:
            from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_1_3_tab import TabImportSubmodule
            self.logger.success("TabImportSubmodule доступен")

            self.logger.check(
                hasattr(TabImportSubmodule, 'import_file'),
                "TabImportSubmodule имеет метод import_file",
                "Метод import_file отсутствует в TabImportSubmodule!"
            )

        except Exception as e:
            self.logger.warning(f"TabImportSubmodule недоступен: {str(e)}")

    def test_04_format_validation(self):
        """ТЕСТ 4: Валидация форматов"""
        self.logger.section("4. Валидация поддерживаемых форматов")

        if not self.module:
            self.logger.fail("Модуль не инициализирован, пропускаем тест")
            return

        try:
            valid_formats = ['XML', 'DXF', 'TAB']
            invalid_formats = ['PDF', 'DOC', 'XYZ']

            for fmt in valid_formats:
                is_supported = fmt in self.module.FORMAT_SUBMODULES
                self.logger.check(
                    is_supported,
                    f"Формат {fmt} корректно определен как поддерживаемый",
                    f"Формат {fmt} должен поддерживаться!"
                )

            for fmt in invalid_formats:
                is_supported = fmt in self.module.FORMAT_SUBMODULES
                self.logger.check(
                    not is_supported,
                    f"Формат {fmt} корректно определен как неподдерживаемый",
                    f"Формат {fmt} не должен поддерживаться!"
                )

        except Exception as e:
            self.logger.error(f"Ошибка валидации форматов: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_05_xml_submodule(self):
        """ТЕСТ 5: Тест XML сабмодуля"""
        self.logger.section("5. Тест XmlImportSubmodule")

        try:
            from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_1_1_xml import XmlImportSubmodule

            xml_module = XmlImportSubmodule(self.iface)
            self.logger.success("XmlImportSubmodule инициализирован")

            required_methods = ['import_file', 'validate_import', 'supports_format']
            for method_name in required_methods:
                if hasattr(xml_module, method_name):
                    self.logger.success(f"Метод {method_name} существует")
                else:
                    self.logger.warning(f"Метод {method_name} отсутствует")

        except Exception as e:
            self.logger.warning(f"Ошибка теста XML модуля: {str(e)}")

    def test_06_dxf_submodule(self):
        """ТЕСТ 6: Тест DXF сабмодуля"""
        self.logger.section("6. Тест DxfImportSubmodule")

        try:
            from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_1_2_dxf import DxfImportSubmodule

            dxf_module = DxfImportSubmodule(self.iface)
            self.logger.success("DxfImportSubmodule инициализирован")

            required_methods = ['import_file', 'validate_import', 'supports_format']
            for method_name in required_methods:
                if hasattr(dxf_module, method_name):
                    self.logger.success(f"Метод {method_name} существует")
                else:
                    self.logger.warning(f"Метод {method_name} отсутствует")

        except Exception as e:
            self.logger.warning(f"Ошибка теста DXF модуля: {str(e)}")

    def test_07_tab_submodule(self):
        """ТЕСТ 7: Тест TAB сабмодуля"""
        self.logger.section("7. Тест TabImportSubmodule")

        try:
            from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_1_3_tab import TabImportSubmodule

            tab_module = TabImportSubmodule(self.iface)
            self.logger.success("TabImportSubmodule инициализирован")

            required_methods = ['import_file', 'validate_import', 'supports_format']
            for method_name in required_methods:
                if hasattr(tab_module, method_name):
                    self.logger.success(f"Метод {method_name} существует")
                else:
                    self.logger.warning(f"Метод {method_name} отсутствует")

        except Exception as e:
            self.logger.warning(f"Ошибка теста TAB модуля: {str(e)}")

    def test_08_real_import(self):
        """ТЕСТ 8: Реальный импорт тестового DXF файла"""
        self.logger.section("8. Тест реального импорта DXF")

        if not self.test_dir:
            self.logger.fail("test_dir не инициализирован, пропускаем тест")
            return

        test_dxf = None
        imported_layer_ids = []

        try:
            import os
            from Daman_QGIS.tools.F_1_data.F_1_1_universal_import import F_1_1_UniversalImport
            from qgis.core import QgsProject

            # Создаем тестовый DXF файл
            test_dxf = os.path.join(self.test_dir, "test_boundary.dxf")
            self._create_test_dxf(test_dxf)

            # Инициализируем F_1_1
            f11 = F_1_1_UniversalImport(self.iface)
            f11.set_project_manager(self.project_manager)
            f11.set_layer_manager(self.layer_manager)

            self.logger.success("F_1_1_UniversalImport инициализирован для теста импорта")

            # Выполняем импорт
            options = {
                'format': 'DXF',
                'files': [test_dxf],
                'layers': {
                    'L_1_1_1_Границы_работ': {
                        'name': 'L_1_1_1_Границы_работ',
                        'group': 'Границы'
                    }
                },
                'options': {}
            }

            self.logger.info(f"Запуск импорта файла: {os.path.basename(test_dxf)}")
            f11.import_with_options(options)

            # Проверяем результат
            project = QgsProject.instance()
            layers = project.mapLayers()
            root = project.layerTreeRoot()

            self.logger.info(f"Всего слоёв в проекте после импорта: {len(layers)}")

            # Выводим структуру дерева слоёв
            self.logger.info("Структура дерева слоёв:")
            self._log_layer_tree(root, indent="  ")

            # Ищем наш слой и собираем ID для удаления
            boundary_layer = None
            l_1_1_1_found = False
            l_1_1_2_found = False

            for layer_id, layer in layers.items():
                layer_name = layer.name()
                self.logger.info(f"  - Слой: {layer_name} (id: {layer_id[:50]}...)")

                if layer_name == 'L_1_1_1_Границы_работ':
                    l_1_1_1_found = True
                    boundary_layer = layer
                    imported_layer_ids.append(layer_id)
                    self.logger.success(f"    ✓ L_1_1_1 найден!")

                if layer_name == 'L_1_1_2_Границы_работ_10_м':
                    l_1_1_2_found = True
                    imported_layer_ids.append(layer_id)
                    self.logger.success(f"    ✓ L_1_1_2 найден (буферный слой)!")

            # Итоговая проверка
            if l_1_1_1_found and boundary_layer is not None:
                self.logger.success(f"✓ Основной слой найден: L_1_1_1_Границы_работ")
                self.logger.success(f"  Тип геометрии: {boundary_layer.geometryType()}")
                self.logger.success(f"  Количество объектов: {boundary_layer.featureCount()}")

                # Проверяем, в какой группе находится слой
                layer_node = root.findLayer(boundary_layer.id())
                if layer_node:
                    parent = layer_node.parent()
                    group_path = []
                    while parent and parent != root:
                        group_path.insert(0, parent.name())
                        parent = parent.parent()

                    if group_path:
                        self.logger.success(f"  Расположение в дереве: {' / '.join(group_path)}")
                    else:
                        self.logger.warning(f"  Слой в корне проекта (не в группе!)")
                else:
                    self.logger.warning(f"  Узел слоя не найден в дереве!")
            else:
                self.logger.error("✗ Основной слой L_1_1_1_Границы_работ НЕ НАЙДЕН в проекте!")

            if l_1_1_2_found:
                self.logger.success(f"✓ Буферный слой найден: L_1_1_2_Границы_работ_10_м")
            else:
                self.logger.warning(f"⚠ Буферный слой L_1_1_2 не создан")

        except Exception as e:
            self.logger.error(f"Ошибка теста реального импорта: {str(e)}")
            import traceback
            self.logger.error(traceback.format_exc())

        finally:
            # Очистка: удаляем импортированные слои из проекта
            try:
                from qgis.core import QgsProject
                project = QgsProject.instance()

                for layer_id in imported_layer_ids:
                    project.removeMapLayer(layer_id)

                if imported_layer_ids:
                    self.logger.info(f"Удалено {len(imported_layer_ids)} тестовых слоёв из проекта")

            except Exception as e:
                self.logger.warning(f"Не удалось удалить тестовые слои: {str(e)}")

            # Закрываем файл DXF перед удалением
            if test_dxf and os.path.exists(test_dxf):
                try:
                    import time
                    time.sleep(0.5)  # Даём время на освобождение файла
                    os.remove(test_dxf)
                    self.logger.info(f"Удалён тестовый DXF файл")
                except Exception as e:
                    self.logger.warning(f"Не удалось удалить DXF файл: {str(e)}")

    def _log_layer_tree(self, node, indent=""):
        """Рекурсивный вывод структуры дерева слоёв"""
        from qgis.core import QgsLayerTreeGroup, QgsLayerTreeLayer

        for child in node.children():
            if isinstance(child, QgsLayerTreeGroup):
                self.logger.info(f"{indent}📁 Группа: {child.name()}")
                self._log_layer_tree(child, indent + "  ")
            elif isinstance(child, QgsLayerTreeLayer):
                layer = child.layer()
                if layer:
                    visible = "👁" if child.isVisible() else "🚫"
                    self.logger.info(f"{indent}{visible} Слой: {layer.name()}")

    def _create_test_dxf(self, file_path: str):
        """Создание тестового DXF файла с простой линией"""
        try:
            import ezdxf

            doc = ezdxf.new('R2010')  # type: ignore[reportPrivateImportUsage]
            msp = doc.modelspace()

            # Создаем простую прямоугольную границу
            points = [
                (0, 0),
                (100, 0),
                (100, 100),
                (0, 100),
                (0, 0)
            ]

            msp.add_lwpolyline(points, dxfattribs={'layer': 'Границы_работ'})

            doc.saveas(file_path)
            self.logger.info(f"Создан тестовый DXF: {file_path}")

        except Exception as e:
            self.logger.warning(f"Не удалось создать тестовый DXF: {str(e)}")
