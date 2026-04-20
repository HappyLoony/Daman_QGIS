# -*- coding: utf-8 -*-
"""
Модуль управления макетами и компоновками
Часть инструмента F_1_4_Запрос
"""

import os
from qgis.PyQt.QtXml import QDomDocument
from qgis.core import (
    QgsProject, QgsPrintLayout,
    QgsLayoutExporter, QgsReadWriteContext,
    QgsLayoutItemLabel, QgsLayoutItemMap, QgsLayoutItemLegend,
    QgsRectangle, QgsVectorLayer
)
from Daman_QGIS.database.project_db import ProjectDB
from Daman_QGIS.constants import PLUGIN_NAME, EXPORT_DPI_ROSREESTR
from Daman_QGIS.utils import log_info, log_warning, log_error
from Daman_QGIS.title_generator import TitleGenerator
from Daman_QGIS.managers import registry
from Daman_QGIS.managers.styling.submodules.Msm_46_utils import find_legend


class LayoutManager:
    """Менеджер макетов и компоновок"""
    
    def _get_layout(self):
        """Получение макета из менеджера по имени
        
        Returns:
            QgsPrintLayout или None если макет не найден
        """
        if not self.layout_name:
            return None
        
        # Получаем макет из менеджера проекта
        return QgsProject.instance().layoutManager().layoutByName(self.layout_name)
    
    def __init__(self, iface):
        """Инициализация менеджера

        Args:
            iface: Интерфейс QGIS
        """
        self.iface = iface
        self.layout_name = None  # Храним только имя макета, не ссылку
        self._layout_ref = None  # Ссылка на layout для предотвращения удаления сборщиком мусора

    def create_layout(self, selected_layer_ids, nspd_layers, use_satellite=False):
        """Создание компоновки программно из JSON конфигурации

        Args:
            selected_layer_ids: Список ID выбранных слоев
            nspd_layers: Словарь выбранных слоев НСПД
            use_satellite: Использовать спутниковый снимок вместо ЦОС для главной карты

        Returns:
            tuple: (success, error_msg)
        """
        self.layout_name = None
        self._layout_ref = None

        project = QgsProject.instance()

        # Проверяем наличие слоев НСПД с данными
        available_nspd_layers = []
        for layer in project.mapLayers().values():
            layer_name = layer.name()
            if (layer_name.startswith('L_1_2_') or layer_name.startswith('Le_1_2_')) and isinstance(layer, QgsVectorLayer):
                if hasattr(layer, 'featureCount') and layer.featureCount() > 0:
                    available_nspd_layers.append(layer_name)

        if not available_nspd_layers:
            log_info("Fsm_1_4_5: Макет не создается - нет слоев НСПД с данными для отображения")
            raise RuntimeError("Нет слоев НСПД для отображения")

        # Удаляем все старые макеты "Графика к запросу"
        layouts_to_remove = []
        for layout in project.layoutManager().layouts():
            if layout.name().startswith("Графика к запросу"):
                layout_name_to_remove = layout.name()
                layouts_to_remove.append((layout, layout_name_to_remove))

        for layout, layout_name_to_remove in layouts_to_remove:
            project.layoutManager().removeLayout(layout)
            log_info(f"Fsm_1_4_5: Удален старый макет: {layout_name_to_remove}")

        layout_name = "Графика к запросу"
        layout_mgr = registry.get('M_34')

        # Программная генерация из JSON
        layout = layout_mgr.build_layout(layout_name=layout_name, page_format='A4')

        if not layout:
            raise RuntimeError("Не удалось создать макет из JSON конфигурации")

        # Через M_34 — корректная обработка конфликта имён
        # (removeLayout(existing) + addLayout(new))
        if not layout_mgr.add_layout_to_project(layout):
            raise RuntimeError("Не удалось добавить макет в менеджер")

        self.layout_name = layout_name
        self._layout_ref = layout

        log_info(f"Fsm_1_4_5: Макет '{layout_name}' создан")

        # Настройка макета
        self.update_object_name()
        self.update_legend_layers(selected_layer_ids, nspd_layers)
        self.configure_map_filters(nspd_layers, use_satellite)
        self._apply_map_extents(layout)

        return True, None

    def _apply_map_extents(self, layout):
        """Программная установка экстентов карт через M_18_ExtentManager

        Использует адаптивный padding для вытянутых bounding box.
        Заменяет data-defined выражения в шаблоне.

        Масштабы:
        - main_map: по экстенту слоя границ с padding 10%
        - overview_map: масштаб проекта * 100 (для показа контекста расположения)

        Args:
            layout: QgsPrintLayout макет
        """
        import os

        # Ищем слой границ работ
        boundaries_layer = None
        for layer in QgsProject.instance().mapLayers().values():
            if layer.name() == 'L_1_1_1_Границы_работ':
                boundaries_layer = layer
                break

        if not boundaries_layer:
            log_warning("Fsm_1_4_5: Слой L_1_1_1_Границы_работ не найден, экстент не установлен")
            return

        if boundaries_layer.featureCount() == 0:
            log_warning("Fsm_1_4_5: Слой границ пуст, экстент не установлен")
            return

        extent_manager = registry.get('M_18')

        # === MAIN_MAP: экстент по границам работ с равномерным padding ===
        # Размеры из Base_layout.json (без перезаписи)
        main_map = extent_manager.applier.get_map_item_by_id(layout, 'main_map')
        if not main_map:
            log_warning("Fsm_1_4_5: Карта 'main_map' не найдена в макете")
            return

        map_width = main_map.rect().width()
        map_height = main_map.rect().height()

        if map_width <= 0 or map_height <= 0:
            log_error(
                f"Fsm_1_4_5: Некорректные размеры main_map из Base_layout.json: "
                f"{map_width}x{map_height} мм"
            )
            return

        # Z-order: main_map на дно стека (overlay поверх)
        layout.moveItemToBottom(main_map)

        # Label Blocking: подписи карты не рендерятся под overlay-элементами
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
        result_main = extent_manager.applier.apply_extent(main_map, extent)

        if result_main:
            log_info(
                f"Fsm_1_4_5: Экстент main_map установлен "
                f"({map_width:.0f}x{map_height:.0f} мм)"
            )
        else:
            log_warning("Fsm_1_4_5: Не удалось установить экстент main_map")

        # M_46: централизованное управление условниками
        # collect → calculate → plan (wrap/col/symbol) → apply (inline)
        legend_mgr = registry.get('M_46')
        config_key = self._resolve_config_key(layout)
        legend_mgr.plan_and_apply(layout, config_key)

        # Адаптация легенды + сдвиг экстента main_map на юг
        # (территория сверху, подложка под легендой снизу — паттерн F_6_6)
        layout_mgr_m34 = registry.get('M_34')
        layout_mgr_m34.adapt_legend(layout)

        # === OVERVIEW_MAP: масштаб проекта * 100 для контекста ===
        # Обзорная карта должна показывать место расположения относительно НП

        # Получаем масштаб проекта из метаданных
        overview_scale = None
        try:
            project_home = os.path.normpath(QgsProject.instance().homePath())
            structure_manager = registry.get('M_19')
            structure_manager.project_root = project_home
            gpkg_path = structure_manager.get_gpkg_path(create=False)

            if gpkg_path and os.path.exists(gpkg_path):
                project_db = ProjectDB(gpkg_path)
                scale_data = project_db.get_metadata('2_10_main_scale')

                if scale_data and scale_data.get('value'):
                    scale_value = scale_data['value']
                    # Преобразуем "1:1000" или "1000" в число
                    if isinstance(scale_value, str) and ':' in scale_value:
                        scale_number = int(scale_value.split(':')[1])
                    else:
                        scale_number = int(scale_value)

                    # Масштаб обзорной карты = масштаб проекта * 100
                    overview_scale = scale_number * 100
                    log_info(f"Fsm_1_4_5: Масштаб обзорной карты: 1:{overview_scale} (проект 1:{scale_number} * 100)")
        except Exception as e:
            log_warning(f"Fsm_1_4_5: Не удалось получить масштаб проекта: {e}")

        # Получаем карту overview_map
        overview_map = extent_manager.applier.get_map_item_by_id(layout, 'overview_map')
        if overview_map:
            # Вычисляем экстент с небольшим padding
            extent = extent_manager.calculate_extent(
                boundaries_layer,
                padding_percent=5.0,
                adaptive=True
            )

            # Подгоняем под aspect ratio карты
            width, height = extent_manager.fitter.get_map_item_dimensions(overview_map)
            extent = extent_manager.fit_to_ratio(extent, width, height)

            # Применяем экстент с масштабом
            if overview_scale:
                result_overview = extent_manager.applier.apply_extent_with_scale(
                    overview_map,
                    extent,
                    scale=overview_scale,
                    clear_data_defined=True
                )
            else:
                # Fallback: если масштаб не определён, используем большой padding
                result_overview = extent_manager.apply_layer_extent_to_map(
                    layout,
                    map_id='overview_map',
                    layer=boundaries_layer,
                    padding_percent=500.0,  # Большой padding как fallback
                    adaptive_padding=True,
                    fit_to_map_ratio=True
                )

            if result_overview:
                log_info("Fsm_1_4_5: Экстент overview_map установлен программно")
            else:
                log_warning("Fsm_1_4_5: Не удалось установить экстент overview_map")
        else:
            log_warning("Fsm_1_4_5: Карта 'overview_map' не найдена в макете")

    def _resolve_config_key(self, layout) -> str:
        """Определить config_key Base_layout для текущего макета F_1_4.

        F_1_4 всегда готовит материалы ДПТ → суффикс 'DPT'.
        Формат/ориентация листа берутся из метаданных проекта через M_34.

        Args:
            layout: QgsPrintLayout (не используется, оставлен для расширения
                до передачи формата из самого layout в будущем).

        Returns:
            Строковый ключ вида 'A4_landscape_DPT' (для Base_layout.json).
        """
        layout_mgr = registry.get('M_34')
        meta_format, meta_orientation = layout_mgr.get_page_format_from_metadata()
        orientation_code = layout_mgr.get_orientation_code(meta_orientation)
        return f"{meta_format}_{orientation_code}_DPT"

    def update_object_name(self):
        """Обновление названия объекта в заголовке

        Использует TitleGenerator для формирования заголовка схемы на основе метаданных проекта.

        Returns:
            bool: Успешность обновления
        """
        # Получаем макет из менеджера
        layout = self._get_layout()
        if not layout:
            return False

        # Получаем метаданные из БД
        project_home = os.path.normpath(QgsProject.instance().homePath())
        structure_manager = registry.get('M_19')
        structure_manager.project_root = project_home
        gpkg_path = structure_manager.get_gpkg_path(create=False)

        # Значения по умолчанию
        metadata_dict = {
            "1_1_full_name": "объекта",
            "1_2_object_type": "Площадной",
            "1_2_1_object_type_value": "-",
            "1_5_doc_type": "ДПТ",
            "1_6_stage": "Первичная",
            "1_7_is_single_object": "Да"
        }

        # Загружаем метаданные из БД
        if gpkg_path and os.path.exists(gpkg_path):
            project_db = ProjectDB(gpkg_path)

            for key in metadata_dict.keys():
                metadata = project_db.get_metadata(key)
                if metadata and metadata['value']:
                    metadata_dict[key] = metadata['value']

        # Генерируем заголовок через TitleGenerator
        title_generator = TitleGenerator()
        title_text = title_generator.generate_scheme_title(metadata_dict)

        # Находим элемент заголовка в компоновке и обновляем его
        for item in layout.items():
            if isinstance(item, QgsLayoutItemLabel) and item.id() == 'title_label':
                item.setText(title_text)
                log_info(f"Fsm_1_4_5: Заголовок схемы обновлен: {title_text}")
                return True

        log_warning("Fsm_1_4_5: Элемент заголовка 'title_label' не найден в компоновке")
        return False

    def update_legend_layers(self, selected_layer_ids, nspd_layers):
        """Обновление слоев в легенде

        Добавляет в легенду векторные слои из okno_egrn
        для корректного отображения стилей и названий.

        Args:
            selected_layer_ids: Список ID выбранных слоев
            nspd_layers: Словарь выбранных слоев НСПД

        Returns:
            bool: Успешность обновления
        """
        # Получаем макет из менеджера
        layout = self._get_layout()
        if not layout:
            return False
        # Находим элемент легенды (OPT-2: общий helper из Msm_46_utils)
        legend = find_legend(layout)

        if not legend:
            log_warning("Fsm_1_4_5: Легенда не найдена в шаблоне")
            return False

        # Отключаем автообновление
        legend.setAutoUpdateModel(False)

        # Получаем модель легенды
        model = legend.model()
        root_group = model.rootGroup()

        # Очищаем существующие элементы
        root_group.removeAllChildren()

        project = QgsProject.instance()

        # Получаем метаданные из БД для формирования названия слоя границ
        project_home = os.path.normpath(QgsProject.instance().homePath())
        structure_manager = registry.get('M_19')
        structure_manager.project_root = project_home
        gpkg_path = structure_manager.get_gpkg_path(create=False)

        # Значения по умолчанию
        metadata_dict = {
            "1_2_object_type": "Площадной",
            "1_2_1_object_type_value": "-",
            "1_5_doc_type": "ДПТ",
            "1_6_stage": "Первичная",
            "1_7_is_single_object": "Да"
        }

        # Загружаем метаданные из БД
        if gpkg_path and os.path.exists(gpkg_path):
            project_db = ProjectDB(gpkg_path)

            for key in metadata_dict.keys():
                metadata = project_db.get_metadata(key)
                if metadata and metadata['value']:
                    metadata_dict[key] = metadata['value']

        # Добавляем слои в легенду в правильном порядке
        # Сначала проверяем слой границ работ (L_1_1_1)
        for layer_id in selected_layer_ids:
            layer = project.mapLayer(layer_id)
            if layer and layer.name() == 'L_1_1_1_Границы_работ':
                layer_node = root_group.addLayer(layer)
                if layer_node:
                    # Генерируем название слоя границ через TitleGenerator
                    title_generator = TitleGenerator()
                    legend_title_base = title_generator.generate_boundary_layer_title(metadata_dict)

                    # Wrap применит M_46 (Msm_46_4.InlinePlacement) на основе плана
                    legend_title = legend_title_base

                    layer_node.setCustomProperty("legend/title-label", legend_title)
                break

        # Затем добавляем векторные слои ЕГРН в порядке выбора пользователя
        # ВАЖНО: Новый формат nspd_layers = {layer_name: True}
        # Получаем информацию о слоях из Base_layers.json для определения порядка и описаний
        from Daman_QGIS.managers import get_reference_managers

        ref_managers = get_reference_managers()
        layer_manager = ref_managers.layer

        if layer_manager and nspd_layers:
            all_base_layers = layer_manager.get_base_layers()

            # Создаём маппинг: layer_name -> (description, order_layers)
            layer_info_map = {}
            for idx, layer_data in enumerate(all_base_layers):
                full_name = layer_data.get('full_name', '')
                description = layer_data.get('description', full_name)
                # КРИТИЧЕСКИ ВАЖНО: Используем order_layers из Base_layers.json, а НЕ idx
                order_layers = layer_data.get('order_layers', 999)
                try:
                    order_layers = int(order_layers) if order_layers and order_layers != '-' else 999
                except (ValueError, TypeError):
                    order_layers = 999
                layer_info_map[full_name] = (description, order_layers)

            # Собираем выбранные слои с порядком из Base_layers.json
            selected_layers_with_order = []
            for layer_name in nspd_layers.keys():
                if layer_name in layer_info_map:
                    description, order = layer_info_map[layer_name]
                    selected_layers_with_order.append((layer_name, description, order))

            # Сортируем по порядку из Base_layers.json
            selected_layers_with_order.sort(key=lambda x: x[2])

            # Добавляем слои в легенду
            for layer_name, legend_title, order in selected_layers_with_order:
                # Ищем слой в проекте
                found_layer = None
                for layer_id, layer in project.mapLayers().items():
                    if layer.name() == layer_name:
                        found_layer = layer
                        break

                # Добавляем найденный слой в легенду
                if found_layer:
                    layer_node = root_group.addLayer(found_layer)
                    if layer_node:
                        # Wrap применит M_46 (Msm_46_4.InlinePlacement) на основе плана
                        wrapped_title = legend_title
                        layer_node.setCustomProperty("legend/title-label", wrapped_title)

        # Обновляем размер легенды
        legend.adjustBoxSize()

        return True

    def configure_map_filters(self, nspd_layers, use_satellite=False):
        """Настройка фильтров слоев для карт через темы (Map Themes)

        Создает две темы карт:
        - F_1_4_1_main_map: выбранные слои + подложка L_1_3_2_NSPD_Ref (если use_satellite=False) или L_1_3_1_NSPD_Ortho (ЕЭКО ортофото, если use_satellite=True)
        - F_1_4_2_overview_map: только слои с 1_1_1 и L_1_3_3_NSPD_Base (ЦОС всегда включена в обзорной)

        Args:
            nspd_layers: Словарь выбранных слоев НСПД
            use_satellite: Если True - использовать ЕЭКО ортофото на главной карте, иначе L_1_3_2_NSPD_Ref

        Returns:
            bool: Успешность настройки
        """
        # Получаем макет из менеджера
        layout = self._get_layout()
        if not layout:
            log_warning("Fsm_1_4_5: Макет не создан или удален, пропускаем настройку фильтров")
            return False

        project = QgsProject.instance()
        map_theme_collection = project.mapThemeCollection()

        # Удаляем старые темы если существуют
        if map_theme_collection.hasMapTheme('F_1_4_1_main_map'):
            map_theme_collection.removeMapTheme('F_1_4_1_main_map')
        if map_theme_collection.hasMapTheme('F_1_4_2_overview_map'):
            map_theme_collection.removeMapTheme('F_1_4_2_overview_map')

        # Создаем записи для тем
        from qgis.core import QgsMapThemeCollection

        main_theme_record = QgsMapThemeCollection.MapThemeRecord()
        overview_theme_record = QgsMapThemeCollection.MapThemeRecord()

        main_theme_layers = []
        overview_theme_layers = []

        # ВАЖНО: Новый формат nspd_layers = {layer_name: True}
        # Создаём множество выбранных слоёв для быстрого поиска
        selected_layer_names = set(nspd_layers.keys()) if nspd_layers else set()

        # Проходим по всем слоям и создаем записи для тем
        for layer_id, layer in project.mapLayers().items():
            layer_name = layer.name()

            # Создаем запись слоя для темы
            layer_record = QgsMapThemeCollection.MapThemeLayerRecord(layer)
            layer_record.usingCurrentStyle = True
            layer_record.currentStyle = layer.styleManager().currentStyle()

            # Для главной карты:
            # Показываем только выбранные слои + границы + подложки
            layer_is_selected = False

            # Границы работ всегда видимы (исключая буферные Le_1_1_2 и Le_1_1_3)
            if 'L_1_1_1' in layer_name:
                layer_is_selected = True
            # Буферные слои НЕ отображаем
            elif layer_name.startswith('Le_1_1_2') or layer_name.startswith('Le_1_1_3'):
                layer_is_selected = False
            # Подложки всегда видимы
            elif layer_name.startswith('L_1_3_') or layer_name.startswith('Le_1_3_'):
                layer_is_selected = True
            # Проверяем выбранные векторные слои
            elif layer_name in selected_layer_names:
                layer_is_selected = True
            
            # Если слой не выбран - пропускаем
            if not layer_is_selected:
                continue
            
            # ГЛАВНАЯ КАРТА: Используем L_1_3_2_NSPD_Ref (НСПД) по умолчанию
            # Если use_satellite=True - показываем ЕЭКО ортофото (L_1_3_1), скрываем схематичные подложки НСПД
            # Если use_satellite=False - показываем L_1_3_2_NSPD_Ref, скрываем ортофото
            if use_satellite:
                # Режим ортофото: показываем ЕЭКО ортофото, скрываем схематичные подложки НСПД
                if 'L_1_3_2' in layer_name or 'L_1_3_3' in layer_name:
                    # Скрываем Справочный слой и ЦОС
                    layer_record.isVisible = False
                elif 'L_1_3_1' in layer_name:
                    # Показываем ЕЭКО ортофото
                    layer_record.isVisible = True
                else:
                    # Все остальное видимо
                    layer_record.isVisible = True
            else:
                # Режим по умолчанию: показываем L_1_3_2_NSPD_Ref
                if 'L_1_3_1' in layer_name or 'L_1_3_3' in layer_name:
                    # Скрываем ортофото и ЦОС
                    layer_record.isVisible = False
                elif 'L_1_3_2' in layer_name:
                    # Показываем Справочный слой НСПД (подложка по умолчанию для главной карты)
                    layer_record.isVisible = True
                else:
                    # Все остальное видимо
                    layer_record.isVisible = True

            # Добавляем в тему главной карты
            main_theme_layers.append(layer_record)

            # Для обзорной карты - только границы работ (L_1_1_1) и ЦОС (L_1_3_3)
            # ЦОС всегда включена независимо от use_satellite
            if layer_name.startswith('L_1_1_1') or layer_name.startswith('L_1_3_3'):
                overview_record = QgsMapThemeCollection.MapThemeLayerRecord(layer)
                overview_record.isVisible = True
                overview_record.usingCurrentStyle = True
                overview_record.currentStyle = layer.styleManager().currentStyle()
                overview_theme_layers.append(overview_record)

        # Устанавливаем слои для тем
        main_theme_record.setLayerRecords(main_theme_layers)
        overview_theme_record.setLayerRecords(overview_theme_layers)

        # Добавляем темы в коллекцию
        map_theme_collection.insert('F_1_4_1_main_map', main_theme_record)
        map_theme_collection.insert('F_1_4_2_overview_map', overview_theme_record)

        log_info(f"Fsm_1_4_5: Создана тема 'F_1_4_1_main_map' с {len(main_theme_layers)} слоями")
        log_info(f"Fsm_1_4_5: Создана тема 'F_1_4_2_overview_map' с {len(overview_theme_layers)} слоями")

        # Применяем темы к картам в макете
        for item in layout.items():
            if isinstance(item, QgsLayoutItemMap):
                if item.id() == 'main_map':
                    item.setFollowVisibilityPreset(True)  # Включаем использование темы
                    item.setFollowVisibilityPresetName('F_1_4_1_main_map')
                    log_info("Fsm_1_4_5: Тема 'F_1_4_1_main_map' применена к главной карте")
                elif item.id() == 'overview_map':
                    item.setFollowVisibilityPreset(True)  # Включаем использование темы
                    item.setFollowVisibilityPresetName('F_1_4_2_overview_map')
                    log_info("Fsm_1_4_5: Тема 'F_1_4_2_overview_map' применена к обзорной карте")

        # НЕ вызываем layout.refresh() здесь - это провоцирует массовые запросы
        # к WMS/WMTS слоям НСПД, что вызывает burst retry
        # Обновление макета произойдёт при экспорте в PDF или в диалоге превью

        return True
    def get_overview_map_scale(self):
        """Получение текущего масштаба обзорной карты

        Returns:
            float: Масштаб карты или None
        """
        layout = self._get_layout()
        if not layout:
            return None

        for item in layout.items():
            if isinstance(item, QgsLayoutItemMap) and item.id() == 'overview_map':
                return item.scale()

        return None

    def set_overview_map_scale(self, scale: float):
        """Установка масштаба обзорной карты

        Args:
            scale: Новый масштаб карты
        """
        layout = self._get_layout()
        if not layout:
            return

        for item in layout.items():
            if isinstance(item, QgsLayoutItemMap) and item.id() == 'overview_map':
                item.setScale(scale)
                item.refresh()
                log_info(f"Fsm_1_4_5: Масштаб overview_map установлен: 1:{int(scale)}")
                return

    def export_to_pdf(self, pdf_path, dpi: int = EXPORT_DPI_ROSREESTR):
        """Экспорт компоновки в PDF

        Args:
            pdf_path: Путь для сохранения PDF файла
            dpi: Разрешение экспорта (по умолчанию 300 DPI согласно Приказу Росреестра П/0148)

        Returns:
            tuple: (success, error_msg)
        """
        # Получаем макет из менеджера
        layout = self._get_layout()
        if not layout:
            raise RuntimeError("Макет не создан или удален")

        # НЕ вызываем triggerRepaint/refresh - тайлы уже загружены в кэш при превью
        # Повторный refresh() вызывает burst retry к НСПД

        exporter = QgsLayoutExporter(layout)

        # Настройки экспорта для РАСТРОВОГО PDF
        settings = QgsLayoutExporter.PdfExportSettings()

        # РАСТРОВЫЙ ЭКСПОРТ с указанным DPI
        # Причина: роза ветров "утолщается" в векторном формате и становится нечитаемой
        # Решение: экспортируем весь макет в растре с высоким качеством
        # QGIS API не поддерживает выборочную растеризацию отдельных элементов
        settings.dpi = dpi

        # РАСТРОВЫЙ режим - экспортируем весь макет как растр
        settings.rasterizeWholeImage = True  # Растеризация всего макета
        settings.forceVectorOutput = False  # Отключаем векторный вывод

        # Упрощение геометрии не требуется для растра
        settings.simplifyGeometries = False

        # Метаданные (можно отключить для ускорения)
        settings.exportMetadata = False

        # Настройки рендеринга для корректного отображения стилей
        # ВАЖНО: При растровом экспорте можно включить продвинутые эффекты
        from qgis.core import QgsLayoutRenderContext
        layout.renderContext().setFlag(QgsLayoutRenderContext.FlagUseAdvancedEffects, True)
        layout.renderContext().setFlag(QgsLayoutRenderContext.FlagForceVectorOutput, False)

        # Экспортируем
        result = exporter.exportToPdf(pdf_path, settings)

        if result != QgsLayoutExporter.Success:
            raise RuntimeError("Ошибка экспорта в PDF")

        log_info(f"Fsm_1_4_5: Схема экспортирована в {pdf_path} с разрешением {dpi} DPI (растровый режим)")

        return True, None
    def get_layout_extent(self):
        """Получение экстента из карт в макете

        Returns:
            QgsRectangle: Экстент карты или None
        """
        # Получаем макет из менеджера
        layout = self._get_layout()
        if not layout:
            return None

        # Ищем основную карту в макете
        for item in layout.items():
            if isinstance(item, QgsLayoutItemMap) and item.id() == 'main_map':
                # Получаем экстент карты
                extent = item.extent()

                # Увеличиваем на 10%
                width = extent.width()
                height = extent.height()

                new_extent = QgsRectangle(
                    extent.xMinimum() - width * 0.10,
                    extent.yMinimum() - height * 0.10,
                    extent.xMaximum() + width * 0.10,
                    extent.yMaximum() + height * 0.10
                )

                return new_extent

        return None
    def get_boundaries_extent(self):
        """Получение экстента из слоя границ работ

        Returns:
            QgsRectangle: Экстент границ или None
        """
        # Ищем слой границ работ
        for layer in QgsProject.instance().mapLayers().values():
            if layer.name() == "1_1_1_Границы_работ":
                extent = layer.extent()

                # Увеличиваем на 10%
                width = extent.width()
                height = extent.height()

                new_extent = QgsRectangle(
                    extent.xMinimum() - width * 0.10,
                    extent.yMinimum() - height * 0.10,
                    extent.xMaximum() + width * 0.10,
                    extent.yMaximum() + height * 0.10
                )

                return new_extent

        return None
    
    def get_layout(self):
        """Получение текущего макета
        
        Returns:
            QgsPrintLayout: Текущий макет или None
        """
        return self._get_layout()
