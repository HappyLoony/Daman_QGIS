# -*- coding: utf-8 -*-
"""
Fsm_2_1_8: Движок выборки земельных участков и ОКС
Основная логика выборки объектов по пересечению с границами
"""

from typing import Optional, Tuple
from qgis.core import (
    QgsVectorLayer, QgsGeometry, QgsFeature,
    QgsCoordinateTransform, QgsProject, QgsWkbTypes
)

from Daman_QGIS.constants import (
    LAYER_SELECTION_ZU, LAYER_SELECTION_ZU_10M, LAYER_SELECTION_OKS,
    LAYER_SELECTION_NP, LAYER_SELECTION_TERZONY, LAYER_SELECTION_VODA,
    BOUNDARY_INNER_BUFFER_M, BUFFER_SEGMENTS
)
from Daman_QGIS.utils import log_info, log_warning, log_error, log_debug
from Daman_QGIS.managers import CoordinatePrecisionManager
from Daman_QGIS.managers.submodules.Msm_13_2_attribute_processor import AttributeProcessor
from Daman_QGIS.managers.submodules.Msm_13_5_attribute_mapper import AttributeMapper
from Daman_QGIS.tools.F_2_processing.submodules.Fsm_2_1_5_geometry_processor import Fsm_2_1_5_GeometryProcessor
from Daman_QGIS.tools.F_2_processing.submodules.Fsm_2_1_6_layer_builder import Fsm_2_1_6_LayerBuilder
from Daman_QGIS.tools.F_2_processing.submodules.Fsm_2_1_9_oks_characteristic_mapper import Fsm_2_1_9_OKSCharacteristicMapper


