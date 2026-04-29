# -*- coding: utf-8 -*-
"""
Fsm_6_6_2: Менеджер макетов мастер-плана.

Создание макета А3 через M_34, настройка заголовка, легенды,
экстентов карт и экспорт в PDF.
"""

import os
from typing import Optional, List

from qgis.core import (
    QgsProject, QgsPrintLayout, QgsLayoutExporter,
    QgsLayoutItemMap, QgsLayoutItemLabel, QgsLayoutItemLegend,
    QgsLayoutRenderContext, QgsLayoutSize, QgsVectorLayer,
    Qgis
)

from Daman_QGIS.utils import log_info, log_error, log_warning
from Daman_QGIS.constants import EXPORT_DPI_ROSREESTR
from Daman_QGIS.managers import registry
from Daman_QGIS.managers.styling.submodules.Msm_46_utils import (
    find_legend, filter_print_visible,
)


# Имя слоя границ работ (хардкод)
_BOUNDARIES_LAYER = 'L_1_1_1_Границы_работ'


class Fsm_6_6_2_LayoutManager:
    """Менеджер макетов для схем мастер-плана."""

    def __init__(self, iface):
        """
        Инициализация.

        Args:
            iface: Интерфейс QGIS
        """
        self.iface = iface

    def create_layout(self, layout_name: str) -> Optional[QgsPrintLayout]:
        """
        Создать макет A3 landscape через M_34.

        Args:
            layout_name: Название макета

        Returns:
            QgsPrintLayout или None при ошибке
        """
        try:
            layout_mgr = registry.get('M_34')
            layout = layout_mgr.build_layout(
                layout_name=layout_name,
                page_format='A3',
                orientation='landscape',
                doc_type='Мастер-план'
            )

            if not layout:
                log_error(f"Fsm_6_6_2: M_34 вернул None для '{layout_name}'")
                return None

            log_info(f"Fsm_6_6_2: Макет '{layout_name}' создан")
            return layout

        except Exception as e:
            log_error(f"Fsm_6_6_2: Ошибка создания макета '{layout_name}': {e}")
            return None

    def set_title(self, layout: QgsPrintLayout,
                  location_text: str, drawing_name: str) -> bool:
        """
        Установить тексты на макете:
        - title_label → адрес территории (из DaData)
        - appendix_label → название схемы (drawing_name)

        Args:
            layout: Макет QGIS
            location_text: Адрес территории (многострочный)
            drawing_name: Название схемы

        Returns:
            True при успехе
        """
        for item in layout.items():
            if isinstance(item, QgsLayoutItemLabel):
                if item.id() == 'title_label':
                    item.setText(location_text)
                    log_info(f"Fsm_6_6_2: Адрес территории установлен")
                elif item.id() == 'appendix_label':
                    item.setText(drawing_name)
                    # Убираем underline (appendix по умолчанию с подчёркиванием)
                    text_format = item.textFormat()
                    font = text_format.font()
                    font.setUnderline(False)
                    text_format.setFont(font)
                    item.setTextFormat(text_format)
                    log_info(f"Fsm_6_6_2: Название схемы: {drawing_name}")

        return True

    def set_organization(self, layout: QgsPrintLayout) -> bool:
        """
        Установить подпись организации на макете (только для МП).

        Читает значение `2_3_company` из ProjectDB (GeoPackage проекта)
        и устанавливает текст на label с id='organization_label'.

        Если в макете нет organization_label (например DPT — поля "-" в
        Excel), метод тихо выходит. Если нет gpkg/metadata — устанавливает
        пустую строку и логирует warning, не падает (графика продолжает
        генерироваться).

        Args:
            layout: Макет QGIS

        Returns:
            True если label найден и обработан, False если label отсутствует
            в макете (для DPT — нормальный случай).
        """
        # Найти label
        org_label = None
        for item in layout.items():
            if isinstance(item, QgsLayoutItemLabel) and item.id() == 'organization_label':
                org_label = item
                break

        if org_label is None:
            return False  # элемент не предусмотрен в этом макете (DPT)

        # Прочитать metadata
        company_text = ''
        try:
            project_home = os.path.normpath(QgsProject.instance().homePath())
            structure_manager = registry.get('M_19')
            structure_manager.project_root = project_home
            gpkg_path = structure_manager.get_gpkg_path(create=False)

            if gpkg_path and os.path.exists(gpkg_path):
                from Daman_QGIS.database.project_db import ProjectDB
                project_db = ProjectDB(gpkg_path)
                company_data = project_db.get_metadata('2_3_company')
                if company_data and company_data.get('value'):
                    company_text = str(company_data['value'])
        except Exception as e:
            log_warning(
                f"Fsm_6_6_2: Не удалось прочитать '2_3_company' из ProjectDB: {e}"
            )

        org_label.setText(company_text)
        if company_text:
            log_info(f"Fsm_6_6_2: Подпись организации: {company_text}")
        else:
            log_warning(
                f"Fsm_6_6_2: '2_3_company' пусто в metadata — "
                f"organization_label оставлен без текста"
            )
        return True

    def update_legend(
        self, layout: QgsPrintLayout, visible_layer_names: List[str]
    ) -> bool:
        """
        Обновить легенду: filter_by_map, привязка к main_map.
        Паттерн из Fsm_1_4_5.

        Args:
            layout: Макет QGIS
            visible_layer_names: Имена слоёв для отображения в легенде

        Returns:
            True при успехе
        """
        # Найти легенду (OPT-2: общий helper из Msm_46_utils)
        legend = find_legend(layout)
        main_map = None
        for item in layout.items():
            if isinstance(item, QgsLayoutItemMap) and item.id() == 'main_map':
                main_map = item
                break

        if not legend:
            log_warning("Fsm_6_6_2: Легенда не найдена в макете")
            return False

        if not main_map:
            log_warning("Fsm_6_6_2: main_map не найден в макете")
            return False

        # Привязка к main_map
        legend.setLinkedMap(main_map)

        # Отключаем автообновление для ручного управления
        legend.setAutoUpdateModel(False)

        # Очищаем и заполняем
        model = legend.model()
        root_group = model.rootGroup()
        root_group.removeAllChildren()

        project = QgsProject.instance()

        # Исключаем подложки из легенды (L_1_3_*)
        legend_layer_names = [
            name for name in visible_layer_names
            if not name.startswith('L_1_3_')
        ]

        # Фильтр not_print (Base_layers): защитный слой на случай, если
        # visible_layer_names содержит слои, скрытые от печати. F_6_6
        # уже фильтрует через _expand_layer_patterns, но update_legend
        # принимает произвольный список — защита от прямых вызовов.
        legend_layer_names, hidden_from_print = filter_print_visible(
            legend_layer_names
        )
        if hidden_from_print:
            log_info(
                f"Fsm_6_6_2: Исключены not_print слои из легенды: "
                f"{', '.join(hidden_from_print)}"
            )

        for layer_name in legend_layer_names:
            # Найти слой в проекте
            found_layer = None
            for layer_id, layer in project.mapLayers().items():
                if layer.name() == layer_name:
                    found_layer = layer
                    break

            if found_layer:
                layer_node = root_group.addLayer(found_layer)
                if layer_node:
                    # Описание из Base_layers если доступно
                    description = self._get_layer_description(layer_name)
                    if description:
                        layer_node.setCustomProperty(
                            "legend/title-label", description
                        )

        log_info(
            f"Fsm_6_6_2: Легенда обновлена, "
            f"{len(legend_layer_names)} слоёв"
        )
        return True

    def _get_layer_description(self, layer_name: str) -> Optional[str]:
        """
        Получить описание слоя из Base_layers.json.

        Args:
            layer_name: Имя слоя

        Returns:
            Описание или None
        """
        try:
            from Daman_QGIS.managers import get_reference_managers
            ref_managers = get_reference_managers()
            layer_manager = ref_managers.layer

            if not layer_manager:
                return None

            for layer_data in layer_manager.get_base_layers():
                if layer_data.get('full_name') == layer_name:
                    return layer_data.get('description')
        except Exception:
            pass

        return None

    def apply_main_map_extent(self, layout: QgsPrintLayout) -> bool:
        """
        Установить экстент основной карты по границам работ L_1_1_1.
        Паттерн из Fsm_1_4_5._apply_map_extents.

        Args:
            layout: Макет QGIS

        Returns:
            True при успехе
        """
        boundaries_layer = None
        for layer in QgsProject.instance().mapLayers().values():
            if layer.name() == _BOUNDARIES_LAYER:
                boundaries_layer = layer
                break

        if not boundaries_layer:
            log_warning("Fsm_6_6_2: Слой границ работ не найден")
            return False

        if isinstance(boundaries_layer, QgsVectorLayer) and boundaries_layer.featureCount() == 0:
            log_warning("Fsm_6_6_2: Слой границ пуст")
            return False

        extent_manager = registry.get('M_18')

        # Получаем main_map (размеры из Base_layout.json, без перезаписи)
        main_map = extent_manager.applier.get_map_item_by_id(layout, 'main_map')
        if not main_map:
            log_warning("Fsm_6_6_2: main_map не найден")
            return False

        map_width = main_map.rect().width()
        map_height = main_map.rect().height()

        # Z-order: main_map на дно стека
        layout.moveItemToBottom(main_map)

        # Label Blocking
        for item_id in ['overview_map', 'legend', 'north_arrow']:
            item = layout.itemById(item_id)
            if item:
                main_map.addLabelBlockingItem(item)

        # Экстент по границам работ с равномерным padding
        # Label blocking (выше) резервирует площадь под overlay-элементами
        extent = extent_manager.calculate_extent(
            boundaries_layer, padding_percent=10.0, adaptive=True
        )
        extent = extent_manager.fitter.fit_extent_to_ratio(
            extent, map_width, map_height
        )
        result = extent_manager.applier.apply_extent(main_map, extent)

        if result:
            log_info(f"Fsm_6_6_2: Экстент main_map установлен ({map_width:.0f}x{map_height:.0f} мм)")
        else:
            log_warning("Fsm_6_6_2: Не удалось установить экстент main_map")

        return result

    def apply_overview_scale(
        self, layout: QgsPrintLayout, target_scale: float
    ) -> bool:
        """
        Установить масштаб обзорной карты.

        Args:
            layout: Макет QGIS
            target_scale: Целевой масштаб

        Returns:
            True при успехе
        """
        extent_manager = registry.get('M_18')

        overview_map = extent_manager.applier.get_map_item_by_id(
            layout, 'overview_map'
        )
        if not overview_map:
            log_warning("Fsm_6_6_2: overview_map не найден")
            return False

        # Ставим экстент по границам работ
        boundaries_layer = None
        for layer in QgsProject.instance().mapLayers().values():
            if layer.name() == _BOUNDARIES_LAYER:
                boundaries_layer = layer
                break

        if boundaries_layer:
            extent = extent_manager.calculate_extent(
                boundaries_layer, padding_percent=5.0, adaptive=True
            )
            width, height = extent_manager.fitter.get_map_item_dimensions(
                overview_map
            )
            extent = extent_manager.fit_to_ratio(extent, width, height)

            extent_manager.applier.apply_extent_with_scale(
                overview_map,
                extent,
                scale=target_scale,
                clear_data_defined=True
            )

        log_info(f"Fsm_6_6_2: Масштаб overview_map: 1:{int(target_scale)}")
        return True

    def export_to_pdf(
        self,
        layout: QgsPrintLayout,
        pdf_path: str,
        dpi: int = EXPORT_DPI_ROSREESTR
    ) -> bool:
        """
        Экспорт макета в PDF.

        Args:
            layout: Макет QGIS
            pdf_path: Путь для сохранения
            dpi: Разрешение (по умолчанию 300 DPI)

        Returns:
            True при успехе

        Raises:
            RuntimeError: При ошибке экспорта
        """
        os.makedirs(os.path.dirname(pdf_path), exist_ok=True)

        exporter = QgsLayoutExporter(layout)

        settings = QgsLayoutExporter.PdfExportSettings()
        settings.dpi = dpi
        settings.rasterizeWholeImage = True
        settings.forceVectorOutput = False
        settings.simplifyGeometries = False
        settings.exportMetadata = False

        # Продвинутые эффекты
        layout.renderContext().setFlag(
            QgsLayoutRenderContext.FlagUseAdvancedEffects, True
        )
        layout.renderContext().setFlag(
            QgsLayoutRenderContext.FlagForceVectorOutput, False
        )

        result = exporter.exportToPdf(pdf_path, settings)

        if result != QgsLayoutExporter.Success:
            raise RuntimeError(
                f"Ошибка экспорта в PDF: {pdf_path}, код: {result}"
            )

        log_info(
            f"Fsm_6_6_2: Экспорт PDF: {os.path.basename(pdf_path)} "
            f"({dpi} DPI)"
        )
        return True
