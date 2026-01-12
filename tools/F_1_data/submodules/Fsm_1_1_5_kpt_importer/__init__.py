# -*- coding: utf-8 -*-
"""
Fsm_1_1_5: Импортер КПТ (Кадастровый План Территории)

Потоковый парсинг XML через lxml.iterparse для файлов 10-100+ MB.
Адаптировано из external_modules/kd_kpt для интеграции в Daman_QGIS.
"""

from .Fsm_1_1_5_kpt_importer import Fsm_1_1_5_KptImporter

__all__ = ['Fsm_1_1_5_KptImporter']
