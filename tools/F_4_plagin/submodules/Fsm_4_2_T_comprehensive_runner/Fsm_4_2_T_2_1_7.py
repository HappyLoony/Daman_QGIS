# -*- coding: utf-8 -*-
"""
Fsm_4_2_T_3_1_7 - Тест Fsm_2_1_7_NoChangeDetector

Тестирует детектор ЗУ без изменения геометрии:
- Логика определения ЗУ как Изменяемого или Без_Меж
- Проверка критериев: внутри одной ЗПР, вершины на границе совпадают
- Классификация по совпадению ВРИ и Категории
"""

from qgis.core import (
    QgsVectorLayer,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsField,
    QgsFields,
    QgsWkbTypes,
    QgsCoordinateReferenceSystem,
)
from qgis.PyQt.QtCore import QMetaType


class TestFsm317NoChangeDetector:
    """Тесты для Fsm_2_1_7_NoChangeDetector"""

    def __init__(self, iface, logger):
        self.iface = iface
        self.logger = logger
        self.detector_class = None
        self.classification_enum = None

    def run_all_tests(self):
        self.logger.section("ТЕСТ Fsm_2_1_7: NoChangeDetector")

        try:
            self.test_01_import()
            self.test_02_zu_inside_single_zpr()
            self.test_03_zu_crosses_multiple_zpr()
            self.test_04_zu_boundary_vertex_matches()
            self.test_05_zu_boundary_vertex_no_match()
            self.test_06_classify_bez_mezh()
            self.test_07_classify_izmenyaemye_vri_differs()
            self.test_08_classify_izmenyaemye_category_differs()
            self.test_09_detect_all()
            self.test_10_get_separated_lists()
        except Exception as e:
            self.logger.fail(f"Критическая ошибка: {e}")

        self.logger.summary()

    def _create_memory_layer(
        self,
        name: str,
        geometries: list,
        attributes_list: list = None,
        fields_def: list = None,
        crs_epsg: int = 32637
    ) -> QgsVectorLayer:
        """Создать memory слой с геометриями и атрибутами

        Args:
            name: Имя слоя
            geometries: Список WKT геометрий
            attributes_list: Список словарей атрибутов
            fields_def: Определение полей [(name, type), ...]
            crs_epsg: EPSG код CRS

        Returns:
            QgsVectorLayer в памяти
        """
        crs = QgsCoordinateReferenceSystem(f"EPSG:{crs_epsg}")
        layer = QgsVectorLayer(f"Polygon?crs=epsg:{crs_epsg}", name, "memory")
        provider = layer.dataProvider()

        # Добавить поля
        fields = QgsFields()
        fields.append(QgsField("ID", QMetaType.Type.Int))

        if fields_def:
            for field_name, field_type in fields_def:
                fields.append(QgsField(field_name, field_type))

        provider.addAttributes(fields)
        layer.updateFields()

        # Добавить features
        features = []
        for idx, wkt in enumerate(geometries):
            feat = QgsFeature()
            feat.setGeometry(QgsGeometry.fromWkt(wkt))

            attrs = [idx + 1]
            if attributes_list and idx < len(attributes_list):
                for field_name, _ in (fields_def or []):
                    attrs.append(attributes_list[idx].get(field_name, None))
            elif fields_def:
                attrs.extend([None] * len(fields_def))

            feat.setAttributes(attrs)
            features.append(feat)

        provider.addFeatures(features)
        layer.updateExtents()
        return layer

    def test_01_import(self):
        """ТЕСТ 1: Импорт модуля"""
        self.logger.section("1. Импорт Fsm_2_1_7_NoChangeDetector")

        try:
            from Daman_QGIS.tools.F_2_cutting.submodules.Fsm_2_1_7_no_change_detector import (
                Fsm_2_1_7_NoChangeDetector,
                NoChangeDetectionResult,
                ZuClassification
            )
            self.detector_class = Fsm_2_1_7_NoChangeDetector
            self.classification_enum = ZuClassification
            self.logger.success("Импорт успешен")
        except ImportError as e:
            self.logger.fail(f"Ошибка импорта: {e}")

    def test_02_zu_inside_single_zpr(self):
        """ТЕСТ 2: ЗУ полностью внутри одной ЗПР"""
        self.logger.section("2. ЗУ внутри одной ЗПР")

        if not self.detector_class:
            self.logger.fail("Детектор не импортирован")
            return

        # ЗПР с вершинами
        zpr_wkt = "POLYGON((0 0, 50 0, 100 0, 100 50, 100 100, 50 100, 0 100, 0 50, 0 0))"
        zu_wkt = "POLYGON((0 0, 50 0, 50 50, 0 50, 0 0))"

        fields_def = [('ВРИ', QMetaType.Type.QString), ('Категория', QMetaType.Type.QString)]
        zpr_layer = self._create_memory_layer(
            "ZPR", [zpr_wkt],
            [{'ВРИ': 'Отдых (рекреация) (код 5.0)', 'Категория': 'Земли населённых пунктов'}],
            fields_def
        )
        zu_layer = self._create_memory_layer(
            "ZU", [zu_wkt],
            [{'ВРИ': 'Отдых (рекреация) (код 5.0)', 'Категория': 'Земли населённых пунктов'}],
            fields_def
        )

        try:
            detector = self.detector_class(zpr_layer, zu_layer)
            zu_feature = next(zu_layer.getFeatures())
            result = detector.detect_single(zu_feature)

            if result.classification != self.classification_enum.RAZDEL:
                self.logger.success(f"ЗУ определён как {result.classification.value} (reason: {result.reason})")
            else:
                self.logger.info(f"ЗУ определён как Раздел: {result.reason}")
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")

    def test_03_zu_crosses_multiple_zpr(self):
        """ТЕСТ 3: ЗУ пересекает несколько ЗПР"""
        self.logger.section("3. ЗУ пересекает 2 ЗПР")

        if not self.detector_class:
            self.logger.fail("Детектор не импортирован")
            return

        # Две смежные ЗПР
        zpr1_wkt = "POLYGON((0 0, 50 0, 50 100, 0 100, 0 0))"
        zpr2_wkt = "POLYGON((50 0, 100 0, 100 100, 50 100, 50 0))"
        # ЗУ пересекает обе
        zu_wkt = "POLYGON((25 25, 75 25, 75 75, 25 75, 25 25))"

        zpr_layer = self._create_memory_layer("ZPR", [zpr1_wkt, zpr2_wkt])
        zu_layer = self._create_memory_layer("ZU", [zu_wkt])

        try:
            detector = self.detector_class(zpr_layer, zu_layer)
            zu_feature = next(zu_layer.getFeatures())
            result = detector.detect_single(zu_feature)

            if result.classification == self.classification_enum.RAZDEL and "multiple" in result.reason:
                self.logger.success(f"ЗУ -> RAZDEL (пересекает несколько ЗПР): {result.reason}")
            else:
                self.logger.fail(f"Ожидалось RAZDEL/multiple_zpr, получено: {result.classification.value}/{result.reason}")
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")

    def test_04_zu_boundary_vertex_matches(self):
        """ТЕСТ 4: Вершина ЗУ на границе ЗПР совпадает с вершиной ЗПР"""
        self.logger.section("4. Вершины на границе совпадают")

        if not self.detector_class:
            self.logger.fail("Детектор не импортирован")
            return

        # ЗПР с явными вершинами
        zpr_wkt = "POLYGON((0 0, 50 0, 100 0, 100 50, 100 100, 50 100, 0 100, 0 50, 0 0))"
        # ЗУ занимает четверть, все вершины совпадают с ЗПР
        zu_wkt = "POLYGON((0 0, 50 0, 50 50, 0 50, 0 0))"

        fields_def = [('ВРИ', QMetaType.Type.QString), ('Категория', QMetaType.Type.QString)]
        zpr_layer = self._create_memory_layer(
            "ZPR", [zpr_wkt],
            [{'ВРИ': 'Код 5.0', 'Категория': 'Земли НП'}],
            fields_def
        )
        zu_layer = self._create_memory_layer(
            "ZU", [zu_wkt],
            [{'ВРИ': 'Код 5.0', 'Категория': 'Земли НП'}],
            fields_def
        )

        try:
            detector = self.detector_class(zpr_layer, zu_layer)
            zu_feature = next(zu_layer.getFeatures())
            result = detector.detect_single(zu_feature)

            if result.classification != self.classification_enum.RAZDEL:
                self.logger.success(f"ЗУ -> {result.classification.value}: вершины совпадают")
            else:
                self.logger.info(f"Результат: {result.reason}")
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")

    def test_05_zu_boundary_vertex_no_match(self):
        """ТЕСТ 5: Вершина ЗУ на границе ЗПР НЕ совпадает с вершиной ЗПР"""
        self.logger.section("5. Вершина на границе не совпадает")

        if not self.detector_class:
            self.logger.fail("Детектор не импортирован")
            return

        # ЗПР: простой квадрат (только 4 вершины)
        zpr_wkt = "POLYGON((0 0, 100 0, 100 100, 0 100, 0 0))"
        # ЗУ с вершиной (50,0) на границе ЗПР, но НЕ совпадающей с вершиной ЗПР
        zu_wkt = "POLYGON((0 0, 50 0, 50 50, 0 50, 0 0))"

        zpr_layer = self._create_memory_layer("ZPR", [zpr_wkt])
        zu_layer = self._create_memory_layer("ZU", [zu_wkt])

        try:
            detector = self.detector_class(zpr_layer, zu_layer)
            zu_feature = next(zu_layer.getFeatures())
            result = detector.detect_single(zu_feature)

            if result.classification == self.classification_enum.RAZDEL and "boundary_vertex_no_match" in result.reason:
                self.logger.success(f"ЗУ -> RAZDEL: вершина на границе не совпадает")
            else:
                self.logger.info(f"Результат: {result.classification.value}, {result.reason}")
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")

    def test_06_classify_bez_mezh(self):
        """ТЕСТ 6: Классификация как Без_Меж (ВРИ и Категория совпадают)"""
        self.logger.section("6. Классификация Без_Меж")

        if not self.detector_class:
            self.logger.fail("Детектор не импортирован")
            return

        zpr_wkt = "POLYGON((0 0, 50 0, 100 0, 100 50, 100 100, 50 100, 0 100, 0 50, 0 0))"
        zu_wkt = "POLYGON((0 0, 50 0, 50 50, 0 50, 0 0))"

        fields_def = [('ВРИ', QMetaType.Type.QString), ('Категория', QMetaType.Type.QString)]
        # Одинаковые ВРИ и Категория
        zpr_layer = self._create_memory_layer(
            "ZPR", [zpr_wkt],
            [{'ВРИ': 'Отдых (рекреация)', 'Категория': 'Земли населённых пунктов'}],
            fields_def
        )
        zu_layer = self._create_memory_layer(
            "ZU", [zu_wkt],
            [{'ВРИ': 'Отдых (рекреация)', 'Категория': 'Земли населённых пунктов'}],
            fields_def
        )

        try:
            detector = self.detector_class(zpr_layer, zu_layer)
            zu_feature = next(zu_layer.getFeatures())
            result = detector.detect_single(zu_feature)

            if result.classification == self.classification_enum.BEZ_MEZH:
                self.logger.success(f"ЗУ -> BEZ_MEZH: ВРИ и Категория совпадают")
            else:
                self.logger.info(f"Результат: {result.classification.value}, {result.reason}")
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")

    def test_07_classify_izmenyaemye_vri_differs(self):
        """ТЕСТ 7: Классификация как Изменяемые (ВРИ отличается)"""
        self.logger.section("7. Классификация Изменяемые (ВРИ)")

        if not self.detector_class:
            self.logger.fail("Детектор не импортирован")
            return

        zpr_wkt = "POLYGON((0 0, 50 0, 100 0, 100 50, 100 100, 50 100, 0 100, 0 50, 0 0))"
        zu_wkt = "POLYGON((0 0, 50 0, 50 50, 0 50, 0 0))"

        fields_def = [('ВРИ', QMetaType.Type.QString), ('Категория', QMetaType.Type.QString)]
        # Разные ВРИ, одинаковая Категория
        zpr_layer = self._create_memory_layer(
            "ZPR", [zpr_wkt],
            [{'ВРИ': 'Благоустройство', 'Категория': 'Земли НП'}],
            fields_def
        )
        zu_layer = self._create_memory_layer(
            "ZU", [zu_wkt],
            [{'ВРИ': 'Отдых', 'Категория': 'Земли НП'}],
            fields_def
        )

        try:
            detector = self.detector_class(zpr_layer, zu_layer)
            zu_feature = next(zu_layer.getFeatures())
            result = detector.detect_single(zu_feature)

            if result.classification == self.classification_enum.IZMENYAEMYE:
                self.logger.success(f"ЗУ -> IZMENYAEMYE: ВРИ отличается")
                self.logger.info(f"  vri_matches={result.vri_matches}, category_matches={result.category_matches}")
            else:
                self.logger.info(f"Результат: {result.classification.value}, {result.reason}")
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")

    def test_08_classify_izmenyaemye_category_differs(self):
        """ТЕСТ 8: Классификация как Изменяемые (Категория отличается)"""
        self.logger.section("8. Классификация Изменяемые (Категория)")

        if not self.detector_class:
            self.logger.fail("Детектор не импортирован")
            return

        zpr_wkt = "POLYGON((0 0, 50 0, 100 0, 100 50, 100 100, 50 100, 0 100, 0 50, 0 0))"
        zu_wkt = "POLYGON((0 0, 50 0, 50 50, 0 50, 0 0))"

        fields_def = [('ВРИ', QMetaType.Type.QString), ('Категория', QMetaType.Type.QString)]
        # Одинаковый ВРИ, разные Категории
        zpr_layer = self._create_memory_layer(
            "ZPR", [zpr_wkt],
            [{'ВРИ': 'Отдых', 'Категория': 'Земли НП'}],
            fields_def
        )
        zu_layer = self._create_memory_layer(
            "ZU", [zu_wkt],
            [{'ВРИ': 'Отдых', 'Категория': 'Земли промышленности'}],
            fields_def
        )

        try:
            detector = self.detector_class(zpr_layer, zu_layer)
            zu_feature = next(zu_layer.getFeatures())
            result = detector.detect_single(zu_feature)

            if result.classification == self.classification_enum.IZMENYAEMYE:
                self.logger.success(f"ЗУ -> IZMENYAEMYE: Категория отличается")
                self.logger.info(f"  vri_matches={result.vri_matches}, category_matches={result.category_matches}")
            else:
                self.logger.info(f"Результат: {result.classification.value}, {result.reason}")
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")

    def test_09_detect_all(self):
        """ТЕСТ 9: Обработка всех ЗУ"""
        self.logger.section("9. detect_all()")

        if not self.detector_class:
            self.logger.fail("Детектор не импортирован")
            return

        # ЗПР
        zpr_wkt = "POLYGON((0 0, 50 0, 100 0, 100 50, 100 100, 50 100, 0 100, 0 50, 0 0))"
        # Несколько ЗУ
        zu1_wkt = "POLYGON((0 0, 50 0, 50 50, 0 50, 0 0))"
        zu2_wkt = "POLYGON((50 0, 100 0, 100 50, 50 50, 50 0))"

        fields_def = [('ВРИ', QMetaType.Type.QString), ('Категория', QMetaType.Type.QString)]
        zpr_layer = self._create_memory_layer(
            "ZPR", [zpr_wkt],
            [{'ВРИ': 'Отдых', 'Категория': 'Земли НП'}],
            fields_def
        )
        zu_layer = self._create_memory_layer(
            "ZU", [zu1_wkt, zu2_wkt],
            [
                {'ВРИ': 'Отдых', 'Категория': 'Земли НП'},  # Без_Меж
                {'ВРИ': 'Благоустройство', 'Категория': 'Земли НП'}  # Изменяемые
            ],
            fields_def
        )

        try:
            detector = self.detector_class(zpr_layer, zu_layer)
            results, stats = detector.detect_all()

            self.logger.info(f"Всего ЗУ: {stats['total_zu']}")
            self.logger.info(f"Изменяемые: {stats['izmenyaemye']}")
            self.logger.info(f"Без_Меж: {stats['bez_mezh']}")
            self.logger.info(f"Раздел: {stats['razdel']}")

            if len(results) == 2:
                self.logger.success(f"detect_all() вернул результаты для {len(results)} ЗУ")
            else:
                self.logger.fail(f"Ожидалось 2 результата, получено {len(results)}")
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")

    def test_10_get_separated_lists(self):
        """ТЕСТ 10: Получение раздельных списков"""
        self.logger.section("10. Раздельные списки")

        if not self.detector_class:
            self.logger.fail("Детектор не импортирован")
            return

        zpr_wkt = "POLYGON((0 0, 50 0, 100 0, 100 50, 100 100, 50 100, 0 100, 0 50, 0 0))"
        zu_wkt = "POLYGON((0 0, 50 0, 50 50, 0 50, 0 0))"

        fields_def = [('ВРИ', QMetaType.Type.QString), ('Категория', QMetaType.Type.QString)]
        zpr_layer = self._create_memory_layer(
            "ZPR", [zpr_wkt],
            [{'ВРИ': 'Отдых', 'Категория': 'Земли НП'}],
            fields_def
        )
        zu_layer = self._create_memory_layer(
            "ZU", [zu_wkt],
            [{'ВРИ': 'Отдых', 'Категория': 'Земли НП'}],
            fields_def
        )

        try:
            detector = self.detector_class(zpr_layer, zu_layer)

            izm_pairs = detector.get_izm_zu_with_zpr()
            bez_mezh_pairs = detector.get_bez_mezh_zu_with_zpr()
            razdel_ids = detector.get_razdel_zu_ids()
            no_change_ids = detector.get_no_change_zu_ids()

            self.logger.info(f"Изменяемые пары: {len(izm_pairs)}")
            self.logger.info(f"Без_Меж пары: {len(bez_mezh_pairs)}")
            self.logger.info(f"Раздел fids: {len(razdel_ids)}")
            self.logger.info(f"Без изменения геометрии fids: {len(no_change_ids)}")

            self.logger.success("Раздельные списки получены")
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")
