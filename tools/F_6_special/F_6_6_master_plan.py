# -*- coding: utf-8 -*-
"""
F_6_6: Мастер-план - Генерация комплекта PDF-схем мастер-плана на формате А3.

Координатор: загружает Base_drawings.json, фильтрует доступные схемы,
показывает GUI для выбора, генерирует макеты через M_34 и экспортирует PDF.
Результат: один объединённый PDF со всеми выбранными схемами.
"""

import os
from typing import Optional, List, Dict, Any

from qgis.PyQt.QtWidgets import QMessageBox, QFileDialog, QApplication
from qgis.core import (
    QgsProject, QgsMapThemeCollection, QgsLayoutExporter,
    QgsLayoutItemMap, QgsLayoutItemLabel, QgsLayoutItemLegend,
    QgsLayoutRenderContext, QgsLayoutSize, QgsVectorLayer
)
from qgis.core import Qgis

from Daman_QGIS.core.base_tool import BaseTool
from Daman_QGIS.utils import log_info, log_error, log_warning, log_success
from Daman_QGIS.constants import EXPORT_DPI_ROSREESTR
from Daman_QGIS.managers import get_reference_managers, registry

from .submodules.Fsm_6_6_1_dialog import Fsm_6_6_1_Dialog
from .submodules.Fsm_6_6_2_layout_manager import Fsm_6_6_2_LayoutManager
from .submodules.Fsm_6_6_3_pdf_assembler import Fsm_6_6_3_PdfAssembler


# Хардкод подложек
_MAIN_MAP_BASEMAP = 'L_1_3_2_Справочный_слой'
_OVERVIEW_MAP_BASEMAP = 'L_1_3_3_ЦОС'
_BOUNDARIES_LAYER = 'L_1_1_1_Границы_работ'


