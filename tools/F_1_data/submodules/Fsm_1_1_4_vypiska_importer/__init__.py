# -*- coding: utf-8 -*-
"""
Fsm_1_1_4 - Модуль импорта выписок ЕГРН (DATABASE-DRIVEN)

Структура субмодулей:
- Fsm_1_1_4_3_geometry - Извлечение геометрии из XML
- Fsm_1_1_4_4_layer_creator - Создание слоя и запись в GPKG
- Fsm_1_1_4_6_layer_splitter - Разделение по типам геометрии

Парсинг полей: через FieldMappingManager (ZERO HARDCODE)
Константы: см. Daman_QGIS/constants.py (ROOT_TAG_TO_RECORD_MAP, CLOSURE_TOLERANCE)
"""

from .Fsm_1_1_4_vypiska_importer import Fsm_1_1_4_VypiskaImporter

__all__ = ['Fsm_1_1_4_VypiskaImporter']
