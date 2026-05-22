# -*- coding: utf-8 -*-
"""
Fsm_1_1_8_3 - Создание слоя "Уведомление_сервитут" и запись в GPKG

Memory-слой MultiPolygonM (M = delta_geopoint), 16 атрибутов public_easement.
При наличии gpkg_path - запись в GPKG через QgsVectorFileWriter (как в Fsm_1_1_4_4).
"""

import os
from typing import List, Dict, Any, Optional

from qgis.core import (
    QgsVectorLayer, QgsFeature, QgsField, QgsFields, QgsGeometry,
    QgsCoordinateReferenceSystem, QgsCoordinateTransformContext,
    QgsVectorFileWriter, QgsProject, Qgis,
)
from qgis.PyQt.QtCore import QMetaType

from Daman_QGIS.utils import log_info, log_warning, log_error


# Имя слоя в проекте/GPKG. БЕЗ префикса L_X_Y_Z - этот слой не входит в
# Base_layers.json (ownership пользователя), используем descriptive имя.
LAYER_NAME = "Уведомление_сервитут"

# Структура полей слоя: 16 атрибутов из public_easement + guid + source_file.
# (field_name, QMetaType, alias)
# QMetaType, а не deprecated QVariant - см. CLAUDE.md "PyQGIS Requirements".
LAYER_FIELDS: List[tuple] = [
    ('guid',                     QMetaType.Type.QString, 'GUID документа'),
    ('type_boundary',            QMetaType.Type.Int,     'Тип границы'),
    ('name_object',              QMetaType.Type.QString, 'Наименование объекта'),
    ('is_changing',              QMetaType.Type.Bool,    'Изменение существующей'),
    ('reg_numb_border',          QMetaType.Type.QString, 'Реестровый номер границы'),
    ('quarter_cad_number',       QMetaType.Type.QString, 'КН кадастрового квартала'),
    ('name_by_doc',              QMetaType.Type.QString, 'Наименование по документу'),
    ('authority_decision',       QMetaType.Type.QString, 'Орган, принявший решение'),
    ('purpose_public_easement',  QMetaType.Type.QString, 'Цель сервитута (код)'),
    ('purpose_other',            QMetaType.Type.QString, 'Цель сервитута (текст)'),
    ('period_text',              QMetaType.Type.QString, 'Срок действия (текст)'),
    ('period_start',             QMetaType.Type.QString, 'Дата начала'),
    ('period_end',               QMetaType.Type.QString, 'Дата окончания'),
    ('period_indefinite',        QMetaType.Type.Bool,    'Бессрочно'),
    ('holder_type',              QMetaType.Type.QString, 'Тип правообладателя'),
    ('holder_name',              QMetaType.Type.QString, 'Полное наименование'),
    ('holder_inn',               QMetaType.Type.QString, 'ИНН'),
    ('holder_ogrn',              QMetaType.Type.QString, 'ОГРН'),
    ('sk_code',                  QMetaType.Type.QString, 'Код СК (МСК)'),
    ('source_file',              QMetaType.Type.QString, 'Имя исходного файла'),
]


def _build_qgs_fields() -> QgsFields:
    """Построить QgsFields из LAYER_FIELDS."""
    fields = QgsFields()
    for name, qmeta_type, _alias in LAYER_FIELDS:
        field = QgsField(name, qmeta_type)
        fields.append(field)
    return fields


def _apply_field_aliases(layer: QgsVectorLayer) -> None:
    """Установить QGIS-алиасы для всех полей слоя.

    Маппинг по имени поля - корректно работает и для memory-слоя
    (поля LAYER_FIELDS в позициях 0..N-1) и для GPKG-слоя
    (GDAL добавляет служебное `fid` в позицию 0, сдвигая остальные).
    """
    if not layer or not layer.isValid():
        return
    alias_map = {name: alias for name, _qt, alias in LAYER_FIELDS}
    layer_fields = layer.fields()
    for idx in range(layer_fields.count()):
        field_name = layer_fields.field(idx).name()
        alias = alias_map.get(field_name)
        if alias and alias.strip():
            layer.setFieldAlias(idx, alias)


def _populate_feature_attributes(
    feat: QgsFeature,
    data: Dict[str, Any],
    fields: QgsFields,
) -> None:
    """
    Заполнить атрибуты QgsFeature из словаря data.

    Поля, отсутствующие в data, остаются NULL (None). Длина массива атрибутов
    гарантированно равна fields.count() (важно для silent skip в addFeature -
    см. CLAUDE.md "QgsVectorLayer.addFeature() silent returns False").
    """
    for idx in range(fields.count()):
        field_name = fields.field(idx).name()
        value = data.get(field_name)
        feat.setAttribute(idx, value if value is not None else None)


