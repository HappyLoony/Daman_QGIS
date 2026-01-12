# -*- coding: utf-8 -*-
"""
Модуль экспорта в MapInfo TAB
Часть инструмента 0_5_Графика к запросу
Обертка над TabExporter из Tool_8
"""

import os
from qgis.core import (
    QgsProject, QgsMessageLog, Qgis,
    QgsCoordinateReferenceSystem,
    QgsVectorLayer, QgsField,
    QgsFeature, QgsGeometry, QgsWkbTypes
)
from qgis.PyQt.QtCore import QMetaType
from ..core.tab_exporter import TabExporter as BaseTabExporter
from Daman_QGIS.constants import PLUGIN_NAME
from Daman_QGIS.utils import log_info, log_warning, log_error


class TabExporter:
    """Обертка для TabExporter из Tool_8 с добавлением ID атрибута для Tool_0_5"""
    
    def __init__(self, iface):
        """Инициализация экспортера
        
        Args:
            iface: Интерфейс QGIS
        """
        self.iface = iface
        self.base_exporter = BaseTabExporter(iface)
    def export_to_tab(self, boundaries_layer, output_folder):
        """Экспорт слоя в MapInfo TAB формат с атрибутом ID

        Args:
            boundaries_layer: Слой с границами работ
            output_folder: Папка для сохранения файлов

        Returns:
            tuple: (success, error_msg)
        """
        # Получаем информацию о СК
        crs_short_name, _ = self.base_exporter.get_project_crs_info()

        # Создаем временный слой с атрибутом ID (специфично для Tool_0_5)
        temp_layer = self._create_layer_with_id(boundaries_layer)

        if not temp_layer:
            raise RuntimeError("Не удалось создать временный слой с атрибутами")

        # Используем базовый экспортер для экспорта в TAB
        # С конкретными именами файлов для Tool_0_5
        results = self.base_exporter.export_layers(
            [temp_layer],
            output_folder,
            filename_pattern=f"Границы работ_{crs_short_name.replace(' ', '_')}" if crs_short_name else "Границы работ",
            create_wgs84=True,  # Всегда создаем оба файла в Tool_0_5
            use_non_earth=True  # Используем Nonearth для МСК
        )

        if not results.get(temp_layer.name(), False):
            raise RuntimeError("Ошибка экспорта в TAB")

        log_info(f"Fsm_1_4_4: TAB файлы созданы в {output_folder}")

        return True, None

    
    def _create_layer_with_id(self, source_layer):
        """Создание временного слоя с атрибутом ID для каждого контура

        Преобразует полигоны в линии (границы) для экспорта в MapInfo TAB.

        Args:
            source_layer: Исходный слой

        Returns:
            QgsVectorLayer: Временный слой с атрибутами
        """
        try:
            # Определяем тип геометрии исходного слоя
            geom_type = source_layer.wkbType()
            is_polygon = QgsWkbTypes.geometryType(geom_type) == QgsWkbTypes.PolygonGeometry

            # Создаем временный слой в памяти (всегда LineString для границ)
            temp_layer = QgsVectorLayer(
                f"LineString?crs={source_layer.crs().authid()}",
                "temp_boundaries",
                "memory"
            )

            if not temp_layer.isValid():
                raise Exception("Не удалось создать временный слой")

            # Добавляем поле ID
            provider = temp_layer.dataProvider()
            # Используем новый API для QgsField
            provider.addAttributes([QgsField("ID", QMetaType.Type.Int)])
            temp_layer.updateFields()

            # Копируем объекты с добавлением ID
            features_to_add = []
            contour_id = 1

            for feature in source_layer.getFeatures():
                geom = feature.geometry()
                if not geom or geom.isEmpty():
                    continue

                # Если это полигон - извлекаем границу (convertToType)
                if is_polygon:
                    # Конвертируем полигон в линию (boundary)
                    boundary_geom = QgsGeometry(geom.constGet().boundary())

                    if boundary_geom.isEmpty():
                        log_warning(f"Fsm_1_4_4: Пустая граница для объекта ID={contour_id}")
                        continue

                    # Если результат MultiLineString - разбиваем на части
                    # МИГРАЦИЯ LINESTRING → MULTILINESTRING: упрощённый паттерн
                    parts = boundary_geom.asMultiPolyline() if boundary_geom.isMultipart() else [boundary_geom.asPolyline()]
                    for part in parts:
                        new_feature = QgsFeature()
                        new_geom = QgsGeometry.fromPolylineXY(part)
                        new_feature.setGeometry(new_geom)
                        new_feature.setAttributes([contour_id])
                        features_to_add.append(new_feature)
                        contour_id += 1
                else:
                    # Уже линия - копируем как есть
                    # МИГРАЦИЯ LINESTRING → MULTILINESTRING: упрощённый паттерн
                    parts = geom.asMultiPolyline() if geom.isMultipart() else [geom.asPolyline()]
                    for part in parts:
                        new_feature = QgsFeature()
                        new_geom = QgsGeometry.fromPolylineXY(part)
                        new_feature.setGeometry(new_geom)
                        new_feature.setAttributes([contour_id])
                        features_to_add.append(new_feature)
                        contour_id += 1

            # Добавляем объекты в слой
            provider.addFeatures(features_to_add)

            log_info(f"Fsm_1_4_4: Создан временный слой с {len(features_to_add)} контурами")

            return temp_layer

        except Exception as e:
            log_error(f"Fsm_1_4_4: Ошибка создания слоя с ID: {str(e)}")
            return None

