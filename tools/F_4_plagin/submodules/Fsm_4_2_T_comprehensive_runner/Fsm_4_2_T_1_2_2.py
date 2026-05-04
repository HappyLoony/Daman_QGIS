# -*- coding: utf-8 -*-
"""
Субмодуль Fsm_4_2_T_1_2_2 - Тесты OSM Loader (нативный Overpass API + OGR)
Проверка инициализации, unit-тесты _build_overpass_query, _find_sublayers_in_base,
_combine_osm_layers, парсинг osm_values, URL дедупликация, обработка ошибок Overpass.
"""

import os
import re
import tempfile
import shutil
from typing import Dict, List, Optional

from qgis.core import (
    QgsProject, QgsCoordinateReferenceSystem, QgsRectangle,
    QgsVectorLayer, QgsFeature, QgsGeometry, QgsPointXY,
    QgsWkbTypes, Qgis, QgsFields, QgsField, NULL)
from qgis.PyQt.QtCore import QMetaType


class TestQuickOSMLoader:
    """Тесты OSM Loader (нативный Overpass API + OGR)"""

    def __init__(self, iface, logger):
        """Инициализация теста"""
        self.iface = iface
        self.logger = logger
        self.test_dir = None
        self.original_project_path = None
        self.loader = None  # Экземпляр OSM Loader (Overpass API + OGR) для unit-тестов

    def run_all_tests(self):
        """Запуск всех тестов OSM Loader"""
        self.logger.section("ТЕСТ 7.3.2: OSM Loader (Overpass API + OGR)")

        try:
            # Подготовка окружения
            self._setup()

            # Секция 1: Импорт и инициализация
            self._test_import_and_init()

            # Секция 2: _build_overpass_query (unit-тесты OQL генерации)
            self._test_build_overpass_query()

            # Секция 3: _find_sublayers_in_base (поиск sublayer)
            self._test_find_sublayers_in_base()

            # Секция 4: _combine_osm_layers (объединение по геометрии)
            self._test_combine_osm_layers()

            # Секция 5: Парсинг osm_values и URL дедупликация
            self._test_osm_values_parsing()

            # Секция 6: Обработка ошибок _download_osm_data
            self._test_download_error_handling()

            # Секция 7: osm_no_data маркер
            self._test_osm_no_data_marker()

            # Секция 8: _merge_line_segments (объединение сегментов)
            self._test_merge_line_segments()

            # Секция 9: Фильтрация типов геометрии при обрезке (FIX-1 Round 3)
            self._test_clip_geometry_type_filter()

            self.logger.success("===== ТЕСТ 7.3.2 ПРОЙДЕН =====")

        except Exception as e:
            self.logger.fail(f"КРИТИЧЕСКАЯ ОШИБКА: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

        finally:
            self._cleanup()

        self.logger.summary()

    # -----------------------------------------------------------------
    # Setup / Cleanup
    # -----------------------------------------------------------------

    def _setup(self):
        """Подготовка тестового окружения"""
        project = QgsProject.instance()
        self.original_project_path = project.absolutePath()

        self.test_dir = tempfile.mkdtemp(prefix="qgis_test_osm_loader_")
        test_project_path = os.path.join(self.test_dir, "test_project.qgs")
        test_gpkg_path = os.path.join(self.test_dir, "project.gpkg")

        self._create_test_gpkg(test_gpkg_path)
        project.write(test_project_path)

        self.logger.info(f"Тестовое окружение: {self.test_dir}")

    def _create_test_gpkg(self, gpkg_path: str) -> None:
        """Создание минимального тестового GeoPackage"""
        import sqlite3

        conn = sqlite3.connect(gpkg_path)
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS gpkg_contents (
                table_name TEXT NOT NULL PRIMARY KEY,
                data_type TEXT NOT NULL,
                identifier TEXT UNIQUE,
                description TEXT DEFAULT '',
                last_change DATETIME NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                min_x DOUBLE, min_y DOUBLE, max_x DOUBLE, max_y DOUBLE,
                srs_id INTEGER
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS gpkg_spatial_ref_sys (
                srs_name TEXT NOT NULL,
                srs_id INTEGER NOT NULL PRIMARY KEY,
                organization TEXT NOT NULL,
                organization_coordsys_id INTEGER NOT NULL,
                definition TEXT NOT NULL,
                description TEXT
            )
        """)
        cursor.execute("""
            INSERT OR IGNORE INTO gpkg_spatial_ref_sys
            (srs_name, srs_id, organization, organization_coordsys_id, definition)
            VALUES ('WGS 84', 4326, 'EPSG', 4326,
            'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]]')
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS _metadata (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        conn.commit()
        conn.close()

    def _cleanup(self) -> None:
        """Очистка временных файлов"""
        if self.test_dir and os.path.exists(self.test_dir):
            try:
                shutil.rmtree(self.test_dir)
                self.logger.info("Временные файлы очищены")
            except Exception as e:
                self.logger.warning(f"Не удалось удалить временные файлы: {e}")

    # -----------------------------------------------------------------
    # Секция 1: Импорт и инициализация
    # -----------------------------------------------------------------

    def _test_import_and_init(self):
        """Тест импорта и создания экземпляра"""
        self.logger.warning(">>> СЕКЦИЯ 1: Импорт и инициализация")

        # 1.1 Проверка requests
        try:
            import requests as _req
            self.logger.success(f"requests доступен (v{_req.__version__})")
        except ImportError:
            self.logger.fail("requests не установлен! Необходим для Overpass API")
            return

        # 1.2 Импорт модуля
        from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_2_3_quickosm_loader import Fsm_1_2_3_QuickOSMLoader
        self.logger.success("Импорт Fsm_1_2_3_QuickOSMLoader OK")

        # 1.3 Создание экземпляра
        from Daman_QGIS.managers import APIManager, ProjectManager, LayerManager

        plugin_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
        project_manager = ProjectManager(self.iface, plugin_dir)
        project_manager._project_path = self.test_dir
        project_manager._gpkg_path = os.path.join(self.test_dir, "project.gpkg")
        layer_manager = LayerManager(self.iface)
        api_manager = APIManager()

        self.loader = Fsm_1_2_3_QuickOSMLoader(self.iface, layer_manager, project_manager, api_manager)
        self.logger.success("Экземпляр создан")

        # 1.4 Проверка публичных методов
        for method_name in ['load_osm_layer', 'load_all_osm_layers', 'save_layer_to_gpkg', 'get_boundary_extent']:
            self.logger.check(
                hasattr(self.loader, method_name),
                f"Публичный метод {method_name}()",
                f"Метод {method_name}() отсутствует!"
            )

        # 1.5 Проверка приватных методов
        for method_name in ['_build_overpass_query', '_download_osm_data', '_load_osm_via_ogr',
                            '_find_sublayers_in_base', '_cleanup_osm_file', '_try_load_from_server',
                            '_combine_osm_layers', '_clip_layer_by_boundaries', '_filter_osm_layer',
                            '_merge_line_segments']:
            self.logger.check(
                hasattr(self.loader, method_name),
                f"Приватный метод {method_name}()",
                f"Метод {method_name}() отсутствует!"
            )

    # -----------------------------------------------------------------
    # Секция 2: _build_overpass_query
    # -----------------------------------------------------------------

    def _test_build_overpass_query(self):
        """Unit-тесты генерации OQL запроса"""
        self.logger.warning(">>> СЕКЦИЯ 2: _build_overpass_query (OQL)")

        if not self.loader:
            self.logger.fail("Loader не инициализирован, пропуск секции 2")
            return

        build = self.loader._build_overpass_query
        bbox = QgsRectangle(37.5, 55.7, 37.7, 55.8)  # Москва (xMin, yMin, xMax, yMax)

        # 2.1 Базовый запрос без values
        query_no_values = build(bbox, 'highway')
        self.logger.check(
            '[out:xml]' in query_no_values,
            "OQL: формат [out:xml]",
            "OQL: отсутствует [out:xml]!"
        )
        self.logger.check(
            '[timeout:25]' in query_no_values,
            "OQL: timeout=25 по умолчанию (Variant A.2, 2026-04-30)",
            "OQL: неверный timeout!"
        )
        self.logger.check(
            '[maxsize:1073741824]' in query_no_values,
            "OQL: maxsize=1073741824 (1 GB) для крупных bbox (Variant A, 2026-04-30)",
            "OQL: maxsize не задан в OQL!"
        )
        self.logger.check(
            '["highway"]' in query_no_values,
            "OQL: фильтр без values = [\"key\"]",
            "OQL: неверный фильтр без values!"
        )
        self.logger.check(
            'way' in query_no_values and 'relation' in query_no_values,
            "OQL: way + relation",
            "OQL: отсутствует way или relation!"
        )
        self.logger.check(
            '(._;>;)' in query_no_values,
            "OQL: рекурсивное разворачивание нодов (._;>;)",
            "OQL: отсутствует (._;>;)!"
        )
        self.logger.check(
            'out body' in query_no_values,
            "OQL: out body",
            "OQL: отсутствует 'out body'!"
        )

        # 2.2 bbox формат: (south, west, north, east) = (yMin, xMin, yMax, xMax)
        self.logger.check(
            '(55.7,37.5,55.8,37.7)' in query_no_values,
            "OQL: bbox = (south,west,north,east) = (yMin,xMin,yMax,xMax)",
            f"OQL: неверный bbox! Ожидалось (55.7,37.5,55.8,37.7)"
        )

        # 2.3 Запрос с values (regex фильтрация)
        query_with_values = build(bbox, 'highway', ['motorway', 'trunk', 'primary'])
        self.logger.check(
            '~"^(motorway|trunk|primary)$"' in query_with_values,
            "OQL: regex фильтрация ^(val1|val2|val3)$",
            f"OQL: неверная regex фильтрация!"
        )

        # 2.4 re.escape() для спецсимволов
        query_special = build(bbox, 'name', ['test[1]', 'path.2', 'a(b)'])
        # re.escape превращает [ -> \[, . -> \., ( -> \(, ) -> \)
        self.logger.check(
            r'test\[1\]' in query_special,
            "OQL: re.escape() экранирует [ и ]",
            "OQL: спецсимволы [ ] не экранированы!"
        )
        self.logger.check(
            r'path\.2' in query_special,
            "OQL: re.escape() экранирует точку",
            "OQL: спецсимвол '.' не экранирован!"
        )
        self.logger.check(
            r'a\(b\)' in query_special,
            "OQL: re.escape() экранирует скобки",
            "OQL: спецсимволы ( ) не экранированы!"
        )

        # 2.5 Пустой список values = как None
        query_empty_list = build(bbox, 'highway', [])
        self.logger.check(
            '["highway"]' in query_empty_list,
            "OQL: пустой values=[] => фильтр без regex",
            "OQL: пустой values обработан неверно!"
        )

        # 2.6 Кастомный timeout
        query_custom_timeout = build(bbox, 'highway', timeout=120)
        self.logger.check(
            '[timeout:120]' in query_custom_timeout,
            "OQL: кастомный timeout=120",
            "OQL: кастомный timeout не применён!"
        )

        # 2.7 Валидация формата ключа (FIX-3)
        try:
            build(bbox, 'invalid"key')
            self.logger.fail("OQL: невалидный ключ 'invalid\"key' не вызвал ValueError!")
        except ValueError:
            self.logger.success("OQL: невалидный ключ корректно отклонён (ValueError)")
        except Exception as e:
            self.logger.fail(f"OQL: неожиданное исключение для невалидного ключа: {type(e).__name__}: {e}")

        # 2.7b Валидные ключи с двоеточиями (addr:street, building:levels)
        try:
            query_colon = build(bbox, 'addr:street')
            self.logger.check(
                '["addr:street"]' in query_colon,
                "OQL: ключ с двоеточием 'addr:street' принят",
                "OQL: ключ с двоеточием не принят!"
            )
        except ValueError:
            self.logger.fail("OQL: валидный ключ 'addr:street' отклонён!")

    # -----------------------------------------------------------------
    # Секция 3: _find_sublayers_in_base
    # -----------------------------------------------------------------

    def _test_find_sublayers_in_base(self):
        """Тест поиска sublayer в Base_layers.json"""
        self.logger.warning(">>> СЕКЦИЯ 3: _find_sublayers_in_base")

        if not self.loader:
            self.logger.fail("Loader не инициализирован, пропуск секции 3")
            return

        # 3.1 Парсинг корректного layer_name
        result = self.loader._find_sublayers_in_base("L_1_4_1_OSM_Дороги")
        self.logger.check(
            isinstance(result, dict),
            "Возвращает dict",
            f"Возвращает {type(result).__name__} вместо dict!"
        )

        # 3.2 Проверка что нашлись sublayer для дорог
        if result:
            has_line = 'line' in result
            has_poly = 'poly' in result
            self.logger.check(
                has_line,
                f"Sublayer 'line' найден: {result.get('line', '?')}",
                "Sublayer 'line' не найден для L_1_4_1!"
            )
            if has_line:
                self.logger.check(
                    result['line'].startswith('Le_'),
                    f"Имя начинается с 'Le_': {result['line']}",
                    f"Имя sublayer не начинается с 'Le_': {result['line']}!"
                )
            self.logger.info(f"Sublayer map для дорог: {result}")
        else:
            self.logger.warning("Base_layers.json не загружен или sublayer не найдены (допустимо в тестовом окружении)")

        # 3.3 Парсинг ЖД
        result_railway = self.loader._find_sublayers_in_base("L_1_4_2_OSM_ЖД")
        self.logger.check(
            isinstance(result_railway, dict),
            f"ЖД sublayer map: {result_railway}",
            "Ошибка парсинга L_1_4_2_OSM_ЖД!"
        )

        # 3.4 Некорректный layer_name (< 4 частей)
        result_bad = self.loader._find_sublayers_in_base("L_1_4")
        self.logger.check(
            result_bad == {},
            "Короткий layer_name => пустой dict",
            f"Короткий layer_name вернул непустой результат: {result_bad}!"
        )

        # 3.5 Несуществующая группа
        result_none = self.loader._find_sublayers_in_base("L_1_99_99_Несуществующий")
        self.logger.check(
            result_none == {},
            "Несуществующая группа => пустой dict",
            f"Несуществующая группа вернула: {result_none}!"
        )

    # -----------------------------------------------------------------
    # Секция 4: _combine_osm_layers
    # -----------------------------------------------------------------

    def _test_combine_osm_layers(self):
        """Тест объединения OGR слоёв по геометрии + sublayer_map"""
        self.logger.warning(">>> СЕКЦИЯ 4: _combine_osm_layers")

        if not self.loader:
            self.logger.fail("Loader не инициализирован, пропуск секции 4")
            return

        # 4.1 Создаём тестовые memory layers
        line_layer = QgsVectorLayer("LineString?crs=EPSG:4326", "test_lines", "memory")
        poly_layer = QgsVectorLayer("Polygon?crs=EPSG:4326", "test_polys", "memory")

        # Добавляем features в line layer
        line_layer.startEditing()
        line_layer.dataProvider().addAttributes([QgsField("name", QMetaType.Type.QString)])
        line_layer.updateFields()
        feat_line = QgsFeature(line_layer.fields())
        feat_line.setGeometry(QgsGeometry.fromPolylineXY([QgsPointXY(37.5, 55.7), QgsPointXY(37.6, 55.8)]))
        feat_line.setAttribute("name", "Test Road")
        line_layer.addFeature(feat_line)
        line_layer.commitChanges()

        # Добавляем features в poly layer
        poly_layer.startEditing()
        poly_layer.dataProvider().addAttributes([QgsField("name", QMetaType.Type.QString)])
        poly_layer.updateFields()
        feat_poly = QgsFeature(poly_layer.fields())
        feat_poly.setGeometry(QgsGeometry.fromPolygonXY([[
            QgsPointXY(37.5, 55.7), QgsPointXY(37.6, 55.7),
            QgsPointXY(37.6, 55.8), QgsPointXY(37.5, 55.8),
            QgsPointXY(37.5, 55.7)
        ]]))
        feat_poly.setAttribute("name", "Test Area")
        poly_layer.addFeature(feat_poly)
        poly_layer.commitChanges()

        # 4.2 Объединение с sublayer_map
        sublayer_map = {
            'line': 'Le_1_4_1_1_OSM_АД_line',
            'poly': 'Le_1_4_1_2_OSM_АД_poly'
        }
        combined = self.loader._combine_osm_layers(
            [line_layer, poly_layer], "L_1_4_1_OSM_Дороги", sublayer_map
        )

        self.logger.check(
            len(combined) >= 1,
            f"Объединение вернуло {len(combined)} слой(ёв)",
            "Объединение вернуло пустой список!"
        )

        # 4.3 Проверяем имена слоёв из sublayer_map
        combined_names = [lyr.name() for lyr in combined]
        self.logger.info(f"Имена слоёв после объединения: {combined_names}")

        has_sublayer_name = any(
            name in ['Le_1_4_1_1_OSM_АД_line', 'Le_1_4_1_2_OSM_АД_poly']
            for name in combined_names
        )
        self.logger.check(
            has_sublayer_name,
            "Имена из sublayer_map применены",
            f"sublayer_map имена не применены! Получено: {combined_names}"
        )

        # 4.4 Объединение без sublayer_map (fallback)
        combined_fallback = self.loader._combine_osm_layers(
            [line_layer], "L_1_4_1_OSM_Дороги", None
        )
        fallback_names = [lyr.name() for lyr in combined_fallback]
        self.logger.check(
            any('L_1_4_1_OSM_Дороги' in n for n in fallback_names),
            f"Fallback: имя содержит базовое имя: {fallback_names}",
            f"Fallback: неверные имена: {fallback_names}!"
        )

    # -----------------------------------------------------------------
    # Секция 5: Парсинг osm_values и URL дедупликация
    # -----------------------------------------------------------------

    def _test_osm_values_parsing(self):
        """Тест парсинга osm_values из endpoint и дедупликации URL"""
        self.logger.warning(">>> СЕКЦИЯ 5: Парсинг osm_values + URL дедупликация")

        # 5.1 Нормальный split
        values_str = "motorway;trunk;primary;secondary"
        values = [v for v in values_str.split(';') if v] if values_str else []
        self.logger.check(
            values == ['motorway', 'trunk', 'primary', 'secondary'],
            f"Split ';': 4 значения",
            f"Неверный split: {values}!"
        )

        # 5.2 Пустая строка
        values_empty = ""
        values_e = [v for v in values_empty.split(';') if v] if values_empty else []
        self.logger.check(
            values_e == [],
            "Пустая строка => пустой список",
            f"Пустая строка дала: {values_e}!"
        )

        # 5.3 None (get с default '')
        values_none_str = None
        values_n_str = values_none_str or ''
        values_n = [v for v in values_n_str.split(';') if v] if values_n_str else []
        self.logger.check(
            values_n == [],
            "None => пустой список",
            f"None дал: {values_n}!"
        )

        # 5.4 Trailing semicolon (защита от 'motorway;trunk;')
        values_trailing = "motorway;trunk;"
        values_t = [v for v in values_trailing.split(';') if v] if values_trailing else []
        self.logger.check(
            values_t == ['motorway', 'trunk'],
            "Trailing ';' не создает пустой элемент",
            f"Trailing ';' дал: {values_t}!"
        )

        # 5.5 URL дедупликация
        fallback_servers = [
            {'base_url': 'https://maps.mail.ru/osm/tools/overpass/api/'},
            {'base_url': 'https://overpass-api.de/api/'},
            {'base_url': 'https://maps.mail.ru/osm/tools/overpass/api/'},  # дубль
            {'base_url': 'https://overpass.kumi.systems/api/'},
        ]

        seen: set = set()
        server_urls: list = []
        for ep in fallback_servers:
            url = ep['base_url']
            if url not in seen:
                seen.add(url)
                server_urls.append(url)

        self.logger.check(
            len(server_urls) == 3,
            f"URL дедупликация: 4 -> {len(server_urls)} (убран дубль)",
            f"URL дедупликация: ожидалось 3, получено {len(server_urls)}!"
        )
        self.logger.check(
            server_urls[0] == 'https://maps.mail.ru/osm/tools/overpass/api/',
            "Порядок сохранён: Mail.ru первый",
            f"Порядок нарушен: первый = {server_urls[0]}!"
        )

    # -----------------------------------------------------------------
    # Секция 6: Обработка ошибок _download_osm_data
    # -----------------------------------------------------------------

    def _test_download_error_handling(self):
        """Тест обработки ошибок Overpass (без реальных запросов)"""
        self.logger.warning(">>> СЕКЦИЯ 6: Обработка ошибок Overpass")

        if not self.loader:
            self.logger.fail("Loader не инициализирован, пропуск секции 6")
            return

        # 6.1 Проверяем что _download_osm_data корректно бросает исключения
        # Делаем запрос к несуществующему серверу
        test_query = '[out:xml][timeout:5];\n(\n  way["highway"](0,0,0.001,0.001);\n);\n(._;>;);\nout body;'

        try:
            self.loader._download_osm_data(test_query, "http://127.0.0.1:1/api/", timeout=3)
            self.logger.fail("Запрос к несуществующему серверу не бросил исключение!")
        except Exception as e:
            error_msg = str(e)
            self.logger.success(f"Несуществующий сервер -> Exception: {error_msg[:80]}")

        # 6.2 Behavioral tests: mock-based Overpass error detection (FIX-2)
        from unittest.mock import MagicMock, patch

        # 6.2.1 Test: Overpass timeout detection
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.content = (
            b'<?xml version="1.0"?>\n'
            b'<html><p class="body">The server is probably too busy to handle your request.\n'
            b'runtime error: Query timed out in "query" at line 4</p></html>'
        )

        try:
            with patch('requests.post', return_value=mock_response):
                self.loader._download_osm_data(
                    "[out:xml][timeout:5];", "http://test/api/", timeout=5
                )
            self.logger.fail("Overpass timeout response не вызвал исключение!")
        except Exception as e:
            self.logger.check(
                'timeout' in str(e).lower(),
                f"Overpass timeout корректно обнаружен: {str(e)[:60]}",
                f"Неверное исключение для timeout: {e}"
            )

        # 6.2.2 Test: Overpass out-of-memory detection
        mock_response_oom = MagicMock()
        mock_response_oom.status_code = 200
        mock_response_oom.raise_for_status = MagicMock()
        mock_response_oom.content = (
            b'<?xml version="1.0"?>\n'
            b'<html><p>runtime error: out of memory</p></html>'
        )

        try:
            with patch('requests.post', return_value=mock_response_oom):
                self.loader._download_osm_data(
                    "[out:xml][timeout:5];", "http://test/api/", timeout=5
                )
            self.logger.fail("Overpass OOM response не вызвал исключение!")
        except Exception as e:
            self.logger.check(
                'memory' in str(e).lower(),
                f"Overpass out-of-memory корректно обнаружен: {str(e)[:60]}",
                f"Неверное исключение для OOM: {e}"
            )

        # 6.2.3 Test: Non-XML response detection
        mock_response_html = MagicMock()
        mock_response_html.status_code = 200
        mock_response_html.raise_for_status = MagicMock()
        mock_response_html.content = b'<html><body>503 Service Unavailable</body></html>'

        try:
            with patch('requests.post', return_value=mock_response_html):
                self.loader._download_osm_data(
                    "[out:xml][timeout:5];", "http://test/api/", timeout=5
                )
            self.logger.fail("Non-XML response не вызвал исключение!")
        except Exception as e:
            self.logger.check(
                'xml' in str(e).lower() or 'не-xml' in str(e).lower(),
                f"Non-XML ответ корректно обнаружен: {str(e)[:60]}",
                f"Неверное исключение для non-XML: {e}"
            )

        # 6.2.4 Test: Valid XML response succeeds
        mock_response_ok = MagicMock()
        mock_response_ok.status_code = 200
        mock_response_ok.raise_for_status = MagicMock()
        mock_response_ok.content = (
            b'<?xml version="1.0" encoding="UTF-8"?>\n'
            b'<osm version="0.6">\n'
            b'</osm>'
        )

        try:
            with patch('requests.post', return_value=mock_response_ok):
                result_path = self.loader._download_osm_data(
                    "[out:xml][timeout:5];", "http://test/api/", timeout=5
                )
            self.logger.check(
                os.path.exists(result_path),
                f"Валидный XML ответ сохранён: {result_path}",
                "Валидный XML ответ не сохранён!"
            )
            # Cleanup
            if os.path.exists(result_path):
                os.remove(result_path)
        except Exception as e:
            self.logger.fail(f"Валидный XML ответ вызвал исключение: {e}")

        # 6.3 Structural checks (supplementary -- encoding correctness)
        import inspect
        source = inspect.getsource(self.loader._download_osm_data)
        self.logger.check(
            'response.content' in source,
            "Используется response.content (bytes) для кириллицы",
            "Используется response.text вместо response.content!"
        )
        self.logger.check(
            "mode='wb'" in source or 'mode="wb"' in source,
            "Файл пишется в бинарном режиме (mode='wb')",
            "Файл пишется не в бинарном режиме!"
        )

    # -----------------------------------------------------------------
    # Секция 7: osm_no_data маркер
    # -----------------------------------------------------------------

    def _test_osm_no_data_marker(self):
        """Тест маркера osm_no_data для пустых областей"""
        self.logger.warning(">>> СЕКЦИЯ 7: osm_no_data маркер")

        if not self.loader:
            self.logger.fail("Loader не инициализирован, пропуск секции 7")
            return

        # 7.1 Проверяем что _try_load_from_server устанавливает маркер
        import inspect
        source_try = inspect.getsource(self.loader._try_load_from_server)
        self.logger.check(
            'osm_no_data' in source_try,
            "_try_load_from_server использует маркер 'osm_no_data'",
            "_try_load_from_server не использует маркер 'osm_no_data'!"
        )

        # 7.2 Проверяем что load_osm_layer проверяет маркер
        source_load = inspect.getsource(self.loader.load_osm_layer)
        self.logger.check(
            'osm_no_data' in source_load,
            "load_osm_layer проверяет маркер 'osm_no_data'",
            "load_osm_layer не проверяет маркер 'osm_no_data'!"
        )

        # 7.3 Проверяем что save_layer_to_gpkg обрабатывает маркер
        source_save = inspect.getsource(self.loader.save_layer_to_gpkg)
        self.logger.check(
            'osm_no_data' in source_save,
            "save_layer_to_gpkg обрабатывает маркер 'osm_no_data'",
            "save_layer_to_gpkg не обрабатывает маркер 'osm_no_data'!"
        )

        # 7.4 Функциональный тест: создаём слой с маркером
        empty_layer = QgsVectorLayer("LineString?crs=EPSG:4326", "test_empty", "memory")
        empty_layer.setCustomProperty("osm_no_data", True)
        self.logger.check(
            empty_layer.customProperty("osm_no_data") == True,
            "customProperty 'osm_no_data' устанавливается и читается",
            "customProperty 'osm_no_data' не работает!"
        )

        # 7.5 Проверяем двойную проверку featureCount в _load_osm_via_ogr
        # OGR OSM driver может вернуть -1 (unknown) вместо 0
        # После materialize featureCount() всегда точный
        source_ogr = inspect.getsource(self.loader._load_osm_via_ogr)
        materialize_count = source_ogr.count('featureCount()')
        self.logger.check(
            materialize_count >= 2,
            f"_load_osm_via_ogr: двойная проверка featureCount ({materialize_count} вызова)",
            f"_load_osm_via_ogr: ожидалось >= 2 проверок featureCount, "
            f"найдено {materialize_count} (OGR OSM может вернуть -1)!"
        )
        self.logger.check(
            'materialize' in source_ogr,
            "_load_osm_via_ogr использует materialize()",
            "_load_osm_via_ogr не использует materialize()!"
        )


    # -----------------------------------------------------------------
    # Секция 8: _merge_line_segments (объединение линейных сегментов)
    # -----------------------------------------------------------------

    def _test_merge_line_segments(self):
        """Тест объединения связанных OSM линейных сегментов"""
        self.logger.warning(">>> СЕКЦИЯ 8: _merge_line_segments")

        if not self.loader:
            self.logger.fail("Loader не инициализирован, пропуск секции 8")
            return

        # 8.1 Метод существует
        self.logger.check(
            hasattr(self.loader, '_merge_line_segments'),
            "_merge_line_segments() существует",
            "_merge_line_segments() отсутствует!"
        )

        # Хелпер: создать line memory layer с полями highway + name + other_tags
        def _create_line_layer(
            features_data: list,
            crs: str = "EPSG:4326",
            with_other_tags: bool = False
        ) -> QgsVectorLayer:
            """
            Создать memory layer с LineString геометрией.

            features_data: list of tuples:
              - (highway_val, name_val, [(x1,y1), ...])
              - (highway_val, name_val, [(x1,y1), ...], other_tags_str)  если with_other_tags
            """
            layer = QgsVectorLayer(f"LineString?crs={crs}", "test_lines", "memory")
            pr = layer.dataProvider()

            fields = QgsFields()
            fields.append(QgsField("osm_id", QMetaType.Type.QString))
            fields.append(QgsField("highway", QMetaType.Type.QString))
            fields.append(QgsField("name", QMetaType.Type.QString))
            if with_other_tags:
                fields.append(QgsField("other_tags", QMetaType.Type.QString))
            pr.addAttributes(fields)
            layer.updateFields()

            for i, item in enumerate(features_data):
                hw, nm, coords = item[0], item[1], item[2]
                other_tags = item[3] if len(item) > 3 else None

                feat = QgsFeature(layer.fields())
                feat.setAttribute("osm_id", str(1000 + i))
                feat.setAttribute("highway", hw)
                feat.setAttribute("name", nm)
                if with_other_tags and other_tags:
                    feat.setAttribute("other_tags", other_tags)
                points = [QgsPointXY(x, y) for x, y in coords]
                feat.setGeometry(QgsGeometry.fromPolylineXY(points))
                pr.addFeature(feat)

            layer.updateExtents()
            return layer

        # 8.2 Polygon layer -- возвращается без изменений
        poly_layer = QgsVectorLayer("Polygon?crs=EPSG:4326", "test_poly", "memory")
        result = self.loader._merge_line_segments(poly_layer, "highway")
        self.logger.check(
            result is poly_layer,
            "Polygon layer возвращается без изменений (passthrough)",
            "Polygon layer НЕ прошёл passthrough!"
        )

        # 8.3 Пустой line layer -- возвращается без изменений
        empty_layer = QgsVectorLayer("LineString?crs=EPSG:4326", "test_empty", "memory")
        result = self.loader._merge_line_segments(empty_layer, "highway")
        self.logger.check(
            result is empty_layer,
            "Пустой line layer возвращается без изменений",
            "Пустой line layer НЕ прошёл passthrough!"
        )

        # 8.4 Named segments: 2 "ул. Ленина" + 1 "пр. Мира" -> 2 features
        data_named = [
            ("residential", "ул. Ленина", [(37.0, 55.0), (37.001, 55.001)]),
            ("residential", "ул. Ленина", [(37.001, 55.001), (37.002, 55.002)]),
            ("primary", "пр. Мира", [(37.01, 55.01), (37.02, 55.02)]),
        ]
        layer_named = _create_line_layer(data_named)
        self.logger.check(
            layer_named.featureCount() == 3,
            f"Исходный слой: {layer_named.featureCount()} features",
            f"Ожидалось 3, получено {layer_named.featureCount()}"
        )

        result_named = self.loader._merge_line_segments(layer_named, "highway")
        self.logger.check(
            result_named.featureCount() == 2,
            f"Named merge: 3 -> {result_named.featureCount()} (ожидалось 2)",
            f"Named merge: ожидалось 2, получено {result_named.featureCount()}"
        )

        # 8.5a Unnamed segments: 2 unnamed touches, same highway -> 1 (объединяются)
        data_unnamed_touch = [
            ("service", None, [(37.0, 55.0), (37.001, 55.001)]),
            ("service", None, [(37.001, 55.001), (37.002, 55.002)]),
        ]
        layer_unnamed_touch = _create_line_layer(data_unnamed_touch)
        result_unnamed_touch = self.loader._merge_line_segments(layer_unnamed_touch, "highway")
        self.logger.check(
            result_unnamed_touch.featureCount() == 1,
            f"Unnamed touches merge: {result_unnamed_touch.featureCount()} (ожидалось 1)",
            f"Unnamed touches merge: ожидалось 1, получено {result_unnamed_touch.featureCount()}"
        )

        # 8.5b Unnamed segments: 2 unnamed НЕ touches -> 2 (НЕ объединяются)
        data_unnamed_far = [
            ("service", None, [(37.0, 55.0), (37.001, 55.001)]),
            ("service", None, [(37.01, 55.01), (37.011, 55.011)]),
        ]
        layer_unnamed_far = _create_line_layer(data_unnamed_far)
        result_unnamed_far = self.loader._merge_line_segments(layer_unnamed_far, "highway")
        self.logger.check(
            result_unnamed_far.featureCount() == 2,
            f"Unnamed far: {result_unnamed_far.featureCount()} features (не объединены)",
            f"Unnamed far: ожидалось 2, получено {result_unnamed_far.featureCount()}"
        )

        # 8.5c Unnamed: gravel + asphalt touches -> 2 (разный surface, НЕ объединяются)
        data_diff_surface = [
            ("service", None, [(37.0, 55.0), (37.001, 55.001)], '"surface"=>"gravel"'),
            ("service", None, [(37.001, 55.001), (37.002, 55.002)], '"surface"=>"asphalt"'),
        ]
        layer_diff_surface = _create_line_layer(data_diff_surface, with_other_tags=True)
        result_diff_surface = self.loader._merge_line_segments(layer_diff_surface, "highway")
        self.logger.check(
            result_diff_surface.featureCount() == 2,
            f"Different surface: {result_diff_surface.featureCount()} (не объединены)",
            f"Different surface: ожидалось 2, получено {result_diff_surface.featureCount()}"
        )

        # 8.5d Unnamed: 3 gravel цепочка A-B-C touches -> 1 (транзитивный merge)
        data_chain = [
            ("service", None, [(37.0, 55.0), (37.001, 55.001)], '"surface"=>"gravel"'),
            ("service", None, [(37.001, 55.001), (37.002, 55.002)], '"surface"=>"gravel"'),
            ("service", None, [(37.002, 55.002), (37.003, 55.003)], '"surface"=>"gravel"'),
        ]
        layer_chain = _create_line_layer(data_chain, with_other_tags=True)
        result_chain = self.loader._merge_line_segments(layer_chain, "highway")
        self.logger.check(
            result_chain.featureCount() == 1,
            f"Chain merge: 3 -> {result_chain.featureCount()} (ожидалось 1)",
            f"Chain merge: ожидалось 1, получено {result_chain.featureCount()}"
        )

        # 8.5e Unnamed: 30 features -> 3 кластера по 10 (Union-Find масштаб)
        # Pre-compute x координаты чтобы смежные сегменты делили exact float значения
        # (разные пути вычисления x_start+0.001 vs 37.0+(i+1)*0.001 дают IEEE 754 расхождения)
        x_coords = [37.0 + i * 0.001 for i in range(11)]
        data_large = []
        for cluster_y in [55.0, 55.01, 55.02]:
            for i in range(10):
                data_large.append(
                    ("service", None, [(x_coords[i], cluster_y), (x_coords[i + 1], cluster_y)],
                     '"surface"=>"gravel"')
                )
        layer_large = _create_line_layer(data_large, with_other_tags=True)
        self.logger.check(
            layer_large.featureCount() == 30,
            f"Large test: {layer_large.featureCount()} input features",
            f"Large test: ожидалось 30, получено {layer_large.featureCount()}"
        )
        result_large = self.loader._merge_line_segments(layer_large, "highway")
        self.logger.check(
            result_large.featureCount() == 3,
            f"Large merge: 30 -> {result_large.featureCount()} (ожидалось 3 кластера)",
            f"Large merge: ожидалось 3, получено {result_large.featureCount()}"
        )

        # 8.6 Смешанный: 2 named + 1 unnamed + 1 другое имя -> 3
        data_mixed = [
            ("residential", "ул. Ленина", [(37.0, 55.0), (37.001, 55.001)]),
            ("residential", "ул. Ленина", [(37.001, 55.001), (37.002, 55.002)]),
            ("residential", None, [(37.01, 55.01), (37.011, 55.011)]),
            ("primary", "пр. Мира", [(37.02, 55.02), (37.021, 55.021)]),
        ]
        layer_mixed = _create_line_layer(data_mixed)
        result_mixed = self.loader._merge_line_segments(layer_mixed, "highway")
        self.logger.check(
            result_mixed.featureCount() == 3,
            f"Mixed merge: 4 -> {result_mixed.featureCount()} (ожидалось 3)",
            f"Mixed merge: ожидалось 3, получено {result_mixed.featureCount()}"
        )

        # 8.7 Отсутствует поле key -- возвращается без изменений
        layer_nokey = _create_line_layer(data_named)
        result_nokey = self.loader._merge_line_segments(layer_nokey, "waterway")
        self.logger.check(
            result_nokey is layer_nokey,
            "Отсутствующий key field -> passthrough",
            "Отсутствующий key field НЕ прошёл passthrough!"
        )

        # 8.8 Результат merge -- валидный MultiLineString
        for feat in result_named.getFeatures():
            geom = feat.geometry()
            wkb_type = geom.wkbType()
            is_multi_line = QgsWkbTypes.geometryType(wkb_type) == Qgis.GeometryType.Line
            self.logger.check(
                is_multi_line and geom.isMultipart(),
                f"Feature '{feat.attribute('name')}': MultiLineString (valid)",
                f"Feature '{feat.attribute('name')}': "
                f"тип {QgsWkbTypes.displayString(wkb_type)}, multi={geom.isMultipart()}"
            )
            break  # Проверяем первый feature

        # 8.9 osm_id = None для merged features (OPT-1)
        for feat in result_named.getFeatures():
            name = feat.attribute('name')
            osm_id = feat.attribute('osm_id')
            if name == 'ул. Ленина':
                # 2 features merged -> osm_id should be NULL (QVariant NULL)
                # PyQGIS: setAttribute(idx, None) -> QVariant(NULL)
                # QVariant(NULL) is not Python None, check via isNull() or falsy
                from qgis.PyQt.QtCore import QVariant
                is_null = (
                    osm_id is None
                    or (isinstance(osm_id, QVariant) and osm_id.isNull())
                    or osm_id == ''
                    or osm_id == NULL
                )
                self.logger.check(
                    is_null,
                    f"Merged '{name}': osm_id = NULL (корректно)",
                    f"Merged '{name}': osm_id = '{osm_id}' (ожидалось NULL)"
                )
            elif name == 'пр. Мира':
                # 1 feature, not merged -> osm_id preserved
                from qgis.PyQt.QtCore import QVariant
                is_valid = (
                    osm_id is not None
                    and osm_id != ''
                    and not (isinstance(osm_id, QVariant) and osm_id.isNull())
                )
                self.logger.check(
                    is_valid,
                    f"Single '{name}': osm_id = '{osm_id}' (сохранен)",
                    f"Single '{name}': osm_id утерян"
                )


    def _test_clip_geometry_type_filter(self):
        """Секция 9: Фильтрация типов геометрии при обрезке (FIX-1 Round 3)"""
        self.logger.section("9: Clip geometry type filtering")

        if not self.loader:
            self.logger.fail("Loader не инициализирован")
            return

        # 9.1 Метод _clip_layer_by_boundaries существует
        has_method = hasattr(self.loader, '_clip_layer_by_boundaries')
        self.logger.check(
            has_method,
            "_clip_layer_by_boundaries метод существует",
            "_clip_layer_by_boundaries метод НЕ найден!"
        )
        if not has_method:
            return

        # 9.2 Polygon layer: результат содержит только Polygon/MultiPolygon
        # Создаём polygon layer с feature, затем clip
        poly_layer = QgsVectorLayer("Polygon?crs=EPSG:4326", "test_poly_clip", "memory")
        pr = poly_layer.dataProvider()
        fields = QgsFields()
        fields.append(QgsField("name", QMetaType.Type.QString))
        pr.addAttributes(fields)
        poly_layer.updateFields()

        # Полигон полностью внутри bbox
        feat = QgsFeature(poly_layer.fields())
        feat.setAttribute("name", "test_building")
        feat.setGeometry(QgsGeometry.fromWkt(
            "POLYGON((37.0 55.0, 37.001 55.0, 37.001 55.001, 37.0 55.001, 37.0 55.0))"
        ))
        pr.addFeature(feat)
        poly_layer.updateExtents()

        result = self.loader._clip_layer_by_boundaries(poly_layer)
        if result and result.featureCount() > 0:
            for f in result.getFeatures():
                geom_type = QgsWkbTypes.geometryType(f.geometry().wkbType())
                self.logger.check(
                    geom_type == Qgis.GeometryType.Polygon,
                    f"Clip polygon: результат = PolygonGeometry",
                    f"Clip polygon: результат = {QgsWkbTypes.geometryDisplayString(geom_type)} (ожидался Polygon)"
                )
                break
        else:
            self.logger.info("9.2 Skip: clip вернул пустой результат (нет boundary layer)")

        # 9.3 Line layer: результат содержит только Line/MultiLine
        line_layer = QgsVectorLayer("LineString?crs=EPSG:4326", "test_line_clip", "memory")
        pr2 = line_layer.dataProvider()
        fields2 = QgsFields()
        fields2.append(QgsField("name", QMetaType.Type.QString))
        pr2.addAttributes(fields2)
        line_layer.updateFields()

        feat2 = QgsFeature(line_layer.fields())
        feat2.setAttribute("name", "test_road")
        feat2.setGeometry(QgsGeometry.fromWkt(
            "LINESTRING(37.0 55.0, 37.001 55.001)"
        ))
        pr2.addFeature(feat2)
        line_layer.updateExtents()

        result2 = self.loader._clip_layer_by_boundaries(line_layer)
        if result2 and result2.featureCount() > 0:
            for f in result2.getFeatures():
                geom_type = QgsWkbTypes.geometryType(f.geometry().wkbType())
                self.logger.check(
                    geom_type == Qgis.GeometryType.Line,
                    f"Clip line: результат = LineGeometry",
                    f"Clip line: результат = {QgsWkbTypes.geometryDisplayString(geom_type)} (ожидался Line)"
                )
                break
        else:
            self.logger.info("9.3 Skip: clip вернул пустой результат (нет boundary layer)")

        # 9.4 Проверяем что код фильтрации присутствует (code inspection)
        import inspect
        source = inspect.getsource(self.loader._clip_layer_by_boundaries)
        has_type_check = 'target_geom_type' in source and 'result_geom_type' in source
        self.logger.check(
            has_type_check,
            "Код содержит проверку target_geom_type vs result_geom_type",
            "Код НЕ содержит проверку типа геометрии после intersection!"
        )

        # 9.5 GeometryCollection обработка присутствует
        has_gc_handling = 'GeometryCollection' in source and 'asGeometryCollection' in source
        self.logger.check(
            has_gc_handling,
            "Код содержит обработку GeometryCollection",
            "Код НЕ содержит обработку GeometryCollection!"
        )


def run_tests(iface, logger):
    """Точка входа для запуска тестов"""
    test = TestQuickOSMLoader(iface, logger)
    test.run_all_tests()
    return test
