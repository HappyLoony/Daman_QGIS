# -*- coding: utf-8 -*-
"""
Субмодуль Fsm_4_2_T_project_db - Тестирование database/project_db.py

Тестирует:
- CRUD операции GeoPackage (create, add_layer, get_layer, list_layers, remove_layer)
- Метаданные (set/get/delete_metadata, get_all_metadata)
- Настройки проекта (save/load_project_settings)
- Edge cases (несуществующий файл, unicode, close)
"""

import os
import tempfile
import shutil
import sqlite3
from datetime import datetime

from qgis.core import (
    QgsVectorLayer, QgsCoordinateReferenceSystem,
    QgsField, QgsFeature, QgsGeometry, QgsPointXY
)

from qgis.PyQt.QtCore import QMetaType
FIELD_TYPE_STRING = QMetaType.Type.QString
FIELD_TYPE_INT = QMetaType.Type.Int


class TestProjectDB:
    """Тесты database/project_db.py"""

    def __init__(self, iface, logger):
        self.iface = iface
        self.logger = logger
        self.test_dir = None
        self.db = None

    def run_all_tests(self):
        self.logger.section("ТЕСТ PROJECT_DB: Database CRUD")

        self.test_dir = tempfile.mkdtemp(prefix="qgis_test_project_db_")
        self.logger.info(f"Временная директория: {self.test_dir}")

        try:
            self.test_01_import_module()
            self.test_02_create_gpkg()
            self.test_03_create_metadata_table()
            self.test_04_add_layer()
            self.test_05_get_layer()
            self.test_06_list_layers()
            self.test_07_remove_layer()
            self.test_08_save_project_settings()
            self.test_09_load_project_settings()
            self.test_10_set_metadata()
            self.test_11_get_metadata()
            self.test_12_delete_metadata()
            self.test_13_get_all_metadata()
            self.test_14_metadata_overwrite()
            self.test_15_unicode_metadata()
            self.test_16_nonexistent_file()
            self.test_17_close()
        except Exception as e:
            self.logger.error(f"Критическая ошибка тестов ProjectDB: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())
        finally:
            self._cleanup()

        self.logger.summary()

    def _cleanup(self):
        """Очистка временных файлов"""
        if self.db:
            try:
                self.db.close()
            except Exception:
                pass
        if self.test_dir and os.path.exists(self.test_dir):
            try:
                shutil.rmtree(self.test_dir)
                self.logger.info("Временные файлы очищены")
            except Exception as e:
                self.logger.warning(f"Не удалось удалить временные файлы: {str(e)}")

    def _create_test_layer(self, name="test_layer", geom_type="Point", crs_id="EPSG:4326"):
        """Создание тестового векторного слоя с одним объектом"""
        layer = QgsVectorLayer(
            f"{geom_type}?crs={crs_id}&field=name:string&field=value:integer",
            name,
            "memory"
        )
        pr = layer.dataProvider()
        feat = QgsFeature()
        feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(37.6, 55.7)))
        feat.setAttributes(["test_object", 42])
        pr.addFeatures([feat])
        layer.updateExtents()
        return layer

    # -------------------------------------------------------------------------
    # Тесты
    # -------------------------------------------------------------------------

    def test_01_import_module(self):
        """ТЕСТ 1: Импорт модуля ProjectDB"""
        self.logger.section("1. Импорт модуля ProjectDB")
        try:
            from Daman_QGIS.database.project_db import ProjectDB
            self.logger.success("Модуль ProjectDB импортирован")

            self.logger.check(
                callable(ProjectDB),
                "ProjectDB является вызываемым классом",
                "ProjectDB не является вызываемым классом"
            )

            # Проверяем наличие ключевых методов
            expected_methods = [
                'create', 'exists', 'add_layer', 'get_layer',
                'list_layers', 'remove_layer', 'save_project_settings',
                'load_project_settings', 'create_metadata_table',
                'set_metadata', 'get_metadata', 'delete_metadata',
                'get_all_metadata', 'close'
            ]
            for method_name in expected_methods:
                self.logger.check(
                    hasattr(ProjectDB, method_name),
                    f"Метод {method_name} существует",
                    f"Метод {method_name} отсутствует"
                )

        except Exception as e:
            self.logger.error(f"Ошибка импорта ProjectDB: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_02_create_gpkg(self):
        """ТЕСТ 2: Создание GeoPackage через create()"""
        self.logger.section("2. Создание GeoPackage")
        try:
            from Daman_QGIS.database.project_db import ProjectDB

            gpkg_path = os.path.join(self.test_dir, "subdir", "test_project.gpkg")
            self.db = ProjectDB(gpkg_path)

            # Проверяем что файла еще нет
            self.logger.check(
                not self.db.exists(),
                "GeoPackage еще не существует (ожидаемо)",
                "GeoPackage уже существует до create()"
            )

            crs = QgsCoordinateReferenceSystem("EPSG:4326")
            result = self.db.create(crs)

            self.logger.check(
                result is True,
                "create() вернул True",
                f"create() вернул {result}"
            )

            self.logger.check(
                self.db.exists(),
                "Файл GeoPackage создан на диске",
                "Файл GeoPackage НЕ создан"
            )

            self.logger.check(
                os.path.exists(os.path.dirname(gpkg_path)),
                "Промежуточная директория создана",
                "Промежуточная директория НЕ создана"
            )

            # Проверяем что таблица метаданных создана
            with sqlite3.connect(gpkg_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='_metadata'"
                )
                table = cursor.fetchone()

            self.logger.check(
                table is not None,
                "Таблица _metadata создана в GeoPackage",
                "Таблица _metadata НЕ создана"
            )

        except Exception as e:
            self.logger.error(f"Ошибка создания GeoPackage: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_03_create_metadata_table(self):
        """ТЕСТ 3: Создание таблицы метаданных"""
        self.logger.section("3. Создание таблицы метаданных")
        try:
            if not self.db or not self.db.exists():
                self.logger.fail("GeoPackage не создан, пропускаем тест")
                return

            # Таблица уже создана в create(), проверяем структуру
            with sqlite3.connect(self.db.gpkg_path) as conn:
                cursor = conn.cursor()
                cursor.execute("PRAGMA table_info(_metadata)")
                columns = cursor.fetchall()

            col_names = [col[1] for col in columns]
            self.logger.check(
                'key' in col_names,
                "Колонка 'key' существует в _metadata",
                "Колонка 'key' отсутствует"
            )
            self.logger.check(
                'value' in col_names,
                "Колонка 'value' существует в _metadata",
                "Колонка 'value' отсутствует"
            )
            self.logger.check(
                'description' in col_names,
                "Колонка 'description' существует в _metadata",
                "Колонка 'description' отсутствует"
            )

            # Повторный вызов create_metadata_table не должен падать
            result = self.db.create_metadata_table()
            self.logger.check(
                result is True,
                "Повторный create_metadata_table() не вызвал ошибку",
                "Повторный create_metadata_table() вызвал ошибку"
            )

        except Exception as e:
            self.logger.error(f"Ошибка проверки таблицы метаданных: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_04_add_layer(self):
        """ТЕСТ 4: Добавление слоя в GeoPackage"""
        self.logger.section("4. Добавление слоя (add_layer)")
        try:
            if not self.db or not self.db.exists():
                self.logger.fail("GeoPackage не создан, пропускаем тест")
                return

            layer = self._create_test_layer("memory_layer")
            self.logger.check(
                layer.isValid(),
                "Тестовый memory-слой валиден",
                "Тестовый memory-слой невалиден"
            )

            result = self.db.add_layer(layer, "test_points")
            self.logger.check(
                result is True,
                "add_layer() вернул True",
                f"add_layer() вернул {result}"
            )

            # Проверяем кэш
            self.logger.check(
                "test_points" in self.db.layers,
                "Слой добавлен в кэш",
                "Слой НЕ добавлен в кэш"
            )

            # Добавляем второй слой для list_layers
            layer2 = self._create_test_layer("another_layer")
            self.db.add_layer(layer2, "test_polygons")
            self.logger.success("Второй тестовый слой добавлен")

        except Exception as e:
            self.logger.error(f"Ошибка добавления слоя: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_05_get_layer(self):
        """ТЕСТ 5: Получение слоя из GeoPackage"""
        self.logger.section("5. Получение слоя (get_layer)")
        try:
            if not self.db or not self.db.exists():
                self.logger.fail("GeoPackage не создан, пропускаем тест")
                return

            # Очищаем кэш чтобы проверить загрузку из файла
            self.db.layers.clear()

            layer = self.db.get_layer("test_points")
            self.logger.check(
                layer is not None,
                "get_layer('test_points') вернул слой",
                "get_layer('test_points') вернул None"
            )

            if layer:
                self.logger.check(
                    layer.isValid(),
                    "Загруженный слой валиден",
                    "Загруженный слой невалиден"
                )
                self.logger.check(
                    layer.featureCount() > 0,
                    f"Слой содержит {layer.featureCount()} объект(ов)",
                    "Слой пустой"
                )

            # Несуществующий слой
            missing = self.db.get_layer("nonexistent_layer")
            self.logger.check(
                missing is None,
                "get_layer() для несуществующего слоя вернул None",
                f"get_layer() для несуществующего слоя вернул {missing}"
            )

            # Невалидное имя (спецсимволы) - должно вернуть None
            invalid = self.db.get_layer("layer; DROP TABLE")
            self.logger.check(
                invalid is None,
                "get_layer() для невалидного имени вернул None",
                "get_layer() для невалидного имени НЕ вернул None"
            )

        except Exception as e:
            self.logger.error(f"Ошибка получения слоя: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_06_list_layers(self):
        """ТЕСТ 6: Список слоев в GeoPackage"""
        self.logger.section("6. Список слоев (list_layers)")
        try:
            if not self.db or not self.db.exists():
                self.logger.fail("GeoPackage не создан, пропускаем тест")
                return

            layers = self.db.list_layers()
            self.logger.check(
                isinstance(layers, list),
                "list_layers() вернул list",
                f"list_layers() вернул {type(layers)}"
            )

            self.logger.data("Слои в GPKG", str(layers))

            self.logger.check(
                "test_points" in layers,
                "Слой 'test_points' в списке",
                "Слой 'test_points' НЕ найден в списке"
            )
            self.logger.check(
                "test_polygons" in layers,
                "Слой 'test_polygons' в списке",
                "Слой 'test_polygons' НЕ найден в списке"
            )

            # Служебные таблицы не должны попадать в список
            for layer_name in layers:
                self.logger.check(
                    not layer_name.startswith("gpkg_"),
                    f"'{layer_name}' не является служебной таблицей",
                    f"'{layer_name}' - служебная таблица в списке слоев"
                )

        except Exception as e:
            self.logger.error(f"Ошибка получения списка слоев: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_07_remove_layer(self):
        """ТЕСТ 7: Удаление слоя из GeoPackage"""
        self.logger.section("7. Удаление слоя (remove_layer)")
        try:
            if not self.db or not self.db.exists():
                self.logger.fail("GeoPackage не создан, пропускаем тест")
                return

            # Убеждаемся что слой есть
            layers_before = self.db.list_layers()
            self.logger.check(
                "test_polygons" in layers_before,
                "Слой 'test_polygons' существует перед удалением",
                "Слой 'test_polygons' НЕ найден перед удалением"
            )

            result = self.db.remove_layer("test_polygons")
            self.logger.check(
                result is True,
                "remove_layer() вернул True",
                f"remove_layer() вернул {result}"
            )

            # Проверяем что слой удален из кэша
            self.logger.check(
                "test_polygons" not in self.db.layers,
                "Слой удален из кэша",
                "Слой остался в кэше после удаления"
            )

            # Проверяем что слой удален из GPKG
            layers_after = self.db.list_layers()
            self.logger.check(
                "test_polygons" not in layers_after,
                "Слой удален из GeoPackage",
                "Слой остался в GeoPackage после удаления"
            )

            # remove_layer с невалидным именем - должен бросить ValueError
            try:
                self.db.remove_layer("layer; DROP TABLE")
                self.logger.fail("remove_layer() с SQL injection НЕ вызвал ValueError")
            except ValueError:
                self.logger.success("remove_layer() с невалидным именем вызвал ValueError")

        except Exception as e:
            self.logger.error(f"Ошибка удаления слоя: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_08_save_project_settings(self):
        """ТЕСТ 8: Сохранение настроек проекта"""
        self.logger.section("8. Сохранение настроек (save_project_settings)")
        try:
            if not self.db:
                self.logger.fail("ProjectDB не инициализирован, пропускаем тест")
                return

            from Daman_QGIS.database.schemas import ProjectSettings

            now = datetime.now()
            settings = ProjectSettings(
                name="Тестовый проект",
                created=now,
                modified=now,
                version="2.0.0",
                crs_epsg=4326,
                gpkg_path=self.db.gpkg_path,
                work_dir=self.test_dir,
                object_name="Тестовый объект",
                object_type="Площадной",
                crs_description="WGS 84",
                auto_numbering=True,
                readonly_imports=False,
                versioning_enabled=True,
                current_version="01_Работа",
                custom_settings={"key1": "value1", "key2": 42}
            )

            result = self.db.save_project_settings(settings)
            self.logger.check(
                result is True,
                "save_project_settings() вернул True",
                f"save_project_settings() вернул {result}"
            )

            # Проверяем что файл настроек создан
            settings_path = self.db.gpkg_path.replace('.gpkg', '_settings.json')
            self.logger.check(
                os.path.exists(settings_path),
                f"Файл настроек создан: {os.path.basename(settings_path)}",
                "Файл настроек НЕ создан"
            )

        except Exception as e:
            self.logger.error(f"Ошибка сохранения настроек: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_09_load_project_settings(self):
        """ТЕСТ 9: Загрузка настроек проекта (round-trip)"""
        self.logger.section("9. Загрузка настроек (load_project_settings)")
        try:
            if not self.db:
                self.logger.fail("ProjectDB не инициализирован, пропускаем тест")
                return

            loaded = self.db.load_project_settings()
            self.logger.check(
                loaded is not None,
                "load_project_settings() вернул объект",
                "load_project_settings() вернул None"
            )

            if loaded:
                from Daman_QGIS.database.schemas import ProjectSettings
                self.logger.check(
                    isinstance(loaded, ProjectSettings),
                    "Результат является ProjectSettings",
                    f"Результат имеет тип {type(loaded)}"
                )
                self.logger.check(
                    loaded.name == "Тестовый проект",
                    f"name: '{loaded.name}' (ожидалось 'Тестовый проект')",
                    f"name не совпадает: '{loaded.name}'"
                )
                self.logger.check(
                    loaded.crs_epsg == 4326,
                    f"crs_epsg: {loaded.crs_epsg}",
                    f"crs_epsg не совпадает: {loaded.crs_epsg}"
                )
                self.logger.check(
                    loaded.object_name == "Тестовый объект",
                    "object_name round-trip OK",
                    f"object_name: '{loaded.object_name}'"
                )
                self.logger.check(
                    loaded.object_type == "Площадной",
                    "object_type round-trip OK",
                    f"object_type: '{loaded.object_type}'"
                )
                self.logger.check(
                    loaded.readonly_imports is False,
                    "readonly_imports round-trip OK (False)",
                    f"readonly_imports: {loaded.readonly_imports}"
                )
                self.logger.check(
                    loaded.custom_settings.get("key1") == "value1",
                    "custom_settings round-trip OK",
                    f"custom_settings: {loaded.custom_settings}"
                )

            # Несуществующий файл настроек
            from Daman_QGIS.database.project_db import ProjectDB
            fake_db = ProjectDB(os.path.join(self.test_dir, "nonexistent.gpkg"))
            no_settings = fake_db.load_project_settings()
            self.logger.check(
                no_settings is None,
                "load_project_settings() для несуществующего файла вернул None",
                f"load_project_settings() вернул {no_settings}"
            )

        except Exception as e:
            self.logger.error(f"Ошибка загрузки настроек: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_10_set_metadata(self):
        """ТЕСТ 10: Установка метаданных"""
        self.logger.section("10. Установка метаданных (set_metadata)")
        try:
            if not self.db or not self.db.exists():
                self.logger.fail("GeoPackage не создан, пропускаем тест")
                return

            result = self.db.set_metadata("project_version", "2.0.0", "Версия проекта")
            self.logger.check(
                result is True,
                "set_metadata() вернул True",
                f"set_metadata() вернул {result}"
            )

            result2 = self.db.set_metadata("author", "test_user", "Автор проекта")
            self.logger.check(
                result2 is True,
                "Второй set_metadata() вернул True",
                f"Второй set_metadata() вернул {result2}"
            )

            # Без description
            result3 = self.db.set_metadata("simple_key", "simple_value")
            self.logger.check(
                result3 is True,
                "set_metadata() без description вернул True",
                f"set_metadata() без description вернул {result3}"
            )

        except Exception as e:
            self.logger.error(f"Ошибка установки метаданных: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_11_get_metadata(self):
        """ТЕСТ 11: Получение метаданных (round-trip)"""
        self.logger.section("11. Получение метаданных (get_metadata)")
        try:
            if not self.db or not self.db.exists():
                self.logger.fail("GeoPackage не создан, пропускаем тест")
                return

            meta = self.db.get_metadata("project_version")
            self.logger.check(
                meta is not None,
                "get_metadata('project_version') вернул результат",
                "get_metadata('project_version') вернул None"
            )

            if meta:
                self.logger.check(
                    isinstance(meta, dict),
                    "Результат является dict",
                    f"Результат имеет тип {type(meta)}"
                )
                self.logger.check(
                    meta.get('value') == "2.0.0",
                    f"value: '{meta.get('value')}'",
                    f"value не совпадает: '{meta.get('value')}'"
                )
                self.logger.check(
                    meta.get('description') == "Версия проекта",
                    f"description: '{meta.get('description')}'",
                    f"description не совпадает: '{meta.get('description')}'"
                )

            # Несуществующий ключ
            missing = self.db.get_metadata("nonexistent_key")
            self.logger.check(
                missing is None,
                "get_metadata() для несуществующего ключа вернул None",
                f"get_metadata() вернул {missing}"
            )

        except Exception as e:
            self.logger.error(f"Ошибка получения метаданных: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_12_delete_metadata(self):
        """ТЕСТ 12: Удаление метаданных"""
        self.logger.section("12. Удаление метаданных (delete_metadata)")
        try:
            if not self.db or not self.db.exists():
                self.logger.fail("GeoPackage не создан, пропускаем тест")
                return

            # Устанавливаем ключ для удаления
            self.db.set_metadata("to_delete", "temp_value", "Будет удален")

            # Проверяем что ключ есть
            before = self.db.get_metadata("to_delete")
            self.logger.check(
                before is not None,
                "Ключ 'to_delete' существует перед удалением",
                "Ключ 'to_delete' НЕ найден перед удалением"
            )

            result = self.db.delete_metadata("to_delete")
            self.logger.check(
                result is True,
                "delete_metadata() вернул True",
                f"delete_metadata() вернул {result}"
            )

            # Проверяем что ключ удален
            after = self.db.get_metadata("to_delete")
            self.logger.check(
                after is None,
                "Ключ 'to_delete' удален (get_metadata вернул None)",
                f"Ключ 'to_delete' все еще существует: {after}"
            )

            # Удаление несуществующего ключа
            result_missing = self.db.delete_metadata("nonexistent_key_xyz")
            self.logger.check(
                result_missing is False,
                "delete_metadata() для несуществующего ключа вернул False",
                f"delete_metadata() вернул {result_missing}"
            )

        except Exception as e:
            self.logger.error(f"Ошибка удаления метаданных: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_13_get_all_metadata(self):
        """ТЕСТ 13: Получение всех метаданных"""
        self.logger.section("13. Все метаданные (get_all_metadata)")
        try:
            if not self.db or not self.db.exists():
                self.logger.fail("GeoPackage не создан, пропускаем тест")
                return

            all_meta = self.db.get_all_metadata()
            self.logger.check(
                isinstance(all_meta, dict),
                "get_all_metadata() вернул dict",
                f"get_all_metadata() вернул {type(all_meta)}"
            )

            self.logger.data("Количество метаданных", str(len(all_meta)))

            # Должны быть ключи из test_10
            self.logger.check(
                "project_version" in all_meta,
                "'project_version' в метаданных",
                "'project_version' НЕ найден"
            )
            self.logger.check(
                "author" in all_meta,
                "'author' в метаданных",
                "'author' НЕ найден"
            )
            self.logger.check(
                "simple_key" in all_meta,
                "'simple_key' в метаданных",
                "'simple_key' НЕ найден"
            )

            # Структура каждой записи
            if "project_version" in all_meta:
                entry = all_meta["project_version"]
                self.logger.check(
                    'value' in entry and 'description' in entry,
                    "Запись содержит 'value' и 'description'",
                    f"Неожиданная структура записи: {entry}"
                )

        except Exception as e:
            self.logger.error(f"Ошибка получения всех метаданных: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_14_metadata_overwrite(self):
        """ТЕСТ 14: Перезапись метаданных (INSERT OR REPLACE)"""
        self.logger.section("14. Перезапись метаданных")
        try:
            if not self.db or not self.db.exists():
                self.logger.fail("GeoPackage не создан, пропускаем тест")
                return

            # Устанавливаем начальное значение
            self.db.set_metadata("overwrite_test", "original", "Оригинал")

            # Перезаписываем
            self.db.set_metadata("overwrite_test", "updated", "Обновлено")

            meta = self.db.get_metadata("overwrite_test")
            self.logger.check(
                meta is not None and meta.get('value') == "updated",
                "Метаданные перезаписаны: 'updated'",
                f"Перезапись не сработала: {meta}"
            )
            self.logger.check(
                meta is not None and meta.get('description') == "Обновлено",
                "Description обновлен: 'Обновлено'",
                f"Description не обновлен: {meta}"
            )

        except Exception as e:
            self.logger.error(f"Ошибка перезаписи метаданных: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_15_unicode_metadata(self):
        """ТЕСТ 15: Unicode в метаданных"""
        self.logger.section("15. Unicode метаданные")
        try:
            if not self.db or not self.db.exists():
                self.logger.fail("GeoPackage не создан, пропускаем тест")
                return

            unicode_key = "unicode_test"
            unicode_value = "Тестовое значение с кириллицей"
            unicode_desc = "Описание"

            self.db.set_metadata(unicode_key, unicode_value, unicode_desc)

            meta = self.db.get_metadata(unicode_key)
            self.logger.check(
                meta is not None and meta.get('value') == unicode_value,
                f"Кириллица сохранена: '{unicode_value}'",
                f"Кириллица потеряна: {meta}"
            )

            # Спецсимволы
            special_value = "path/to/file & <tag> \"quoted\" 'single'"
            self.db.set_metadata("special_chars", special_value)
            meta_special = self.db.get_metadata("special_chars")
            self.logger.check(
                meta_special is not None and meta_special.get('value') == special_value,
                "Спецсимволы сохранены корректно",
                f"Спецсимволы повреждены: {meta_special}"
            )

            # Длинная строка
            long_value = "A" * 10000
            self.db.set_metadata("long_value", long_value)
            meta_long = self.db.get_metadata("long_value")
            self.logger.check(
                meta_long is not None and len(meta_long.get('value', '')) == 10000,
                "Длинная строка (10000 символов) сохранена",
                f"Длинная строка повреждена: длина {len(meta_long.get('value', '')) if meta_long else 0}"
            )

        except Exception as e:
            self.logger.error(f"Ошибка unicode метаданных: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_16_nonexistent_file(self):
        """ТЕСТ 16: Операции с несуществующим файлом"""
        self.logger.section("16. Edge case: несуществующий файл")
        try:
            from Daman_QGIS.database.project_db import ProjectDB

            fake_path = os.path.join(self.test_dir, "does_not_exist.gpkg")
            fake_db = ProjectDB(fake_path)

            # exists() должен вернуть False
            self.logger.check(
                fake_db.exists() is False,
                "exists() для несуществующего файла вернул False",
                "exists() для несуществующего файла вернул True"
            )

            # list_layers() должен вернуть пустой список
            layers = fake_db.list_layers()
            self.logger.check(
                layers == [],
                "list_layers() для несуществующего файла вернул []",
                f"list_layers() вернул {layers}"
            )

            # get_metadata() для несуществующего файла
            try:
                meta = fake_db.get_metadata("any_key")
                # Если не упал - проверяем что вернул None или пустой результат
                self.logger.check(
                    meta is None,
                    "get_metadata() для несуществующего GPKG вернул None",
                    f"get_metadata() вернул {meta}"
                )
            except Exception as e:
                # Допустимо - файл не существует, sqlite3 может бросить ошибку
                self.logger.info(f"get_metadata() бросил исключение (допустимо): {type(e).__name__}")

        except Exception as e:
            self.logger.error(f"Ошибка тестов с несуществующим файлом: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_17_close(self):
        """ТЕСТ 17: Закрытие соединения"""
        self.logger.section("17. Закрытие соединения (close)")
        try:
            if not self.db:
                self.logger.fail("ProjectDB не инициализирован, пропускаем тест")
                return

            # Добавляем слой в кэш чтобы проверить очистку
            if not self.db.layers:
                # Загружаем слой в кэш
                self.db.get_layer("test_points")

            cached_before = len(self.db.layers)
            self.logger.data("Слоев в кэше до close()", str(cached_before))

            self.db.close()

            self.logger.check(
                len(self.db.layers) == 0,
                "Кэш слоев очищен после close()",
                f"В кэше осталось {len(self.db.layers)} слоев"
            )

            # Повторный close() не должен падать
            try:
                self.db.close()
                self.logger.success("Повторный close() не вызвал ошибку")
            except Exception as e:
                self.logger.fail(f"Повторный close() вызвал ошибку: {str(e)}")

        except Exception as e:
            self.logger.error(f"Ошибка закрытия соединения: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())
