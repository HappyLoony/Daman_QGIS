# -*- coding: utf-8 -*-
"""
Fsm_1_1_4_4 - Создание слоёв и запись в GPKG (DATABASE-DRIVEN)

Поля создаются динамически из Base_field_mapping_EGRN.json через FieldMappingManager.
ZERO HARDCODE - все атрибуты загружаются из базы данных.

Геометрии импортируются "как есть" из XML без валидации/исправления.
Используется стандартный QgsVectorFileWriter.
"""

import os
from typing import List, Dict, Any, Optional
from qgis.core import (
    QgsVectorLayer, QgsFeature, QgsGeometry, QgsProject,
    QgsVectorFileWriter, QgsFields, QgsField, QgsCoordinateReferenceSystem,
    QgsCoordinateTransformContext, QgsWkbTypes, Qgis
)
from qgis.PyQt.QtCore import QVariant, QMetaType

from Daman_QGIS.utils import log_info, log_error, log_warning
from Daman_QGIS.constants import USE_FIELD_ALIASES, MAX_FIELD_LEN


def create_and_save_layer(features_data: List[Dict[str, Any]],
                          output_gpkg_path: str,
                          crs: Optional[QgsCoordinateReferenceSystem] = None,
                          field_mapper=None,
                          record_type: Optional[str] = None) -> bool:
    """
    Создание слоя из данных и сохранение в GPKG (DATABASE-DRIVEN)

    Args:
        features_data: Список словарей с данными фич
        output_gpkg_path: Путь к GPKG файлу
        crs: Система координат
        field_mapper: FieldMappingManager для создания полей (опционально)
        record_type: Тип записи для определения полей (опционально)

    Returns:
        True если успешно
    """
    if not features_data:
        return False

    # Определяем CRS
    if crs is None:
        project = QgsProject.instance()
        crs = project.crs() if project else QgsCoordinateReferenceSystem("EPSG:3857")

    # Имя слоя
    layer_name = "ЕГРН_выписки"

    # Определяем преобладающий тип геометрии из данных
    geom_type_counts = {'MultiPolygon': 0, 'MultiLineString': 0, 'MultiPoint': 0, 'NoGeometry': 0}

    for feat_data in features_data:
        if feat_data.get('geometry'):
            geom = feat_data['geometry']
            # Проверяем, что геометрия не пустая
            if geom and not geom.isEmpty():
                if hasattr(geom, 'type'):
                    geom_type = geom.type()  # Qgis.GeometryType: Point=0, Line=1, Polygon=2
                    if geom_type == Qgis.GeometryType.Point:
                        geom_type_counts['MultiPoint'] += 1
                    elif geom_type == Qgis.GeometryType.Line:
                        geom_type_counts['MultiLineString'] += 1
                    elif geom_type == Qgis.GeometryType.Polygon:
                        geom_type_counts['MultiPolygon'] += 1
                else:
                    geom_type_counts['NoGeometry'] += 1
            else:
                geom_type_counts['NoGeometry'] += 1
        else:
            geom_type_counts['NoGeometry'] += 1

    # Выбираем тип геометрии по большинству
    dominant_type = max(geom_type_counts, key=lambda k: geom_type_counts[k])
    layer_geom_type = dominant_type

    log_info(f"Fsm_1_1_4_4: Преобладающий тип геометрии: {dominant_type} ({geom_type_counts[dominant_type]} объектов)")

    # Определяем WKB тип геометрии для QgsVectorFileWriter
    # FIX: Используем *M типы для хранения M-координат (delta_geopoint)
    if layer_geom_type == 'MultiPolygon':
        wkb_type = QgsWkbTypes.MultiPolygonM
    elif layer_geom_type == 'MultiLineString':
        wkb_type = QgsWkbTypes.MultiLineStringM
    elif layer_geom_type == 'MultiPoint':
        wkb_type = QgsWkbTypes.MultiPointM
    else:
        wkb_type = QgsWkbTypes.NoGeometry

    # Создаем структуру полей ДИНАМИЧЕСКИ из FieldMappingManager
    if field_mapper and record_type:
        # ZERO HARDCODE - все поля из базы данных
        fields = field_mapper.create_fields_for_record_type(record_type)
        log_info(f"Fsm_1_1_4_4: Создано {len(fields)} полей для record_type='{record_type}'")
    else:
        # Fallback - минимальный набор полей (для обратной совместимости)
        log_warning("Fsm_1_1_4_4: FieldMappingManager не предоставлен, используется минимальный набор полей")
        fields = QgsFields()
        fields.append(QgsField("cad_number", QMetaType.Type.QString, len=50))
        fields.append(QgsField("included_objects", QMetaType.Type.QString, len=MAX_FIELD_LEN))

    # Сохраняем в GPKG через прямую запись (минуя memory layer)
    saved_layer = save_to_gpkg_direct(
        features_data,
        fields,
        layer_name,
        output_gpkg_path,
        crs,
        wkb_type,
        layer_geom_type
    )

    if not saved_layer:
        return False

    # Устанавливаем алиасы полей (если включено)
    if field_mapper and record_type:
        set_field_aliases(saved_layer, field_mapper, record_type)

    # Добавляем слой в проект
    QgsProject.instance().addMapLayer(saved_layer)
    feature_count = saved_layer.featureCount()

    log_info(f"Fsm_1_1_4_4: Слой '{layer_name}' добавлен: {feature_count} объектов")

    return True