class F_6_6_MasterPlan(BaseTool):
    """Генерация комплекта PDF-схем мастер-плана."""

    def __init__(self, iface):
        super().__init__(iface)
        self._created_themes: List[str] = []

    def run(self) -> None:
        """Запуск функции."""
        log_info("F_6_6: Запуск функции Мастер-план")

        # Проверка проекта
        if not self.check_project_opened():
            return

        # 1. Загрузить Base_drawings.json, отфильтровать по doc_type="Мастер-план"
        ref_managers = get_reference_managers()
        all_drawings = ref_managers.drawings.get_drawings()

        master_plan_drawings = [
            d for d in all_drawings
            if d.get('doc_type') == 'Мастер-план'
        ]

        if not master_plan_drawings:
            log_warning("F_6_6: Нет записей с doc_type='Мастер-план' в Base_drawings.json")
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Мастер-план",
                "В справочнике чертежей нет записей для мастер-плана."
            )
            return

        # 2. Фильтрация: visible_layers не null (слои могут отсутствовать — warning)
        available_drawings = self._filter_available_drawings(master_plan_drawings)

        if not available_drawings:
            log_warning("F_6_6: Нет схем с заполненными visible_layers")
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Мастер-план",
                "Нет схем с заполненными слоями (visible_layers)."
            )
            return

        log_info(f"F_6_6: Доступно {len(available_drawings)} схем из {len(master_plan_drawings)}")

        # 3. Диалог выбора схем и папки экспорта
        dialog = Fsm_6_6_1_Dialog(available_drawings, self.iface.mainWindow())
        if dialog.exec() == 0:
            log_info("F_6_6: Отмена пользователем")
            return

        selected_drawings = dialog.get_selected_drawings()
        output_folder = dialog.get_output_folder()

        if not selected_drawings:
            log_warning("F_6_6: Не выбрано ни одной схемы")
            return

        if not output_folder:
            log_warning("F_6_6: Не указана папка экспорта")
            return

        os.makedirs(output_folder, exist_ok=True)

        log_info(
            f"F_6_6: Выбрано {len(selected_drawings)} схем, "
            f"папка: {output_folder}"
        )

        # 4. Диалог масштаба обзорной карты (аналог Fsm_1_4_10)
        overview_scale_factor = self._get_overview_scale_factor()
        if overview_scale_factor is None:
            log_info("F_6_6: Отмена выбора масштаба обзорной карты")
            return

        # 5. Генерация PDF для каждой выбранной схемы
        layout_mgr = Fsm_6_6_2_LayoutManager(self.iface)
        pdf_paths: List[str] = []
        self._created_themes = []

        total = len(selected_drawings)
        for i, drawing in enumerate(selected_drawings):
            drawing_name = drawing.get('drawing_name', f'Схема_{i + 1}')
            log_info(f"F_6_6: Обработка схемы {i + 1}/{total}: {drawing_name}")

            try:
                pdf_path = self._generate_single_scheme(
                    drawing=drawing,
                    index=i,
                    output_folder=output_folder,
                    layout_mgr=layout_mgr,
                    overview_scale_factor=overview_scale_factor
                )
                if pdf_path:
                    pdf_paths.append(pdf_path)
                    log_info(f"F_6_6: Схема экспортирована: {pdf_path}")
            except Exception as e:
                log_error(f"F_6_6: Ошибка при генерации схемы '{drawing_name}': {e}")
                continue

        if not pdf_paths:
            log_error("F_6_6: Не удалось создать ни одного PDF")
            QMessageBox.critical(
                self.iface.mainWindow(),
                "Мастер-план",
                "Не удалось создать ни одного PDF."
            )
            self._cleanup_themes()
            return

        # 6. Склейка PDF в один файл
        assembler = Fsm_6_6_3_PdfAssembler()
        merged_filename = "Мастер-план.pdf"
        merged_path = os.path.join(output_folder, merged_filename)

        merge_success = assembler.merge(pdf_paths, merged_path)

        # 7. Очистка временных map themes
        self._cleanup_themes()

        # 8. Открытие результата
        if merge_success:
            log_success(f"F_6_6: Мастер-план создан: {merged_path}")
            self._open_result(merged_path)
        else:
            log_warning("F_6_6: Склейка не удалась, отдельные PDF сохранены")
            self.iface.messageBar().pushMessage(
                "Мастер-план",
                f"Создано {len(pdf_paths)} отдельных PDF в {output_folder}",
                level=Qgis.MessageLevel.Warning,
                duration=5
            )

    def _filter_available_drawings(
        self, drawings: List[Dict]
    ) -> List[Dict]:
        """
        Фильтрация: оставить только схемы, где visible_layers не null.
        Отсутствующие слои — warning, но схема остаётся доступной.

        Args:
            drawings: Список чертежей из Base_drawings.json

        Returns:
            Отфильтрованный список (visible_layers заполнены)
        """
        project = QgsProject.instance()
        project_layer_names = {
            layer.name() for layer in project.mapLayers().values()
        }

        available = []
        for d in drawings:
            visible_layers = d.get('visible_layers')
            if not visible_layers:
                continue

            # Предупреждаем об отсутствующих слоях, но не блокируем
            missing = [
                lyr for lyr in visible_layers
                if lyr not in project_layer_names
            ]
            if missing:
                log_warning(
                    f"F_6_6: Схема '{d.get('drawing_name')}' — "
                    f"отсутствуют слои: {', '.join(missing)}"
                )

            available.append(d)

        return available

    def _get_overview_scale_factor(self) -> Optional[float]:
        """
        Показать диалог выбора масштаба обзорной карты.
        Аналог Fsm_1_4_10, но без привязки к конкретному layout.

        Создаёт временный layout для получения overview_map,
        показывает OverviewPreviewDialog, возвращает scale_factor.

        Returns:
            float scale_factor или None при отмене
        """
        # Получаем масштаб проекта для базового масштаба обзорной карты
        overview_base_scale = self._get_project_overview_scale()
        if not overview_base_scale:
            # Fallback: масштаб 100000
            overview_base_scale = 100000.0

        # Создаём временный layout для превью
        layout_mgr_m34 = registry.get('M_34')
        temp_layout = layout_mgr_m34.build_layout(
            layout_name='_temp_overview_preview', page_format='A3'
        )
        if not temp_layout:
            log_warning("F_6_6: Не удалось создать временный макет для превью")
            return 1.0  # Fallback: базовый масштаб

        project = QgsProject.instance()
        layout_manager = project.layoutManager()
        layout_manager.addLayout(temp_layout)

        try:
            # Настраиваем overview_map с темой ЦОС
            overview_map = None
            for item in temp_layout.items():
                if isinstance(item, QgsLayoutItemMap) and item.id() == 'overview_map':
                    overview_map = item
                    break

            if not overview_map:
                log_warning("F_6_6: overview_map не найден во временном макете")
                return 1.0

            # Устанавливаем базовый масштаб
            overview_map.setScale(overview_base_scale)

            # Устанавливаем экстент по границам работ
            self._set_overview_extent(overview_map)

            from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_4_10_overview_preview_dialog import (
                OverviewPreviewDialog
            )
            preview_dialog = OverviewPreviewDialog(
                temp_layout, overview_base_scale, self.iface.mainWindow()
            )

            if preview_dialog.exec() == 1:  # Accepted
                _dpi, scale_factor = preview_dialog.get_selected_variant()
                log_info(f"F_6_6: Выбран масштаб обзорной карты: x{scale_factor}")
                return scale_factor
            else:
                return None

        finally:
            # Удаляем временный макет
            layout_manager.removeLayout(temp_layout)

    def _get_project_overview_scale(self) -> Optional[float]:
        """
        Получить масштаб обзорной карты из метаданных проекта.
        Масштаб = масштаб проекта * 100.

        Returns:
            float масштаб или None
        """
        try:
            project_home = os.path.normpath(QgsProject.instance().homePath())
            structure_manager = registry.get('M_19')
            structure_manager.project_root = project_home
            gpkg_path = structure_manager.get_gpkg_path(create=False)

            if gpkg_path and os.path.exists(gpkg_path):
                from Daman_QGIS.database.project_db import ProjectDB
                project_db = ProjectDB(gpkg_path)
                scale_data = project_db.get_metadata('2_10_main_scale')

                if scale_data and scale_data.get('value'):
                    scale_value = scale_data['value']
                    if isinstance(scale_value, str) and ':' in scale_value:
                        scale_number = int(scale_value.split(':')[1])
                    else:
                        scale_number = int(scale_value)

                    overview_scale = scale_number * 100
                    log_info(f"F_6_6: Масштаб обзорной карты: 1:{overview_scale}")
                    return float(overview_scale)
        except Exception as e:
            log_warning(f"F_6_6: Не удалось получить масштаб проекта: {e}")

        return None

    def _set_overview_extent(self, overview_map: QgsLayoutItemMap) -> None:
        """
        Установить экстент обзорной карты по слою границ работ.

        Args:
            overview_map: Элемент карты
        """
        try:
            boundaries_layer = None
            for layer in QgsProject.instance().mapLayers().values():
                if layer.name() == _BOUNDARIES_LAYER:
                    boundaries_layer = layer
                    break

            if not boundaries_layer:
                log_warning("F_6_6: Слой границ работ не найден для обзорной карты")
                return

            extent_manager = registry.get('M_18')
            extent = extent_manager.calculate_extent(
                boundaries_layer, padding_percent=5.0, adaptive=True
            )
            width, height = extent_manager.fitter.get_map_item_dimensions(overview_map)
            extent = extent_manager.fit_to_ratio(extent, width, height)
            extent_manager.applier.apply_extent(overview_map, extent)
        except Exception as e:
            log_warning(f"F_6_6: Не удалось установить экстент обзорной карты: {e}")

    def _generate_single_scheme(
        self,
        drawing: Dict,
        index: int,
        output_folder: str,
        layout_mgr: 'Fsm_6_6_2_LayoutManager',
        overview_scale_factor: float
    ) -> Optional[str]:
        """
        Генерация одной схемы мастер-плана.

        Args:
            drawing: Запись из Base_drawings.json
            index: Порядковый номер (0-based)
            output_folder: Папка для PDF
            layout_mgr: Менеджер макетов
            overview_scale_factor: Множитель масштаба обзорной карты

        Returns:
            Путь к PDF или None при ошибке
        """
        drawing_name = drawing.get('drawing_name', f'Схема_{index + 1}')
        visible_layers = drawing.get('visible_layers', [])
        overview_layers = drawing.get('overview_layers', [])

        # a/b. Списки слоёв
        main_layers = list(visible_layers) + [_MAIN_MAP_BASEMAP]
        overview_layer_list = list(overview_layers) + [_OVERVIEW_MAP_BASEMAP]

        # c/d. Создать map themes
        main_theme_name = f'F_6_6_main_{index}'
        overview_theme_name = f'F_6_6_overview_{index}'

        self._create_map_theme(main_theme_name, main_layers)
        self._created_themes.append(main_theme_name)

        self._create_map_theme(overview_theme_name, overview_layer_list)
        self._created_themes.append(overview_theme_name)

        # e. Создать макет A3 через M_34
        layout_name = f'Мастер-план — {drawing_name}'
        layout = layout_mgr.create_layout(layout_name)
        if not layout:
            log_error(f"Fsm_6_6_2: Не удалось создать макет для '{drawing_name}'")
            return None

        project = QgsProject.instance()
        lm = project.layoutManager()
        lm.addLayout(layout)

        try:
            # f/g. Привязать темы к картам
            for item in layout.items():
                if isinstance(item, QgsLayoutItemMap):
                    if item.id() == 'main_map':
                        item.setFollowVisibilityPreset(True)
                        item.setFollowVisibilityPresetName(main_theme_name)
                    elif item.id() == 'overview_map':
                        item.setFollowVisibilityPreset(True)
                        item.setFollowVisibilityPresetName(overview_theme_name)

            # h. Заголовок
            layout_mgr.set_title(layout, drawing_name)

            # i. Легенда (filter_by_map)
            layout_mgr.update_legend(layout, main_layers)

            # j. Экстент карты по границам работ L_1_1_1
            layout_mgr.apply_main_map_extent(layout)

            # k. Масштаб обзорной карты
            overview_base = self._get_project_overview_scale() or 100000.0
            target_scale = overview_base * overview_scale_factor
            layout_mgr.apply_overview_scale(layout, target_scale)

            # l. Экспорт PDF
            safe_name = drawing_name.replace('/', '_').replace('\\', '_')
            pdf_filename = f"{index + 1:02d}_{safe_name}.pdf"
            pdf_path = os.path.join(output_folder, pdf_filename)

            layout_mgr.export_to_pdf(layout, pdf_path)

        finally:
            # m. Удалить макет из проекта
            lm.removeLayout(layout)

        return pdf_path

    def _create_map_theme(
        self, theme_name: str, layer_names: List[str]
    ) -> None:
        """
        Создать map theme с указанными слоями.

        Args:
            theme_name: Имя темы
            layer_names: Список имён слоёв для включения
        """
        project = QgsProject.instance()
        theme_collection = project.mapThemeCollection()

        # Удаляем если существует
        if theme_collection.hasMapTheme(theme_name):
            theme_collection.removeMapTheme(theme_name)

        theme_record = QgsMapThemeCollection.MapThemeRecord()
        layer_records = []

        layer_names_set = set(layer_names)

        for layer_id, layer in project.mapLayers().items():
            if layer.name() in layer_names_set:
                record = QgsMapThemeCollection.MapThemeLayerRecord(layer)
                record.isVisible = True
                record.usingCurrentStyle = True
                record.currentStyle = layer.styleManager().currentStyle()
                layer_records.append(record)

        theme_record.setLayerRecords(layer_records)
        theme_collection.insert(theme_name, theme_record)

        log_info(f"F_6_6: Создана тема '{theme_name}' с {len(layer_records)} слоями")

    def _cleanup_themes(self) -> None:
        """Удалить все временные map themes, созданные при генерации."""
        theme_collection = QgsProject.instance().mapThemeCollection()
        for theme_name in self._created_themes:
            try:
                if theme_collection.hasMapTheme(theme_name):
                    theme_collection.removeMapTheme(theme_name)
            except Exception as e:
                log_warning(f"F_6_6: Не удалось удалить тему '{theme_name}': {e}")

        self._created_themes.clear()
        log_info("F_6_6: Временные темы очищены")

    def _open_result(self, pdf_path: str) -> None:
        """
        Открыть результат в системном просмотрщике.

        Args:
            pdf_path: Путь к PDF файлу
        """
        try:
            import subprocess
            import sys

            if sys.platform == 'win32':
                os.startfile(pdf_path)
            elif sys.platform == 'darwin':
                subprocess.run(['open', pdf_path])
            else:
                subprocess.run(['xdg-open', pdf_path])

            log_info(f"F_6_6: Открыт файл: {pdf_path}")
        except Exception as e:
            log_warning(f"F_6_6: Не удалось открыть файл: {e}")
            self.iface.messageBar().pushMessage(
                "Мастер-план",
                f"PDF создан: {pdf_path}",
                level=Qgis.MessageLevel.Info,
                duration=10
            )
