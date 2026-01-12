# -*- coding: utf-8 -*-
"""
Субмодуль обработки границ для выборки бюджета
Преобразует полилинии в полигон с буфером
"""

import os
import processing
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsMessageLog, Qgis,
    QgsVectorFileWriter, QgsCoordinateTransformContext,
    QgsGeometry, QgsRectangle, QgsPointXY,
    QgsCoordinateTransform, QgsCoordinateReferenceSystem
)
from Daman_QGIS.utils import log_info


class BoundariesProcessor:
    """Обработчик границ для выборки"""
    
    def __init__(self, iface, project_manager, layer_manager):
        """Инициализация обработчика"""
        self.iface = iface
        self.project = QgsProject.instance()
        self.project_manager = project_manager
        self.layer_manager = layer_manager
    def process_boundaries(self):
        """Получение слоя границ работ для F_1_3_Бюджет

        Для F_1_3 используется L_1_1_1_Границы_работ БЕЗ буфера.
        L_1_1_2 (с буфером 10м) используется только в F_1_2.

        Returns:
            QgsVectorLayer: Слой L_1_1_1_Границы_работ или None
        """
        # Получаем слой L_1_1_1_Границы_работ
        boundaries_layer = None
        for layer in self.project.mapLayers().values():
            if layer.name() == "L_1_1_1_Границы_работ":
                boundaries_layer = layer
                break

        if not boundaries_layer:
            raise ValueError("Не найден слой L_1_1_1_Границы_работ")

        log_info("Fsm_1_3_1: Используется существующий слой L_1_1_1_Границы_работ")
        return boundaries_layer
    
    def _check_existing_layer(self):
        """Проверка наличия существующего слоя L_1_1_2_Границы_работ_10_м
        
        Returns:
            QgsVectorLayer: Существующий слой или None
        """
        layer_name = "L_1_1_2_Границы_работ_10_м"
        
        # Проверяем есть ли слой в проекте
        for layer in self.project.mapLayers().values():
            if layer.name() == layer_name:
                return layer
        
        # Проверяем в GeoPackage
        if not self.project_manager or not self.project_manager.project_db:
            return None
            
        gpkg_path = self.project_manager.project_db.gpkg_path
        if not gpkg_path:
            return None
        
        # Пытаемся загрузить слой
        layer = QgsVectorLayer(
            f"{gpkg_path}|layername={layer_name}",
            layer_name,
            "ogr"
        )
        
        if layer.isValid():
            # Добавляем через layer_manager
            if self.layer_manager:
                layer.setName(layer_name)
                self.layer_manager.add_layer(layer, make_readonly=False, auto_number=False, check_precision=False)
            else:
                self.project.addMapLayer(layer)
            return layer
        
        return None
    def _save_to_geopackage(self, layer):
        """Сохранение слоя в project.gpkg через project_manager

        Args:
            layer: Временный слой для сохранения

        Returns:
            QgsVectorLayer: Сохраненный слой или None
        """
        if not self.project_manager or not self.project_manager.project_db:
            raise ValueError("ProjectManager не инициализирован")
        
        gpkg_path = self.project_manager.project_db.gpkg_path
        if not gpkg_path:
            raise ValueError("Путь к GeoPackage не найден")

        layer_name = "L_1_1_2_Границы_работ_10_м"

        # Настройки сохранения
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GPKG"
        options.layerName = layer_name

        if os.path.exists(gpkg_path):
            options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer
        else:
            options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteFile

        # Сохраняем
        error = QgsVectorFileWriter.writeAsVectorFormatV3(
            layer,
            gpkg_path,
            QgsCoordinateTransformContext(),
            options
        )

        if error[0] == QgsVectorFileWriter.NoError:
            # Загружаем сохраненный слой
            saved_layer = QgsVectorLayer(
                f"{gpkg_path}|layername={layer_name}",
                layer_name,
                "ogr"
            )

            if saved_layer.isValid():
                # Добавляем через layer_manager с применением стиля
                if self.layer_manager:
                    saved_layer.setName(layer_name)
                    self.layer_manager.add_layer(saved_layer, make_readonly=False, auto_number=False, check_precision=False)
                else:
                    self.project.addMapLayer(saved_layer)

                log_info(f"Fsm_1_3_1: Слой сохранен в {gpkg_path}")

                return saved_layer
        else:
            raise ValueError(f"Ошибка сохранения - {error[1]}")
    def get_boundaries_geometry_for_api(self, boundaries_layer):
        """Получение геометрии границ для API в формате GeoJSON

        Args:
            boundaries_layer: Слой с границами

        Returns:
            dict: Геометрия в формате GeoJSON (WGS84)
        """
        if not boundaries_layer or not boundaries_layer.isValid():
            return None

        # Получаем extent слоя
        extent = boundaries_layer.extent()

        # Трансформируем в WGS84 для API
        crs_src = boundaries_layer.crs()
        crs_dest = QgsCoordinateReferenceSystem('EPSG:4326')
        transform = QgsCoordinateTransform(crs_src, crs_dest, self.project)

        # Создаем координаты прямоугольника
        coords = [
            transform.transform(QgsPointXY(extent.xMinimum(), extent.yMinimum())),
            transform.transform(QgsPointXY(extent.xMaximum(), extent.yMinimum())),
            transform.transform(QgsPointXY(extent.xMaximum(), extent.yMaximum())),
            transform.transform(QgsPointXY(extent.xMinimum(), extent.yMaximum())),
            transform.transform(QgsPointXY(extent.xMinimum(), extent.yMinimum()))
        ]

        # Формируем GeoJSON
        return {
            "type": "Polygon",
            "coordinates": [[[pt.x(), pt.y()] for pt in coords]]
        }
