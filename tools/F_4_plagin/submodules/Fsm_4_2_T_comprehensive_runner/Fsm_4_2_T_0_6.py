# -*- coding: utf-8 -*-
"""
Fsm_4_2_T_0_6 - Тест функции F_0_6_Трансформация координат

Проверяет:
1. Импорт всех модулей F_0_6 и shared core/math
2. Shared Helmert2D solver (core.math.helmert_2d) - математика
3. OffsetMethod - простой сдвиг (2P)
4. Helmert2DMethod - конформная трансформация (4P)
5. AffineMethod - 6-параметрическая аффинная (6P)
6. Auto-select метода
7. Blunder detection
8. TransformApplicator - трансформация геометрий (QgsAbstractGeometryTransformer)
9. Округление координат 0.01м через M_6
10. Конвертация non-editable слоёв в GPKG
"""

import math
import tempfile
import os
import shutil

from qgis.core import (
    QgsVectorLayer,
    QgsVectorFileWriter,
    QgsFeature,
    QgsGeometry,
    QgsProject,
)


# Тестовые данные: 6 контрольных точек
# Исходные точки (неправильный слой)
SRC_POINTS = [
    (100.00, 200.00),
    (200.00, 200.00),
    (200.00, 300.00),
    (100.00, 300.00),
    (150.00, 250.00),
    (175.00, 225.00),
]

# Целевые точки: сдвиг dx=10, dy=20 (точный Offset)
DST_POINTS_OFFSET = [
    (110.00, 220.00),
    (210.00, 220.00),
    (210.00, 320.00),
    (110.00, 320.00),
    (160.00, 270.00),
    (185.00, 245.00),
]

# Целевые точки: Helmert2D (dx=10, dy=20, rotation=0.001 rad, scale=1.0001)
# Рассчитаны аналитически
_ROT = 0.001  # ~3.44 угл.сек
_SCALE = 1.0001
_A = _SCALE * math.cos(_ROT)
_B = _SCALE * math.sin(_ROT)
_DX_H = 10.0
_DY_H = 20.0

DST_POINTS_HELMERT = [
    (_DX_H + _A * x - _B * y, _DY_H + _B * x + _A * y)
    for x, y in SRC_POINTS
]

# Целевые точки с одной грубой ошибкой (blunder на 5-й точке)
DST_POINTS_BLUNDER = list(DST_POINTS_OFFSET)
DST_POINTS_BLUNDER[4] = (160.00 + 5.0, 270.00 + 5.0)  # Ошибка 7+ метров

# Кадастровая точность
TOLERANCE = 0.01  # метров


