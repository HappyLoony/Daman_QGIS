# -*- coding: utf-8 -*-
"""
Fsm_2_1_10: Выборка ЗОУИТ в границах работ

Собирает объекты из ВСЕХ загруженных слоёв ЗОУИТ (Le_1_2_5_*)
в один итоговый слой Le_1_9_5_1_ЕГРН_ЗОУИТ_Перечень.

Отличия от других выборок:
- N исходных слоёв (вся группа Le_1_2_5_*) → 1 итоговый слой
- 4 захардкоженных поля: Слой, reg_numb_border, type_zone, name_by_doc
- Без буфера (только exact boundaries), хотя ЗОУИТ грузятся по 500м
"""

from typing import Optional, List, Callable

from qgis.PyQt.QtCore import QMetaType
from qgis.core import (
    QgsVectorLayer, QgsGeometry, QgsFeature, QgsField,
    QgsProject, QgsWkbTypes
)

from Daman_QGIS.constants import (
    LAYER_ZOUIT_PREFIX, LAYER_SELECTION_ZOUIT,
    MAX_FIELD_LEN, BOUNDARY_INNER_BUFFER_M, BUFFER_SEGMENTS
)
from Daman_QGIS.utils import log_info, log_warning, log_error
from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_2_13_selection.Fsm_1_2_13_4_geometry_processor import Fsm_2_1_5_GeometryProcessor
from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_2_13_selection.Fsm_1_2_13_2_layer_builder import Fsm_2_1_6_LayerBuilder
from Daman_QGIS.managers import CoordinatePrecisionManager


# Поля итогового слоя ЗОУИТ (захардкожены — малый объём, стабильная структура)
ZOUIT_RESULT_FIELDS = [
    ("Слой", QMetaType.Type.QString),
    ("reg_numb_border", QMetaType.Type.QString),
    ("type_zone", QMetaType.Type.QString),
    ("name_by_doc", QMetaType.Type.QString),
]


