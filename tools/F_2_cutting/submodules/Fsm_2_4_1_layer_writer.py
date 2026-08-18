# -*- coding: utf-8 -*-
"""
Fsm_2_4_1_LayerWriter - Запись полигональных слоёв этапности в GeoPackage

НАЗНАЧЕНИЕ:
    Создание слоя этапности в project.gpkg через OGR и подключение к проекту:
    схема полей из переданного QgsFields, опциональные поля "Этап" и
    "Состав_контуров", запись атрибутов с приведением типов, санитизация через
    M_13 и нормализация колец через M_47 (pass-2).

ОСОБЕННОСТИ:
    - Существующий слой с тем же именем удаляется перед созданием.
    - Поле fid пропускается: GeoPackage ведёт его сам, ID хранит номер контура.
    - Отсутствующее в слое поле логируется один раз и пропускается.

ИСПОЛЬЗОВАНИЕ:
    Вызывается F_2_4_Staging для каждого полигонального слоя этапности
    (1 этап, 2 этап, Итог).
"""

from typing import Any, Dict, List, Optional, TYPE_CHECKING

from qgis.core import QgsFields, QgsVectorLayer
from qgis.PyQt.QtCore import QMetaType

from Daman_QGIS.managers import DataCleanupManager
from Daman_QGIS.utils import log_info, log_warning, log_error, commit_or_rollback

from .Fsm_2_4_2_value_converter import Fsm_2_4_2_ValueConverter

if TYPE_CHECKING:
    from Daman_QGIS.managers import LayerManager


