# -*- coding: utf-8 -*-
"""
Fsm_1_zone_id_helper: Гарантировать наличие поля 'ID' в слоях
функциональных (Le_1_2_8_*) и территориальных (Le_1_2_9_*) зон.

Используется:
- F_1_1 (universal_import) после импорта слоя если префикс матчит ZONE_PREFIXES
- F_1_2 (Fsm_1_2_17/18 distributors) при создании target подслоёв из source

Поведение:
- Если поле 'ID' уже есть → no-op (returns False)
- Иначе добавляет 'ID' (String, max length 50) в КОНЕЦ схемы.
  В GPKG (SQLite) ALTER TABLE ADD COLUMN BEFORE недоступен — добавление
  только в конец. Логический «первый после fid» порядок отображения
  настраивается отдельно через QGIS attribute form (вне scope helper).
- Без default value — поле остаётся пустым, заполняется пользователем
  вручную в attribute table или другими функциями.
"""

from typing import Tuple

from qgis.core import QgsField, QgsVectorLayer
from qgis.PyQt.QtCore import QVariant

from Daman_QGIS.utils import log_info, log_warning
from Daman_QGIS.constants import ZONE_PREFIXES

__all__ = ['ensure_id_field', 'is_zone_layer', 'ZONE_PREFIXES']

# Параметры поля
_ID_FIELD_NAME = 'ID'
_ID_FIELD_TYPE = QVariant.String
_ID_FIELD_TYPE_NAME = 'String'
_ID_FIELD_LENGTH = 50


def is_zone_layer(layer_name: str) -> bool:
    """Проверить что имя слоя соответствует Терзон (Le_1_2_9_*) или
    Фунзон (Le_1_2_8_*).

    Args:
        layer_name: Имя слоя (без расширения)

    Returns:
        True если слой попадает под ZONE_PREFIXES.
    """
    if not layer_name:
        return False
    return layer_name.startswith(ZONE_PREFIXES)


def ensure_id_field(layer: QgsVectorLayer) -> bool:
    """Добавить поле 'ID' (String 50) в схему слоя если его нет.

    Безопасно вызывать повторно — если поле уже существует, no-op.

    Args:
        layer: Векторный слой (memory или GPKG-backed).

    Returns:
        True если поле добавлено, False если уже было / не удалось.
    """
    if not layer or not layer.isValid():
        return False

    if layer.fields().indexOf(_ID_FIELD_NAME) >= 0:
        return False  # уже есть, no-op

    provider = layer.dataProvider()
    if provider is None:
        log_warning(
            f"Fsm_1_zone_id: dataProvider() = None для слоя '{layer.name()}'"
        )
        return False

    field = QgsField(
        _ID_FIELD_NAME,
        _ID_FIELD_TYPE,
        _ID_FIELD_TYPE_NAME,
        _ID_FIELD_LENGTH,
    )
    success = provider.addAttributes([field])
    if not success:
        log_warning(
            f"Fsm_1_zone_id: не удалось добавить '{_ID_FIELD_NAME}' "
            f"в слой '{layer.name()}'"
        )
        return False

    layer.updateFields()
    log_info(
        f"Fsm_1_zone_id: Добавлено поле '{_ID_FIELD_NAME}' "
        f"({_ID_FIELD_TYPE_NAME} {_ID_FIELD_LENGTH}) в слой '{layer.name()}'"
    )
    return True
