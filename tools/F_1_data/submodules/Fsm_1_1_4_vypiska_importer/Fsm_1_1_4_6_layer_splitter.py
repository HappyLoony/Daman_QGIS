# -*- coding: utf-8 -*-
"""
Fsm_1_1_4_6 - Разделение выписок по типам объектов и геометрии

Создаёт слои по структуре Base_layers.json:
- Le_1_6_1_Y_Выписки_ЗУ_geom (земельные участки)
- Le_1_6_2_Y_Выписки_ОКС_geom (объекты капитального строительства)
- Le_1_6_3_Y_Выписки_ЕЗ_geom (единое землепользование)
- Le_1_6_4_Y_Выписки_чзу_geom (части земельного участка)
"""

from collections import defaultdict
from typing import List, Dict, Any, Optional
from qgis.core import (
    QgsCoordinateReferenceSystem, QgsVectorLayer, QgsFeature, QgsFields,
    QgsField, QgsProject, QgsVectorFileWriter, QgsCoordinateTransformContext,
    QgsWkbTypes, QgsGeometry, QgsMultiPolygon
)
from qgis.PyQt.QtCore import QMetaType

from Daman_QGIS.utils import log_info, log_warning, log_error
from Daman_QGIS.constants import MAX_FIELD_LEN
from Daman_QGIS.managers import StyleManager
from .Fsm_1_1_4_4_layer_creator import set_field_aliases

# Служебные поля, которые НЕ записываются в GPKG
# ВАЖНО: 'fid' - PRIMARY KEY из GPKG, не копируется в атрибуты
RESERVED_FIELDS = {'record_type', 'geometry', 'included_objects', 'fid'}

# Маппинг типов записей на базовые слои (из Base_layers.json)
RECORD_TO_BASE_SUBLAYER = {
    'land_record': ('Le_1_6_1', 'ЗУ'),
    'unified_land_record': ('Le_1_6_3', 'ЕЗ'),
    'build_record': ('Le_1_6_2', 'ОКС'),
    'construction_record': ('Le_1_6_2', 'ОКС'),
    'object_under_construction_record': ('Le_1_6_2', 'ОКС'),
    'premises_record': ('Le_1_6_2', 'ОКС'),
    'car_parking_space_record': ('Le_1_6_2', 'ОКС'),
    'unified_real_estate_complex_record': ('Le_1_6_2', 'ОКС'),
    'enterprise_as_property_complex_record': ('Le_1_6_2', 'ОКС'),
    'object_part': ('Le_1_6_4', 'чзу')
}

# Маппинг типов геометрии на номер подслоя и суффикс (общий для ОКС, ЕЗ, чзу)
GEOM_TO_SUBLAYER_SUFFIX = {
    'MultiPolygon': ('2', 'poly'),
    'MultiLineString': ('1', 'line'),
    'NoGeometry': ('3', 'not')
}

# Специальный маппинг для ЗУ (нет линий, поэтому нумерация 1, 2)
GEOM_TO_SUBLAYER_SUFFIX_ZU = {
    'MultiPolygon': ('1', 'poly'),
    'NoGeometry': ('2', 'not')
}