class Fsm_2_1_8_SelectionEngine:
    """Движок выборки земельных участков и ОКС"""

    def __init__(self, iface, plugin_dir: str, gpkg_path: str):
        """Инициализация

        Args:
            iface: QGIS interface
            plugin_dir: Путь к директории плагина
            gpkg_path: Путь к project.gpkg
        """
        self.iface = iface
        self.plugin_dir = plugin_dir
        self.gpkg_path = gpkg_path

        # Инициализация субмодулей
        self.geo_processor = Fsm_2_1_5_GeometryProcessor()
        self.layer_builder = Fsm_2_1_6_LayerBuilder(plugin_dir)
        self.attr_mapper = AttributeMapper()
        self.attribute_processor = AttributeProcessor()

    def perform_selection_zu(self, boundaries_exact: QgsVectorLayer, boundaries_10m: QgsVectorLayer,
                            boundaries_minus2cm: QgsVectorLayer, source_layer: QgsVectorLayer,
                            object_type: str = 'ZU') -> Tuple[Optional[QgsVectorLayer], Optional[QgsVectorLayer]]:
        """Выполнение выборки для ЗУ

        Args:
            boundaries_exact: Слой точных границ (L_1_1_1)
            boundaries_10m: Слой границ с буфером 10м (L_1_1_2)
            boundaries_minus2cm: Слой границ с буфером -2см (L_1_1_4)
            source_layer: Исходный слой (ЗУ)
            object_type: Тип объекта ('ZU')

        Returns:
            tuple: (final_layer_1, final_layer_2) или (None, None) при ошибке
        """
        try:
            # Проверяем что слои границ не пустые
            if boundaries_10m.featureCount() == 0:
                raise ValueError(f"Слой '{boundaries_10m.name()}' не содержит объектов. Сначала импортируйте границы через F_1_1.")
            if boundaries_exact.featureCount() == 0:
                raise ValueError(f"Слой '{boundaries_exact.name()}' не содержит объектов. Сначала импортируйте границы через F_1_1.")
            if boundaries_minus2cm.featureCount() == 0:
                raise ValueError(f"Слой '{boundaries_minus2cm.name()}' не содержит объектов. Сначала импортируйте границы через F_1_1.")

            # Получаем объединенные геометрии для трёх слоёв границ
            boundaries_geom_10m = self.geo_processor.get_boundaries_geometry(boundaries_10m)
            boundaries_geom_exact = self.geo_processor.get_boundaries_geometry(boundaries_exact)
            boundaries_geom_minus2cm = self.geo_processor.get_boundaries_geometry(boundaries_minus2cm)

            if not boundaries_geom_10m:
                raise ValueError(f"Не удалось получить валидную геометрию из слоя '{boundaries_10m.name()}'")
            if not boundaries_geom_exact:
                raise ValueError(f"Не удалось получить валидную геометрию из слоя '{boundaries_exact.name()}'")
            if not boundaries_geom_minus2cm:
                raise ValueError(f"Не удалось получить валидную геометрию из слоя '{boundaries_minus2cm.name()}'")

            # Создаем границы 10м с буфером -2см для повторной проверки слоя 10м
            boundaries_geom_10m_minus2cm = self._create_minus2cm_buffer(boundaries_geom_10m)

            log_info(f"Fsm_2_1_8: Начало выборки. Всего объектов: {source_layer.featureCount()}")

            # Создаем СК трансформации
            transform_to_project, transform_for_intersection = self.geo_processor.create_coordinate_transforms(
                source_layer, boundaries_10m
            )

            # ========== ЭТАП 1: Создаём два слоя и выполняем первичную выборку ==========
            log_info("Fsm_2_1_8: ЭТАП 1: ПЕРВИЧНАЯ ВЫБОРКА")
            # КРИТИЧНО: Используем СК проекта как единственный источник истины
            # НЕ доверяем boundaries_layer.crs() - он может быть неправильно импортирован
            target_crs = QgsProject.instance().crs()

            result_layer_1 = self.layer_builder.create_result_layer(source_layer, layer_name=LAYER_SELECTION_ZU, object_type=object_type, target_crs=target_crs)
            if not result_layer_1:
                raise ValueError(f"Не удалось создать слой {LAYER_SELECTION_ZU}")

            result_layer_2 = self.layer_builder.create_result_layer(source_layer, layer_name=LAYER_SELECTION_ZU_10M, object_type=object_type, target_crs=target_crs)
            if not result_layer_2:
                raise ValueError(f"Не удалось создать слой {LAYER_SELECTION_ZU_10M}")

            # Выполняем выборку для ОБОИХ слоёв с РАЗНЫМИ границами
            selected_count_1 = 0  # Счетчик для Le_2_1_1_1 (точные границы)
            selected_count_2 = 0  # Счетчик для Le_2_1_1_2 (буфер 10м)

            result_layer_1.startEditing()
            result_layer_2.startEditing()

            for feature in source_layer.getFeatures():
                geom = feature.geometry()
                if not geom or geom.isNull():
                    continue

                # Обработка геометрии: трансформация, округление, Multi-тип
                final_geom, test_geom = self._process_feature_geometry(
                    geom, transform_to_project, transform_for_intersection
                )

                # Проверяем пересечение с точными границами и границами 10м
                intersects_exact = test_geom.intersects(boundaries_geom_exact)
                intersects_10m = test_geom.intersects(boundaries_geom_10m)

                # Проверка 1: Пересечение с точными границами (для Le_2_1_1_1)
                if intersects_exact:
                    new_feature_1 = QgsFeature(result_layer_1.fields())
                    new_feature_1.setGeometry(QgsGeometry(final_geom))
                    self.attr_mapper.map_attributes(feature, new_feature_1, source_layer.fields(), object_type=object_type)

                    # Нормализуем порядок прав и собственников
                    self._normalize_feature_rights(new_feature_1)

                    # Капитализируем первую букву во всех полях
                    self._capitalize_all_fields(new_feature_1)

                    result_layer_1.addFeature(new_feature_1)
                    selected_count_1 += 1

                # Проверка 2: Пересечение с границами 10м (для Le_2_1_1_2)
                # ВСЕ объекты, пересекающиеся с расширенными границами (включая те, что в точных)
                if intersects_10m:
                    new_feature_2 = QgsFeature(result_layer_2.fields())
                    new_feature_2.setGeometry(QgsGeometry(final_geom))
                    self.attr_mapper.map_attributes(feature, new_feature_2, source_layer.fields(), object_type=object_type)

                    # Нормализуем порядок прав и собственников
                    self._normalize_feature_rights(new_feature_2)

                    # Капитализируем первую букву во всех полях
                    self._capitalize_all_fields(new_feature_2)

                    result_layer_2.addFeature(new_feature_2)
                    selected_count_2 += 1

            result_layer_1.commitChanges()
            result_layer_2.commitChanges()

            log_info(f"Fsm_2_1_8: Первичная выборка завершена:")
            log_info(f"Fsm_2_1_8:   Le_2_1_1_1_Выборка_ЗУ (точная): {selected_count_1} объектов")
            log_info(f"Fsm_2_1_8:   Le_2_1_1_2_Выборка_ЗУ_10_м: {selected_count_2} объектов")

            # ========== ЭТАП 2: ЭТАП ПОВТОРНОЙ ПРОВЕРКИ ПОСЛЕ ОКРУГЛЕНИЯ ==========
            # Проверяем оба слоя с границами -2см
            log_info("Fsm_2_1_8: ЭТАП 2: ПОВТОРНАЯ ПРОВЕРКА ПОСЛЕ ОКРУГЛЕНИЯ")

            count_after_recheck_1 = selected_count_1
            count_after_recheck_2 = selected_count_2

            if selected_count_1 > 0:
                removed_1 = self.geo_processor.recheck_intersection_after_rounding(result_layer_1, boundaries_geom_minus2cm)
                count_after_recheck_1 = result_layer_1.featureCount()
                log_info(f"Fsm_2_1_8: Le_2_1_1_1: после повторной проверки осталось {count_after_recheck_1} (удалено {removed_1})")

            if selected_count_2 > 0:
                # Для слоя 10м используем границы 10м с буфером -2см
                removed_2 = self.geo_processor.recheck_intersection_after_rounding(result_layer_2, boundaries_geom_10m_minus2cm)
                count_after_recheck_2 = result_layer_2.featureCount()
                log_info(f"Fsm_2_1_8: Le_2_1_1_2: после повторной проверки осталось {count_after_recheck_2} (удалено {removed_2})")

            # Этап 2.5 удалён - нумерация "№ п/п" больше не используется

            # ========== ЭТАП 2.6: Дополнение поля ЕЗ из выписок ==========
            # FIX (2025-12-17): Поле "ЕЗ" не приходит из WFS (wfs_zu_field="-")
            # Дополняем из слоёв выписок (Le_1_6_3_2_Выписки_ЕЗ_poly)
            log_info("Fsm_2_1_8: ЭТАП 2.6: ДОПОЛНЕНИЕ ПОЛЯ ЕЗ ИЗ ВЫПИСОК")

            if count_after_recheck_1 > 0:
                self._supplement_ez_field_from_extracts(result_layer_1)
            if count_after_recheck_2 > 0:
                self._supplement_ez_field_from_extracts(result_layer_2)

            # ========== ЭТАП 2.7: Дополнение атрибутов из выписок ==========
            # FIX (2025-12-18): WFS содержит ограниченные данные, выписки - полные
            # Дополняем: Категория, ВРИ, Права, Обременения, Собственники, Арендаторы
            log_info("Fsm_2_1_8: ЭТАП 2.7: ДОПОЛНЕНИЕ АТРИБУТОВ ИЗ ВЫПИСОК")

            if count_after_recheck_1 > 0:
                self._supplement_attributes_from_extracts(result_layer_1)
            if count_after_recheck_2 > 0:
                self._supplement_attributes_from_extracts(result_layer_2)

            # ========== ЭТАП 3: Финальная обработка NULL значений (ДО сохранения) ==========
            log_info("Fsm_2_1_8: ЭТАП 3: ФИНАЛЬНАЯ ОБРАБОТКА NULL ЗНАЧЕНИЙ")

            if count_after_recheck_1 > 0:
                self.attr_mapper.finalize_layer_null_values(result_layer_1, LAYER_SELECTION_ZU)
            if count_after_recheck_2 > 0:
                self.attr_mapper.finalize_layer_null_values(result_layer_2, LAYER_SELECTION_ZU_10M)

            # ========== ЭТАП 4: Сохранение в GeoPackage (ПОСЛЕ обработки NULL) ==========
            log_info("Fsm_2_1_8: ЭТАП 4: СОХРАНЕНИЕ В GEOPACKAGE")

            final_layer_1 = None
            final_layer_2 = None

            if count_after_recheck_1 > 0:
                final_layer_1 = self.layer_builder.save_layer_to_gpkg(result_layer_1, LAYER_SELECTION_ZU, self.gpkg_path)
            else:
                log_info(f"Fsm_2_1_8: Слой {LAYER_SELECTION_ZU} пуст после проверки - пропускаем сохранение")

            if count_after_recheck_2 > 0:
                final_layer_2 = self.layer_builder.save_layer_to_gpkg(result_layer_2, LAYER_SELECTION_ZU_10M, self.gpkg_path)
            else:
                log_info(f"Fsm_2_1_8: Слой {LAYER_SELECTION_ZU_10M} пуст после проверки - пропускаем сохранение")

            return final_layer_1, final_layer_2

        except Exception as e:
            log_error(f"Fsm_2_1_8: Ошибка при выполнении выборки ЗУ: {str(e)}")
            return None, None

    def perform_selection_oks(self, boundaries_exact: QgsVectorLayer,
                              source_layer: QgsVectorLayer) -> Optional[QgsVectorLayer]:
        """Выполнение выборки для ОКС (упрощённая версия - без буфера 10м и повторной проверки)

        Args:
            boundaries_exact: Слой точных границ (L_1_1_1)
            source_layer: Исходный слой ОКС (L_1_2_4_WFS_ОКС)

        Returns:
            QgsVectorLayer: Финальный слой или None при ошибке
        """
        try:
            log_info("Fsm_2_1_8: ВЫПОЛНЕНИЕ ВЫБОРКИ ОКС")

            # Проверяем что слой границ не пустой
            feature_count = boundaries_exact.featureCount()
            log_info(f"Fsm_2_1_8: Слой границ '{boundaries_exact.name()}': {feature_count} объектов")
            if feature_count == 0:
                raise ValueError(f"Слой '{boundaries_exact.name()}' не содержит объектов. Сначала импортируйте границы через F_1_1.")

            # Получаем объединенную геометрию границ
            boundaries_geom_exact = self.geo_processor.get_boundaries_geometry(boundaries_exact)
            if not boundaries_geom_exact:
                raise ValueError(f"Не удалось получить валидную геометрию из слоя '{boundaries_exact.name()}'")

            # Создаем СК трансформации
            transform_to_project, transform_for_intersection = self.geo_processor.create_coordinate_transforms(
                source_layer, boundaries_exact
            )

            # ========== ЭТАП 1: СОЗДАНИЕ СЛОЯ И ВЫБОРКА ==========
            log_info("Fsm_2_1_8: ЭТАП 1: ВЫБОРКА ОКС")

            # Логируем доступные поля в исходном слое ОКС
            source_field_names = [field.name() for field in source_layer.fields()]
            log_info(f"Fsm_2_1_8: Исходный слой ОКС '{source_layer.name()}': доступные поля: {', '.join(source_field_names)}")

            # Логируем информацию о слоях для отладки
            project_crs = QgsProject.instance().crs()
            log_info(f"Fsm_2_1_8: ОКС: Исходный слой '{source_layer.name()}': {source_layer.featureCount()} объектов, CRS: {source_layer.crs().authid()}")
            log_info(f"Fsm_2_1_8: ОКС: Слой границ '{boundaries_exact.name()}': {boundaries_exact.featureCount()} объектов, CRS: {boundaries_exact.crs().authid()}")
            log_info(f"Fsm_2_1_8: ОКС: СК проекта: {project_crs.authid()}")

            # КРИТИЧНО: Используем СК проекта как единственный источник истины
            # НЕ доверяем boundaries_layer.crs() - он может быть неправильно импортирован
            target_crs = project_crs

            result_layer = self.layer_builder.create_result_layer(source_layer, layer_name=LAYER_SELECTION_OKS, object_type='OKS', target_crs=target_crs)
            if not result_layer:
                raise ValueError(f"Не удалось создать слой {LAYER_SELECTION_OKS}")

            selected_count = 0
            checked_count = 0
            result_layer.startEditing()

            for feature in source_layer.getFeatures():
                checked_count += 1
                geom = feature.geometry()
                if not geom or geom.isNull():
                    continue

                # Обработка геометрии: трансформация, округление, Multi-тип
                final_geom, test_geom = self._process_feature_geometry(
                    geom, transform_to_project, transform_for_intersection
                )

                # Проверка пересечения с границами
                if test_geom.intersects(boundaries_geom_exact):
                    new_feature = QgsFeature(result_layer.fields())
                    new_feature.setGeometry(QgsGeometry(final_geom))
                    self.attr_mapper.map_attributes(feature, new_feature, source_layer.fields(), object_type='OKS')

                    # Специальная обработка полей "Значение" и "Характеристика" для ОКС
                    Fsm_2_1_9_OKSCharacteristicMapper.map_characteristic_and_value(
                        feature, new_feature, source_layer.fields()
                    )

                    # Капитализируем первую букву во всех полях
                    self._capitalize_all_fields(new_feature)

                    result_layer.addFeature(new_feature)
                    selected_count += 1

            result_layer.commitChanges()

            log_info(f"Fsm_2_1_8: ОКС: Проверено объектов: {checked_count}, найдено пересечений: {selected_count}")
            log_info(f"Fsm_2_1_8: Первичная выборка завершена: {selected_count} объектов ОКС")

            # Этап 1.5 удалён - нумерация "№ п/п" больше не используется

            # ========== ЭТАП 2: ПОВТОРНАЯ ПРОВЕРКА ПОСЛЕ ОКРУГЛЕНИЯ ==========
            log_info("Fsm_2_1_8: ЭТАП 2: ПОВТОРНАЯ ПРОВЕРКА ПОСЛЕ ОКРУГЛЕНИЯ")

            if selected_count > 0:
                # Создаём boundaries_geom_exact с буфером -2см для повторной проверки
                boundaries_geom_minus2cm = self._create_minus2cm_buffer(boundaries_geom_exact)

                removed = self.geo_processor.recheck_intersection_after_rounding(
                    result_layer, boundaries_geom_minus2cm
                )
                selected_count = result_layer.featureCount()
                log_info(f"Fsm_2_1_8: ОКС: после повторной проверки осталось {selected_count} (удалено {removed})")
            else:
                log_info("Fsm_2_1_8: Слой ОКС пуст - пропускаем повторную проверку")

            # ========== ЭТАП 3: Финальная обработка NULL значений (ДО сохранения) ==========
            log_info("Fsm_2_1_8: ЭТАП 3: ФИНАЛЬНАЯ ОБРАБОТКА NULL ЗНАЧЕНИЙ")
            if selected_count == 0:
                log_info(f"Fsm_2_1_8: Слой {LAYER_SELECTION_OKS} пуст после проверки - пропускаем обработку")
                return None

            self.attr_mapper.finalize_layer_null_values(result_layer, LAYER_SELECTION_OKS)

            # ========== ЭТАП 4: Сохранение в GeoPackage (ПОСЛЕ обработки NULL) ==========
            log_info("Fsm_2_1_8: ЭТАП 4: СОХРАНЕНИЕ В GEOPACKAGE")
            final_layer = self.layer_builder.save_layer_to_gpkg(result_layer, LAYER_SELECTION_OKS, self.gpkg_path)

            return final_layer

        except Exception as e:
            log_error(f"Fsm_2_1_8: Ошибка при выполнении выборки ОКС: {str(e)}")
            return None

    def perform_selection_generic(self, boundaries_exact: QgsVectorLayer,
                                   source_layer: QgsVectorLayer,
                                   target_layer_name: str) -> Optional[QgsVectorLayer]:
        """Выполнение generic выборки (НП, ТерЗоны, Вода и др.)

        Упрощённая выборка без буфера 10м и без специальной обработки атрибутов.
        Поля копируются напрямую из исходного WFS слоя.

        TODO: Создать Base_selection_NP.json, Base_selection_TerZony.json,
              Base_selection_Voda.json для более точного маппинга полей

        Args:
            boundaries_exact: Слой точных границ (L_1_1_1)
            source_layer: Исходный WFS слой (НП, ТерЗоны, Вода)
            target_layer_name: Имя целевого слоя выборки

        Returns:
            QgsVectorLayer: Финальный слой или None при ошибке
        """
        try:
            log_info(f"Fsm_2_1_8: ВЫПОЛНЕНИЕ GENERIC ВЫБОРКИ для {target_layer_name}")

            # Проверяем что слой границ не пустой
            feature_count = boundaries_exact.featureCount()
            log_info(f"Fsm_2_1_8: Слой границ '{boundaries_exact.name()}': {feature_count} объектов")
            if feature_count == 0:
                raise ValueError(f"Слой '{boundaries_exact.name()}' не содержит объектов. Сначала импортируйте границы через F_1_1.")

            # Получаем объединенную геометрию границ
            boundaries_geom_exact = self.geo_processor.get_boundaries_geometry(boundaries_exact)
            if not boundaries_geom_exact:
                raise ValueError(f"Не удалось получить валидную геометрию из слоя '{boundaries_exact.name()}'")

            # Создаем СК трансформации
            transform_to_project, transform_for_intersection = self.geo_processor.create_coordinate_transforms(
                source_layer, boundaries_exact
            )

            # ========== ЭТАП 1: СОЗДАНИЕ СЛОЯ И ВЫБОРКА ==========
            log_info(f"Fsm_2_1_8: ЭТАП 1: ВЫБОРКА {target_layer_name}")

            # Логируем информацию о слоях для отладки
            source_field_names = [field.name() for field in source_layer.fields()]
            project_crs = QgsProject.instance().crs()
            log_info(f"Fsm_2_1_8: Исходный слой '{source_layer.name()}': доступные поля: {', '.join(source_field_names)}")
            log_info(f"Fsm_2_1_8: Исходный слой '{source_layer.name()}': {source_layer.featureCount()} объектов, CRS: {source_layer.crs().authid()}")
            log_info(f"Fsm_2_1_8: Слой границ '{boundaries_exact.name()}': {boundaries_exact.featureCount()} объектов, CRS: {boundaries_exact.crs().authid()}")
            log_info(f"Fsm_2_1_8: СК проекта: {project_crs.authid()}")

            # КРИТИЧНО: Используем СК проекта как единственный источник истины
            # НЕ доверяем boundaries_layer.crs() - он может быть неправильно импортирован
            target_crs = project_crs

            # Создаём слой с GENERIC типом (прямое копирование полей)
            result_layer = self.layer_builder.create_result_layer(
                source_layer, layer_name=target_layer_name, object_type='GENERIC', target_crs=target_crs
            )
            if not result_layer:
                raise ValueError(f"Не удалось создать слой {target_layer_name}")

            selected_count = 0
            checked_count = 0
            result_layer.startEditing()

            for feature in source_layer.getFeatures():
                checked_count += 1
                geom = feature.geometry()
                if not geom or geom.isNull():
                    continue

                # Обработка геометрии: трансформация, округление, Multi-тип
                final_geom, test_geom = self._process_feature_geometry(
                    geom, transform_to_project, transform_for_intersection
                )

                # Проверка пересечения с границами
                if test_geom.intersects(boundaries_geom_exact):
                    new_feature = QgsFeature(result_layer.fields())
                    new_feature.setGeometry(QgsGeometry(final_geom))

                    # Прямое копирование атрибутов (без маппинга)
                    self._copy_attributes_direct(feature, new_feature, source_layer.fields())

                    # Капитализируем первую букву во всех текстовых полях
                    self._capitalize_all_fields(new_feature)

                    result_layer.addFeature(new_feature)
                    selected_count += 1

            result_layer.commitChanges()

            log_info(f"Fsm_2_1_8: {target_layer_name}: Проверено объектов: {checked_count}, найдено пересечений: {selected_count}")
            log_info(f"Fsm_2_1_8: Первичная выборка завершена: {selected_count} объектов")

            # ========== ЭТАП 2: ПОВТОРНАЯ ПРОВЕРКА ПОСЛЕ ОКРУГЛЕНИЯ ==========
            log_info(f"Fsm_2_1_8: ЭТАП 2: ПОВТОРНАЯ ПРОВЕРКА ПОСЛЕ ОКРУГЛЕНИЯ")

            if selected_count > 0:
                # Создаём boundaries_geom_exact с буфером -2см для повторной проверки
                boundaries_geom_minus2cm = self._create_minus2cm_buffer(boundaries_geom_exact)

                removed = self.geo_processor.recheck_intersection_after_rounding(
                    result_layer, boundaries_geom_minus2cm
                )
                selected_count = result_layer.featureCount()
                log_info(f"Fsm_2_1_8: {target_layer_name}: после повторной проверки осталось {selected_count} (удалено {removed})")
            else:
                log_info(f"Fsm_2_1_8: Слой {target_layer_name} пуст - пропускаем повторную проверку")

            # ========== ЭТАП 3: СОХРАНЕНИЕ В GEOPACKAGE ==========
            log_info(f"Fsm_2_1_8: ЭТАП 3: СОХРАНЕНИЕ В GEOPACKAGE")
            if selected_count == 0:
                log_info(f"Fsm_2_1_8: Слой {target_layer_name} пуст после проверки - пропускаем сохранение")
                return None

            final_layer = self.layer_builder.save_layer_to_gpkg(result_layer, target_layer_name, self.gpkg_path)

            return final_layer

        except Exception as e:
            log_error(f"Fsm_2_1_8: Ошибка при выполнении generic выборки {target_layer_name}: {str(e)}")
            return None

    def _copy_attributes_direct(self, source_feature: QgsFeature, target_feature: QgsFeature,
                                 source_fields) -> None:
        """Прямое копирование атрибутов из исходного feature в целевой

        Args:
            source_feature: Исходный feature
            target_feature: Целевой feature (изменяется in-place)
            source_fields: Поля исходного слоя
        """
        for field in source_fields:
            field_name = field.name()
            # Проверяем что поле существует в целевом feature
            if target_feature.fields().indexOf(field_name) != -1:
                value = source_feature.attribute(field_name)
                target_feature.setAttribute(field_name, value)

    def _normalize_feature_rights(self, feature: QgsFeature) -> None:
        """Нормализация порядка прав и собственников в feature

        Args:
            feature: Feature для обработки (изменяется in-place)
        """
        rights_value = feature.attribute('Права')
        owners_value = feature.attribute('Собственники')

        if rights_value and rights_value != '-':
            normalized_rights, normalized_owners = self.attribute_processor.normalize_rights_order(
                rights_value, owners_value
            )
            feature.setAttribute('Права', normalized_rights)
            feature.setAttribute('Собственники', normalized_owners)

    def _capitalize_all_fields(self, feature: QgsFeature) -> None:
        """Капитализация первой буквы во всех текстовых полях

        Args:
            feature: Feature для обработки (изменяется in-place)
        """
        from qgis.PyQt.QtCore import QMetaType

        # Список полей для капитализации (только текстовые поля QString)
        field_names = [f.name() for f in feature.fields() if f.type() == QMetaType.Type.QString]

        for field_name in field_names:
            current_value = feature.attribute(field_name)

            if current_value is None or not isinstance(current_value, str):
                continue

            capitalized_value = self.attribute_processor.capitalize_field(current_value)
            feature.setAttribute(field_name, capitalized_value)

    def _process_feature_geometry(self, geom: QgsGeometry,
                                   transform_to_project: Optional[QgsCoordinateTransform],
                                   transform_for_intersection: Optional[QgsCoordinateTransform]
                                   ) -> Tuple[QgsGeometry, QgsGeometry]:
        """Обработка геометрии feature: трансформация, округление, преобразование в Multi-тип

        Args:
            geom: Исходная геометрия
            transform_to_project: Трансформер в СК проекта (или None)
            transform_for_intersection: Трансформер для проверки пересечения (или None)

        Returns:
            tuple: (final_geom, test_geom)
                - final_geom: Геометрия для результирующего слоя (округлённая, Multi-тип)
                - test_geom: Геометрия для проверки пересечения
        """
        # Трансформируем геометрию для результата
        final_geom = QgsGeometry(geom)
        if transform_to_project:
            final_geom.transform(transform_to_project)

        # Округляем координаты до 0.01м
        final_geom = CoordinatePrecisionManager._round_geometry(final_geom)

        # Преобразуем в Multi-тип если нужно (для совместимости с целевым слоем)
        if not QgsWkbTypes.isMultiType(final_geom.wkbType()):
            final_geom = QgsGeometry.fromMultiPolygonXY([final_geom.asPolygon()])

        # Трансформируем для проверки пересечения
        test_geom = QgsGeometry(geom)
        if transform_for_intersection:
            test_geom.transform(transform_for_intersection)

        return final_geom, test_geom

    def _create_minus2cm_buffer(self, boundaries_geom: QgsGeometry) -> QgsGeometry:
        """Создание буфера -2см для геометрии границ

        Args:
            boundaries_geom: Исходная геометрия границ

        Returns:
            QgsGeometry: Геометрия с буфером -2см

        Raises:
            ValueError: Если не удалось создать буфер
        """
        boundaries_geom_minus2cm = QgsGeometry(boundaries_geom)
        boundaries_geom_minus2cm = boundaries_geom_minus2cm.buffer(BOUNDARY_INNER_BUFFER_M, BUFFER_SEGMENTS)  # -2см буфер

        if not boundaries_geom_minus2cm or boundaries_geom_minus2cm.isNull():
            raise ValueError("Не удалось создать геометрию границ с буфером -2см")

        return boundaries_geom_minus2cm

    def _supplement_ez_field_from_extracts(self, layer: QgsVectorLayer) -> int:
        """Дополнение поля ЕЗ из слоёв выписок

        Поле "ЕЗ" в выборке (Base_selection_ZU.json) содержит КН родительского ЕЗ
        для обособленных участков. Это поле НЕ приходит из WFS (wfs_zu_field="-"),
        поэтому после первичного маппинга оно пустое.

        Логика дополнения:
        1. Загрузить слои выписок с полем "ЕЗ" или "КН_родителя"
        2. Построить кэш {КН: ЕЗ} из выписок
        3. Для каждого feature с пустым полем "ЕЗ" - дополнить из кэша

        Args:
            layer: Слой выборки для дополнения

        Returns:
            int: Количество дополненных записей
        """
        # Проверяем наличие поля "ЕЗ" в целевом слое
        ez_field_idx = layer.fields().indexOf('ЕЗ')
        if ez_field_idx == -1:
            log_warning("Fsm_2_1_8: Поле 'ЕЗ' не найдено в слое выборки")
            return 0

        kn_field_idx = layer.fields().indexOf('КН')
        if kn_field_idx == -1:
            log_warning("Fsm_2_1_8: Поле 'КН' не найдено в слое выборки")
            return 0

        # Слои выписок с полем "ЕЗ" (КН родительского ЕЗ)
        EXTRACT_LAYERS_WITH_EZ = [
            'Le_1_6_3_2_Выписки_ЕЗ_poly',   # Обособленные участки ЕЗ (поле "ЕЗ")
            'Le_1_6_1_1_Выписки_ЗУ_poly',   # Обычные ЗУ (если есть поле "ЕЗ")
        ]

        # Построить кэш {КН: ЕЗ} из слоёв выписок
        ez_cache = {}  # {кадастровый_номер: кн_родительского_ез}

        project = QgsProject.instance()
        for extract_layer_name in EXTRACT_LAYERS_WITH_EZ:
            extract_layers = project.mapLayersByName(extract_layer_name)
            if not extract_layers:
                continue

            layer_obj = extract_layers[0]
            if not isinstance(layer_obj, QgsVectorLayer):
                continue

            extract_layer: QgsVectorLayer = layer_obj
            if not extract_layer.isValid():
                continue

            # Ищем поле с КН родительского ЕЗ (может называться "ЕЗ" или "КН_родителя")
            extract_ez_idx = extract_layer.fields().indexOf('ЕЗ')
            if extract_ez_idx == -1:
                extract_ez_idx = extract_layer.fields().indexOf('КН_родителя')
            if extract_ez_idx == -1:
                log_debug(f"Fsm_2_1_8: Слой {extract_layer_name} не содержит поля 'ЕЗ' или 'КН_родителя'")
                continue

            extract_kn_idx = extract_layer.fields().indexOf('КН')
            if extract_kn_idx == -1:
                continue

            # Загружаем данные в кэш
            for feature in extract_layer.getFeatures():
                kn = feature.attribute(extract_kn_idx)
                ez = feature.attribute(extract_ez_idx)

                # Добавляем только если оба значения валидны и различны
                if kn and ez and kn != ez:
                    # Не перезаписываем если уже есть
                    if kn not in ez_cache:
                        ez_cache[kn] = ez

            log_debug(f"Fsm_2_1_8: Из {extract_layer_name} загружено {len(ez_cache)} записей в кэш ЕЗ")

        if not ez_cache:
            log_debug("Fsm_2_1_8: Кэш ЕЗ пуст - нет данных в слоях выписок")
            return 0

        # Дополнить поле "ЕЗ" в слое выборки
        supplemented_count = 0
        layer.startEditing()

        for feature in layer.getFeatures():
            current_ez = feature.attribute(ez_field_idx)
            kn = feature.attribute(kn_field_idx)

            # Дополняем если поле пустое и есть данные в кэше
            if (not current_ez or current_ez == '-' or current_ez == '') and kn and kn in ez_cache:
                layer.changeAttributeValue(feature.id(), ez_field_idx, ez_cache[kn])
                supplemented_count += 1

        layer.commitChanges()

        if supplemented_count > 0:
            log_info(f"Fsm_2_1_8: Дополнено поле 'ЕЗ' для {supplemented_count} объектов из выписок")
        else:
            log_debug("Fsm_2_1_8: Нет объектов для дополнения поля 'ЕЗ'")

        return supplemented_count

    def _supplement_attributes_from_extracts(self, layer: QgsVectorLayer) -> int:
        """Дополнение атрибутов выборки из слоёв выписок

        FIX (2025-12-18): WFS слой содержит ограниченный набор данных.
        Выписки ЕГРН содержат полные сведения (Категория, ВРИ, Права, Обременения и т.д.)
        Этот метод дополняет пустые поля выборки данными из выписок.

        Логика дополнения:
        1. Загрузить слои выписок (Le_1_6_3_2_Выписки_ЕЗ_poly, Le_1_6_1_1_Выписки_ЗУ_poly)
        2. Построить кэш {КН: {поле: значение}} из выписок
        3. Для каждого feature с пустыми полями - дополнить из кэша

        Дополняемые поля (если пустые в выборке):
        - Адрес_Местоположения
        - Категория
        - ВРИ
        - Права
        - Обременения
        - Собственники
        - Арендаторы

        Args:
            layer: Слой выборки для дополнения

        Returns:
            int: Количество обновлённых записей
        """
        # Поля для дополнения (должны совпадать между выпиской и выборкой)
        FIELDS_TO_SUPPLEMENT = [
            'Адрес_Местоположения',
            'Категория',
            'ВРИ',
            'Права',
            'Обременения',
            'Собственники',
            'Арендаторы',
        ]

        # Проверяем наличие поля "КН" в целевом слое
        kn_field_idx = layer.fields().indexOf('КН')
        if kn_field_idx == -1:
            log_warning("Fsm_2_1_8: Поле 'КН' не найдено в слое выборки")
            return 0

        # Слои выписок с атрибутами
        EXTRACT_LAYERS = [
            'Le_1_6_3_2_Выписки_ЕЗ_poly',   # Обособленные участки ЕЗ
            'Le_1_6_1_1_Выписки_ЗУ_poly',   # Обычные ЗУ
        ]

        # Построить кэш {КН: {поле: значение}} из слоёв выписок
        attr_cache = {}  # {кадастровый_номер: {поле: значение}}

        project = QgsProject.instance()
        for extract_layer_name in EXTRACT_LAYERS:
            extract_layers = project.mapLayersByName(extract_layer_name)
            if not extract_layers:
                continue

            layer_obj = extract_layers[0]
            if not isinstance(layer_obj, QgsVectorLayer):
                continue

            extract_layer: QgsVectorLayer = layer_obj
            if not extract_layer.isValid():
                continue

            extract_kn_idx = extract_layer.fields().indexOf('КН')
            if extract_kn_idx == -1:
                continue

            extract_field_names = [f.name() for f in extract_layer.fields()]

            # Загружаем атрибуты в кэш
            for feature in extract_layer.getFeatures():
                kn = feature.attribute(extract_kn_idx)
                if not kn:
                    continue

                # Не перезаписываем если уже есть (приоритет у первого слоя)
                if kn in attr_cache:
                    continue

                attr_cache[kn] = {}
                for field_name in FIELDS_TO_SUPPLEMENT:
                    if field_name in extract_field_names:
                        value = feature.attribute(field_name)
                        # Сохраняем только непустые значения
                        if value is not None and str(value).strip() not in ['', '-', 'NULL']:
                            attr_cache[kn][field_name] = value

            log_debug(f"Fsm_2_1_8: Из {extract_layer_name} загружено {len(attr_cache)} записей в кэш атрибутов")

        if not attr_cache:
            log_debug("Fsm_2_1_8: Кэш атрибутов пуст - нет данных в слоях выписок")
            return 0

        # Определяем индексы полей в целевом слое
        target_field_indices = {}
        for field_name in FIELDS_TO_SUPPLEMENT:
            idx = layer.fields().indexOf(field_name)
            if idx != -1:
                target_field_indices[field_name] = idx

        if not target_field_indices:
            log_debug("Fsm_2_1_8: Нет полей для дополнения в слое выборки")
            return 0

        # Дополнить атрибуты в слое выборки
        supplemented_count = 0
        layer.startEditing()

        for feature in layer.getFeatures():
            kn = feature.attribute(kn_field_idx)
            if not kn or kn not in attr_cache:
                continue

            cache_data = attr_cache[kn]
            feature_updated = False

            for field_name, field_idx in target_field_indices.items():
                if field_name not in cache_data:
                    continue

                current_value = feature.attribute(field_idx)
                # Дополняем только если текущее значение пустое
                if current_value is None or str(current_value).strip() in ['', '-', 'Сведения отсутствуют', 'Категория не установлена']:
                    layer.changeAttributeValue(feature.id(), field_idx, cache_data[field_name])
                    feature_updated = True

            if feature_updated:
                supplemented_count += 1

        layer.commitChanges()

        if supplemented_count > 0:
            log_info(f"Fsm_2_1_8: Дополнены атрибуты для {supplemented_count} объектов из выписок")
        else:
            log_debug("Fsm_2_1_8: Нет объектов для дополнения атрибутов")

        return supplemented_count

    def _remove_duplicates_by_cadnum(self, layer: QgsVectorLayer) -> int:
        """
        Удаление дублей по кадастровому номеру из слоя

        Оставляет только первую найденную запись для каждого уникального КН.
        Удаляет все последующие дубли.

        Args:
            layer: Слой для дедупликации

        Returns:
            int: Количество удалённых дублей
        """
        # Находим поле кадастрового номера
        cadnum_field = None
        for possible_name in ['cad_num', 'cad_number', 'cadastral_number', 'КН']:
            if layer.fields().indexOf(possible_name) != -1:
                cadnum_field = possible_name
                break

        if not cadnum_field:
            log_warning(f"Fsm_2_1_8: Поле кадастрового номера не найдено в слое {layer.name()}, дедупликация пропущена")
            return 0

        # Собираем уникальные кадастровые номера и ID дублей
        seen_cadnums = set()
        duplicate_ids = []

        for feature in layer.getFeatures():
            cadnum = feature[cadnum_field]

            if not cadnum or cadnum == '' or cadnum == '-':
                continue

            if cadnum in seen_cadnums:
                # Это дубль - добавляем ID для удаления
                duplicate_ids.append(feature.id())
            else:
                # Первая встреча этого КН
                seen_cadnums.add(cadnum)

        # Удаляем дубли
        if duplicate_ids:
            layer.startEditing()
            layer.deleteFeatures(duplicate_ids)
            layer.commitChanges()

            log_info(f"Fsm_2_1_8: Удалено дублей из {layer.name()}: {len(duplicate_ids)} (уникальных КН: {len(seen_cadnums)})")
            return len(duplicate_ids)
        else:
            log_info(f"Fsm_2_1_8: Дублей не найдено в {layer.name()} (всего объектов: {layer.featureCount()})")
            return 0

