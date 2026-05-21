# -*- coding: utf-8 -*-
"""
Fsm_1_1_8 - Импорт XML уведомлений о внесении сведений в реестр границ
            (interact_entry_boundaries v2.0.1, Приказ Росреестра П/0104/25 от 27.02.2026)

MVP: обрабатывается только ветка public_easement (type_boundary=18 -
граница публичного сервитута). Остальные 7 типов границ из information_boundary
будут добавлены в следующих итерациях.

Структура субмодулей:
- Fsm_1_1_8_1_parser - парсинг атрибутов public_easement
- Fsm_1_1_8_2_geometry - извлечение геометрии (обёртка над Fsm_1_1_4_3)
- Fsm_1_1_8_3_layer_creator - создание memory-слоя и запись в GPKG

Геометрия EntitySpatial v2.0.1 идентична таковой в КПТ/выписках ЕГРН:
X/Y swap, M-координата = delta_geopoint, multi-contour с дырами.
"""

from .Fsm_1_1_8_iboundary_importer import Fsm_1_1_8_IBoundaryImporter

__all__ = ['Fsm_1_1_8_IBoundaryImporter']