def save_to_gpkg_direct(features_data: List[Dict[str, Any]],
                         fields: QgsFields,
                         layer_name: str,
                         gpkg_path: str,
                         crs: QgsCoordinateReferenceSystem,
                         wkb_type: int,
                         layer_geom_type: str) -> Optional[QgsVectorLayer]:
    """
    ПРЯМАЯ ЗАПИСЬ в GPKG минуя memory layer (геометрии "как есть", без валидации)

    Args:
        features_data: Список словарей с данными фич
        fields: Структура полей
        layer_name: Имя слоя
        gpkg_path: Путь к GPKG
        crs: Система координат
        wkb_type: Тип геометрии (QgsWkbTypes.*)
        layer_geom_type: Тип геометрии в виде строки

    Returns:
        QgsVectorLayer: Загруженный слой из GPKG или None
    """
    if not gpkg_path:
        log_warning("Fsm_1_1_4_4: Не указан путь к GPKG")
        return None

    try:
        # Настройки записи
        opts = QgsVectorFileWriter.SaveVectorOptions()
        opts.driverName = "GPKG"
        opts.layerName = layer_name
        opts.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer

        # Создаем writer для прямой записи
        writer = QgsVectorFileWriter.create(
            gpkg_path,
            fields,
            wkb_type,
            crs,
            QgsCoordinateTransformContext(),
            opts
        )

        if writer is None:
            log_error("Fsm_1_1_4_4: Ошибка создания QgsVectorFileWriter")
            return None

        # Получаем список всех полей
        field_names = [field.name() for field in fields]

        # Счетчики для отчета
        added_count = 0
        skipped_count = 0
        geometry_added = 0
        geometry_skipped = 0

        # Пишем фичи по одной (геометрии записываются "как есть" БЕЗ ВАЛИДАЦИИ)
        for feat_idx, data in enumerate(features_data):
            feat = QgsFeature(fields)
            cad_number = data.get('КН', 'UNKNOWN')  # Используем рабочее имя из маппинга

            # ДИНАМИЧЕСКАЯ запись ВСЕХ атрибутов из features_data
            for field_name in field_names:
                if field_name == 'record_type':
                    # Служебное поле - берем из data
                    feat.setAttribute(field_name, data.get('record_type'))
                elif field_name in data:
                    # Атрибут из маппинга - берем из data
                    feat.setAttribute(field_name, data.get(field_name))

            # Геометрия - проверяем ТИП для маршрутизации (БЕЗ валидации!)
            has_geometry = False
            if data.get('geometry'):
                geom = data['geometry']

                if geom and not geom.isEmpty():
                    # Определяем тип геометрии для проверки совместимости с типом слоя
                    geom_type = geom.type() if hasattr(geom, 'type') else None
                    feat_wkb_type: Optional[int] = geom.wkbType() if hasattr(geom, 'wkbType') else None

                    # Проверяем совместимость ТИПА (не валидность!)
                    is_compatible = False
                    if layer_geom_type == 'MultiPolygon' and geom_type == Qgis.GeometryType.Polygon:
                        is_compatible = True
                    elif layer_geom_type == 'MultiLineString' and geom_type == Qgis.GeometryType.Line:
                        is_compatible = True
                    elif layer_geom_type == 'MultiPoint' and geom_type == Qgis.GeometryType.Point:
                        is_compatible = True

                    if is_compatible:
                        # ВАЖНО: Геометрия записывается "как есть", БЕЗ валидации/исправления
                        feat.setGeometry(geom)
                        has_geometry = True
                        geometry_added += 1
                    else:
                        # Пропускаем несовместимый тип (иначе попадет не в тот слой)
                        skipped_count += 1
                        geometry_skipped += 1
                        log_warning(f"Fsm_1_1_4_4: {cad_number} пропущен (несовместимый тип геометрии)")
                        continue

            # Пишем напрямую в GPKG (с геометрией или БЕЗ - NULL geometry)
            write_result = writer.addFeature(feat)
            if write_result:
                added_count += 1
            else:
                skipped_count += 1
                log_error(f"Fsm_1_1_4_4: Ошибка записи {cad_number} в GPKG")
                # Проверяем ошибку writer
                if hasattr(writer, 'hasError') and writer.hasError():
                    error_msg = writer.errorMessage() if hasattr(writer, 'errorMessage') else 'Unknown error'
                    log_error(f"Fsm_1_1_4_4: Writer error для {cad_number}: {error_msg}")

        # Освобождаем writer (финализирует запись)
        del writer

        log_info(f"Fsm_1_1_4_4: Записано в GPKG: {added_count} объектов, пропущено: {skipped_count}")

        # Загружаем слой из GPKG
        saved_layer = QgsVectorLayer(
            f"{gpkg_path}|layername={layer_name}",
            layer_name,
            "ogr"
        )

        if not saved_layer.isValid():
            log_error(f"Fsm_1_1_4_4: Не удалось загрузить слой {layer_name} из GPKG")
            return None

        log_info(f"Fsm_1_1_4_4: Слой {layer_name} загружен из GPKG ({saved_layer.featureCount()} фич)")

        return saved_layer

    except Exception as e:
        log_error(f"Fsm_1_1_4_4: Ошибка: {e}")
        import traceback
        log_error(f"Fsm_1_1_4_4: {traceback.format_exc()}")
        return None