def split_and_create_layers(features_data: List[Dict[str, Any]],
                            output_gpkg_path: str,
                            crs: QgsCoordinateReferenceSystem = None,
                            field_mapper=None,
                            dominant_record_type: str = 'land_record') -> Dict[str, Any]:
    """
    Разделение фич по типам объектов и геометрии, создание слоёв по Base_layers.json

    Args:
        features_data: Список словарей с данными фич
        output_gpkg_path: Путь к GPKG файлу
        crs: Система координат
        field_mapper: FieldMappingManager для создания структуры полей
        dominant_record_type: Преобладающий тип записи (для определения структуры полей)

    Returns:
        Dict с результатами импорта
    """
    if not features_data:
        return {
            'success': False,
            'layers': [],
            'message': 'Нет данных для импорта',
            'errors': []
        }

    # Группируем фичи по (record_type, geom_type)
    features_by_type_and_geom = defaultdict(list)

    for feat_data in features_data:
        record_type = feat_data.get('record_type', 'unknown')
        geom = feat_data.get('geometry')

        # Определяем тип геометрии
        if geom is None:
            geom_key = 'NoGeometry'
        else:
            if hasattr(geom, 'type'):
                geom_type = geom.type()  # QgsWkbTypes.GeometryType: 0=Point, 1=Line, 2=Polygon

                if geom_type == 2:  # Polygon
                    geom_key = 'MultiPolygon'
                elif geom_type == 1:  # LineString
                    geom_key = 'MultiLineString'
                elif geom_type == 0:  # Point
                    geom_key = 'MultiPoint'
                else:
                    geom_key = 'NoGeometry'
            else:
                geom_key = 'NoGeometry'

        # Ключ группировки: (record_type, geom_type)
        layer_key = (record_type, geom_key)
        features_by_type_and_geom[layer_key].append(feat_data)

    # Логируем статистику группировки
    log_info(f"Fsm_1_1_4_6: Группировка фич по (record_type, geom_type):")
    for (record_type, geom_key), features in sorted(features_by_type_and_geom.items()):
        log_info(f"  ({record_type}, {geom_key}): {len(features)} объектов")

    # Создаём слои для каждой комбинации (record_type, geom_type)
    created_layer_objects = []
    total_features = 0

    # Создаём StyleManager один раз для всех слоёв
    style_manager = StyleManager()

    for (record_type, geom_key), features in sorted(features_by_type_and_geom.items()):
        if not features:
            continue

        # Определяем имя слоя по Base_layers.json
        if record_type not in RECORD_TO_BASE_SUBLAYER:
            log_warning(f"Fsm_1_1_4_6: Неизвестный тип записи: {record_type}")
            continue

        base_name, object_type = RECORD_TO_BASE_SUBLAYER[record_type]

        # Для ЗУ (land_record) линии не бывают - пропускаем
        if record_type == 'land_record' and geom_key == 'MultiLineString':
            log_warning(f"Fsm_1_1_4_6: Пропуск линейной геометрии для land_record (ЗУ не могут быть линиями)")
            continue

        # Выбираем маппинг геометрии: специальный для ЗУ, общий для остальных
        if record_type == 'land_record':
            sublayer_info = GEOM_TO_SUBLAYER_SUFFIX_ZU.get(geom_key)
        else:
            sublayer_info = GEOM_TO_SUBLAYER_SUFFIX.get(geom_key)

        if not sublayer_info:
            log_warning(f"Fsm_1_1_4_6: Неизвестный тип геометрии: {geom_key} для {record_type}")
            continue

        sublayer_num, geom_name = sublayer_info
        # Формируем имя: Le_1_6_X_Y_Выписки_TYPE_geom
        layer_name = f"{base_name}_{sublayer_num}_Выписки_{object_type}_{geom_name}"

        # Определяем WKB тип геометрии
        # FIX: Используем *M типы для хранения M-координат (delta_geopoint)
        if geom_key == 'MultiPolygon':
            wkb_type = QgsWkbTypes.MultiPolygonM
        elif geom_key == 'MultiLineString':
            wkb_type = QgsWkbTypes.MultiLineStringM
        elif geom_key == 'MultiPoint':
            wkb_type = QgsWkbTypes.MultiPointM
        else:
            wkb_type = QgsWkbTypes.NoGeometry

        # Создаем структуру полей ДИНАМИЧЕСКИ из FieldMappingManager
        if field_mapper and record_type:
            # ZERO HARDCODE - все поля из базы данных
            fields = field_mapper.create_fields_for_record_type(record_type)
            log_info(f"Fsm_1_1_4_6: Создано {len(fields)} полей для record_type='{record_type}' (слой: {layer_name})")
        else:
            # Fallback - минимальный набор полей (для обратной совместимости)
            log_warning(f"Fsm_1_1_4_6: FieldMappingManager не предоставлен для '{layer_name}', используется минимальный набор полей")
            fields = QgsFields()
            fields.append(QgsField("cad_number", QMetaType.Type.QString, len=50))
            fields.append(QgsField("included_objects", QMetaType.Type.QString, len=MAX_FIELD_LEN))

        # ПРЯМАЯ ЗАПИСЬ В GPKG (минуя memory layer)
        saved_layer = _write_layer_direct_to_gpkg(
            features, fields, layer_name, output_gpkg_path, crs, wkb_type, geom_key,
            field_mapper, record_type
        )

        if saved_layer:
            # Проверяем - есть ли слой с таким именем в проекте
            project = QgsProject.instance()
            existing_layers = project.mapLayersByName(layer_name)

            # Если слой уже есть в проекте - удаляем старую версию
            if existing_layers:
                for old_layer in existing_layers:
                    project.removeMapLayer(old_layer)
                log_info(f"Fsm_1_1_4_6: Удалена старая версия слоя '{layer_name}' из проекта")

            # Добавляем обновлённый слой
            project.addMapLayer(saved_layer)

            # Применяем стиль из Base_layers.json
            style_applied = style_manager.apply_qgis_style(saved_layer, layer_name)
            if style_applied:
                log_info(f"Fsm_1_1_4_6: Стиль применён к слою '{layer_name}'")
            else:
                log_warning(f"Fsm_1_1_4_6: Не удалось применить стиль к слою '{layer_name}'")

            created_layer_objects.append(saved_layer)
            feature_count = saved_layer.featureCount()
            total_features += feature_count
            log_info(f"Fsm_1_1_4_6: Слой '{layer_name}' создан: {feature_count} объектов")
        else:
            log_warning(f"Fsm_1_1_4_6: Не удалось сохранить слой {layer_name}")

    if created_layer_objects:
        # FIX (2025-12-18): Дополнение выборки при импорте выписки ПОСЛЕ выборки
        # Если выборка уже существует - дополняем её атрибутами из новых выписок
        supplemented = supplement_selection_from_extracts(created_layer_objects)

        message = f'Создано слоёв: {len(created_layer_objects)}, объектов: {total_features}'
        if supplemented > 0:
            message += f', дополнено в выборке: {supplemented}'

        return {
            'success': True,
            'layers': created_layer_objects,
            'message': message,
            'errors': []
        }
    else:
        return {
            'success': False,
            'layers': [],
            'message': 'Не удалось создать ни одного слоя',
            'errors': []
        }


