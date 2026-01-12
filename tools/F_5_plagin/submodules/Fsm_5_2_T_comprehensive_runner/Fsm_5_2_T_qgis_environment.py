# -*- coding: utf-8 -*-
"""
Fsm_5_2_T_qgis_environment - Тест окружения QGIS

Проверяет:
1. Версия QGIS и совместимость
2. Доступность Processing framework
3. GDAL/OGR и драйверы
4. Шрифты (GOST 2.304)
5. Пути и переменные окружения
6. Провайдеры данных (ogr, memory, WFS)

Основано на best practices:
- pytest-qgis: https://github.com/GispoCoding/pytest-qgis
- QGIS Plugin Testing: https://github.com/gis-ops/tutorials/blob/master/qgis/QGIS_PluginTesting.md
"""

from typing import Any, List, Dict, Optional
import sys
import os

from qgis.core import (
    Qgis, QgsApplication, QgsProject, QgsProviderRegistry,
    QgsCoordinateReferenceSystem, QgsVectorLayer,
    QgsProcessingRegistry
)


class TestQgisEnvironment:
    """Тесты окружения QGIS"""

    # Минимальные требования
    MIN_QGIS_VERSION = 34000  # 3.40.0
    # Примечание: 'gpkg' не является отдельным провайдером - GeoPackage обрабатывается через 'ogr'
    # Поддержка GPKG проверяется в test_03_gdal_drivers через OGR драйвер 'GPKG'
    REQUIRED_PROVIDERS = ['ogr', 'memory']
    REQUIRED_GDAL_DRIVERS = ['GPKG', 'ESRI Shapefile', 'GeoJSON', 'DXF']

    def __init__(self, iface: Any, logger: Any) -> None:
        """Инициализация теста"""
        self.iface = iface
        self.logger = logger

    def run_all_tests(self) -> None:
        """Запуск всех тестов окружения"""
        self.logger.section("ТЕСТ ОКРУЖЕНИЯ QGIS")

        try:
            self.test_01_qgis_version()
            self.test_02_providers()
            self.test_03_gdal_drivers()
            self.test_04_processing_framework()
            self.test_05_crs_database()
            self.test_06_fonts()
            self.test_07_paths()
            self.test_08_memory_layer()

        except Exception as e:
            self.logger.error(f"Критическая ошибка тестов окружения: {str(e)}")

        self.logger.summary()

    def test_01_qgis_version(self) -> None:
        """ТЕСТ 1: Версия QGIS"""
        self.logger.section("1. Версия QGIS")

        try:
            version_int = Qgis.QGIS_VERSION_INT
            version_str = Qgis.QGIS_VERSION

            self.logger.info(f"QGIS версия: {version_str} ({version_int})")

            # Проверка минимальной версии
            if version_int >= self.MIN_QGIS_VERSION:
                self.logger.success(f"Версия >= {self.MIN_QGIS_VERSION // 10000}.{(self.MIN_QGIS_VERSION % 10000) // 100}")
            else:
                self.logger.warning(f"Версия < {self.MIN_QGIS_VERSION // 10000}.{(self.MIN_QGIS_VERSION % 10000) // 100} (рекомендуется обновить)")

            # Проверка LTR
            if 'LTR' in version_str or version_int % 10000 < 1000:
                self.logger.success("LTR версия")
            else:
                self.logger.info("Не LTR версия")

        except Exception as e:
            self.logger.error(f"Ошибка получения версии: {e}")

    def test_02_providers(self) -> None:
        """ТЕСТ 2: Провайдеры данных"""
        self.logger.section("2. Провайдеры данных")

        try:
            registry = QgsProviderRegistry.instance()
            available_providers = registry.providerList()

            self.logger.info(f"Доступно провайдеров: {len(available_providers)}")

            for provider in self.REQUIRED_PROVIDERS:
                if provider in available_providers:
                    self.logger.success(f"Провайдер '{provider}' доступен")
                else:
                    self.logger.fail(f"Провайдер '{provider}' НЕ доступен!")

            # Проверяем WFS провайдер (для F_1_2)
            if 'WFS' in available_providers:
                self.logger.success("Провайдер 'WFS' доступен")
            else:
                self.logger.warning("Провайдер 'WFS' недоступен (нужен для F_1_2)")

        except Exception as e:
            self.logger.error(f"Ошибка проверки провайдеров: {e}")

    def test_03_gdal_drivers(self) -> None:
        """ТЕСТ 3: GDAL драйверы"""
        self.logger.section("3. GDAL драйверы")

        try:
            from osgeo import gdal, ogr

            # Проверяем версию GDAL
            gdal_version = gdal.VersionInfo('VERSION_NUM')
            self.logger.info(f"GDAL версия: {gdal_version}")

            # Проверяем OGR драйверы
            ogr_driver_count = ogr.GetDriverCount()
            self.logger.info(f"OGR драйверов: {ogr_driver_count}")

            for driver_name in self.REQUIRED_GDAL_DRIVERS:
                driver = ogr.GetDriverByName(driver_name)
                if driver is not None:
                    self.logger.success(f"Драйвер '{driver_name}' доступен")
                else:
                    self.logger.fail(f"Драйвер '{driver_name}' НЕ доступен!")

            # Проверяем TAB (MapInfo)
            tab_driver = ogr.GetDriverByName('MapInfo File')
            if tab_driver is not None:
                self.logger.success("Драйвер 'MapInfo File' (TAB) доступен")
            else:
                self.logger.warning("Драйвер TAB недоступен (нужен для экспорта)")

        except ImportError:
            self.logger.error("osgeo (GDAL) не установлен!")
        except Exception as e:
            self.logger.error(f"Ошибка проверки GDAL: {e}")

    def test_04_processing_framework(self) -> None:
        """ТЕСТ 4: Processing framework"""
        self.logger.section("4. Processing framework")

        try:
            # Проверяем доступность processing
            import processing
            self.logger.success("Модуль processing импортирован")

            # Проверяем registry
            registry = QgsApplication.processingRegistry()
            providers = registry.providers()
            self.logger.info(f"Processing провайдеров: {len(providers)}")

            # Проверяем native алгоритмы
            native_provider = None
            for provider in providers:
                if provider.id() == 'native':
                    native_provider = provider
                    break

            if native_provider:
                alg_count = len(native_provider.algorithms())
                self.logger.success(f"Native провайдер: {alg_count} алгоритмов")

                # Проверяем ключевые алгоритмы для плагина
                key_algorithms = [
                    'native:fixgeometries',
                    'native:dissolve',
                    'native:buffer',
                    'native:intersection',
                    'native:difference',
                ]

                for alg_id in key_algorithms:
                    alg = QgsApplication.processingRegistry().algorithmById(alg_id)
                    if alg:
                        self.logger.success(f"Алгоритм '{alg_id}' доступен")
                    else:
                        self.logger.warning(f"Алгоритм '{alg_id}' недоступен")
            else:
                self.logger.fail("Native провайдер не найден!")

        except ImportError:
            self.logger.warning("Модуль processing недоступен (запуск вне QGIS?)")
        except Exception as e:
            self.logger.error(f"Ошибка проверки Processing: {e}")

    def test_05_crs_database(self) -> None:
        """ТЕСТ 5: База данных CRS"""
        self.logger.section("5. База данных CRS")

        try:
            # Ключевые CRS для плагина
            test_crs = [
                ("EPSG:4326", "WGS84"),
                ("EPSG:3857", "Web Mercator"),
                ("EPSG:4284", "Pulkovo 1942"),
                ("EPSG:28404", "SK-42 Zone 4"),
            ]

            for epsg, name in test_crs:
                crs = QgsCoordinateReferenceSystem(epsg)
                if crs.isValid():
                    self.logger.success(f"{epsg} ({name}) валидна")
                else:
                    self.logger.fail(f"{epsg} ({name}) НЕ валидна!")

            # Проверяем пользовательские CRS (МСК)
            # Обычно МСК определяются через PROJ строку
            proj_string = "+proj=tmerc +lat_0=0 +lon_0=37.5 +k=1 +x_0=4500000 +y_0=0 +ellps=krass +towgs84=23.57,-140.95,-79.8,0,0.35,0.79,-0.22 +units=m +no_defs"
            custom_crs = QgsCoordinateReferenceSystem()
            custom_crs.createFromProj(proj_string)

            if custom_crs.isValid():
                self.logger.success("Пользовательская МСК (PROJ) создаётся корректно")
            else:
                self.logger.warning("Проблема с созданием пользовательской CRS")

        except Exception as e:
            self.logger.error(f"Ошибка проверки CRS: {e}")

    def test_06_fonts(self) -> None:
        """ТЕСТ 6: Шрифты (GOST 2.304)"""
        self.logger.section("6. Шрифты")

        try:
            from qgis.PyQt.QtGui import QFontDatabase

            font_db = QFontDatabase()
            all_fonts = font_db.families()

            self.logger.info(f"Системных шрифтов: {len(all_fonts)}")

            # Проверяем GOST шрифты
            gost_fonts = [f for f in all_fonts if 'GOST' in f.upper() or 'ГОСТ' in f.upper()]

            if gost_fonts:
                self.logger.success(f"GOST шрифты установлены: {len(gost_fonts)}")
                for font in gost_fonts[:3]:  # Показываем первые 3
                    self.logger.info(f"  - {font}")
            else:
                self.logger.warning("GOST шрифты не найдены (установите через F_5_1)")

        except Exception as e:
            self.logger.error(f"Ошибка проверки шрифтов: {e}")

    def test_07_paths(self) -> None:
        """ТЕСТ 7: Пути и переменные окружения"""
        self.logger.section("7. Пути")

        try:
            # QGIS paths
            qgis_prefix = QgsApplication.prefixPath()
            qgis_settings = QgsApplication.qgisSettingsDirPath()
            qgis_plugins = os.path.join(qgis_settings, 'python', 'plugins')

            self.logger.info(f"QGIS prefix: {qgis_prefix}")
            self.logger.info(f"Settings dir: {qgis_settings}")

            # Проверяем путь к плагинам
            if os.path.exists(qgis_plugins):
                self.logger.success("Папка плагинов существует")
            else:
                self.logger.warning("Папка плагинов не найдена")

            # Python paths
            self.logger.info(f"Python: {sys.executable}")
            self.logger.info(f"Python version: {sys.version.split()[0]}")

            # Проверяем site-packages в пути
            has_site_packages = any('site-packages' in p for p in sys.path)
            if has_site_packages:
                self.logger.success("site-packages в sys.path")
            else:
                self.logger.warning("site-packages не в sys.path")

        except Exception as e:
            self.logger.error(f"Ошибка проверки путей: {e}")

    def test_08_memory_layer(self) -> None:
        """ТЕСТ 8: Создание memory layer"""
        self.logger.section("8. Memory layer")

        try:
            # Создаём тестовый слой в памяти
            layer = QgsVectorLayer(
                "Polygon?crs=EPSG:4326&field=id:integer&field=name:string",
                "test_memory_layer",
                "memory"
            )

            if layer.isValid():
                self.logger.success("Memory layer создан")
            else:
                self.logger.fail("Memory layer НЕ валиден!")
                return

            # Проверяем добавление объекта
            from qgis.core import QgsFeature, QgsGeometry

            provider = layer.dataProvider()
            feature = QgsFeature()
            feature.setGeometry(QgsGeometry.fromWkt("POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))"))
            feature.setAttributes([1, "test"])

            success, _ = provider.addFeatures([feature])
            if success:
                self.logger.success("Feature добавлен в memory layer")
            else:
                self.logger.fail("Ошибка добавления feature!")

            # Проверяем чтение
            if layer.featureCount() == 1:
                self.logger.success("featureCount() работает корректно")
            else:
                self.logger.fail(f"Ожидалось 1 feature, получено {layer.featureCount()}")

            # Очистка
            del layer

        except Exception as e:
            self.logger.error(f"Ошибка теста memory layer: {e}")