def save_to_gpkg(layer: QgsVectorLayer,
                layer_name: str,
                gpkg_path: str,
                crs: QgsCoordinateReferenceSystem) -> Optional[QgsVectorLayer]:
    """
    Сохранение слоя в GPKG через стандартный QgsVectorFileWriter
    (используется в layer_splitter для разделения по типам геометрий)

    Args:
        layer: Слой для сохранения
        layer_name: Имя слоя
        gpkg_path: Путь к GPKG
        crs: Система координат

    Returns:
        QgsVectorLayer: Загруженный слой из GPKG или None
    """
    if not gpkg_path:
        log_warning("Fsm_1_1_4_4: Не указан путь к GPKG")
        return None

    try:
        # Настройки записи (как в backup)
        opts = QgsVectorFileWriter.SaveVectorOptions()
        opts.driverName = "GPKG"
        opts.layerName = layer_name
        opts.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer

        # Записываем в GPKG через стандартный QgsVectorFileWriter
        writer_result = QgsVectorFileWriter.writeAsVectorFormatV3(
            layer, gpkg_path, QgsCoordinateTransformContext(), opts
        )

        if writer_result[0] != QgsVectorFileWriter.NoError:
            log_error(f"Fsm_1_1_4_4: Ошибка записи слоя {layer_name}: {writer_result[1]}")
            return None

        log_info(f"Fsm_1_1_4_4: Слой {layer_name} записан в GPKG ({layer.featureCount()} фич)")

        # Загружаем слой из GPKG
        saved_layer = QgsVectorLayer(
            f"{gpkg_path}|layername={layer_name}",
            layer_name,
            "ogr"
        )

        if not saved_layer.isValid():
            log_error(f"Fsm_1_1_4_4: Не удалось загрузить слой {layer_name} из GPKG")
            return None

        return saved_layer

    except Exception as e:
        log_error(f"Fsm_1_1_4_4: Ошибка: {e}")
        import traceback
        log_error(f"Fsm_1_1_4_4: {traceback.format_exc()}")
        return None


def set_field_aliases(layer: QgsVectorLayer, field_mapper, record_type: str) -> None:
    """
    Установка QGIS алиасов для полей слоя из Base_field_mapping_EGRN.json

    Использует full_name из field_mapper в качестве алиасов для полей.
    Алиасы отображаются в UI QGIS (Attribute Table, Feature Form, Identify Results),
    но не влияют на имена полей в данных.

    Args:
        layer: Слой для установки алиасов
        field_mapper: FieldMappingManager для получения full_name
        record_type: Тип записи для получения маппингов
    """
    if not USE_FIELD_ALIASES:
        return

    if not field_mapper or not record_type:
        log_warning("Fsm_1_1_4_4: Невозможно установить алиасы - отсутствует field_mapper или record_type")
        return

    if not layer or not layer.isValid():
        log_warning("Fsm_1_1_4_4: Невозможно установить алиасы - слой невалиден")
        return

    try:
        # Получаем маппинги для данного record_type
        mappings = field_mapper.get_fields_for_record_type(record_type)
        if not mappings:
            log_warning(f"Fsm_1_1_4_4: Нет маппингов для record_type='{record_type}'")
            return

        # Создаём словарь working_name -> full_name
        mappings_by_name = {m.get('working_name'): m for m in mappings if m.get('working_name')}

        # Счётчик установленных алиасов
        aliases_count = 0

        # Проходим по всем полям слоя
        for field_index, field in enumerate(layer.fields()):
            field_name = field.name()
            mapping = mappings_by_name.get(field_name)

            if mapping:
                full_name = mapping.get('full_name')
                if full_name and full_name.strip():
                    # Устанавливаем алиас
                    layer.setFieldAlias(field_index, full_name)
                    aliases_count += 1

        if aliases_count > 0:
            log_info(f"Fsm_1_1_4_4: Установлено {aliases_count} алиасов для '{layer.name()}'")

    except Exception as e:
        log_error(f"Fsm_1_1_4_4: Ошибка установки алиасов: {e}")
        import traceback
        log_error(f"Fsm_1_1_4_4: {traceback.format_exc()}")
