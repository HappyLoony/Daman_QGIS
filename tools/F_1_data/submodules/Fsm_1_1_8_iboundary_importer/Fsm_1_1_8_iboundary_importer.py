# -*- coding: utf-8 -*-
"""
Fsm_1_1_8 - Импортёр XML уведомлений о внесении сведений в реестр границ
            (interact_entry_boundaries v2.0.1, Приказ Росреестра П/0104/25 от 27.02.2026)

MVP: обрабатывает только ветку public_easement (type_boundary=18 -
граница публичного сервитута). Создаёт один слой "Уведомление_сервитут"
(MultiPolygonM), 16 атрибутов сервитута.

Архитектура (паттерн Fsm_1_1_4):
- Fsm_1_1_8_1_parser.parse_iboundary_xml - парсинг атрибутов
- Fsm_1_1_8_2_geometry.extract_iboundary_geometry - геометрия (обёртка над Fsm_1_1_4_3)
- Fsm_1_1_8_3_layer_creator.create_and_save_layer - слой + GPKG

CRS: на MVP-уровне используется CRS проекта (из метаданных через
BaseImporter.get_project_crs). sk_code из XML сохраняется в атрибуте
для последующей ручной верификации - автоматический resolver не реализован.
"""

import os
from typing import Union, List, Dict, Any, Optional

from qgis.core import QgsProject, QgsCoordinateReferenceSystem

from Daman_QGIS.utils import log_info, log_warning, log_error
from ...core import BaseImporter
from .Fsm_1_1_8_1_parser import parse_iboundary_xml
from .Fsm_1_1_8_2_geometry import extract_iboundary_geometry, get_primary_geometry
from .Fsm_1_1_8_3_layer_creator import create_and_save_layer, LAYER_NAME


class Fsm_1_1_8_IBoundaryImporter(BaseImporter):
    """Импортёр уведомлений interact_entry_boundaries v2.0.1 (public_easement MVP)."""

    def __init__(self, iface):
        super().__init__(iface)

    def supports_format(self, file_extension: str) -> bool:
        return file_extension.lower() in ('.xml',)

    def import_file(
        self,
        file_path: Union[str, List[str]],
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Импорт одного XML или списка XML interact_entry_boundaries.

        Args:
            file_path: путь к XML или список путей.
            **kwargs:
                - gpkg_path: путь к GPKG (если не задан - берётся из
                  project_manager.project_db.gpkg_path).

        Returns:
            Dict {'success': bool, 'layers': [...], 'message': str, 'errors': [...]}.
        """
        # Нормализуем вход в список
        if isinstance(file_path, list):
            files = file_path
        else:
            files = [file_path]

        if not files:
            return {
                'success': False,
                'layers': [],
                'message': 'Не указаны файлы для импорта',
                'errors': [],
            }

        # GPKG-путь
        gpkg_path: Optional[str] = kwargs.get('gpkg_path')
        if not gpkg_path:
            if self.project_manager and hasattr(self.project_manager, 'project_db'):
                gpkg_path = getattr(self.project_manager.project_db, 'gpkg_path', None)

        if not gpkg_path:
            log_warning(
                "Fsm_1_1_8: gpkg_path не определён, слой создаётся только в памяти"
            )

        log_info(f"Fsm_1_1_8: Начало импорта {len(files)} уведомлений о границах")

        # CRS - из метаданных проекта (BaseImporter)
        crs = self.get_project_crs()
        if crs is None or not crs.isValid():
            log_warning(
                "Fsm_1_1_8: CRS проекта не определён, используется CRS QGIS-проекта по умолчанию"
            )
            crs = QgsProject.instance().crs()

        # Собираем все фичи из всех файлов
        all_features: List[Dict[str, Any]] = []
        success_files = 0
        error_files = 0
        errors: List[str] = []

        for f in files:
            try:
                parsed = parse_iboundary_xml(f)
            except Exception as e:
                import traceback
                log_error(f"Fsm_1_1_8: Ошибка парсинга {os.path.basename(f)}: {e}")
                log_error(f"Fsm_1_1_8: {traceback.format_exc()}")
                errors.append(f"{os.path.basename(f)}: {e}")
                error_files += 1
                continue

            if not parsed:
                # Файл валидно распарсен, но не содержит ни одной public_easement
                continue

            # Извлекаем геометрию для каждой ветки
            for attrs in parsed:
                pe_branch = attrs.pop('_pe_branch_element', None)
                geometry = None
                if pe_branch is not None:
                    contours_loc = pe_branch.find('contours_location')
                    if contours_loc is not None:
                        try:
                            geoms = extract_iboundary_geometry(contours_loc)
                            geometry = get_primary_geometry(geoms)
                        except Exception as e:
                            import traceback
                            log_error(
                                f"Fsm_1_1_8: Ошибка извлечения геометрии "
                                f"({attrs.get('reg_numb_border') or attrs.get('guid')}): {e}"
                            )
                            log_error(f"Fsm_1_1_8: {traceback.format_exc()}")

                if geometry is None:
                    log_warning(
                        f"Fsm_1_1_8: Геометрия не извлечена для "
                        f"{attrs.get('reg_numb_border') or attrs.get('guid')} "
                        f"({os.path.basename(f)})"
                    )

                # changing_public_easement несёт ТОЛЬКО изменяемые контуры (полные,
                # после уточнения). Неизменные контуры сервитута в XML отсутствуют.
                # Например, у многоконтурного сервитута с 2+ контурами и изменением
                # в одном контуре - XML содержит только этот контур, а не все.
                # Полную геометрию даёт establishment_* (первичная регистрация) или
                # отдельная выписка extract_about_boundary из ЕГРН.
                if attrs.get('is_changing'):
                    log_warning(
                        f"Fsm_1_1_8: {os.path.basename(f)} - changing_public_easement "
                        f"(reg_numb_border={attrs.get('reg_numb_border')}): импортированы "
                        f"только изменяемые контуры сервитута, не вся геометрия. "
                        f"Если сервитут многоконтурный - неизменные контуры в XML отсутствуют. "
                        f"Полная геометрия доступна через выписку из ЕГРН (extract_about_boundary)."
                    )

                attrs['geometry'] = geometry
                all_features.append(attrs)

            success_files += 1

        log_info(
            f"Fsm_1_1_8: Обработано файлов: успешно={success_files}, "
            f"ошибок={error_files}; извлечено объектов: {len(all_features)}"
        )

        if not all_features:
            return {
                'success': False,
                'layers': [],
                'message': 'Не извлечено ни одного объекта public_easement',
                'errors': errors,
            }

        # Создаём слой и (опц.) сохраняем в GPKG
        layer = create_and_save_layer(
            features_data=all_features,
            output_gpkg_path=gpkg_path,
            crs=crs,
        )

        if layer is None:
            return {
                'success': False,
                'layers': [],
                'message': 'Ошибка создания слоя',
                'errors': errors + ['create_and_save_layer вернул None'],
            }

        return {
            'success': True,
            'layers': [layer],
            'message': (
                f"Импортировано {len(all_features)} объектов в слой '{LAYER_NAME}'"
            ),
            'errors': errors,
        }
