# -*- coding: utf-8 -*-
"""
Msm_25_0 - Общие утилиты для модулей распределения M_25

Содержит функции создания слоёв и сохранения в GeoPackage,
используемые в Msm_25_3 (LayerDistributor).

Вынесено из Fsm_2_3_1 и Fsm_2_3_2 согласно DRY principle.
"""

import os
from typing import Optional

from qgis.core import (
    QgsProject, QgsVectorLayer, QgsVectorFileWriter,
    QgsWkbTypes, QgsCoordinateReferenceSystem
)

from Daman_QGIS.utils import log_info, log_warning, log_error
from Daman_QGIS.managers import get_project_structure_manager


def create_memory_layer(
    source_layer: QgsVectorLayer,
    layer_name: str,
    target_crs: Optional[QgsCoordinateReferenceSystem] = None
) -> Optional[QgsVectorLayer]:
    """
    Создать memory-слой с такой же структурой как исходный

    Args:
        source_layer: Исходный слой (для копирования структуры полей)
        layer_name: Имя нового слоя
        target_crs: Целевая СК (если None, берётся из source_layer)

    Returns:
        QgsVectorLayer: Новый memory-слой или None при ошибке
    """
    try:
        # Определяем тип геометрии
        geom_type = source_layer.wkbType()

        # Убираем Z и M если есть
        if QgsWkbTypes.hasZ(geom_type):
            geom_type = QgsWkbTypes.dropZ(geom_type)
        if QgsWkbTypes.hasM(geom_type):
            geom_type = QgsWkbTypes.dropM(geom_type)

        # Определяем строковое представление типа геометрии
        if QgsWkbTypes.geometryType(geom_type) == QgsWkbTypes.PolygonGeometry:
            if QgsWkbTypes.isMultiType(geom_type):
                geom_string = "MultiPolygon"
            else:
                geom_string = "Polygon"
        else:
            geom_string = QgsWkbTypes.displayString(geom_type)

        # Определяем СК
        crs = target_crs if target_crs else source_layer.crs()

        # Создаём URI для memory layer
        uri = f"{geom_string}?crs={crs.authid()}"
        new_layer = QgsVectorLayer(uri, layer_name, "memory")

        if not new_layer.isValid():
            log_error(f"Msm_25_0: Не удалось создать слой {layer_name}")
            return None

        # Копируем структуру полей
        new_layer.startEditing()
        for field in source_layer.fields():
            new_layer.addAttribute(field)

        log_info(f"Msm_25_0: Создан memory-слой {layer_name}")
        return new_layer

    except Exception as e:
        log_error(f"Msm_25_0: Ошибка создания слоя {layer_name}: {e}")
        return None


def save_layer_to_gpkg(layer: QgsVectorLayer) -> bool:
    """
    Сохранить слой в GeoPackage проекта

    Args:
        layer: Слой для сохранения

    Returns:
        bool: True если успешно
    """
    try:
        project = QgsProject.instance()
        project_path = project.homePath()

        # Используем M_19 для получения пути к GPKG
        structure_manager = get_project_structure_manager()
        if project_path:
            structure_manager.project_root = project_path
        gpkg_path = structure_manager.get_gpkg_path(create=False)

        if not gpkg_path or not os.path.exists(gpkg_path):
            log_warning(f"Msm_25_0: GeoPackage не найден, слой {layer.name()} останется в памяти")
            return False

        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GPKG"
        options.layerName = layer.name()
        options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer

        error = QgsVectorFileWriter.writeAsVectorFormatV3(
            layer,
            gpkg_path,
            QgsProject.instance().transformContext(),
            options
        )

        if error[0] == QgsVectorFileWriter.NoError:
            log_info(f"Msm_25_0: Слой {layer.name()} сохранён в GeoPackage")
            return True
        else:
            log_warning(f"Msm_25_0: Ошибка сохранения {layer.name()} в GeoPackage - {error[1]}")
            return False

    except Exception as e:
        log_error(f"Msm_25_0: Ошибка сохранения слоя: {e}")
        return False


def add_layer_to_project(
    layer: QgsVectorLayer,
    layer_manager=None,
    gpkg_path: Optional[str] = None
) -> Optional[QgsVectorLayer]:
    """
    Добавить слой в проект (из GPKG если возможно)

    Args:
        layer: Слой для добавления
        layer_manager: LayerManager (опционально)
        gpkg_path: Путь к GeoPackage (опционально)

    Returns:
        QgsVectorLayer: Добавленный слой или None
    """
    try:
        project = QgsProject.instance()

        # Если есть gpkg_path - загружаем из него
        if gpkg_path and os.path.exists(gpkg_path):
            layer_name = layer.name()

            # Удаляем memory-версию
            project.removeMapLayer(layer.id())

            # Загружаем из GPKG
            gpkg_layer = QgsVectorLayer(
                f"{gpkg_path}|layername={layer_name}",
                layer_name,
                "ogr"
            )

            if gpkg_layer.isValid():
                if layer_manager:
                    layer_manager.add_layer(
                        gpkg_layer,
                        make_readonly=False,
                        auto_number=False,
                        check_precision=False
                    )
                else:
                    project.addMapLayer(gpkg_layer)

                log_info(f"Msm_25_0: Слой {layer_name} добавлен из GeoPackage")
                return gpkg_layer
            else:
                log_warning(f"Msm_25_0: Не удалось загрузить из GeoPackage: {layer_name}")

        # Fallback - добавляем memory-слой напрямую
        if layer_manager:
            layer_manager.add_layer(
                layer,
                make_readonly=False,
                auto_number=False,
                check_precision=False
            )
        else:
            project.addMapLayer(layer)

        return layer

    except Exception as e:
        log_error(f"Msm_25_0: Ошибка добавления слоя: {e}")
        return None


def get_gpkg_path() -> Optional[str]:
    """
    Получить путь к GeoPackage проекта

    Returns:
        str: Путь к GPKG или None
    """
    project = QgsProject.instance()
    project_path = project.homePath()

    if not project_path:
        return None

    structure_manager = get_project_structure_manager()
    structure_manager.project_root = project_path
    return structure_manager.get_gpkg_path(create=False)