class TestF06:
    """Тесты для F_0_6_Трансформация координат"""

    def __init__(self, iface, logger):
        self.iface = iface
        self.logger = logger
        self.test_dir = None

    def run_all_tests(self):
        self.logger.section("ТЕСТ F_0_6: Трансформация координат")
        self.test_dir = tempfile.mkdtemp(prefix="qgis_test_f06_")

        try:
            self.test_01_import_modules()
            self.test_02_shared_helmert2d()
            self.test_03_offset_method()
            self.test_04_helmert2d_method()
            self.test_05_affine_method()
            self.test_06_auto_select()
            self.test_07_blunder_detection()
            self.test_08_transform_geometry()
            self.test_09_transform_layer()
            self.test_10_coordinate_rounding()
            self.test_11_convert_to_gpkg()
        finally:
            if self.test_dir and os.path.exists(self.test_dir):
                try:
                    import time
                    time.sleep(0.5)
                    shutil.rmtree(self.test_dir)
                except Exception:
                    pass

        self.logger.summary()

    # ========== 1. Импорт модулей ==========

    def test_01_import_modules(self):
        self.logger.section("1. Импорт модулей F_0_6")

        # Entry point
        try:
            from Daman_QGIS.tools.F_0_project.F_0_6_coordinate_transform import (
                F_0_6_CoordinateTransform
            )
            self.logger.success("F_0_6_CoordinateTransform загружен")
        except Exception as e:
            self.logger.error(f"F_0_6_CoordinateTransform: {e}")

        # Dialog
        try:
            from Daman_QGIS.tools.F_0_project.submodules.Fsm_0_6_1_transform_dialog import (
                CoordinateTransformDialog
            )
            self.logger.success("CoordinateTransformDialog загружен")
        except Exception as e:
            self.logger.error(f"CoordinateTransformDialog: {e}")

        # Methods
        try:
            from Daman_QGIS.tools.F_0_project.submodules.Fsm_0_6_2_transform_methods import (
                BaseTransformMethod, TransformResult,
                OffsetMethod, Helmert2DMethod, AffineMethod,
                auto_select_method,
            )
            self.logger.success("Fsm_0_6_2 методы загружены (5 классов + auto_select)")
        except Exception as e:
            self.logger.error(f"Fsm_0_6_2: {e}")

        # Applicator
        try:
            from Daman_QGIS.tools.F_0_project.submodules.Fsm_0_6_3_transform_applicator import (
                TransformApplicator
            )
            self.logger.success("TransformApplicator загружен")
        except Exception as e:
            self.logger.error(f"TransformApplicator: {e}")

        # Shared Helmert2D
        try:
            from Daman_QGIS.core.math.helmert_2d import (
                Helmert2DResult, calculate_helmert_2d,
                transform_point, inverse_transform_point,
            )
            self.logger.success("core.math.helmert_2d загружен (shared)")
        except Exception as e:
            self.logger.error(f"core.math.helmert_2d: {e}")

    # ========== 2. Shared Helmert2D ==========

    def test_02_shared_helmert2d(self):
        self.logger.section("2. Shared Helmert2D solver (core.math)")

        try:
            from Daman_QGIS.core.math.helmert_2d import (
                calculate_helmert_2d, transform_point, inverse_transform_point,
            )

            # Известная трансформация: сдвиг dx=10, dy=20
            result = calculate_helmert_2d(
                SRC_POINTS[:4], DST_POINTS_OFFSET[:4]
            )

            if result.success:
                self.logger.success("Helmert2D рассчитан")
            else:
                self.logger.fail("Helmert2D не сошёлся")
                return

            # Проверяем параметры
            if abs(result.dx - 10.0) < 0.1:
                self.logger.success(f"dx={result.dx:.4f} (ожидалось ~10.0)")
            else:
                self.logger.fail(f"dx={result.dx:.4f} != 10.0")

            if abs(result.dy - 20.0) < 0.1:
                self.logger.success(f"dy={result.dy:.4f} (ожидалось ~20.0)")
            else:
                self.logger.fail(f"dy={result.dy:.4f} != 20.0")

            if abs(result.scale - 1.0) < 0.001:
                self.logger.success(f"scale={result.scale:.6f} (ожидалось ~1.0)")
            else:
                self.logger.fail(f"scale={result.scale:.6f} != 1.0")

            if abs(result.rotation_deg) < 0.01:
                self.logger.success(f"rotation={result.rotation_deg:.6f} deg (ожидалось ~0.0)")
            else:
                self.logger.fail(f"rotation={result.rotation_deg:.6f} deg != 0.0")

            # Round-trip: transform + inverse
            x, y = SRC_POINTS[0]
            tx, ty = transform_point(x, y, result)
            ix, iy = inverse_transform_point(tx, ty, result)

            error = math.sqrt((x - ix) ** 2 + (y - iy) ** 2)
            if error < 1e-6:
                self.logger.success(f"Round-trip: погрешность {error:.2e} м")
            else:
                self.logger.fail(f"Round-trip: погрешность {error:.6f} м (ожидалось < 1e-6)")

        except Exception as e:
            self.logger.error(f"Shared Helmert2D: {e}")

    # ========== 3. OffsetMethod ==========

    def test_03_offset_method(self):
        self.logger.section("3. OffsetMethod (2 параметра)")

        try:
            from Daman_QGIS.tools.F_0_project.submodules.Fsm_0_6_2_transform_methods import (
                OffsetMethod
            )

            method = OffsetMethod()
            result = method.calculate(SRC_POINTS, DST_POINTS_OFFSET)

            if result.success:
                self.logger.success("Offset рассчитан")
            else:
                self.logger.fail("Offset не рассчитан")
                return

            # Точные значения: dx=10, dy=20
            dx = result.params.get('dx', 0)
            dy = result.params.get('dy', 0)

            if abs(dx - 10.0) < TOLERANCE:
                self.logger.success(f"dx={dx:.4f} (ожидалось 10.0)")
            else:
                self.logger.fail(f"dx={dx:.4f} != 10.0")

            if abs(dy - 20.0) < TOLERANCE:
                self.logger.success(f"dy={dy:.4f} (ожидалось 20.0)")
            else:
                self.logger.fail(f"dy={dy:.4f} != 20.0")

            # RMSE для точного сдвига должен быть ~0
            if result.rmse < TOLERANCE:
                self.logger.success(f"RMSE={result.rmse:.6f} м < {TOLERANCE} м")
            else:
                self.logger.fail(f"RMSE={result.rmse:.6f} м > {TOLERANCE} м")

            # Проверка apply_to_point
            tx, ty = method.apply_to_point(100.0, 200.0)
            if abs(tx - 110.0) < TOLERANCE and abs(ty - 220.0) < TOLERANCE:
                self.logger.success(f"apply_to_point: ({tx:.2f}, {ty:.2f})")
            else:
                self.logger.fail(f"apply_to_point: ({tx:.2f}, {ty:.2f}) != (110, 220)")

        except Exception as e:
            self.logger.error(f"OffsetMethod: {e}")

    # ========== 4. Helmert2DMethod ==========

    def test_04_helmert2d_method(self):
        self.logger.section("4. Helmert2DMethod (4 параметра)")

        try:
            from Daman_QGIS.tools.F_0_project.submodules.Fsm_0_6_2_transform_methods import (
                Helmert2DMethod
            )

            method = Helmert2DMethod()
            result = method.calculate(SRC_POINTS, DST_POINTS_HELMERT)

            if result.success:
                self.logger.success("Helmert2D рассчитан")
            else:
                self.logger.fail("Helmert2D не рассчитан")
                return

            # RMSE для аналитически рассчитанных точек должен быть ~0
            if result.rmse < TOLERANCE:
                self.logger.success(f"RMSE={result.rmse:.6f} м < {TOLERANCE} м")
            else:
                self.logger.fail(f"RMSE={result.rmse:.6f} м > {TOLERANCE} м")

            # Параметры
            self.logger.info(f"dx={result.params.get('dx', 0):.4f} м")
            self.logger.info(f"dy={result.params.get('dy', 0):.4f} м")
            self.logger.info(
                f"rotation={result.params.get('rotation_arcsec', 0):.2f}\" "
                f"(ожидалось {math.degrees(_ROT) * 3600:.2f}\")"
            )
            self.logger.info(
                f"scale={result.params.get('scale', 0):.8f} "
                f"(ожидалось {_SCALE:.8f})"
            )

            # Невязки
            if result.residuals:
                max_res = max(result.residuals)
                if max_res < TOLERANCE:
                    self.logger.success(f"Max невязка={max_res:.6f} м < {TOLERANCE} м")
                else:
                    self.logger.fail(f"Max невязка={max_res:.6f} м > {TOLERANCE} м")

                self.logger.success(f"Невязок: {len(result.residuals)} шт")

            # Проверка apply_to_point
            x, y = SRC_POINTS[0]
            ex, ey = DST_POINTS_HELMERT[0]
            tx, ty = method.apply_to_point(x, y)
            err = math.sqrt((tx - ex) ** 2 + (ty - ey) ** 2)

            if err < TOLERANCE:
                self.logger.success(f"apply_to_point: погрешность {err:.6f} м")
            else:
                self.logger.fail(f"apply_to_point: погрешность {err:.6f} м > {TOLERANCE} м")

        except Exception as e:
            self.logger.error(f"Helmert2DMethod: {e}")

    # ========== 5. AffineMethod ==========

    def test_05_affine_method(self):
        self.logger.section("5. AffineMethod (6 параметров)")

        try:
            from Daman_QGIS.tools.F_0_project.submodules.Fsm_0_6_2_transform_methods import (
                AffineMethod
            )

            # Affine с известными параметрами: a1=1, a2=0, tx=10, b1=0, b2=1, ty=20
            # (эквивалент Offset, но через Affine solver)
            method = AffineMethod()
            result = method.calculate(SRC_POINTS, DST_POINTS_OFFSET)

            if result.success:
                self.logger.success("Affine рассчитан")
            else:
                self.logger.fail("Affine не рассчитан")
                return

            # Проверяем параметры
            a1 = result.params.get('a1', 0)
            a2 = result.params.get('a2', 0)
            tx = result.params.get('tx', 0)
            b1 = result.params.get('b1', 0)
            b2 = result.params.get('b2', 0)
            ty = result.params.get('ty', 0)

            # a1 ~1, a2 ~0, tx ~10, b1 ~0, b2 ~1, ty ~20
            if abs(a1 - 1.0) < 0.001:
                self.logger.success(f"a1={a1:.6f} (ожидалось ~1.0)")
            else:
                self.logger.fail(f"a1={a1:.6f} != 1.0")

            if abs(a2) < 0.001:
                self.logger.success(f"a2={a2:.6f} (ожидалось ~0.0)")
            else:
                self.logger.fail(f"a2={a2:.6f} != 0.0")

            if abs(tx - 10.0) < 0.1:
                self.logger.success(f"tx={tx:.4f} (ожидалось ~10.0)")
            else:
                self.logger.fail(f"tx={tx:.4f} != 10.0")

            if abs(b2 - 1.0) < 0.001:
                self.logger.success(f"b2={b2:.6f} (ожидалось ~1.0)")
            else:
                self.logger.fail(f"b2={b2:.6f} != 1.0")

            if abs(ty - 20.0) < 0.1:
                self.logger.success(f"ty={ty:.4f} (ожидалось ~20.0)")
            else:
                self.logger.fail(f"ty={ty:.4f} != 20.0")

            # RMSE
            if result.rmse < TOLERANCE:
                self.logger.success(f"RMSE={result.rmse:.6f} м < {TOLERANCE} м")
            else:
                self.logger.fail(f"RMSE={result.rmse:.6f} м > {TOLERANCE} м")

            # Тест с неравномерным масштабом (истинный Affine)
            # scale_x=1.0002, scale_y=1.0005 (разный масштаб по осям)
            dst_affine = [
                (x * 1.0002 + 5.0, y * 1.0005 + 15.0)
                for x, y in SRC_POINTS
            ]

            method2 = AffineMethod()
            result2 = method2.calculate(SRC_POINTS, dst_affine)

            if result2.success and result2.rmse < TOLERANCE:
                self.logger.success(
                    f"Истинный 6P Affine (разный масштаб X/Y): RMSE={result2.rmse:.6f} м"
                )
            elif result2.success:
                self.logger.warning(
                    f"Affine RMSE={result2.rmse:.6f} м (ожидалось < {TOLERANCE})"
                )
            else:
                self.logger.fail("Affine не сошёлся для данных с разным масштабом X/Y")

        except Exception as e:
            self.logger.error(f"AffineMethod: {e}")

    # ========== 6. Auto-select ==========

    def test_06_auto_select(self):
        self.logger.section("6. Автовыбор метода (auto_select_method)")

        try:
            from Daman_QGIS.tools.F_0_project.submodules.Fsm_0_6_2_transform_methods import (
                auto_select_method
            )

            # Чистый Offset -> должен выбрать Offset (rotation~0, scale~1)
            result_off, method_off = auto_select_method(SRC_POINTS, DST_POINTS_OFFSET)
            if 'Offset' in result_off.method_name:
                self.logger.success(
                    f"Чистый сдвиг -> {result_off.method_name} (RMSE={result_off.rmse:.6f})"
                )
            else:
                self.logger.warning(
                    f"Чистый сдвиг -> {result_off.method_name} "
                    f"(ожидался Offset, RMSE={result_off.rmse:.6f})"
                )

            # Helmert данные -> должен выбрать Helmert
            result_hel, method_hel = auto_select_method(SRC_POINTS, DST_POINTS_HELMERT)
            if 'Helmert' in result_hel.method_name:
                self.logger.success(
                    f"Helmert данные -> {result_hel.method_name} (RMSE={result_hel.rmse:.6f})"
                )
            else:
                self.logger.warning(
                    f"Helmert данные -> {result_hel.method_name} "
                    f"(ожидался Helmert, RMSE={result_hel.rmse:.6f})"
                )

        except Exception as e:
            self.logger.error(f"auto_select_method: {e}")

    # ========== 7. Blunder detection ==========

    def test_07_blunder_detection(self):
        self.logger.section("7. Детекция грубых ошибок (blunders)")

        try:
            from Daman_QGIS.tools.F_0_project.submodules.Fsm_0_6_2_transform_methods import (
                BaseTransformMethod, OffsetMethod
            )

            # Рассчитываем с данными содержащими blunder
            method = OffsetMethod()
            result = method.calculate(SRC_POINTS, DST_POINTS_BLUNDER)

            if result.success:
                self.logger.success("Offset рассчитан (с blunder)")
            else:
                self.logger.fail("Offset не рассчитан")
                return

            # Должен обнаружить blunder на точке 4 (индекс 4)
            if result.blunder_indices:
                self.logger.success(
                    f"Обнаружены blunders: индексы {result.blunder_indices}"
                )
                if 4 in result.blunder_indices:
                    self.logger.success("Точка N5 (index=4) корректно отмечена как blunder")
                else:
                    self.logger.warning(
                        f"Ожидался blunder на index=4, найдены: {result.blunder_indices}"
                    )
            else:
                self.logger.fail("Blunders не обнаружены (ожидался 1+)")

            # Проверяем статический метод detect_blunders
            residuals = [0.01, 0.02, 0.01, 0.015, 5.0, 0.02]
            blunders = BaseTransformMethod.detect_blunders(residuals)

            if 4 in blunders:
                self.logger.success(
                    f"detect_blunders: корректно нашёл index=4 (невязка 5.0)"
                )
            else:
                self.logger.fail(
                    f"detect_blunders: не нашёл index=4 (результат: {blunders})"
                )

        except Exception as e:
            self.logger.error(f"Blunder detection: {e}")

    # ========== 8. Трансформация геометрии ==========

    def test_08_transform_geometry(self):
        self.logger.section("8. Трансформация геометрии (QgsAbstractGeometryTransformer)")

        try:
            from Daman_QGIS.tools.F_0_project.submodules.Fsm_0_6_2_transform_methods import (
                OffsetMethod
            )
            from Daman_QGIS.tools.F_0_project.submodules.Fsm_0_6_3_transform_applicator import (
                _MethodTransformer, _transform_geometry
            )

            # Создаём метод с известным сдвигом
            method = OffsetMethod()
            method.calculate(SRC_POINTS, DST_POINTS_OFFSET)

            # --- Тест 1: LineString ---
            line_wkt = "LINESTRING(100 200, 200 200, 200 300)"
            geom_line = QgsGeometry.fromWkt(line_wkt)
            result_line = _transform_geometry(geom_line, method)

            if result_line is not None:
                self.logger.success("LineString трансформирован")
                # Проверяем первую вершину
                vertex = result_line.vertexAt(0)
                if abs(vertex.x() - 110.0) < 0.001 and abs(vertex.y() - 220.0) < 0.001:
                    self.logger.success(f"Вершина 0: ({vertex.x():.2f}, {vertex.y():.2f})")
                else:
                    self.logger.fail(
                        f"Вершина 0: ({vertex.x():.2f}, {vertex.y():.2f}) "
                        f"!= (110.00, 220.00)"
                    )
            else:
                self.logger.fail("LineString: _transform_geometry вернул None")

            # --- Тест 2: Polygon ---
            poly_wkt = "POLYGON((100 200, 200 200, 200 300, 100 300, 100 200))"
            geom_poly = QgsGeometry.fromWkt(poly_wkt)
            result_poly = _transform_geometry(geom_poly, method)

            if result_poly is not None:
                if result_poly.isGeosValid():
                    self.logger.success("Polygon трансформирован и валиден")
                else:
                    self.logger.fail("Polygon трансформирован, но невалиден")

                # Площадь не должна измениться (только сдвиг)
                orig_area = geom_poly.area()
                new_area = result_poly.area()
                if abs(orig_area - new_area) < 0.01:
                    self.logger.success(
                        f"Площадь сохранена: {orig_area:.2f} -> {new_area:.2f}"
                    )
                else:
                    self.logger.fail(
                        f"Площадь изменилась: {orig_area:.2f} -> {new_area:.2f}"
                    )
            else:
                self.logger.fail("Polygon: _transform_geometry вернул None")

            # --- Тест 3: MultiLineString ---
            mline_wkt = "MULTILINESTRING((100 200, 200 200),(200 300, 100 300))"
            geom_mline = QgsGeometry.fromWkt(mline_wkt)
            result_mline = _transform_geometry(geom_mline, method)

            if result_mline is not None:
                self.logger.success("MultiLineString трансформирован")
            else:
                self.logger.fail("MultiLineString: _transform_geometry вернул None")

            # --- Тест 4: Point ---
            point_wkt = "POINT(100 200)"
            geom_point = QgsGeometry.fromWkt(point_wkt)
            result_point = _transform_geometry(geom_point, method)

            if result_point is not None:
                pt = result_point.asPoint()
                if abs(pt.x() - 110.0) < 0.001 and abs(pt.y() - 220.0) < 0.001:
                    self.logger.success(f"Point: ({pt.x():.2f}, {pt.y():.2f})")
                else:
                    self.logger.fail(f"Point: ({pt.x():.2f}, {pt.y():.2f}) != (110, 220)")
            else:
                self.logger.fail("Point: _transform_geometry вернул None")

        except Exception as e:
            self.logger.error(f"Трансформация геометрии: {e}")

    # ========== 9. Трансформация слоя ==========

    def test_09_transform_layer(self):
        self.logger.section("9. Трансформация слоя (TransformApplicator)")

        try:
            from Daman_QGIS.tools.F_0_project.submodules.Fsm_0_6_2_transform_methods import (
                OffsetMethod
            )
            from Daman_QGIS.tools.F_0_project.submodules.Fsm_0_6_3_transform_applicator import (
                TransformApplicator
            )

            # Создаём memory слой с LineString
            layer = QgsVectorLayer(
                f"LineString?crs=EPSG:32637&field=name:string",
                "test_layer", "memory"
            )

            if not layer.isValid():
                self.logger.fail("Не удалось создать memory слой")
                return

            # Добавляем фичу
            provider = layer.dataProvider()
            feature = QgsFeature()
            feature.setGeometry(QgsGeometry.fromWkt(
                "LINESTRING(100 200, 200 200, 200 300)"
            ))
            feature.setAttributes(["test_line"])
            provider.addFeatures([feature])

            self.logger.success(f"Memory слой: {layer.featureCount()} фич")

            # Backup
            backup = TransformApplicator.backup_layer(layer)
            if len(backup) == 1:
                self.logger.success(f"Backup: {len(backup)} геометрия")
            else:
                self.logger.fail(f"Backup: {len(backup)} (ожидалось 1)")

            # Рассчитываем трансформацию
            method = OffsetMethod()
            method.calculate(SRC_POINTS, DST_POINTS_OFFSET)

            # Применяем
            success, warnings = TransformApplicator.apply_transform(layer, method)

            if success:
                self.logger.success("Трансформация применена")
            else:
                self.logger.fail(f"Трансформация не применена: {warnings}")
                return

            if warnings:
                for w in warnings:
                    self.logger.warning(f"Предупреждение: {w}")

            # Проверяем координаты первой вершины
            for feat in layer.getFeatures():
                geom = feat.geometry()
                vertex = geom.vertexAt(0)
                # Ожидаем 100+10=110, 200+20=220 (с округлением 0.01)
                if abs(vertex.x() - 110.0) < 0.02 and abs(vertex.y() - 220.0) < 0.02:
                    self.logger.success(
                        f"Вершина после трансформации: ({vertex.x():.2f}, {vertex.y():.2f})"
                    )
                else:
                    self.logger.fail(
                        f"Вершина: ({vertex.x():.2f}, {vertex.y():.2f}) != (110.00, 220.00)"
                    )
                break

            # Restore
            restore_ok = TransformApplicator.restore_from_backup(layer, backup)
            if restore_ok:
                for feat in layer.getFeatures():
                    vertex = feat.geometry().vertexAt(0)
                    if abs(vertex.x() - 100.0) < 0.02 and abs(vertex.y() - 200.0) < 0.02:
                        self.logger.success(
                            f"Restore OK: ({vertex.x():.2f}, {vertex.y():.2f})"
                        )
                    else:
                        self.logger.fail(
                            f"Restore: ({vertex.x():.2f}, {vertex.y():.2f}) != (100, 200)"
                        )
                    break
            else:
                self.logger.fail("Restore не удался")

            # Validate
            validation = TransformApplicator.validate_result(layer)
            if not validation:
                self.logger.success("Валидация: без предупреждений")
            else:
                for v in validation:
                    self.logger.warning(f"Валидация: {v}")

        except Exception as e:
            self.logger.error(f"Трансформация слоя: {e}")

    # ========== 10. Округление координат ==========

    def test_10_coordinate_rounding(self):
        self.logger.section("10. Округление координат 0.01м (M_6)")

        try:
            from Daman_QGIS.managers.geometry.M_6_coordinate_precision import (
                CoordinatePrecisionManager
            )

            # Геометрия с "грязными" координатами
            wkt = "LINESTRING(100.123456 200.987654, 200.111111 300.222222)"
            geom = QgsGeometry.fromWkt(wkt)

            rounded = CoordinatePrecisionManager._round_geometry(geom)

            if rounded is not None:
                v0 = rounded.vertexAt(0)
                v1 = rounded.vertexAt(1)

                # Проверяем что координаты округлены до 0.01
                x0_str = f"{v0.x():.2f}"
                y0_str = f"{v0.y():.2f}"

                # Должно быть ровно 2 знака
                if v0.x() == float(x0_str) and v0.y() == float(y0_str):
                    self.logger.success(
                        f"Вершина 0 округлена: ({v0.x():.2f}, {v0.y():.2f})"
                    )
                else:
                    self.logger.fail(
                        f"Вершина 0 не округлена: ({v0.x()}, {v0.y()})"
                    )

                if v1.x() == float(f"{v1.x():.2f}") and v1.y() == float(f"{v1.y():.2f}"):
                    self.logger.success(
                        f"Вершина 1 округлена: ({v1.x():.2f}, {v1.y():.2f})"
                    )
                else:
                    self.logger.fail(
                        f"Вершина 1 не округлена: ({v1.x()}, {v1.y()})"
                    )

                # Проверка что геометрия валидна
                if rounded.isGeosValid():
                    self.logger.success("Округлённая геометрия валидна")
                else:
                    self.logger.fail("Округлённая геометрия невалидна!")

            else:
                self.logger.fail("_round_geometry вернул None")

        except Exception as e:
            self.logger.error(f"Округление координат: {e}")

    # ========== 11. Конвертация в GPKG ==========

    def test_11_convert_to_gpkg(self):
        self.logger.section("11. Конвертация non-editable слоя в GPKG")

        try:
            from Daman_QGIS.tools.F_0_project.submodules.Fsm_0_6_3_transform_applicator import (
                TransformApplicator
            )

            # Создаём GeoJSON файл в test_dir (файловый слой, как DXF)
            # Memory-слои имеют пустой source path, convert_layer_to_gpkg
            # рассчитан на файловые слои (DXF и др.)
            geojson_path = os.path.join(self.test_dir, "convert_test.geojson")

            # Сначала memory -> GeoJSON через QgsVectorFileWriter
            mem_layer = QgsVectorLayer(
                "LineString?crs=EPSG:32637&field=name:string&field=length:double",
                "convert_test", "memory"
            )

            if not mem_layer.isValid():
                self.logger.fail("Не удалось создать memory слой")
                return

            # Добавляем фичи
            provider = mem_layer.dataProvider()
            for i in range(3):
                feat = QgsFeature()
                feat.setGeometry(QgsGeometry.fromWkt(
                    f"LINESTRING({i * 100} {i * 100}, {i * 100 + 50} {i * 100 + 50})"
                ))
                feat.setAttributes([f"line_{i}", float(i * 10)])
                provider.addFeatures([feat])

            # Сохраняем как GeoJSON (файловый слой)
            save_options = QgsVectorFileWriter.SaveVectorOptions()
            save_options.driverName = "GeoJSON"
            save_options.fileEncoding = "UTF-8"
            transform_context = QgsProject.instance().transformContext()

            error = QgsVectorFileWriter.writeAsVectorFormatV3(
                mem_layer, geojson_path, transform_context, save_options,
            )

            if error[0] != QgsVectorFileWriter.NoError:
                self.logger.fail(f"Не удалось сохранить GeoJSON: {error}")
                return

            # Загружаем GeoJSON как OGR-слой
            file_layer = QgsVectorLayer(geojson_path, "convert_test", "ogr")

            if not file_layer.isValid():
                self.logger.fail("Не удалось загрузить GeoJSON как OGR-слой")
                return

            self.logger.success(
                f"GeoJSON слой: {file_layer.featureCount()} фич, "
                f"provider={file_layer.providerType()}"
            )

            # Добавляем в проект (требуется для convert_layer_to_gpkg)
            QgsProject.instance().addMapLayer(file_layer, False)

            # Конвертируем
            new_layer = TransformApplicator.convert_layer_to_gpkg(file_layer)

            if new_layer is not None:
                self.logger.success("Конвертация в GPKG успешна")

                # Проверяем количество фич
                if new_layer.featureCount() == 3:
                    self.logger.success(f"Фич: {new_layer.featureCount()} (ожидалось 3)")
                else:
                    self.logger.fail(
                        f"Фич: {new_layer.featureCount()} (ожидалось 3)"
                    )

                # Проверяем provider
                prov = new_layer.dataProvider()
                if prov:
                    can_edit = bool(prov.capabilities() & prov.ChangeGeometries)
                    if can_edit:
                        self.logger.success("GPKG слой поддерживает редактирование")
                    else:
                        self.logger.fail("GPKG слой НЕ поддерживает редактирование")

                # Проверяем атрибуты
                fields = new_layer.fields()
                field_names = [f.name() for f in fields]
                if 'name' in field_names and 'length' in field_names:
                    self.logger.success(f"Атрибуты сохранены: {field_names}")
                else:
                    self.logger.fail(f"Атрибуты: {field_names} (ожидались name, length)")

                # Проверяем CRS
                if new_layer.crs().authid() == 'EPSG:32637':
                    self.logger.success(f"CRS сохранена: {new_layer.crs().authid()}")
                else:
                    self.logger.fail(
                        f"CRS: {new_layer.crs().authid()} (ожидалась EPSG:32637)"
                    )

                # Сохраняем source ДО удаления (removeMapLayer удаляет C++ объект)
                gpkg_source = new_layer.source()
                gpkg_path = gpkg_source.split('|')[0]

                # Удаляем GPKG слой из проекта
                QgsProject.instance().removeMapLayer(new_layer.id())

                # Удаляем файл
                if os.path.exists(gpkg_path):
                    try:
                        os.remove(gpkg_path)
                    except Exception:
                        pass

            else:
                self.logger.fail("convert_layer_to_gpkg вернул None")

        except Exception as e:
            self.logger.error(f"Конвертация в GPKG: {e}")