class Fsm_2_1_10_ZouitSelection:
    """Выборка ЗОУИТ из всех загруженных слоёв в один перечень"""

    def __init__(self, iface, plugin_dir: str, gpkg_path: str):
        """
        Args:
            iface: QGIS interface
            plugin_dir: Путь к директории плагина
            gpkg_path: Путь к project.gpkg
        """
        self.iface = iface
        self.gpkg_path = gpkg_path
        self.geo_processor = Fsm_2_1_5_GeometryProcessor()
        self.layer_builder = Fsm_2_1_6_LayerBuilder(plugin_dir)

    def find_zouit_layers(self) -> List[QgsVectorLayer]:
        """Найти все загруженные слои ЗОУИТ (Le_1_2_5_*) в проекте

        Returns:
            Список слоёв ЗОУИТ
        """
        zouit_layers = []
        for layer in QgsProject.instance().mapLayers().values():
            if isinstance(layer, QgsVectorLayer) and layer.name().startswith(LAYER_ZOUIT_PREFIX):
                zouit_layers.append(layer)

        return zouit_layers

    def perform(self, boundaries_exact: QgsVectorLayer,
                progress_callback: Optional[Callable[[int, int], None]] = None
                ) -> Optional[QgsVectorLayer]:
        """Выполнить выборку ЗОУИТ из всех Le_1_2_5_* слоёв по exact boundaries

        Args:
            boundaries_exact: Слой точных границ работ (L_1_1_1)
            progress_callback: Callback прогресса (checked, total)

        Returns:
            QgsVectorLayer сохранённый в GeoPackage, или None если нет объектов
        """
        try:
            log_info("Fsm_2_1_10: Запуск выборки ЗОУИТ")

            # Находим все ЗОУИТ слои
            zouit_layers = self.find_zouit_layers()
            if not zouit_layers:
                log_info("Fsm_2_1_10: Слои ЗОУИТ (Le_1_2_5_*) не найдены в проекте")
                return None

            log_info(f"Fsm_2_1_10: Найдено {len(zouit_layers)} слоёв ЗОУИТ")

            # Получаем геометрию границ
            boundaries_geom = self.geo_processor.get_boundaries_geometry(boundaries_exact)
            if not boundaries_geom:
                raise ValueError(f"Не удалось получить геометрию из слоя '{boundaries_exact.name()}'")

            # Создаём итоговый слой с 4 полями
            project_crs = QgsProject.instance().crs()
            result_layer = QgsVectorLayer(
                f"MultiPolygon?crs={project_crs.authid()}",
                LAYER_SELECTION_ZOUIT,
                "memory"
            )
            if not result_layer.isValid():
                raise ValueError(f"Не удалось создать memory слой {LAYER_SELECTION_ZOUIT}")

            result_layer.startEditing()
            for field_name, field_type in ZOUIT_RESULT_FIELDS:
                result_layer.addAttribute(QgsField(field_name, field_type, len=MAX_FIELD_LEN))
            result_layer.commitChanges()

            # Подсчитаем общее число features для прогресса
            total_features = sum(layer.featureCount() for layer in zouit_layers)
            checked_count = 0
            selected_count = 0

            result_layer.startEditing()

            for source_layer in zouit_layers:
                source_name = source_layer.name()

                # Трансформации СК (source → project)
                transform_to_project, transform_for_intersection = \
                    self.geo_processor.create_coordinate_transforms(source_layer, boundaries_exact)

                for feature in source_layer.getFeatures():
                    checked_count += 1
                    if progress_callback and checked_count % 50 == 0:
                        progress_callback(checked_count, total_features)

                    geom = feature.geometry()
                    if not geom or geom.isNull():
                        continue

                    # Трансформация и округление геометрии
                    final_geom, test_geom = self._process_feature_geometry(
                        geom, transform_to_project, transform_for_intersection
                    )

                    # Проверка пересечения с exact boundaries
                    if test_geom.intersects(boundaries_geom):
                        new_feature = QgsFeature(result_layer.fields())
                        new_feature.setGeometry(QgsGeometry(final_geom))

                        # Маппинг 4 полей
                        new_feature.setAttribute("Слой", source_name)
                        new_feature.setAttribute("reg_numb_border", feature.attribute("reg_numb_border"))
                        new_feature.setAttribute("type_zone", feature.attribute("type_zone"))
                        new_feature.setAttribute("name_by_doc", feature.attribute("name_by_doc"))

                        result_layer.addFeature(new_feature)
                        selected_count += 1

            result_layer.commitChanges()

            log_info(
                f"Fsm_2_1_10: Проверено {checked_count} объектов из {len(zouit_layers)} слоёв, "
                f"отобрано {selected_count}"
            )

            if selected_count == 0:
                log_info("Fsm_2_1_10: Нет ЗОУИТ объектов в границах работ")
                return None

            # Повторная проверка после округления (-2см буфер)
            boundaries_geom_minus2cm = QgsGeometry(boundaries_geom)
            boundaries_geom_minus2cm = boundaries_geom_minus2cm.buffer(BOUNDARY_INNER_BUFFER_M, BUFFER_SEGMENTS)
            if boundaries_geom_minus2cm and not boundaries_geom_minus2cm.isNull():
                removed = self.geo_processor.recheck_intersection_after_rounding(
                    result_layer, boundaries_geom_minus2cm
                )
                selected_count = result_layer.featureCount()
                log_info(f"Fsm_2_1_10: После повторной проверки: {selected_count} объектов (удалено {removed})")

            if result_layer.featureCount() == 0:
                log_info("Fsm_2_1_10: Слой пуст после повторной проверки")
                return None

            # Сохраняем в GeoPackage
            final_layer = self.layer_builder.save_layer_to_gpkg(
                result_layer, LAYER_SELECTION_ZOUIT, self.gpkg_path
            )

            if final_layer:
                log_info(f"Fsm_2_1_10: Итого: {final_layer.featureCount()} ЗОУИТ объектов в перечне")

            return final_layer

        except Exception as e:
            log_error(f"Fsm_2_1_10: Ошибка выборки ЗОУИТ: {str(e)}")
            return None

    @staticmethod
    def _process_feature_geometry(geom, transform_to_project, transform_for_intersection):
        """Обработка геометрии: трансформация, округление, Multi-тип

        Args:
            geom: Исходная геометрия
            transform_to_project: Трансформер в СК проекта (или None)
            transform_for_intersection: Трансформер для проверки пересечения (или None)

        Returns:
            tuple: (final_geom, test_geom)
        """
        final_geom = QgsGeometry(geom)
        if transform_to_project:
            final_geom.transform(transform_to_project)

        final_geom = CoordinatePrecisionManager._round_geometry(final_geom)

        if not QgsWkbTypes.isMultiType(final_geom.wkbType()):
            final_geom = QgsGeometry.fromMultiPolygonXY([final_geom.asPolygon()])

        test_geom = QgsGeometry(geom)
        if transform_for_intersection:
            test_geom.transform(transform_for_intersection)

        return final_geom, test_geom