class Fsm_2_4_1_LayerWriter:
    """Запись полигональных слоёв этапности в GeoPackage"""

    def __init__(
        self,
        gpkg_path: str,
        layer_manager: Optional['LayerManager'] = None
    ) -> None:
        """Инициализация писателя слоёв

        Args:
            gpkg_path: Путь к project.gpkg (forward-slash, из M_19)
            layer_manager: Менеджер слоёв для подключения результата к проекту
        """
        self._gpkg_path = gpkg_path
        self.layer_manager = layer_manager
        self._converter = Fsm_2_4_2_ValueConverter()

    def create_staging_layer(
        self,
        layer_name: str,
        crs: Any,
        fields: QgsFields,
        features_data: List[Dict[str, Any]],
        add_merged_field: bool = False,
        add_stage_field: bool = False
    ) -> Optional[QgsVectorLayer]:
        """Создание слоя этапности в GPKG

        Args:
            add_merged_field: Добавить поле "Состав_контуров"
            add_stage_field: Добавить поле "Этап" перед ID (для итогового слоя)
        """
        if not features_data:
            log_info(f"Fsm_2_4_1: Нет данных для слоя {layer_name}")
            return None

        try:
            from osgeo import ogr, osr

            # Открываем GPKG
            ds = ogr.Open(self._gpkg_path, 1)
            if not ds:
                log_error(f"Fsm_2_4_1: Не удалось открыть GPKG: {self._gpkg_path}")
                return None

            # Удаляем существующий слой если есть
            for i in range(ds.GetLayerCount()):
                lyr = ds.GetLayerByIndex(i)
                if lyr and lyr.GetName() == layer_name:
                    ds.DeleteLayer(i)
                    break

            # Создаём SRS
            srs = osr.SpatialReference()
            srs.ImportFromWkt(crs.toWkt())

            # Создаём слой
            # MultiPolygon: объединение контуров 2 этапа даёт multipart, а
            # OGR-провайдер тип геометрии при записи не проверяет — в файл лёг
            # бы чужой wkb без единой ошибки
            ogr_layer = ds.CreateLayer(layer_name, srs, ogr.wkbMultiPolygon)
            if not ogr_layer:
                log_error(f"Fsm_2_4_1: Не удалось создать слой {layer_name}")
                ds = None
                return None

            # Добавляем поле "Этап" ПЕРЕД остальными полями (для итогового слоя)
            if add_stage_field:
                ogr_layer.CreateField(ogr.FieldDefn("Этап", ogr.OFTInteger))

            # Добавляем поля (исключаем зарезервированное поле fid)
            # GeoPackage создаёт fid автоматически, ID используется для номера контура
            for field in fields:
                field_name = field.name()
                if field_name.lower() == 'fid':
                    continue  # Пропускаем системное поле fid
                field_type = ogr.OFTString
                if field.type() == QMetaType.Type.Int:
                    field_type = ogr.OFTInteger
                elif field.type() == QMetaType.Type.Double:
                    field_type = ogr.OFTReal
                ogr_layer.CreateField(ogr.FieldDefn(field_name, field_type))

            # Добавляем поле Состав_контуров для 2 этапа и итогового
            if add_merged_field:
                ogr_layer.CreateField(ogr.FieldDefn("Состав_контуров", ogr.OFTString))

            # Получаем список полей в созданном слое для проверки
            layer_defn = ogr_layer.GetLayerDefn()
            existing_field_names = set()
            for i in range(layer_defn.GetFieldCount()):
                existing_field_names.add(layer_defn.GetFieldDefn(i).GetName())

            # Для отслеживания уже залогированных предупреждений
            warned_fields: set = set()

            # Создаём маппинг имён полей на их типы OGR
            field_types: Dict[str, int] = {}
            for i in range(layer_defn.GetFieldCount()):
                field_defn = layer_defn.GetFieldDefn(i)
                field_types[field_defn.GetName()] = field_defn.GetType()

            # Добавляем объекты
            for item in features_data:
                ogr_feature = ogr.Feature(layer_defn)

                # Геометрия
                geom_wkt = item['geometry'].asWkt()
                ogr_geom = ogr.CreateGeometryFromWkt(geom_wkt)
                if ogr_geom is None or not ogr_geom.IsValid():
                    log_error(
                        f"Fsm_2_4_1: невалидная геометрия контура "
                        f"ID={item.get('attributes', {}).get('ID')} в {layer_name}"
                    )
                    ds = None
                    return None
                ogr_feature.SetGeometry(ogr_geom)

                # Атрибуты (исключаем fid и поля которых нет в слое)
                for field_name, value in item['attributes'].items():
                    if field_name.lower() == 'fid':
                        continue
                    if field_name not in existing_field_names:
                        # Поле не существует в слое - пропускаем (лог один раз)
                        if field_name not in warned_fields:
                            log_warning(f"Fsm_2_4_1: Поле '{field_name}' отсутствует в слое {layer_name}")
                            warned_fields.add(field_name)
                        continue
                    if value is not None:
                        # Конвертируем значение в совместимый тип для OGR
                        field_type: int = field_types.get(field_name, ogr.OFTString)
                        converted_value = self._converter.convert(value, field_type)
                        if converted_value is not None:
                            ogr_feature.SetField(field_name, converted_value)

                # Поле Этап (для итогового слоя)
                if add_stage_field and 'stage' in item:
                    ogr_feature.SetField("Этап", item['stage'])

                # Поле Состав_контуров
                if add_merged_field and 'merged_contours' in item:
                    ogr_feature.SetField("Состав_контуров", item['merged_contours'])

                if ogr_layer.CreateFeature(ogr_feature) != 0:
                    log_error(
                        f"Fsm_2_4_1: CreateFeature отказал в {layer_name} для контура "
                        f"ID={item.get('attributes', {}).get('ID')}"
                    )
                    ds = None
                    return None

            ds = None  # Закрываем

            # Загружаем слой в QGIS
            uri = f"{self._gpkg_path}|layername={layer_name}"
            qgs_layer = QgsVectorLayer(uri, layer_name, "ogr")

            # Условия расклеены: склейка давала ложный диагноз «слой невалиден»
            # там, где на деле не инжектирован layer_manager, а санитизация M_13
            # и нормализация M_47 pass-2 при этом молча пропускались
            if not qgs_layer.isValid():
                log_error(f"Fsm_2_4_1: Слой {layer_name} невалиден")
                return None

            if not self.layer_manager:
                log_error(
                    f"Fsm_2_4_1: layer_manager не инжектирован — санитизация M_13 "
                    f"и нормализация M_47 pass-2 для {layer_name} невозможны"
                )
                return None

            self.layer_manager.add_layer(
                qgs_layer,
                make_readonly=False,
                auto_number=False,
                check_precision=False
            )

            # Санитизация: замена NULL/пустых значений на "-"
            cleanup_manager = DataCleanupManager()
            cleanup_manager.finalize_layer(qgs_layer, layer_name, capitalize=False)

            # M_47 pass-2 (level-map two-pass): normalize_layer на .gpkg-слое после OGR.
            # Идемпотентно: pass-1 нормализовал features_data → OGR WKT сохранил порядок →
            # здесь no-op через equals(); если GDAL переставил кольца на write — чинит.
            # commit-before-M_47 (FIX-rev2-16): finalize_layer мог оставить edit-сессию,
            # strict isEditable guard иначе пропустил бы нормализацию.
            from Daman_QGIS.managers.geometry import PolygonNormalizationManager
            if not commit_or_rollback(qgs_layer, "Fsm_2_4_1"):
                log_error(f"Fsm_2_4_1: слой {layer_name} не сохранён, правки откачены")
                return None
            PolygonNormalizationManager.normalize_layer(qgs_layer)

            # Сверка с числом поданных контуров: расхождение означает
            # потерю объекта по пути, а слой при этом выглядит валидным
            written = qgs_layer.dataProvider().featureCount()
            if written != len(features_data):
                log_error(
                    f"Fsm_2_4_1: в слой {layer_name} записано {written} из "
                    f"{len(features_data)} контуров"
                )
                return None

            log_info(f"Fsm_2_4_1: Создан слой {layer_name} ({written} объектов)")
            return qgs_layer
        except Exception as e:
            log_error(f"Fsm_2_4_1: Ошибка создания слоя {layer_name}: {e}")
            return None