def _write_layer_direct_to_gpkg(features_data: List[Dict[str, Any]],
                                  fields: QgsFields,
                                  layer_name: str,
                                  gpkg_path: str,
                                  crs: QgsCoordinateReferenceSystem,
                                  wkb_type: int,
                                  layer_geom_type: str,
                                  field_mapper=None,
                                  record_type: Optional[str] = None) -> Optional[QgsVectorLayer]:
    """
    Запись в GPKG с автоматической проверкой и обновлением дублей по КН

    Алгоритм:
    1. Проверяет существование слоя в GPKG
    2. Если слой существует → обновление с дедупликацией по полю "КН"
    3. Если слоя нет → создание нового слоя

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
        log_warning("Fsm_1_1_4_6: Не указан путь к GPKG")
        return None

    # ============================================================
    # АВТОМАТИЧЕСКАЯ ПРОВЕРКА СУЩЕСТВОВАНИЯ СЛОЯ И ОБНОВЛЕНИЕ
    # ============================================================
    existing_layer = _check_and_load_existing_layer(gpkg_path, layer_name)

    if existing_layer:
        # Слой существует → обновляем с проверкой дублей по КН
        log_info(f"Fsm_1_1_4_6: Слой '{layer_name}' существует, обновление с проверкой дублей")
        return _update_layer_with_deduplication(
            existing_layer, features_data, fields, layer_name,
            gpkg_path, crs, wkb_type, layer_geom_type,
            field_mapper, record_type
        )

    # Слоя нет → создаём новый (существующая логика ниже)
    log_info(f"Fsm_1_1_4_6: Слой '{layer_name}' не существует, создание нового")

    try:
        # Создаем memory layer
        uri = "None" if layer_geom_type == "NoGeometry" else f"{layer_geom_type}?crs={crs.authid()}"
        layer = QgsVectorLayer(uri, layer_name, "memory")

        if not layer.isValid():
            log_error(f"Fsm_1_1_4_6: Ошибка создания memory layer для {layer_name}")
            return None

        # Добавляем поля
        prov = layer.dataProvider()
        prov.addAttributes(fields)
        layer.updateFields()

        # Получаем список имён полей для динамической записи атрибутов
        field_names = [field.name() for field in layer.fields()]

        # Счетчики
        added_count = 0
        skipped_count = 0

        # Создаем фичи
        features = []
        for i, data in enumerate(features_data, 1):
            cad_number = data.get('cad_number', 'UNKNOWN')

            # Геометрия - проверяем совместимость с типом слоя
            if data.get('geometry'):
                geom = data['geometry']

                if geom and not geom.isEmpty():
                    # Проверяем совместимость
                    is_compatible = False
                    if hasattr(geom, 'type'):
                        geom_type = geom.type()  # 0=Point, 1=Line, 2=Polygon

                        if layer_geom_type == 'MultiPolygon' and geom_type == 2:
                            is_compatible = True
                        elif layer_geom_type == 'MultiLineString' and geom_type == 1:
                            is_compatible = True
                        elif layer_geom_type == 'MultiPoint' and geom_type == 0:
                            is_compatible = True

                    if is_compatible:
                        # ВАЖНО: Геометрия ВСЕГДА MultiPolygon (UNIFIED PATTERN)
                        # Fsm_1_1_4_3_geometry.py гарантирует MultiPolygon через правильное построение
                        # Геометрия импортируется "как есть" из XML (координаты НЕ меняются)

                        # Обычная обработка - ДИНАМИЧЕСКАЯ запись ВСЕХ атрибутов
                        feat = QgsFeature(layer.fields())

                        # Записываем ВСЕ атрибуты из data (КРОМЕ служебных)
                        for field_name in field_names:
                            if field_name in data and field_name not in RESERVED_FIELDS:
                                feat.setAttribute(field_name, data.get(field_name))

                        # КРИТИЧНО: Создаём ГЛУБОКУЮ копию геометрии (как в reference code kd_on.py)
                        # ВАЖНО: Reference code делает feat.setGeometry(geom) напрямую и это работает
                        # потому что каждый вызов extract_geometry() создаёт НОВЫЙ QgsGeometry объект
                        # Однако для безопасности используем прямое присваивание (как в reference)
                        feat.setGeometry(geom)
                        features.append(feat)
                        added_count += 1
                    else:
                        skipped_count += 1
                        log_warning(f"Fsm_1_1_4_6: Несовместимая геометрия для {cad_number}: layer_type={layer_geom_type}, geom_type={geom_type}")
                else:
                    # Пустая геометрия - ДИНАМИЧЕСКАЯ запись ВСЕХ атрибутов
                    feat = QgsFeature(layer.fields())

                    # Записываем ВСЕ атрибуты из data (КРОМЕ служебных)
                    for field_name in field_names:
                        if field_name in data and field_name not in RESERVED_FIELDS:
                            feat.setAttribute(field_name, data.get(field_name))

                    features.append(feat)
                    added_count += 1
            else:
                # NULL geometry - ДИНАМИЧЕСКАЯ запись ВСЕХ атрибутов
                feat = QgsFeature(layer.fields())

                # Записываем ВСЕ атрибуты из data (КРОМЕ служебных)
                for field_name in field_names:
                    if field_name in data and field_name not in RESERVED_FIELDS:
                        feat.setAttribute(field_name, data.get(field_name))

                features.append(feat)
                added_count += 1

        # Добавляем фичи в memory layer
        prov.addFeatures(features)

        # Записываем в GPKG через writeAsVectorFormatV3
        opts = QgsVectorFileWriter.SaveVectorOptions()
        opts.driverName = "GPKG"
        opts.layerName = layer_name
        opts.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer
        opts.skipAttributeCreation = False

        # GPKG driver записывает геометрии "как есть" из Fsm_1_1_4_3_geometry.py
        opts.layerOptions = []
        opts.datasourceOptions = []

        writer_result = QgsVectorFileWriter.writeAsVectorFormatV3(
            layer, gpkg_path, QgsCoordinateTransformContext(), opts
        )

        if writer_result[0] != QgsVectorFileWriter.NoError:
            log_error(f"Fsm_1_1_4_6: Ошибка записи слоя {layer_name}: {writer_result[1]}")
            return None

        log_info(f"Fsm_1_1_4_6: {layer_name} - записано: {added_count}, пропущено: {skipped_count}")

        # Загружаем слой из GPKG
        saved_layer = QgsVectorLayer(
            f"{gpkg_path}|layername={layer_name}",
            layer_name,
            "ogr"
        )

        if not saved_layer.isValid():
            log_error(f"Fsm_1_1_4_6: Не удалось загрузить слой {layer_name} из GPKG")
            return None

        # Проверяем количество загруженных фич
        loaded_count = saved_layer.featureCount()
        if loaded_count != added_count:
            log_warning(f"Fsm_1_1_4_6: Несоответствие для {layer_name}: записано {added_count}, загружено {loaded_count}, потеряно {added_count - loaded_count}")

        # Устанавливаем алиасы полей (если включено)
        if field_mapper and record_type:
            set_field_aliases(saved_layer, field_mapper, record_type)

        return saved_layer

    except Exception as e:
        log_error(f"Fsm_1_1_4_6: Ошибка для {layer_name}: {e}")
        import traceback
        log_error(f"Fsm_1_1_4_6: {traceback.format_exc()}")
        return None


def _get_unique_key_fields(layer_name: str, layer_fields: QgsFields) -> List[str]:
    """
    Определение полей для дедупликации по имени слоя

    Автоматически определяет уникальный ключ для проверки дублей:
    - Основные объекты (ЗУ, ОКС, ЕЗ): ["КН"]
    - Части объектов (чзу): ["КН_родителя", "Номер_части"]

    Args:
        layer_name: Имя слоя (например, "Le_1_6_4_2_Выписки_чзу_poly")
        layer_fields: Структура полей слоя

    Returns:
        Список имён полей для составного ключа или пустой список
    """
    # Слои частей объектов (чзу = части земельных участков)
    if "чзу" in layer_name.lower() or "part" in layer_name.lower():
        # Проверяем наличие обоих полей
        if (layer_fields.indexOf("КН_родителя") != -1 and
            layer_fields.indexOf("Номер_части") != -1):
            return ["КН_родителя", "Номер_части"]

    # Основные слои (ЗУ, ОКС, ЕЗ) - используют КН
    if layer_fields.indexOf("КН") != -1:
        return ["КН"]

    # Дедупликация невозможна (нет известных ключевых полей)
    return []


def _check_and_load_existing_layer(gpkg_path: str, layer_name: str) -> Optional[QgsVectorLayer]:
    """
    Проверка существования слоя в GPKG и загрузка

    Args:
        gpkg_path: Путь к GPKG
        layer_name: Имя слоя

    Returns:
        QgsVectorLayer если слой существует и валиден, иначе None
    """
    import os
    if not os.path.exists(gpkg_path):
        return None

    # Пробуем загрузить слой
    layer = QgsVectorLayer(f"{gpkg_path}|layername={layer_name}", layer_name, "ogr")

    return layer if layer.isValid() else None


def _update_layer_with_deduplication(existing_layer: QgsVectorLayer,
                                      new_features_data: List[Dict[str, Any]],
                                      fields: QgsFields,
                                      layer_name: str,
                                      gpkg_path: str,
                                      crs: QgsCoordinateReferenceSystem,
                                      wkb_type: int,
                                      layer_geom_type: str,
                                      field_mapper=None,
                                      record_type: Optional[str] = None) -> Optional[QgsVectorLayer]:
    """
    Обновление слоя с автоматической проверкой и заменой дублей по ключевым полям

    Алгоритм:
    1. Загружаем все существующие features
    2. Определяем ключевые поля для дедупликации (КН или КН_родителя+Номер_части)
    3. Строим индекс: {composite_key: feature}
    4. Для каждого нового feature: если ключ существует → удаляем старый
    5. Объединяем: оставшиеся старые + все новые
    6. Перезаписываем слой в GPKG

    Args:
        existing_layer: Существующий слой
        new_features_data: Новые данные для добавления
        fields: Структура полей
        layer_name: Имя слоя
        gpkg_path: Путь к GPKG
        crs: Система координат
        wkb_type: Тип геометрии
        layer_geom_type: Тип геометрии в виде строки

    Returns:
        Обновлённый QgsVectorLayer или None
    """
    try:
        # DEBUG: Входные данные

        # 1. Читаем существующие features
        existing_features_list = list(existing_layer.getFeatures())

        # 2. Определяем ключевые поля для дедупликации
        key_fields = _get_unique_key_fields(layer_name, existing_layer.fields())

        if not key_fields:
            # Ключевые поля не найдены → добавляем БЕЗ проверки дублей
            log_warning(f"Fsm_1_1_4_6: Ключевые поля для дедупликации не найдены в слое '{layer_name}', добавление БЕЗ проверки дублей")
            return _append_without_check(
                existing_layer, new_features_data, layer_name,
                gpkg_path, crs, layer_geom_type
            )

        # Логируем используемые ключевые поля
        log_info(f"Fsm_1_1_4_6: Дедупликация слоя '{layer_name}' по полям: {', '.join(key_fields)}")

        # 3. Строим индекс существующих features по составному ключу
        existing_by_key = {}
        for feat in existing_features_list:
            # Формируем составной ключ из значений ключевых полей
            # ВАЖНО: явная проверка на None ДО преобразования в str()
            key_values = []
            for field in key_fields:
                val = feat.attribute(field)
                if val is None:
                    key_values.append('')
                else:
                    key_values.append(str(val))

            # Все части ключа должны быть не пустыми и не 'NULL'
            if all(val and val != 'NULL' for val in key_values):
                composite_key = "::".join(key_values)
                existing_by_key[composite_key] = feat

        # 4. Обрабатываем новые features: удаляем дубликаты из индекса
        # FIX (2025-12-17): При дедупликации сохраняем важные поля из старого feature
        # Проблема: обособленные участки ЕЗ создаются БЕЗ площади, но WFS содержит корректную площадь
        # Решение: если в новом feature поле пустое, а в старом заполнено - переносим значение
        PRESERVE_IF_EMPTY_FIELDS = ['Площадь', 'Значение']  # Площадь для ЗУ, Значение для ОКС

        duplicates_count = 0
        for new_data in new_features_data:
            # Формируем составной ключ из новых данных
            # ВАЖНО: явная проверка на None ДО преобразования в str()
            new_key_values = []
            for field in key_fields:
                val = new_data.get(field)
                if val is None:
                    new_key_values.append('')
                else:
                    new_key_values.append(str(val))

            # Все части ключа должны быть не пустыми и не 'NULL'
            if all(val and val != 'NULL' for val in new_key_values):
                new_composite_key = "::".join(new_key_values)

                if new_composite_key in existing_by_key:
                    # Дубликат найден → сохраняем важные поля из старого feature
                    old_feat = existing_by_key[new_composite_key]

                    for field_name in PRESERVE_IF_EMPTY_FIELDS:
                        # Проверяем: в новом feature поле пустое, в старом - заполнено
                        new_value = new_data.get(field_name)
                        is_new_empty = new_value is None or new_value == '' or new_value == '-'

                        if is_new_empty:
                            old_field_idx = existing_layer.fields().indexOf(field_name)
                            if old_field_idx != -1:
                                old_value = old_feat.attribute(field_name)
                                is_old_filled = old_value is not None and old_value != '' and old_value != '-'

                                if is_old_filled:
                                    # Переносим значение из старого feature в новый
                                    new_data[field_name] = old_value
                                    log_info(
                                        f"Fsm_1_1_4_6: Сохранено поле '{field_name}' из существующего feature: "
                                        f"'{old_value}' для КН={new_composite_key}"
                                    )

                    # Удаляем старый из индекса
                    del existing_by_key[new_composite_key]
                    duplicates_count += 1

        # Логируем найденные дубликаты
        if duplicates_count > 0:
            log_info(f"Fsm_1_1_4_6: Найдено и заменено {duplicates_count} дубликатов в слое '{layer_name}'")
        else:
            # КРИТИЧНО: Если дубликатов НЕТ, это реимпорт НОВЫХ данных (не апдейт существующих)
            # В этом случае мы должны ЗАМЕНИТЬ весь слой, а не добавлять к старым features
            if len(existing_features_list) > 0:
                log_warning(f"Fsm_1_1_4_6: Дубликатов не найдено, но existing_layer содержит {len(existing_features_list)} features")
                log_warning(f"Fsm_1_1_4_6: Это означает РЕИМПОРТ новых данных. Старые features будут УДАЛЕНЫ, новые добавлены.")
                # Очищаем индекс старых features - они все будут удалены
                existing_by_key.clear()

        # КРИТИЧНО: Проверяем remaining_old
        remaining_old_count = len(existing_by_key)

        # КРИТИЧНО: Проверяем КОНФЛИКТ КЛЮЧЕЙ между старыми и новыми
        if remaining_old_count > 0:
            # Собираем ключи из new_features_data
            new_keys = set()
            for data in new_features_data:
                new_key_values = [str(data.get(field, "")) for field in key_fields]
                if all(val and val != 'NULL' for val in new_key_values):
                    new_keys.add("::".join(new_key_values))

            # Собираем ключи из remaining_old
            old_keys = set(existing_by_key.keys())

            # Проверяем пересечение
            conflicting_keys = old_keys & new_keys
            if conflicting_keys:
                log_error(f"Fsm_1_1_4_6: КРИТИЧЕСКАЯ ПРОБЛЕМА - {len(conflicting_keys)} ключей присутствуют И в старых И в новых features!")
                log_error(f"Fsm_1_1_4_6: Примеры конфликтующих ключей (первые 5): {list(conflicting_keys)[:5]}")
                log_error(f"Fsm_1_1_4_6: Это означает что дедупликация НЕ СРАБОТАЛА! Старые features с этими ключами должны были быть удалены.")
                log_error(f"Fsm_1_1_4_6: Memory provider отклонит добавление features с дублирующимися ключами.")

        # 5. Создаём temp memory layer
        uri = "None" if layer_geom_type == "NoGeometry" else f"{layer_geom_type}?crs={crs.authid()}"
        temp_layer = QgsVectorLayer(uri, f"{layer_name}_temp", "memory")

        if not temp_layer.isValid():
            log_error(f"Fsm_1_1_4_6: Ошибка создания temp layer для '{layer_name}'")
            return None

        # Копируем структуру полей (ИСКЛЮЧАЯ 'fid' - PRIMARY KEY из GPKG)
        prov = temp_layer.dataProvider()

        # КРИТИЧНО: Создаём НОВЫЕ поля БЕЗ constraints
        # Memory provider отклоняет features если есть UNIQUE constraint!
        # Нельзя просто скопировать поля - нужно создать новые БЕЗ constraints
        fields_to_copy = []
        for field in existing_layer.fields():
            if field.name() != 'fid':
                # Создаём НОВОЕ поле с теми же параметрами, НО БЕЗ constraints
                # FIX (2025-11-21): Override String field length to 65535 (SQLite TEXT limit)
                # Старые GPKG слои могут иметь длину 10000, но реальные данные содержат 13000+ символов
                if field.type() == QMetaType.Type.QString:
                    new_field = QgsField(field.name(), field.type(), field.typeName(), 65535, field.precision())
                else:
                    new_field = QgsField(field.name(), field.type(), field.typeName(), field.length(), field.precision())
                # НЕ копируем constraints, alias и другие метаданные
                fields_to_copy.append(new_field)

        prov.addAttributes(fields_to_copy)
        temp_layer.updateFields()

        # DEBUG: Проверка структуры полей после updateFields()
        temp_field_names = [f.name() for f in temp_layer.fields()]
        existing_field_names = [f.name() for f in existing_layer.fields()]

        # 6. Добавляем оставшиеся старые features (без дубликатов)
        # КРИТИЧНО: Создаём НОВЫЕ QgsFeature объекты с глубокими копиями геометрий!
        # Старые features загружены из GPKG - их геометрии ссылаются на GPKG layer!
        # Memory provider отклонит их, если мы передадим GPKG-owned геометрии напрямую!
        remaining_old_source = list(existing_by_key.values())
        remaining_old = []

        for old_feat in remaining_old_source:
            # Создаём НОВЫЙ feature с полями temp_layer
            new_feat = QgsFeature(temp_layer.fields())
            new_feat.setId(-1)  # Критично: invalid ID для memory provider

            # Копируем атрибуты
            for field in temp_layer.fields():
                field_name = field.name()
                if field_name != 'fid':  # Пропускаем fid (GPKG primary key)
                    val = old_feat.attribute(field_name)
                    new_feat.setAttribute(field_name, val)

            # КРИТИЧНО: Создаём ГЛУБОКУЮ копию геометрии через WKB!
            # Геометрия old_feat принадлежит GPKG layer, а не memory provider!
            if old_feat.hasGeometry():
                old_geom = old_feat.geometry()
                new_geom = QgsGeometry()
                new_geom.fromWkb(old_geom.asWkb())
                new_feat.setGeometry(new_geom)

            remaining_old.append(new_feat)

        # DEBUG: Проверяем результат добавления старых features
        if remaining_old:
            old_result = prov.addFeatures(remaining_old)
            if isinstance(old_result, tuple):
                old_success, old_added = old_result
                log_info(f"Fsm_1_1_4_6 (_update_layer_with_deduplication): Добавление старых features: success={old_success}, добавлено={len(old_added)}")
            else:
                log_info(f"Fsm_1_1_4_6 (_update_layer_with_deduplication): Добавление старых features: result={old_result}")

        # 7. Добавляем все новые features (С ПРОВЕРКОЙ СОВМЕСТИМОСТИ ГЕОМЕТРИИ)
        field_names = [field.name() for field in temp_layer.fields()]
        new_features = []

        for idx, data in enumerate(new_features_data):
            # Проверяем совместимость геометрии с типом слоя
            geom = data.get('geometry')

            # ДИАГНОСТИКА отключена - вызов geom.constGet() создает Python wrapper
            # который может конфликтовать с memory provider для единичных features

            if geom and not geom.isEmpty():
                # Проверка совместимости типа геометрии
                is_compatible = False
                if hasattr(geom, 'type'):
                    geom_type = geom.type()  # 0=Point, 1=Line, 2=Polygon

                    if layer_geom_type == 'MultiPolygon' and geom_type == 2:
                        is_compatible = True
                    elif layer_geom_type == 'MultiLineString' and geom_type == 1:
                        is_compatible = True
                    elif layer_geom_type == 'MultiPoint' and geom_type == 0:
                        is_compatible = True

                if not is_compatible:
                    # Пропускаем несовместимую геометрию
                    # Универсальный идентификатор для логирования (основные объекты + части)
                    if 'КН' in data:
                        identifier = data['КН']
                    elif 'КН_родителя' in data:
                        part_num = data.get('Номер_части', '?')
                        identifier = f"{data['КН_родителя']}::часть_{part_num}"
                    else:
                        identifier = 'UNKNOWN'

                    log_warning(f"Fsm_1_1_4_6: Пропуск несовместимой геометрии для {identifier}: layer_type={layer_geom_type}, geom_type={geom_type}")
                    continue

            # Создаём feature
            feat = QgsFeature(temp_layer.fields())

            # КРИТИЧНО: Сбрасываем ID для memory provider
            # Memory provider отклоняет features с дублирующимися ID!
            # По умолчанию все features имеют ID=-9223372036854775808 (invalid ID)
            feat.setId(-1)

            # Записываем ВСЕ атрибуты из data (КРОМЕ служебных)
            for field_name in field_names:
                if field_name in data and field_name not in RESERVED_FIELDS:
                    feat.setAttribute(field_name, data.get(field_name))

            # КРИТИЧНО: Прямое setGeometry() как в reference code (kd_on.py)
            # НЕ используем WKB copy - reference code работает БЕЗ него!
            # Каждый вызов extract_geometry() создает НОВЫЙ QgsGeometry объект
            if geom:
                feat.setGeometry(geom)

            new_features.append(feat)

        # DEBUG: Проверка создания features
        skipped_count = len(new_features_data) - len(new_features)

        # DEBUG: Проверка валидности созданных features
        if new_features:
            # КРИТИЧНО: Используем new_features[1] вместо [0] для образца!
            # ПРИЧИНА: sample_feat используется для теста (копируется), но если тест НЕ удаляется
            # правильно, memory provider может "запомнить" C++ указатели и отклонить new_features[0]
            # в батче, т.к. new_features[0] == sample_feat (та же ссылка!)
            # Используя [1], мы гарантируем что [0] никогда не участвовал в тесте
            sample_index = min(1, len(new_features) - 1)  # Безопасно для списков из 1 элемента
            sample_feat = new_features[sample_index]
            sample_data = new_features_data[sample_index]

            # Проверяем какие поля заполнены
            filled_fields = []
            empty_fields = []
            for f in sample_feat.fields():
                val = sample_feat.attribute(f.name())
                if val is None or val == '':
                    empty_fields.append(f.name())
                else:
                    filled_fields.append(f.name())

            # КРИТИЧНО: НЕ вызываем sample_feat.geometry() - это создает extra Python wrapper!
            # Memory provider может отклонить feature если видит дополнительные references!

            # КРИТИЧНО: Проверяем наличие ВНУТРЕННИХ ДУБЛИКАТОВ среди new_features_data
            internal_duplicates = {}
            for i, data in enumerate(new_features_data):
                new_key_values = [str(data.get(field, "")) for field in key_fields]
                if all(val and val != 'NULL' for val in new_key_values):
                    composite_key = "::".join(new_key_values)
                    if composite_key in internal_duplicates:
                        internal_duplicates[composite_key].append(i)
                    else:
                        internal_duplicates[composite_key] = [i]
                else:
                    # Пустой ключ
                    empty_key = "::".join(new_key_values)
                    if empty_key in internal_duplicates:
                        internal_duplicates[empty_key].append(i)
                    else:
                        internal_duplicates[empty_key] = [i]

            # Проверяем пустые ключи
            empty_key_pattern = "::".join([""] * len(key_fields))
            if empty_key_pattern in internal_duplicates:
                log_error(f"Fsm_1_1_4_6: КРИТИЧЕСКАЯ ПРОБЛЕМА - {len(internal_duplicates[empty_key_pattern])} features имеют ПУСТЫЕ ключевые поля!")

            # КРИТИЧНО: Проверяем совпадение полей feature и temp_layer
            feat_field_names = [f.name() for f in sample_feat.fields()]
            temp_field_names = [f.name() for f in temp_layer.fields()]
            if feat_field_names != temp_field_names:
                log_error(f"Fsm_1_1_4_6: НЕСОВПАДЕНИЕ ПОЛЕЙ! feature fields: {feat_field_names}, temp_layer fields: {temp_field_names}")

        # Проверяем геометрию первого feature БЕЗ вызова .geometry()

        # КРИТИЧНО: Попробуем добавлять БАТЧАМИ для выявления проблемы
        BATCH_SIZE = 10
        total_added_successfully = 0
        failed_batches = []

        for i in range(0, len(new_features), BATCH_SIZE):
            batch = new_features[i:i + BATCH_SIZE]
            batch_num = i // BATCH_SIZE + 1
            total_batches = (len(new_features) + BATCH_SIZE - 1) // BATCH_SIZE

            # КРИТИЧНО: НЕ вызываем batch[0].geometry() - создает extra Python wrapper!

            # КРИТИЧНО: Количество features ДО добавления батча
            count_before = temp_layer.featureCount()

            # WORKAROUND: QGIS memory provider bug - addFeatures([single]) fails, но addFeature(single) works
            # Диагностика показала: land_record (1 feature) → FAIL, object_part (22 features) → SUCCESS
            # Единственная разница - batch size! Используем singular method для single features.
            if len(batch) == 1:
                single_success = prov.addFeature(batch[0])
                # Эмулируем формат возвращаемого значения addFeatures() для единообразия дальнейшей обработки
                batch_result = (True, [batch[0]]) if single_success else (False, [])
            else:
                # Обычная batch обработка для len(batch) > 1
                batch_result = prov.addFeatures(batch)

            # КРИТИЧНО: Количество features ПОСЛЕ добавления батча
            count_after = temp_layer.featureCount()
            actually_added = count_after - count_before

            if isinstance(batch_result, tuple):
                batch_success, batch_added = batch_result

                # КРИТИЧНО: Сравниваем reported vs actual
                reported_added = len(batch_added)

                if batch_success:
                    total_added_successfully += reported_added
                    if actually_added != reported_added:
                        log_warning(f"Fsm_1_1_4_6: Батч {batch_num}/{total_batches}: success=True, reported={reported_added}, ACTUAL={actually_added} (расхождение!)")
                else:
                    failed_batches.append((batch_num, len(batch), reported_added, actually_added))
                    log_warning(f"Fsm_1_1_4_6: Батч {batch_num}/{total_batches}: ОШИБКА! success=False, запрошено={len(batch)}, reported={reported_added}, ACTUAL={actually_added}")

                    # Диагностика первого неудачного батча
                    if len(failed_batches) == 1:
                        if hasattr(prov, 'error'):
                            batch_error = prov.error()
                            log_error(f"Fsm_1_1_4_6: Ошибка в батче {batch_num}: summary='{batch_error.summary()}', message='{batch_error.message()}'")

                        # Логируем первый feature из неудачного батча
                        if len(batch) > 0:
                            first_feat = batch[0]
                            kn_value = first_feat.attribute('КН') if first_feat.fields().indexOf('КН') >= 0 else first_feat.attribute('КН_родителя')
                            log_error(f"Fsm_1_1_4_6: Первый feature в неудачном батче: КН={kn_value}")

                            # Валидность геометрии
                            if first_feat.hasGeometry():
                                geom = first_feat.geometry()
                                if hasattr(geom, 'isGeosValid'):
                                    is_valid = geom.isGeosValid()
                                    log_error(f"  - isGeosValid: {is_valid}")
                                    if not is_valid and hasattr(geom, 'validateGeometry'):
                                        errors = geom.validateGeometry()
                                        log_error(f"  - Ошибок валидации: {len(errors)}")
                                        for err in errors[:3]:
                                            log_error(f"    - {err.what()}")

        log_info(f"Fsm_1_1_4_6 (_update_layer_with_deduplication): Итого добавлено успешно: {total_added_successfully} из {len(new_features)}")
        if failed_batches:
            log_error(f"Fsm_1_1_4_6: Неудачных батчей: {len(failed_batches)}")
            for batch_num, requested, reported, actual in failed_batches[:5]:
                log_error(f"  Батч {batch_num}: запрошено={requested}, reported={reported}, ACTUAL={actual}")

        # Проверка temp_layer после добавления
        temp_count = temp_layer.featureCount()

        # 8. Перезаписываем слой в GPKG
        opts = QgsVectorFileWriter.SaveVectorOptions()
        opts.driverName = "GPKG"
        opts.layerName = layer_name
        opts.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer
        opts.skipAttributeCreation = False
        opts.layerOptions = []
        opts.datasourceOptions = []

        writer_result = QgsVectorFileWriter.writeAsVectorFormatV3(
            temp_layer, gpkg_path, QgsCoordinateTransformContext(), opts
        )

        # Проверка результата записи
        if writer_result[0] != QgsVectorFileWriter.NoError:
            log_error(f"Fsm_1_1_4_6: Ошибка записи слоя '{layer_name}': код={writer_result[0]}, сообщение={writer_result[1]}")
            return None

        # 9. Загружаем обновлённый слой
        updated_layer = QgsVectorLayer(
            f"{gpkg_path}|layername={layer_name}",
            layer_name,
            "ogr"
        )

        if updated_layer.isValid():
            final_count = updated_layer.featureCount()
            log_info(f"Fsm_1_1_4_6: Слой '{layer_name}' обновлён ({final_count} features)")

            # Устанавливаем алиасы полей (если включено)
            if field_mapper and record_type:
                set_field_aliases(updated_layer, field_mapper, record_type)

            return updated_layer
        else:
            log_error(f"Fsm_1_1_4_6: Не удалось загрузить обновлённый слой '{layer_name}'")
            return None

    except Exception as e:
        log_error(f"Fsm_1_1_4_6: Ошибка обновления слоя '{layer_name}': {e}")
        import traceback
        log_error(f"Fsm_1_1_4_6: {traceback.format_exc()}")
        return None


def _append_without_check(existing_layer: QgsVectorLayer,
                          new_features_data: List[Dict[str, Any]],
                          layer_name: str,
                          gpkg_path: str,
                          crs: QgsCoordinateReferenceSystem,
                          layer_geom_type: str) -> Optional[QgsVectorLayer]:
    """
    Добавление features БЕЗ проверки дублей (fallback если поля КН нет)

    Args:
        existing_layer: Существующий слой
        new_features_data: Новые данные для добавления
        layer_name: Имя слоя
        gpkg_path: Путь к GPKG
        crs: Система координат
        layer_geom_type: Тип геометрии в виде строки

    Returns:
        Обновлённый QgsVectorLayer или None
    """
    try:
        # Читаем существующие features
        existing_features_list = list(existing_layer.getFeatures())

        # Создаём temp layer
        uri = "None" if layer_geom_type == "NoGeometry" else f"{layer_geom_type}?crs={crs.authid()}"
        temp_layer = QgsVectorLayer(uri, f"{layer_name}_temp", "memory")

        if not temp_layer.isValid():
            return None

        prov = temp_layer.dataProvider()
        prov.addAttributes(existing_layer.fields())
        temp_layer.updateFields()

        # Копируем старые features
        prov.addFeatures(existing_features_list)

        # Добавляем новые features (С ПРОВЕРКОЙ СОВМЕСТИМОСТИ ГЕОМЕТРИИ)
        field_names = [field.name() for field in temp_layer.fields()]
        new_features = []

        for data in new_features_data:
            # Проверяем совместимость геометрии с типом слоя
            geom = data.get('geometry')

            if geom and not geom.isEmpty():
                # Проверка совместимости типа геометрии
                is_compatible = False
                if hasattr(geom, 'type'):
                    geom_type = geom.type()  # 0=Point, 1=Line, 2=Polygon

                    if layer_geom_type == 'MultiPolygon' and geom_type == 2:
                        is_compatible = True
                    elif layer_geom_type == 'MultiLineString' and geom_type == 1:
                        is_compatible = True
                    elif layer_geom_type == 'MultiPoint' and geom_type == 0:
                        is_compatible = True

                if not is_compatible:
                    # Пропускаем несовместимую геометрию
                    log_warning(f"Fsm_1_1_4_6: Пропуск несовместимой геометрии при append: layer_type={layer_geom_type}, geom_type={geom_type}")
                    continue

            # Создаём feature
            feat = QgsFeature(temp_layer.fields())

            for field_name in field_names:
                if field_name in data and field_name not in RESERVED_FIELDS:
                    feat.setAttribute(field_name, data.get(field_name))

            # Геометрия (уже проверена на совместимость)
            if geom:
                feat.setGeometry(geom)

            new_features.append(feat)

        prov.addFeatures(new_features)

        # Перезаписываем в GPKG
        opts = QgsVectorFileWriter.SaveVectorOptions()
        opts.driverName = "GPKG"
        opts.layerName = layer_name
        opts.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer
        opts.skipAttributeCreation = False
        opts.layerOptions = []
        opts.datasourceOptions = []

        writer_result = QgsVectorFileWriter.writeAsVectorFormatV3(
            temp_layer, gpkg_path, QgsCoordinateTransformContext(), opts
        )

        if writer_result[0] != QgsVectorFileWriter.NoError:
            return None

        # Загружаем обновлённый слой
        updated_layer = QgsVectorLayer(
            f"{gpkg_path}|layername={layer_name}",
            layer_name,
            "ogr"
        )

        if updated_layer.isValid():
            log_info(f"Fsm_1_1_4_6: Слой '{layer_name}' обновлён (БЕЗ проверки дублей)")
            return updated_layer
        else:
            return None

    except Exception as e:
        log_error(f"Fsm_1_1_4_6: Ошибка добавления в слой '{layer_name}': {e}")
        return None


def supplement_selection_from_extracts(created_layers: List[QgsVectorLayer]) -> int:
    """Дополнение слоя выборки атрибутами из только что импортированных выписок

    FIX (2025-12-18): Поддержка сценария "выборка ДО выписок".
    Когда выписки импортируются ПОСЛЕ выборки, нужно дополнить
    существующую выборку данными из новых выписок.

    Логика:
    1. Проверить существование слоя выборки (Le_2_1_1_1_Выборка_ЗУ)
    2. Извлечь атрибуты из созданных слоёв выписок
    3. Дополнить пустые поля в выборке по КН

    Args:
        created_layers: Список только что созданных слоёв выписок

    Returns:
        int: Количество обновлённых записей в выборке
    """
    # Слой выборки ЗУ
    SELECTION_LAYER_NAME = 'Le_2_1_1_1_Выборка_ЗУ'

    # Поля для дополнения
    FIELDS_TO_SUPPLEMENT = [
        'Адрес_Местоположения',
        'Категория',
        'ВРИ',
        'Права',
        'Обременения',
        'Собственники',
        'Арендаторы',
    ]

    # Значения считающиеся пустыми
    EMPTY_VALUES = [None, '', '-', 'NULL', 'Сведения отсутствуют', 'Категория не установлена']

    project = QgsProject.instance()

    # Проверяем существование слоя выборки
    selection_layers = project.mapLayersByName(SELECTION_LAYER_NAME)
    if not selection_layers:
        log_info("Fsm_1_1_4_6: Слой выборки не найден - дополнение не требуется")
        return 0

    layer_obj = selection_layers[0]
    if not isinstance(layer_obj, QgsVectorLayer):
        log_warning("Fsm_1_1_4_6: Слой выборки не является векторным")
        return 0

    selection_layer: QgsVectorLayer = layer_obj
    if not selection_layer.isValid():
        log_warning("Fsm_1_1_4_6: Слой выборки невалиден")
        return 0

    if selection_layer.featureCount() == 0:
        log_info("Fsm_1_1_4_6: Слой выборки пуст - дополнение не требуется")
        return 0

    # Проверяем наличие поля "КН" в слое выборки
    kn_field_idx = selection_layer.fields().indexOf('КН')
    if kn_field_idx == -1:
        log_warning("Fsm_1_1_4_6: Поле 'КН' не найдено в слое выборки")
        return 0

    # Строим кэш атрибутов из созданных слоёв выписок
    attr_cache = {}  # {КН: {поле: значение}}

    for layer in created_layers:
        if layer is None or not layer.isValid():
            continue

        # Проверяем что это слой выписок (Le_1_6_*)
        layer_name = layer.name()
        if not layer_name.startswith('Le_1_6_'):
            continue

        extract_kn_idx = layer.fields().indexOf('КН')
        if extract_kn_idx == -1:
            continue

        extract_field_names = [f.name() for f in layer.fields()]

        for feature in layer.getFeatures():
            kn = feature.attribute(extract_kn_idx)
            if not kn:
                continue

            kn_str = str(kn)

            # Инициализируем или дополняем кэш для этого КН
            if kn_str not in attr_cache:
                attr_cache[kn_str] = {}

            for field_name in FIELDS_TO_SUPPLEMENT:
                if field_name in extract_field_names:
                    value = feature.attribute(field_name)
                    # Сохраняем только непустые значения
                    # Не перезаписываем уже существующие в кэше
                    if field_name not in attr_cache[kn_str]:
                        if value is not None and str(value).strip() not in ['', '-', 'NULL']:
                            attr_cache[kn_str][field_name] = value

    if not attr_cache:
        log_info("Fsm_1_1_4_6: Нет данных для дополнения выборки")
        return 0

    log_info(f"Fsm_1_1_4_6: Загружено {len(attr_cache)} КН из выписок для дополнения выборки")

    # Определяем индексы полей в слое выборки
    target_field_indices = {}
    for field_name in FIELDS_TO_SUPPLEMENT:
        idx = selection_layer.fields().indexOf(field_name)
        if idx != -1:
            target_field_indices[field_name] = idx

    if not target_field_indices:
        log_warning("Fsm_1_1_4_6: Нет полей для дополнения в слое выборки")
        return 0

    # Дополняем атрибуты в слое выборки
    supplemented_count = 0
    selection_layer.startEditing()

    for feature in selection_layer.getFeatures():
        kn = feature.attribute(kn_field_idx)
        if not kn:
            continue

        kn_str = str(kn)
        if kn_str not in attr_cache:
            continue

        cache_data = attr_cache[kn_str]
        feature_updated = False

        for field_name, field_idx in target_field_indices.items():
            if field_name not in cache_data:
                continue

            current_value = feature.attribute(field_idx)
            # Дополняем только если текущее значение пустое
            current_str = str(current_value).strip() if current_value is not None else ''
            if current_value is None or current_str in ['', '-', 'Сведения отсутствуют', 'Категория не установлена']:
                selection_layer.changeAttributeValue(feature.id(), field_idx, cache_data[field_name])
                feature_updated = True

        if feature_updated:
            supplemented_count += 1

    selection_layer.commitChanges()

    if supplemented_count > 0:
        log_info(f"Fsm_1_1_4_6: Дополнены атрибуты для {supplemented_count} объектов в слое выборки")
    else:
        log_info("Fsm_1_1_4_6: Нет объектов для дополнения в слое выборки")

    return supplemented_count