def create_and_save_layer(
    features_data: List[Dict[str, Any]],
    output_gpkg_path: Optional[str],
    crs: Optional[QgsCoordinateReferenceSystem] = None,
) -> Optional[QgsVectorLayer]:
    """
    Создать слой "Уведомление_сервитут" и (опционально) сохранить в GPKG.

    Args:
        features_data: Список словарей с атрибутами + ключом 'geometry' (QgsGeometry).
                       Возможно None в geometry - такие фичи записываются БЕЗ геометрии.
        output_gpkg_path: Путь к GPKG (None - только memory-слой).
        crs: Целевая СК (по умолчанию - CRS проекта QGIS).

    Returns:
        QgsVectorLayer (из GPKG если запись прошла, иначе memory-слой) или None при ошибке.
    """
    if not features_data:
        log_warning("Fsm_1_1_8_3: Нет данных для создания слоя")
        return None

    # CRS: project_manager обычно уже передал актуальный, но если None - берём из проекта
    if crs is None:
        project = QgsProject.instance()
        crs = project.crs() if project else QgsCoordinateReferenceSystem("EPSG:4326")

    if not crs or not crs.isValid():
        log_warning(
            f"Fsm_1_1_8_3: CRS невалиден, fallback на CRS проекта QGIS"
        )
        crs = QgsProject.instance().crs()

    fields = _build_qgs_fields()
    wkb_type = Qgis.WkbType.MultiPolygonM

    # Memory-слой для накопления (используется и сам по себе, и как источник для GPKG)
    uri = f"MultiPolygon?crs={crs.authid()}" if crs.authid() else "MultiPolygon"
    memory_layer = QgsVectorLayer(uri, LAYER_NAME, "memory")

    if not memory_layer.isValid():
        log_error(f"Fsm_1_1_8_3: Memory-слой невалиден (uri={uri})")
        return None

    provider = memory_layer.dataProvider()
    provider.addAttributes([fields.field(i) for i in range(fields.count())])
    memory_layer.updateFields()

    # Прямая запись в GPKG минуя memory-провайдер - паттерн из Fsm_1_1_4_4
    if output_gpkg_path:
        return _write_to_gpkg(
            features_data=features_data,
            fields=fields,
            crs=crs,
            wkb_type=wkb_type,
            gpkg_path=output_gpkg_path,
        )

    # Иначе - только memory-слой
    _add_features_to_memory(memory_layer, features_data, fields)
    _apply_field_aliases(memory_layer)
    QgsProject.instance().addMapLayer(memory_layer)
    log_info(
        f"Fsm_1_1_8_3: Memory-слой '{LAYER_NAME}' создан, "
        f"объектов: {memory_layer.featureCount()}"
    )
    return memory_layer


def _add_features_to_memory(
    layer: QgsVectorLayer,
    features_data: List[Dict[str, Any]],
    fields: QgsFields,
) -> None:
    """Заполнить memory-слой фичами."""
    provider = layer.dataProvider()
    out_features = []
    for data in features_data:
        feat = QgsFeature(layer.fields())
        geom = data.get('geometry')
        if geom is not None and not geom.isEmpty():
            feat.setGeometry(geom)
        _populate_feature_attributes(feat, data, fields)
        out_features.append(feat)

    if out_features:
        ok, _added = provider.addFeatures(out_features)
        if not ok:
            log_error(
                f"Fsm_1_1_8_3: addFeatures вернул False для memory-слоя "
                f"'{LAYER_NAME}'"
            )


def _write_to_gpkg(
    features_data: List[Dict[str, Any]],
    fields: QgsFields,
    crs: QgsCoordinateReferenceSystem,
    wkb_type,
    gpkg_path: str,
) -> Optional[QgsVectorLayer]:
    """
    Прямая запись в GPKG через QgsVectorFileWriter.create (без memory-промежуточника).

    Паттерн взят из Fsm_1_1_4_4_layer_creator.save_to_gpkg_direct.
    """
    try:
        opts = QgsVectorFileWriter.SaveVectorOptions()
        opts.driverName = "GPKG"
        opts.layerName = LAYER_NAME
        opts.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer

        writer = QgsVectorFileWriter.create(
            gpkg_path,
            fields,
            wkb_type,
            crs,
            QgsCoordinateTransformContext(),
            opts,
        )

        if writer is None:
            log_error("Fsm_1_1_8_3: QgsVectorFileWriter.create вернул None")
            return None

        added = 0
        skipped = 0

        for data in features_data:
            feat = QgsFeature(fields)
            _populate_feature_attributes(feat, data, fields)

            geom = data.get('geometry')
            if geom is not None and not geom.isEmpty():
                # Проверяем что тип геометрии совместим (полигон)
                if hasattr(geom, 'type') and geom.type() == Qgis.GeometryType.Polygon:
                    feat.setGeometry(geom)
                else:
                    log_warning(
                        f"Fsm_1_1_8_3: пропущена несовместимая геометрия "
                        f"({data.get('reg_numb_border') or data.get('guid')})"
                    )
                    skipped += 1
                    continue
            # NULL geometry допустима - feature всё равно пишется

            if writer.addFeature(feat):
                added += 1
            else:
                skipped += 1
                err = writer.errorMessage() if hasattr(writer, 'errorMessage') else 'unknown'
                log_error(
                    f"Fsm_1_1_8_3: addFeature вернул False для "
                    f"{data.get('reg_numb_border') or data.get('guid')}: {err}"
                )

        # Финализация записи
        del writer

        log_info(
            f"Fsm_1_1_8_3: GPKG '{os.path.basename(gpkg_path)}' слой "
            f"'{LAYER_NAME}': записано {added}, пропущено {skipped}"
        )

        saved_layer = QgsVectorLayer(
            f"{gpkg_path}|layername={LAYER_NAME}",
            LAYER_NAME,
            "ogr",
        )
        if not saved_layer.isValid():
            log_error(f"Fsm_1_1_8_3: Не удалось перезагрузить слой '{LAYER_NAME}' из GPKG")
            return None

        _apply_field_aliases(saved_layer)
        QgsProject.instance().addMapLayer(saved_layer)
        log_info(
            f"Fsm_1_1_8_3: Слой '{LAYER_NAME}' добавлен в проект: "
            f"{saved_layer.featureCount()} объектов"
        )
        return saved_layer

    except Exception as e:
        import traceback
        log_error(f"Fsm_1_1_8_3: Ошибка записи в GPKG: {e}")
        log_error(f"Fsm_1_1_8_3: {traceback.format_exc()}")
        return None
