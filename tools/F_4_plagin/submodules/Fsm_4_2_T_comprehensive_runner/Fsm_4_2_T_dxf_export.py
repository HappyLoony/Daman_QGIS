# -*- coding: utf-8 -*-
"""
Fsm_4_2_T_dxf_export - Тесты DXF экспорта (субмодули Fsm_dxf_1..5)

Покрывает исправления из adversarial review:
- FIX-1: Cross-CRS block geometry (transformed_geometry parameter)
- FIX-2: Hatch holes support (hatch_manager, geometry_exporter, block_exporter)
- FIX-3: Linetype patterns (total_pattern_length prefix)
- FIX-4: MULTILEADER layer assignment via dxfattribs + O(1) access
"""

import os
import tempfile
import traceback

import ezdxf
from ezdxf.filemanagement import new as ezdxf_new

from qgis.core import (
    QgsVectorLayer, QgsFeature, QgsGeometry, QgsProject,
    QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsPointXY
)


class TestDxfExport:
    """Тесты для DXF экспорта (Fsm_dxf_1..5)"""

    def __init__(self, iface, logger):
        """Инициализация теста"""
        self.iface = iface
        self.logger = logger

    def run_all_tests(self):
        """Запуск всех тестов DXF экспорта"""
        self.logger.section("ТЕСТ DXF EXPORT: Субмодули Fsm_dxf_1..5")

        try:
            self.test_01_imports()
            self.test_02_linetype_patterns()
            self.test_03_hatch_manager_holes()
            self.test_04_geometry_exporter_hatch_holes()
            self.test_05_block_exporter_transformed_geometry()
            self.test_06_block_exporter_hatch_holes()
            self.test_07_multileader_layer_assignment()
            self.test_08_zoom_extents()
            self.test_09_remove_closing_point()
            self.test_10_point_deduplication()

        except Exception as e:
            self.logger.error(f"Критическая ошибка тестов DXF: {str(e)}")
            self.logger.data("Traceback", traceback.format_exc())

        self.logger.summary()

    # =========================================================================
    # ТЕСТ 1: Импорты
    # =========================================================================

    def test_01_imports(self):
        """ТЕСТ 1: Проверка импортов всех DXF субмодулей"""
        self.logger.section("1. Импорты DXF субмодулей")

        try:
            from Daman_QGIS.tools.F_1_data.core.dxf.Fsm_dxf_1_block_exporter import DxfBlockExporter
            self.logger.success("DxfBlockExporter импортирован")
        except Exception as e:
            self.logger.fail(f"Ошибка импорта DxfBlockExporter: {e}")

        try:
            from Daman_QGIS.tools.F_1_data.core.dxf.Fsm_dxf_2_geometry_exporter import DxfGeometryExporter
            self.logger.success("DxfGeometryExporter импортирован")
        except Exception as e:
            self.logger.fail(f"Ошибка импорта DxfGeometryExporter: {e}")

        try:
            from Daman_QGIS.tools.F_1_data.core.dxf.Fsm_dxf_3_label_exporter import DxfLabelExporter
            self.logger.success("DxfLabelExporter импортирован")
        except Exception as e:
            self.logger.fail(f"Ошибка импорта DxfLabelExporter: {e}")

        try:
            from Daman_QGIS.tools.F_1_data.core.dxf.Fsm_dxf_4_hatch_manager import DxfHatchManager
            self.logger.success("DxfHatchManager импортирован")
        except Exception as e:
            self.logger.fail(f"Ошибка импорта DxfHatchManager: {e}")

        try:
            from Daman_QGIS.tools.F_1_data.core.dxf.Fsm_dxf_5_layer_utils import DxfLayerUtils
            self.logger.success("DxfLayerUtils импортирован")
        except Exception as e:
            self.logger.fail(f"Ошибка импорта DxfLayerUtils: {e}")

        try:
            import ezdxf
            self.logger.success(f"ezdxf v{ezdxf.__version__} доступен")
        except Exception as e:
            self.logger.fail(f"ezdxf не доступен: {e}")

    # =========================================================================
    # ТЕСТ 2: FIX-3 - Linetype patterns (total_pattern_length)
    # =========================================================================

    def test_02_linetype_patterns(self):
        """ТЕСТ 2: FIX-3 - Корректный формат паттернов типов линий"""
        self.logger.section("2. FIX-3: Linetype patterns")

        try:
            from Daman_QGIS.tools.F_1_data.core.dxf.Fsm_dxf_5_layer_utils import DxfLayerUtils
            from Daman_QGIS.managers import get_reference_managers

            ref_managers = get_reference_managers()
            layer_utils = DxfLayerUtils(ref_managers)

            doc = ezdxf_new('AC1027')

            # Добавляем DASHED
            layer_utils.add_linetype(doc, 'DASHED')
            self.logger.check(
                'DASHED' in doc.linetypes,
                "DASHED linetype добавлен",
                "DASHED linetype НЕ добавлен!"
            )

            if 'DASHED' in doc.linetypes:
                lt = doc.linetypes.get('DASHED')
                pattern = lt.pattern_tags.tags
                # Проверяем что паттерн не пустой и не вызывает ошибку при сохранении
                self.logger.check(
                    len(pattern) > 0,
                    f"DASHED паттерн содержит {len(pattern)} элементов",
                    "DASHED паттерн пустой!"
                )

                # FIX-3: Проверяем количество элементов паттерна
                # ezdxf pattern_tags содержит DXFTag объекты:
                # group 53 = element count, group 40 = total_length + elements
                # Для DASHED: total + dash + gap = 3 DXFTag(40,...) + 1 DXFTag(53,...)
                # Главная проверка: element count (group 73) должен быть 2 (dash + gap)
                # Без FIX-3 было: count=1 (только gap), что давало CONTINUOUS
                element_count_tags = [t for t in pattern if t.code == 73]
                if element_count_tags:
                    elem_count = int(element_count_tags[0].value)
                    self.logger.check(
                        elem_count == 2,
                        f"DASHED: element_count={elem_count} (dash + gap)",
                        f"DASHED: element_count={elem_count}, ожидалось 2! (Баг FIX-3: first elem consumed as total_length)"
                    )

            # Добавляем DASHDOT
            layer_utils.add_linetype(doc, 'DASHDOT')
            self.logger.check(
                'DASHDOT' in doc.linetypes,
                "DASHDOT linetype добавлен",
                "DASHDOT linetype НЕ добавлен!"
            )

            if 'DASHDOT' in doc.linetypes:
                lt = doc.linetypes.get('DASHDOT')
                pattern = lt.pattern_tags.tags
                element_count_tags = [t for t in pattern if t.code == 73]
                if element_count_tags:
                    elem_count = int(element_count_tags[0].value)
                    self.logger.check(
                        elem_count == 4,
                        f"DASHDOT: element_count={elem_count} (dash + gap + dot + gap)",
                        f"DASHDOT: element_count={elem_count}, ожидалось 4! (Баг FIX-3)"
                    )

            # Проверяем что DXF файл сохраняется без ошибок с кастомными linetypes
            fd, tmp_path = tempfile.mkstemp(suffix='.dxf')
            os.close(fd)
            try:
                msp = doc.modelspace()
                # Добавляем линию с DASHED чтобы linetype использовался
                dxf_layer = doc.layers.add('TestDashed')
                dxf_layer.dxf.linetype = 'DASHED'
                msp.add_lwpolyline([(0, 0), (10, 0)], dxfattribs={'layer': 'TestDashed'})

                doc.saveas(tmp_path)
                self.logger.success("DXF с кастомными linetypes сохранён без ошибок")

                # Перечитываем и проверяем
                doc2 = ezdxf.readfile(tmp_path)
                self.logger.check(
                    'DASHED' in doc2.linetypes,
                    "DASHED сохранился в DXF",
                    "DASHED не найден в сохранённом DXF!"
                )
                self.logger.check(
                    'DASHDOT' in doc2.linetypes,
                    "DASHDOT сохранился в DXF",
                    "DASHDOT не найден в сохранённом DXF!"
                )
            finally:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)

        except Exception as e:
            self.logger.error(f"Ошибка теста linetype: {e}")
            self.logger.data("Traceback", traceback.format_exc())

    # =========================================================================
    # ТЕСТ 3: FIX-2a - Hatch Manager holes support
    # =========================================================================

    def test_03_hatch_manager_holes(self):
        """ТЕСТ 3: FIX-2a - DxfHatchManager поддержка дырок"""
        self.logger.section("3. FIX-2a: Hatch Manager holes")

        try:
            from Daman_QGIS.tools.F_1_data.core.dxf.Fsm_dxf_4_hatch_manager import DxfHatchManager

            hatch_mgr = DxfHatchManager()
            doc = ezdxf_new('AC1027')
            msp = doc.modelspace()

            # Координаты внешнего контура (квадрат 10x10)
            exterior_coords = [(0, 0), (10, 0), (10, 10), (0, 10)]

            # Координаты дырки (квадрат 3x3 внутри)
            hole_coords = [(3, 3), (6, 3), (6, 6), (3, 6)]

            style = {'hatch': 'SOLID'}
            dxf_attribs = {'color': 256, 'layer': '0'}

            # Тест 3.1: Штриховка БЕЗ дырок (обратная совместимость)
            hatch_mgr.apply_hatch(msp, exterior_coords, style, dxf_attribs)
            hatches = list(msp.query('HATCH'))
            self.logger.check(
                len(hatches) == 1,
                "HATCH без дырок создан (1 штриховка)",
                f"Ожидалась 1 штриховка, получено {len(hatches)}"
            )

            if hatches:
                paths_count = len(hatches[0].paths)
                self.logger.check(
                    paths_count == 1,
                    "HATCH без дырок имеет 1 boundary path",
                    f"Ожидался 1 path, получено {paths_count}"
                )

                # Проверяем FLAGS внешнего контура
                ext_flags = hatches[0].paths[0].path_type_flags
                self.logger.check(
                    ext_flags & ezdxf.const.BOUNDARY_PATH_EXTERNAL != 0,
                    f"Внешний контур имеет EXTERNAL flag ({ext_flags})",
                    f"Внешний контур НЕ имеет EXTERNAL flag ({ext_flags})! Ожидался бит {ezdxf.const.BOUNDARY_PATH_EXTERNAL}"
                )

            # Тест 3.2: Штриховка С дыркой
            hatch_mgr.apply_hatch(msp, exterior_coords, style, dxf_attribs, holes=[hole_coords])
            hatches = list(msp.query('HATCH'))
            self.logger.check(
                len(hatches) == 2,
                "HATCH с дыркой создан (всего 2 штриховки)",
                f"Ожидалось 2 штриховки, получено {len(hatches)}"
            )

            # Проверяем что вторая штриховка имеет 2 boundary paths (exterior + hole)
            if len(hatches) >= 2:
                paths_count = len(hatches[1].paths)
                self.logger.check(
                    paths_count == 2,
                    "HATCH с дыркой имеет 2 boundary paths (exterior + hole)",
                    f"Ожидалось 2 paths, получено {paths_count}"
                )

                # FIX-2: Проверяем FLAGS дырки
                # BOUNDARY_PATH_EXTERNAL=1 (внешний), BOUNDARY_PATH_OUTERMOST=16 (дырка)
                if paths_count >= 2:
                    hole_flags = hatches[1].paths[1].path_type_flags
                    self.logger.check(
                        hole_flags & ezdxf.const.BOUNDARY_PATH_OUTERMOST != 0,
                        f"Дырка имеет OUTERMOST flag ({hole_flags})",
                        f"Дырка НЕ имеет OUTERMOST flag ({hole_flags})! Ожидался бит {ezdxf.const.BOUNDARY_PATH_OUTERMOST}"
                    )

            # Тест 3.3: Штриховка с НЕСКОЛЬКИМИ дырками
            hole2 = [(7, 7), (9, 7), (9, 9), (7, 9)]
            hatch_mgr.apply_hatch(msp, exterior_coords, style, dxf_attribs, holes=[hole_coords, hole2])
            hatches = list(msp.query('HATCH'))
            latest_hatch = hatches[-1]
            paths_count = len(latest_hatch.paths)
            self.logger.check(
                paths_count == 3,
                "HATCH с 2 дырками имеет 3 boundary paths",
                f"Ожидалось 3 paths, получено {paths_count}"
            )

        except Exception as e:
            self.logger.error(f"Ошибка теста hatch holes: {e}")
            self.logger.data("Traceback", traceback.format_exc())

    # =========================================================================
    # ТЕСТ 4: FIX-2b - Geometry Exporter hatch holes
    # =========================================================================

    def test_04_geometry_exporter_hatch_holes(self):
        """ТЕСТ 4: FIX-2b - DxfGeometryExporter передача дырок в штриховку"""
        self.logger.section("4. FIX-2b: Geometry Exporter hatch holes")

        try:
            from Daman_QGIS.tools.F_1_data.core.dxf.Fsm_dxf_2_geometry_exporter import DxfGeometryExporter
            from Daman_QGIS.tools.F_1_data.core.dxf.Fsm_dxf_4_hatch_manager import DxfHatchManager

            hatch_mgr = DxfHatchManager()
            geom_exporter = DxfGeometryExporter(hatch_manager=hatch_mgr)

            doc = ezdxf_new('AC1027')
            msp = doc.modelspace()
            doc.layers.add('TestPolygon')

            # Создаём слой с полигоном-с-дыркой
            layer = QgsVectorLayer(
                "Polygon?crs=epsg:4326&field=id:integer&field=name:string",
                "test_polygon_holes", "memory"
            )

            # Полигон с дыркой: внешний 0,0-10,10, дырка 3,3-6,6
            wkt = "POLYGON((0 0, 10 0, 10 10, 0 10, 0 0),(3 3, 6 3, 6 6, 3 6, 3 3))"
            feature = QgsFeature(layer.fields())
            geom = QgsGeometry.fromWkt(wkt)
            feature.setGeometry(geom)
            feature.setAttributes([1, "poly_with_hole"])
            layer.dataProvider().addFeature(feature)

            # Экспортируем со сплошной заливкой через колонку fill
            # (с 2026-04-30 заливка управляется fill=1 + fill_color, а не hatch=SOLID).
            # Regression-guard FIX-2b: проверяется что HATCH с holes создаётся
            # независимо от триггера заливки.
            style = {
                'fill': 1,
                'fill_color': 1,
                'linetype': 'CONTINUOUS',
                'color': 1,
                'lineweight': 100
            }

            for feat in layer.getFeatures():
                geom_exporter.export_simple_geometry(
                    feat, layer, 'TestPolygon', doc, msp,
                    style=style,
                    coordinate_precision=6
                )

            # Проверяем результат
            hatches = list(msp.query('HATCH'))
            self.logger.check(
                len(hatches) >= 1,
                f"Штриховка создана ({len(hatches)} шт)",
                "Штриховка НЕ создана для полигона с дыркой!"
            )

            # Проверяем наличие boundary paths с дыркой
            if hatches:
                # Ищем штриховку с 2 boundary paths (exterior + hole)
                found_hatch_with_hole = False
                for h in hatches:
                    if len(h.paths) >= 2:
                        found_hatch_with_hole = True
                        break

                self.logger.check(
                    found_hatch_with_hole,
                    "Штриховка содержит дырку (2+ boundary paths)",
                    "Штриховка НЕ содержит дырку - дырки не передаются!"
                )

            # Проверяем что полилинии тоже есть (контур + дырка)
            polylines = list(msp.query('LWPOLYLINE'))
            self.logger.check(
                len(polylines) >= 2,
                f"Полилинии: {len(polylines)} (контур + дырка)",
                f"Ожидалось >= 2 полилиний, получено {len(polylines)}"
            )

        except Exception as e:
            self.logger.error(f"Ошибка теста geometry hatch holes: {e}")
            self.logger.data("Traceback", traceback.format_exc())

    # =========================================================================
    # ТЕСТ 5: FIX-1 - Block Exporter transformed_geometry
    # =========================================================================

    def test_05_block_exporter_transformed_geometry(self):
        """ТЕСТ 5: FIX-1 - DxfBlockExporter: transformed_geometry вместо повторного feature.geometry()"""
        self.logger.section("5. FIX-1: Block Exporter transformed_geometry")

        try:
            from Daman_QGIS.tools.F_1_data.core.dxf.Fsm_dxf_1_block_exporter import DxfBlockExporter

            block_exporter = DxfBlockExporter()

            doc = ezdxf_new('AC1027')
            msp = doc.modelspace()
            doc.layers.add('TestBlock')

            # Создаём слой в EPSG:4326
            layer = QgsVectorLayer(
                "Polygon?crs=epsg:4326&field=id:integer&field=name:string",
                "test_block_crs", "memory"
            )

            # Полигон в координатах WGS-84 (центр Москвы)
            wkt = "POLYGON((37.61 55.74, 37.62 55.74, 37.62 55.75, 37.61 55.75, 37.61 55.74))"
            feature = QgsFeature(layer.fields())
            geom = QgsGeometry.fromWkt(wkt)
            feature.setGeometry(geom)
            feature.setAttributes([1, "moscow"])
            layer.dataProvider().addFeature(feature)

            # Создаём трансформацию в Web Mercator (EPSG:3857)
            crs_src = QgsCoordinateReferenceSystem("EPSG:4326")
            crs_dst = QgsCoordinateReferenceSystem("EPSG:3857")
            crs_transform = QgsCoordinateTransform(crs_src, crs_dst, QgsProject.instance())

            style = {
                'color': 1,
                'linetype': 'CONTINUOUS',
                'lineweight': 100
            }

            # Экспортируем с CRS трансформацией
            for feat in layer.getFeatures():
                block_exporter.export_feature_as_block(
                    feat, layer, 'TestBlock', doc, msp,
                    crs_transform=crs_transform,
                    style=style,
                    coordinate_precision=2
                )

            # Проверяем что блоки созданы
            block_refs = list(msp.query('INSERT'))
            self.logger.check(
                len(block_refs) >= 1,
                f"Блок создан ({len(block_refs)} INSERT)",
                "Блок НЕ создан!"
            )

            if block_refs:
                # Проверяем координаты insert point - должны быть в EPSG:3857 (метры),
                # а НЕ в EPSG:4326 (градусы)
                insert = block_refs[0].dxf.insert
                x, y = insert.x, insert.y

                # EPSG:3857 координаты для Москвы: ~4185000, ~7473000
                # EPSG:4326 координаты: ~37.6, ~55.7
                # Если CRS трансформация НЕ применилась, координаты будут маленькими (<100)
                self.logger.check(
                    abs(x) > 1000,
                    f"Insert point X={x:.0f} (EPSG:3857, трансформация применена)",
                    f"Insert point X={x:.2f} слишком мал - CRS трансформация НЕ применена!"
                )
                self.logger.check(
                    abs(y) > 1000,
                    f"Insert point Y={y:.0f} (EPSG:3857, трансформация применена)",
                    f"Insert point Y={y:.2f} слишком мал - CRS трансформация НЕ применена!"
                )

                # FIX-1 ГЛАВНАЯ ПРОВЕРКА: координаты внутри блока должны быть в
                # трансформированной СК (EPSG:3857, метры), а НЕ в исходной (EPSG:4326, градусы)
                #
                # Баг FIX-1: _create_block_for_feature() вызывал feature.geometry() повторно,
                # получая НЕТРАНСФОРМИРОВАННУЮ копию. Центроид блока = трансформированный,
                # а вершины = нетрансформированные. После INSERT + vertex = МУСОР.
                #
                # Тест-полигон: 37.61-37.62, 55.74-55.75 (WGS-84) = ~0.01 градуса
                # В EPSG:3857: это ~1000м по X и ~700м по Y (разница координат)
                # Если баг: смещение вершин от центроида будет ~0.005 (градусы)
                # Если ОК: смещение вершин от центроида будет ~500м (метры)
                block_name = block_refs[0].dxf.name
                block = doc.blocks.get(block_name)
                polylines = list(block.query('LWPOLYLINE'))

                if polylines:
                    vertices = list(polylines[0].get_points(format='xy'))
                    if len(vertices) >= 2:
                        # Вычисляем размах координат (max - min)
                        xs = [v[0] for v in vertices]
                        ys = [v[1] for v in vertices]
                        span_x = max(xs) - min(xs)
                        span_y = max(ys) - min(ys)

                        # В EPSG:3857: span ~1000м, в EPSG:4326: span ~0.01
                        # Порог 10 отсекает градусы от метров
                        self.logger.check(
                            span_x > 10,
                            f"Блок внутр. span_x={span_x:.1f}м (EPSG:3857, трансформация в блоке)",
                            f"Блок внутр. span_x={span_x:.6f} слишком мал - блок в ИСХОДНОЙ СК! (Баг FIX-1)"
                        )
                        self.logger.check(
                            span_y > 10,
                            f"Блок внутр. span_y={span_y:.1f}м (EPSG:3857, трансформация в блоке)",
                            f"Блок внутр. span_y={span_y:.6f} слишком мал - блок в ИСХОДНОЙ СК! (Баг FIX-1)"
                        )
                    else:
                        self.logger.warning(f"Полилиния имеет {len(vertices)} вершин, нужно >= 2")
                else:
                    self.logger.fail("Полилинии не найдены в блоке!")

        except Exception as e:
            self.logger.error(f"Ошибка теста block CRS: {e}")
            self.logger.data("Traceback", traceback.format_exc())

    # =========================================================================
    # ТЕСТ 6: FIX-2c - Block Exporter hatch holes
    # =========================================================================

    def test_06_block_exporter_hatch_holes(self):
        """ТЕСТ 6: FIX-2c - DxfBlockExporter: штриховка с дырками внутри блока"""
        self.logger.section("6. FIX-2c: Block Exporter hatch holes")

        try:
            from Daman_QGIS.tools.F_1_data.core.dxf.Fsm_dxf_1_block_exporter import DxfBlockExporter

            block_exporter = DxfBlockExporter()

            doc = ezdxf_new('AC1027')
            msp = doc.modelspace()
            doc.layers.add('TestBlockHatch')

            # Создаём слой с полигоном-с-дыркой
            layer = QgsVectorLayer(
                "Polygon?crs=epsg:4326&field=id:integer&field=name:string",
                "test_block_holes", "memory"
            )

            # Полигон с дыркой
            wkt = "POLYGON((0 0, 100 0, 100 100, 0 100, 0 0),(20 20, 40 20, 40 40, 20 40, 20 20))"
            feature = QgsFeature(layer.fields())
            geom = QgsGeometry.fromWkt(wkt)
            feature.setGeometry(geom)
            feature.setAttributes([1, "block_with_hole"])
            layer.dataProvider().addFeature(feature)

            # Сплошная заливка через колонку fill (с 2026-04-30).
            # Regression-guard FIX-2c: HATCH с holes должен попасть внутрь BLOCK
            # независимо от триггера заливки.
            style = {
                'color': 1,
                'linetype': 'CONTINUOUS',
                'lineweight': 100,
                'fill': 1,
                'fill_color': 1
            }

            for feat in layer.getFeatures():
                block_exporter.export_feature_as_block(
                    feat, layer, 'TestBlockHatch', doc, msp,
                    style=style,
                    coordinate_precision=2
                )

            # Проверяем что блок создан и содержит HATCH
            block_refs = list(msp.query('INSERT'))
            self.logger.check(
                len(block_refs) >= 1,
                f"Блок создан ({len(block_refs)} INSERT)",
                "Блок НЕ создан!"
            )

            if block_refs:
                block_name = block_refs[0].dxf.name
                block = doc.blocks.get(block_name)

                # Проверяем наличие HATCH в блоке
                hatches = list(block.query('HATCH'))
                self.logger.check(
                    len(hatches) >= 1,
                    f"HATCH в блоке: {len(hatches)} шт",
                    "HATCH НЕ найден в блоке!"
                )

                # Проверяем наличие дырки в HATCH (2+ boundary paths)
                if hatches:
                    paths_count = len(hatches[0].paths)
                    self.logger.check(
                        paths_count >= 2,
                        f"HATCH в блоке имеет {paths_count} boundary paths (exterior + hole)",
                        f"HATCH в блоке имеет только {paths_count} path - дырка НЕ передана!"
                    )

                # Проверяем наличие полилинии дырки
                polylines = list(block.query('LWPOLYLINE'))
                self.logger.check(
                    len(polylines) >= 2,
                    f"Полилинии в блоке: {len(polylines)} (контур + дырка)",
                    f"Ожидалось >= 2 полилиний в блоке, получено {len(polylines)}"
                )

        except Exception as e:
            self.logger.error(f"Ошибка теста block hatch holes: {e}")
            self.logger.data("Traceback", traceback.format_exc())

    # =========================================================================
    # ТЕСТ 7: FIX-4 - MULTILEADER layer assignment
    # =========================================================================

    def test_07_multileader_layer_assignment(self):
        """ТЕСТ 7: FIX-4 - DxfLabelExporter: MULTILEADER создаётся на правильном слое"""
        self.logger.section("7. FIX-4: MULTILEADER layer assignment")

        try:
            from Daman_QGIS.tools.F_1_data.core.dxf.Fsm_dxf_3_label_exporter import DxfLabelExporter

            label_exporter = DxfLabelExporter()

            doc = ezdxf_new('AC1027')
            msp = doc.modelspace()

            # Создаём слои
            doc.layers.add('TestLayer')
            label_layer = doc.layers.add('TestLayer_Номер')

            # Создаём текстовый стиль GOST 2.304
            if 'GOST 2.304' not in doc.styles:
                doc.styles.add('GOST 2.304', font='gost.shx')

            # Создаём слой QGIS с объектом
            layer = QgsVectorLayer(
                "Polygon?crs=epsg:4326&field=id:integer&field=cn:string",
                "test_label", "memory"
            )

            wkt = "POLYGON((0 0, 10 0, 10 10, 0 10, 0 0))"
            feature = QgsFeature(layer.fields())
            geom = QgsGeometry.fromWkt(wkt)
            feature.setGeometry(geom)
            feature.setAttributes([1, "77:01:0001001:123"])
            layer.dataProvider().addFeature(feature)

            # Конфигурация подписи
            label_config = {
                'label_field': 'cn',
                'label_font_size': 4.0,
                'label_font_family': 'GOST 2.304',
                'label_auto_wrap_length': 50,
                'label_dogleg_length': 5.0,
                'label_landing_gap': 2.0,
                'label_font_color_RGB': '0,0,0'
            }

            # Экспортируем MULTILEADER
            for feat in layer.getFeatures():
                result = label_exporter.export_label_as_multileader(
                    msp, feat, 'TestLayer', None, label_config,
                    layer_color_rgb=(0, 0, 0),
                    label_scale_factor=1.0
                )

                self.logger.check(
                    result is True,
                    "MULTILEADER создан успешно",
                    "MULTILEADER НЕ создан!"
                )

            # Проверяем что MULTILEADER на правильном слое
            multileaders = list(msp.query('MULTILEADER'))
            self.logger.check(
                len(multileaders) >= 1,
                f"MULTILEADER найден в msp ({len(multileaders)} шт)",
                "MULTILEADER НЕ найден в msp!"
            )

            if multileaders:
                ml_layer = multileaders[0].dxf.layer
                expected_layer = 'TestLayer_Номер'
                self.logger.check(
                    ml_layer == expected_layer,
                    f"MULTILEADER на слое '{ml_layer}' (правильно)",
                    f"MULTILEADER на слое '{ml_layer}', ожидался '{expected_layer}'!"
                )

        except Exception as e:
            self.logger.error(f"Ошибка теста MULTILEADER: {e}")
            self.logger.data("Traceback", traceback.format_exc())

    # =========================================================================
    # ТЕСТ 8: zoom.extents - Центрирование DXF
    # =========================================================================

    def test_08_zoom_extents(self):
        """ТЕСТ 8: zoom.extents - Начальный вид центрируется на объектах"""
        self.logger.section("8. zoom.extents - центрирование DXF")

        try:
            from ezdxf import zoom

            doc = ezdxf_new('AC1027')
            msp = doc.modelspace()

            # Добавляем объекты далеко от начала координат (имитация МСК)
            msp.add_lwpolyline(
                [(500000, 6000000), (500100, 6000000), (500100, 6000100), (500000, 6000100)],
                close=True
            )

            # Применяем zoom.extents
            zoom.extents(msp)

            # zoom.extents() модифицирует VPORT *Active entry (center + height),
            # а НЕ $VIEWCTR header variable.
            # VPORT таблица может содержать несколько записей с одним именем,
            # поэтому get() возвращает list.
            vport_list = doc.viewports.get_config('*Active')
            self.logger.check(
                len(vport_list) > 0,
                f"VPORT *Active найден ({len(vport_list)} записей)",
                "VPORT *Active НЕ найден!"
            )

            if vport_list:
                vport = vport_list[0]
                vport_center = vport.dxf.center
                cx, cy = vport_center.x, vport_center.y

                # Центр объектов: ~500050, ~6000050
                self.logger.check(
                    abs(cx - 500050) < 1000,
                    f"VPORT center X={cx:.0f} (центрирован на объектах)",
                    f"VPORT center X={cx:.0f} далеко от объектов (ожидалось ~500050)!"
                )
                self.logger.check(
                    abs(cy - 6000050) < 1000,
                    f"VPORT center Y={cy:.0f} (центрирован на объектах)",
                    f"VPORT center Y={cy:.0f} далеко от объектов (ожидалось ~6000050)!"
                )

                # Проверяем что height установлен (bbox ~100x100)
                vport_height = vport.dxf.height
                self.logger.check(
                    vport_height > 0,
                    f"VPORT height={vport_height:.0f} (viewport настроен)",
                    f"VPORT height={vport_height} - не настроен!"
                )

            # Сохраняем и перечитываем чтобы убедиться что VPORT сохраняется
            fd, tmp_path = tempfile.mkstemp(suffix='.dxf')
            os.close(fd)
            try:
                doc.saveas(tmp_path)
                doc2 = ezdxf.readfile(tmp_path)
                vport_list2 = doc2.viewports.get_config('*Active')

                if vport_list2:
                    cx2 = vport_list2[0].dxf.center.x
                    self.logger.check(
                        abs(cx2 - 500050) < 1000,
                        "VPORT center сохранён в DXF файле",
                        f"VPORT center не сохранён: X={cx2:.0f}!"
                    )
                else:
                    self.logger.fail("VPORT *Active не найден после перечитывания DXF!")
            finally:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)

        except Exception as e:
            self.logger.error(f"Ошибка теста zoom.extents: {e}")
            self.logger.data("Traceback", traceback.format_exc())

    # =========================================================================
    # ТЕСТ 9: _remove_closing_point
    # =========================================================================

    def test_09_remove_closing_point(self):
        """ТЕСТ 9: _remove_closing_point - удаление замыкающей точки"""
        self.logger.section("9. _remove_closing_point")

        try:
            from Daman_QGIS.tools.F_1_data.core.dxf.Fsm_dxf_2_geometry_exporter import DxfGeometryExporter

            exporter = DxfGeometryExporter()

            # Тест 9.1: Полигон с замыкающей точкой
            coords_closed = [(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)]
            result = exporter._remove_closing_point(coords_closed)
            self.logger.check(
                len(result) == 4,
                "Замыкающая точка удалена (5 -> 4 координаты)",
                f"Ожидалось 4, получено {len(result)}"
            )

            # Тест 9.2: Полигон БЕЗ замыкающей точки
            coords_open = [(0, 0), (1, 0), (1, 1), (0, 1)]
            result = exporter._remove_closing_point(coords_open)
            self.logger.check(
                len(result) == 4,
                "Без замыкающей точки: 4 координаты сохранены",
                f"Ожидалось 4, получено {len(result)}"
            )

            # Тест 9.3: Пустой список
            result = exporter._remove_closing_point([])
            self.logger.check(
                len(result) == 0,
                "Пустой список обработан",
                f"Ожидалось 0, получено {len(result)}"
            )

            # Тест 9.4: Одна точка
            result = exporter._remove_closing_point([(0, 0)])
            self.logger.check(
                len(result) == 1,
                "Одна точка: без изменений",
                f"Ожидалось 1, получено {len(result)}"
            )

        except Exception as e:
            self.logger.error(f"Ошибка теста remove_closing_point: {e}")
            self.logger.data("Traceback", traceback.format_exc())

    # =========================================================================
    # ТЕСТ 10: Дедупликация точек
    # =========================================================================

    def test_10_point_deduplication(self):
        """ТЕСТ 10: DxfGeometryExporter - дедупликация точек"""
        self.logger.section("10. Дедупликация точек")

        try:
            from Daman_QGIS.tools.F_1_data.core.dxf.Fsm_dxf_2_geometry_exporter import DxfGeometryExporter

            exporter = DxfGeometryExporter()
            exporter.clear_point_cache()

            doc = ezdxf_new('AC1027')
            msp = doc.modelspace()
            doc.layers.add('TestPoints')

            # Создаём слой с точками
            layer = QgsVectorLayer(
                "Point?crs=epsg:4326&field=id:integer&field=name:string",
                "test_points", "memory"
            )

            # Добавляем 3 точки, 2 из которых в одной позиции
            for i, (x, y) in enumerate([(1.0, 1.0), (1.0, 1.0), (2.0, 2.0)]):
                feat = QgsFeature(layer.fields())
                feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(x, y)))
                feat.setAttributes([i, f"point_{i}"])
                layer.dataProvider().addFeature(feat)

            style = {'line_scale': 1.5, 'hatch': '-'}

            for feat in layer.getFeatures():
                exporter.export_simple_geometry(
                    feat, layer, 'TestPoints', doc, msp,
                    style=style,
                    coordinate_precision=6
                )

            # Проверяем: должно быть 2 CIRCLE (не 3), т.к. 2 точки в одном месте
            circles = list(msp.query('CIRCLE'))
            self.logger.check(
                len(circles) == 2,
                f"Дедупликация: {len(circles)} CIRCLE (2 уникальные из 3)",
                f"Ожидалось 2 CIRCLE, получено {len(circles)} - дедупликация не работает!"
            )

            # Очистка кэша
            exporter.clear_point_cache()
            self.logger.check(
                len(exporter._exported_points) == 0,
                "Кэш точек очищен",
                "Кэш точек НЕ очищен!"
            )

        except Exception as e:
            self.logger.error(f"Ошибка теста дедупликации: {e}")
            self.logger.data("Traceback", traceback.format_exc())
