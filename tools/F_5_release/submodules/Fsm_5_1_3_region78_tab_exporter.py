# -*- coding: utf-8 -*-
"""
Fsm_5_1_3 - Экспортер DPT_* слоев для региона 78 (СПб)

Назначение:
    Подготовка слоев с полями по требованиям КГА СПб
    для экспорта в TAB формат через TabExporter.

    Слои L_4_1_* из GPKG трансформируются в DPT_* с:
    - Именами по приказу КГА (DPT_OKS_PL, DPT_REDL и т.д.)
    - Полями по разделам 4.1-4.12 приказа
    - Проекцией NonEarth с bounds 0,0,200000,200000

    Для Mixed слоев (DPT_UDS, DPT_OI_I) используется temp GPKG,
    т.к. QGIS memory provider НЕ поддерживает mixed geometries.

Зависимости:
    - Fsm_5_1_2_region78_schema (LAYER_MAPPING, DPT_LAYERS, get_layer_fields, TAB_BOUNDS, OUTPUT_FOLDERS)
"""

import os
import tempfile
from typing import Optional, Tuple, List, Dict, Any

from qgis.core import (
    QgsVectorLayer,
    QgsFeature,
    QgsField,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QMetaType

from Daman_QGIS.utils import log_info, log_error, log_warning

from .Fsm_5_1_2_region78_schema import (
    LAYER_MAPPING,
    DPT_LAYERS,
    TAB_BOUNDS,
    OUTPUT_FOLDERS,
    get_layer_fields,
    get_dpt_name,
)


# Маппинг типов полей schema -> QMetaType
_FIELD_TYPE_MAP = {
    'string': QMetaType.Type.QString,
    'float': QMetaType.Type.Double,
    'integer': QMetaType.Type.Int,
}

# Маппинг типов полей schema -> OGR field type
_OGR_FIELD_TYPE_MAP = {
    'string': 'String',
    'float': 'Real',
    'integer': 'Integer',
}

# Маппинг geometry_type schema -> QGIS URI string (для memory layers)
_GEOM_TYPE_MAP = {
    'Polygon': 'Polygon',
    'LineString': 'LineString',
    'Point': 'Point',
}


class Fsm_5_1_3_Region78TabExporter:
    """Подготовка DPT_* слоев для экспорта в TAB по требованиям КГА СПб"""

    def __init__(self) -> None:
        self._temp_files: List[str] = []

    def is_dpt_layer(self, layer_name: str) -> bool:
        """
        Проверить, является ли слой DPT_* слоем региона 78.

        Args:
            layer_name: Имя слоя в проекте (например 'L_4_1_1_DPT_OKS_PL')

        Returns:
            True если слой есть в LAYER_MAPPING
        """
        return layer_name in LAYER_MAPPING

    def prepare_dpt_layer(
        self,
        source_layer: QgsVectorLayer
    ) -> Tuple[Optional[QgsVectorLayer], str]:
        """
        Создать слой с DPT схемой и скопировать геометрию.

        Для обычных типов — memory layer.
        Для Mixed — temp GPKG (memory provider не поддерживает mixed).

        Args:
            source_layer: Исходный слой (L_4_1_*)

        Returns:
            (layer, dpt_name) или (None, '') при ошибке
        """
        layer_name = source_layer.name()
        dpt_name = get_dpt_name(layer_name)

        if not dpt_name:
            log_error(
                f"Fsm_5_1_3: Слой {layer_name} не найден в LAYER_MAPPING"
            )
            return None, ''

        layer_def = DPT_LAYERS.get(dpt_name)
        if not layer_def:
            log_error(
                f"Fsm_5_1_3: DPT слой {dpt_name} не найден в DPT_LAYERS"
            )
            return None, ''

        schema_geom_type = layer_def['geometry_type']
        is_mixed = schema_geom_type == 'Mixed'
        dpt_fields = get_layer_fields(dpt_name)

        if is_mixed:
            return self._prepare_mixed_layer(
                source_layer, dpt_name, dpt_fields
            )
        else:
            return self._prepare_memory_layer(
                source_layer, dpt_name, dpt_fields, schema_geom_type
            )

    def _prepare_memory_layer(
        self,
        source_layer: QgsVectorLayer,
        dpt_name: str,
        dpt_fields: List[Dict[str, Any]],
        geom_type: str
    ) -> Tuple[Optional[QgsVectorLayer], str]:
        """Создать memory layer для простых типов геометрий."""
        uri_geom_type = _GEOM_TYPE_MAP.get(geom_type, 'Polygon')
        crs_id = source_layer.crs().authid()
        uri = f"{uri_geom_type}?crs={crs_id}"
        mem_layer = QgsVectorLayer(uri, dpt_name, "memory")

        if not mem_layer.isValid():
            log_error(
                f"Fsm_5_1_3: Не удалось создать memory layer для {dpt_name}"
            )
            return None, ''

        provider = mem_layer.dataProvider()
        if provider is None:
            log_error(f"Fsm_5_1_3: dataProvider is None для {dpt_name}")
            return None, ''

        # Добавляем поля из DPT схемы
        qgs_fields = self._make_qgs_fields(dpt_fields)
        provider.addAttributes(qgs_fields)
        mem_layer.updateFields()

        # Копируем features
        source_field_names = [f.name() for f in source_layer.fields()]
        dpt_field_names = [f.name() for f in mem_layer.fields()]
        matching = set(dpt_field_names) & set(source_field_names)

        features_to_add = []
        for src_feat in source_layer.getFeatures():
            if not src_feat.hasGeometry():
                continue

            new_feat = QgsFeature(mem_layer.fields())
            new_feat.setGeometry(src_feat.geometry())
            self._copy_matching_attrs(
                src_feat, new_feat, source_layer, mem_layer, matching
            )
            features_to_add.append(new_feat)

        if features_to_add:
            provider.addFeatures(features_to_add)

        log_info(
            f"Fsm_5_1_3: {dpt_name}: {len(features_to_add)} features, "
            f"{len(qgs_fields)} полей, {geom_type}, "
            f"совпадающих атрибутов: {len(matching)}"
        )

        return mem_layer, dpt_name

    def _prepare_mixed_layer(
        self,
        source_layer: QgsVectorLayer,
        dpt_name: str,
        dpt_fields: List[Dict[str, Any]]
    ) -> Tuple[Optional[QgsVectorLayer], str]:
        """
        Создать temp GPKG для Mixed слоев.

        QGIS memory provider НЕ поддерживает mixed geometries —
        используем временный GPKG через OGR/GDAL с ogr.wkbUnknown.
        """
        try:
            from osgeo import ogr, osr

            # Временный файл
            temp_dir = tempfile.mkdtemp(prefix='daman_dpt_')
            temp_path = os.path.join(temp_dir, f"{dpt_name}.gpkg")
            self._temp_files.append(temp_path)

            # Создаем GPKG
            driver = ogr.GetDriverByName('GPKG')
            if not driver:
                log_error("Fsm_5_1_3: Драйвер GPKG не найден")
                return None, ''

            ds = driver.CreateDataSource(temp_path)
            if not ds:
                log_error(
                    f"Fsm_5_1_3: Не удалось создать {temp_path}"
                )
                return None, ''

            # SRS из исходного слоя
            srs = osr.SpatialReference()
            srs.ImportFromWkt(source_layer.crs().toWkt())

            # Создаем слой с wkbUnknown
            lyr = ds.CreateLayer(dpt_name, srs, ogr.wkbUnknown)
            if not lyr:
                log_error(
                    f"Fsm_5_1_3: Не удалось создать OGR слой {dpt_name}"
                )
                ds = None
                return None, ''

            # Добавляем поля
            for field_def in dpt_fields:
                ogr_type_str = _OGR_FIELD_TYPE_MAP.get(field_def['type'])
                if ogr_type_str == 'String':
                    ogr_type = ogr.OFTString
                elif ogr_type_str == 'Real':
                    ogr_type = ogr.OFTReal
                elif ogr_type_str == 'Integer':
                    ogr_type = ogr.OFTInteger
                else:
                    continue

                field_defn = ogr.FieldDefn(field_def['name'], ogr_type)
                if 'length' in field_def and ogr_type == ogr.OFTString:
                    field_defn.SetWidth(field_def['length'])
                lyr.CreateField(field_defn)

            # Маппинг совпадающих полей
            source_field_names = [f.name() for f in source_layer.fields()]
            dpt_field_names_list = [f['name'] for f in dpt_fields]
            matching = set(dpt_field_names_list) & set(source_field_names)

            # Копируем features
            feat_count = 0
            for src_feat in source_layer.getFeatures():
                if not src_feat.hasGeometry():
                    continue

                ogr_feat = ogr.Feature(lyr.GetLayerDefn())
                wkt = src_feat.geometry().asWkt()
                ogr_geom = ogr.CreateGeometryFromWkt(wkt)
                if ogr_geom:
                    ogr_feat.SetGeometry(ogr_geom)

                # Инициализируем все строковые поля пустой строкой
                # (OGR по умолчанию ставит NULL, КГА требует пустые)
                for field_def in dpt_fields:
                    if field_def['type'] == 'string':
                        ogr_feat.SetField(field_def['name'], '')

                # Копируем совпадающие атрибуты
                for field_name in matching:
                    src_idx = source_layer.fields().lookupField(field_name)
                    if src_idx >= 0:
                        value = src_feat.attribute(src_idx)
                        if value is not None:
                            ogr_feat.SetField(field_name, value)

                lyr.CreateFeature(ogr_feat)
                feat_count += 1

            ds = None  # Закрываем datasource

            # Открываем как QgsVectorLayer
            result_layer = QgsVectorLayer(
                temp_path, dpt_name, "ogr"
            )
            if not result_layer.isValid():
                log_error(
                    f"Fsm_5_1_3: Не удалось открыть temp GPKG: {temp_path}"
                )
                return None, ''

            result_layer.setCustomProperty('daman_mixed_geometry', True)

            log_info(
                f"Fsm_5_1_3: {dpt_name}: {feat_count} features, "
                f"{len(dpt_fields)} полей, Mixed (temp GPKG), "
                f"совпадающих атрибутов: {len(matching)}"
            )

            return result_layer, dpt_name

        except Exception as e:
            log_error(
                f"Fsm_5_1_3 (_prepare_mixed_layer): "
                f"Ошибка для {dpt_name}: {e}"
            )
            return None, ''

    def _make_qgs_fields(
        self,
        dpt_fields: List[Dict[str, Any]]
    ) -> List[QgsField]:
        """Конвертировать список определений полей в QgsField."""
        result = []
        for field_def in dpt_fields:
            field_type = _FIELD_TYPE_MAP.get(field_def['type'])
            if field_type is None:
                log_warning(
                    f"Fsm_5_1_3: Неизвестный тип поля "
                    f"'{field_def['type']}' для {field_def['name']}"
                )
                continue

            qgs_field = QgsField(field_def['name'], field_type)
            if 'length' in field_def:
                qgs_field.setLength(field_def['length'])
            result.append(qgs_field)
        return result

    @staticmethod
    def _copy_matching_attrs(
        src_feat: QgsFeature,
        dst_feat: QgsFeature,
        src_layer: QgsVectorLayer,
        dst_layer: QgsVectorLayer,
        matching: set
    ) -> None:
        """Копировать совпадающие по имени атрибуты."""
        for field_name in matching:
            src_idx = src_layer.fields().lookupField(field_name)
            dst_idx = dst_layer.fields().lookupField(field_name)
            if src_idx >= 0 and dst_idx >= 0:
                dst_feat.setAttribute(
                    dst_idx, src_feat.attribute(src_idx)
                )

    def get_tab_bounds(self) -> str:
        """Bounds для NonEarth проекции КГА СПб."""
        return TAB_BOUNDS

    def get_output_subfolder(self) -> str:
        """Имя подпапки для векторных слоев."""
        return OUTPUT_FOLDERS['vector_layers']
