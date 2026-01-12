# -*- coding: utf-8 -*-
"""
Субмодуль F_1_2: Управление родительскими слоями
Создание родительских слоёв из подслоёв (например, L_1_2_4_WFS_ОКС из Le_1_2_4_X)
"""

import os
from typing import Dict
from qgis.core import (
    QgsVectorLayer, QgsFeature, QgsFields, QgsWkbTypes
)

from Daman_QGIS.utils import log_info, log_warning, log_error, log_success
from Daman_QGIS.constants import PROVIDER_OGR


class Fsm_1_2_7_ParentLayerManager:
    """Менеджер создания родительских слоёв из подслоёв"""

    def __init__(self, iface, layer_manager):
        """
        Инициализация менеджера родительских слоёв

        Args:
            iface: Интерфейс QGIS
            layer_manager: LayerManager для добавления слоёв
        """
        self.iface = iface
        self.layer_manager = layer_manager

    def create_parent_layers(self, loaded_sublayers: Dict, gpkg_path: str) -> None:
        """
        Создать родительские слои из загруженных подслоёв

        Args:
            loaded_sublayers: Словарь {(section, group, layer_num, layer): [слои]}
            gpkg_path: Путь к GeoPackage
        """
        from Daman_QGIS.managers import get_reference_managers

        ref_managers = get_reference_managers()

        for parent_key, sublayers in loaded_sublayers.items():
            section_num, group_num, layer_num, layer_name = parent_key

            # Проверяем есть ли родительский слой в базе
            all_layers = ref_managers.layer.get_base_layers()
            parent_info = None

            for item in all_layers:
                if (item.get('section_num') == section_num and
                    item.get('group_num') == group_num and
                    item.get('layer_num') == layer_num and
                    item.get('layer') == layer_name and
                    item.get('sublayer_num') is None):
                    parent_info = item
                    break

            if not parent_info:
                continue

            parent_full_name = parent_info['full_name']
            log_info(f"Fsm_1_2_7: Создание родительского слоя {parent_full_name} из {len(sublayers)} подслоёв")

            try:
                # Объединяем геометрии всех подслоёв
                if not sublayers:
                    log_warning(f"Fsm_1_2_7:   Нет подслоёв для {parent_full_name}")
                    continue

                # Используем CRS первого подслоя
                first_sublayer = sublayers[0]
                crs = first_sublayer.crs()

                # ВАЖНО: Анализируем типы геометрии ВСЕХ подслоёв
                # Если типы разные - используем Multi* или GeometryCollection
                geom_types_set = set()
                for sublayer in sublayers:
                    geom_type = sublayer.geometryType()
                    geom_types_set.add(geom_type)

                # Если все подслои имеют одинаковый тип - используем его
                # Если разные типы - используем GeometryCollection или самый "большой" тип
                if len(geom_types_set) == 1:
                    target_geom_type = geom_types_set.pop()
                else:
                    # Разные типы! Выбираем самый общий
                    # QGIS geometryType: 0=Point, 1=Line, 2=Polygon
                    # Используем самый "большой" тип
                    if 2 in geom_types_set or 6 in geom_types_set:  # Polygon или MultiPolygon
                        target_geom_type = 6  # MultiPolygon
                    elif 1 in geom_types_set or 5 in geom_types_set:  # Line или MultiLineString
                        target_geom_type = 5  # MultiLineString
                    else:  # Point или MultiPoint
                        target_geom_type = 4  # MultiPoint

                # Создаём memory layer для родителя
                geom_type = first_sublayer.wkbType()
                geom_type_str = QgsWkbTypes.displayString(geom_type)
                parent_layer = QgsVectorLayer(
                    f"{geom_type_str}?crs={crs.authid()}",
                    parent_full_name,
                    "memory"
                )

                # Объединяем структуру полей от всех подслоёв
                merged_fields = QgsFields()
                field_names = set()

                for sublayer in sublayers:
                    for field in sublayer.fields():
                        if field.name() not in field_names:
                            merged_fields.append(field)
                            field_names.add(field.name())

                parent_layer.dataProvider().addAttributes(merged_fields)
                parent_layer.updateFields()

                # Начинаем редактирование
                parent_layer.startEditing()

                # НОВЫЙ ПОДХОД: Создаём слой НАПРЯМУЮ в GeoPackage через GDAL/OGR
                # Это полностью избегает проблем с fid в memory layers
                try:
                    from osgeo import ogr, osr

                    # Удаляем существующий слой если есть
                    if os.path.exists(gpkg_path):
                        ds = ogr.Open(gpkg_path, 1)
                        if ds:
                            for i in range(ds.GetLayerCount()):
                                lyr = ds.GetLayerByIndex(i)
                                if lyr and lyr.GetName() == parent_full_name:
                                    ds.DeleteLayer(i)
                                    break
                            ds = None

                    # Открываем/создаём GeoPackage
                    ds = ogr.Open(gpkg_path, 1) if os.path.exists(gpkg_path) else ogr.GetDriverByName('GPKG').CreateDataSource(gpkg_path)
                    if not ds:
                        raise Exception(f"Не удалось открыть GeoPackage: {gpkg_path}")

                    # Определяем тип геометрии для OGR
                    # ВАЖНО: QGIS geometryType() возвращает: 0=Point, 1=Line, 2=Polygon
                    # Маппим на OGR wkb типы
                    geom_type_map = {
                        0: ogr.wkbPoint,           # Point
                        1: ogr.wkbLineString,      # Line
                        2: ogr.wkbPolygon,         # Polygon
                        3: ogr.wkbUnknown,         # Unknown (если вдруг)
                        4: ogr.wkbMultiPoint,      # MultiPoint
                        5: ogr.wkbMultiLineString, # MultiLineString
                        6: ogr.wkbMultiPolygon,    # MultiPolygon
                    }
                    ogr_geom_type = geom_type_map.get(target_geom_type, ogr.wkbUnknown)

                    # Создаём SRS
                    srs = osr.SpatialReference()
                    srs.ImportFromProj4(crs.toProj())

                    # Создаём слой (fid будет auto-increment!)
                    ogr_layer = ds.CreateLayer(parent_full_name, srs, ogr_geom_type)
                    if not ogr_layer:
                        raise Exception(f"Не удалось создать слой {parent_full_name}")

                    # Создаём поля (пропускаем "fid" - это зарезервированное поле!)
                    for field in merged_fields:
                        field_name = field.name()

                        # ВАЖНО: Пропускаем поле "fid" - оно зарезервировано в GeoPackage
                        if field_name.lower() == 'fid':
                            continue

                        field_defn = ogr.FieldDefn(field_name, ogr.OFTString)
                        if field.type() == 2:  # Int
                            field_defn.SetType(ogr.OFTInteger)
                        elif field.type() == 6:  # Double
                            field_defn.SetType(ogr.OFTReal)
                        elif field.type() == 10:  # String
                            field_defn.SetType(ogr.OFTString)
                        ogr_layer.CreateField(field_defn)

                    # Копируем объекты НАПРЯМУЮ в GeoPackage (fid создаётся автоматически!)
                    total_features = 0
                    for sublayer in sublayers:
                        for feature in sublayer.getFeatures():
                            ogr_feature = ogr.Feature(ogr_layer.GetLayerDefn())
                            ogr_feature.SetGeometry(ogr.CreateGeometryFromWkt(feature.geometry().asWkt()))

                            # Копируем атрибуты (пропускаем "fid"!)
                            for field in sublayer.fields():
                                field_name = field.name()

                                # Пропускаем зарезервированное поле "fid"
                                if field_name.lower() == 'fid':
                                    continue

                                if field_name in field_names:
                                    value = feature[field_name]

                                    # Пропускаем NULL значения
                                    if value is None:
                                        continue

                                    # ВАЖНО: Конвертируем типы QGIS в нативные Python типы
                                    # OGR не понимает QVariant и другие специальные типы QGIS
                                    try:
                                        field_type = field.type()

                                        if field_type == 2:  # Integer
                                            ogr_feature.SetField(field_name, int(value))
                                        elif field_type == 6:  # Double
                                            ogr_feature.SetField(field_name, float(value))
                                        elif field_type == 10:  # String
                                            ogr_feature.SetField(field_name, str(value))
                                        else:
                                            # Для остальных типов пытаемся конвертировать в строку
                                            ogr_feature.SetField(field_name, str(value))
                                    except (ValueError, TypeError) as conv_error:
                                        # Если конвертация не удалась - пропускаем это поле
                                        log_warning(f"Fsm_1_2_7: Не удалось конвертировать значение поля '{field_name}': {conv_error}")
                                        continue

                            ogr_layer.CreateFeature(ogr_feature)  # FID создаётся автоматически!
                            ogr_feature = None
                            total_features += 1

                    ds = None  # Закрываем датасет

                    # Загружаем слой из GeoPackage
                    parent_layer = QgsVectorLayer(
                        f"{gpkg_path}|layername={parent_full_name}",
                        parent_full_name,
                        PROVIDER_OGR
                    )

                    if not parent_layer.isValid():
                        raise Exception(f"Не удалось загрузить слой {parent_full_name} из GeoPackage")

                    log_success(f"Fsm_1_2_7: Родительский слой {parent_full_name} создан: {total_features} объектов")

                except Exception as ogr_error:
                    log_error(f"Fsm_1_2_7: Ошибка создания слоя через OGR: {str(ogr_error)}")
                    raise

                # Добавляем через layer_manager
                if self.layer_manager:
                    parent_layer.setName(parent_full_name)
                    self.layer_manager.add_layer(parent_layer, make_readonly=False, auto_number=False, check_precision=False)

            except Exception as e:
                log_error(f"Fsm_1_2_7: Ошибка создания родительского слоя {parent_full_name}: {str(e)}")
