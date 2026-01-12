# -*- coding: utf-8 -*-
"""
Модуль управления макетами и компоновками
Часть инструмента F_1_4_Запрос
"""

import os
from qgis.PyQt.QtXml import QDomDocument
from qgis.core import (
    QgsProject, QgsMessageLog, Qgis, QgsPrintLayout,
    QgsLayoutExporter, QgsReadWriteContext,
    QgsLayoutItemLabel, QgsLayoutItemMap, QgsLayoutItemLegend,
    QgsRectangle
)
from Daman_QGIS.database.project_db import ProjectDB
from Daman_QGIS.constants import PLUGIN_NAME
from Daman_QGIS.utils import log_info, log_warning, log_error
from Daman_QGIS.title_generator import TitleGenerator


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
    def create_layout_from_template(self, selected_layer_ids, nspd_layers, use_satellite=False):
        """Создание компоновки из готового шаблона

        Args:
            selected_layer_ids: Список ID выбранных слоев
            nspd_layers: Словарь выбранных слоев НСПД
            use_satellite: Использовать спутниковый снимок вместо ЦОС для главной карты

        Returns:
            tuple: (success, error_msg)
        """
        # Обнуляем имя старого макета сразу в начале
        self.layout_name = None
        self._layout_ref = None

        project = QgsProject.instance()

        # Проверяем наличие слоев НСПД с данными
        # ВАЖНО: Учитываем родительские слои созданные через F_1_2
        available_nspd_layers = []
        for layer in project.mapLayers().values():
            layer_name = layer.name()
            # Проверяем векторные слои НСПД (включая родительские слои)
            if (layer_name.startswith('L_1_2_') or layer_name.startswith('Le_1_2_')) and not layer_name.startswith('Le_1_2_7'):
                # Это векторный слой НСПД
                if hasattr(layer, 'featureCount') and layer.featureCount() > 0:
                    available_nspd_layers.append(layer_name)

        if not available_nspd_layers:
            log_info("Fsm_1_4_5: Макет не создается - нет слоев НСПД с данными для отображения")
            raise RuntimeError("Нет слоев НСПД для отображения")

        # Удаляем все старые макеты "Графика к запросу"
        layouts_to_remove = []
        for layout in project.layoutManager().layouts():
            if layout.name().startswith("Графика к запросу"):
                # Сохраняем имя ДО удаления
                layout_name_to_remove = layout.name()
                layouts_to_remove.append((layout, layout_name_to_remove))

        for layout, layout_name_to_remove in layouts_to_remove:
            project.layoutManager().removeLayout(layout)
            log_info(f"Fsm_1_4_5: Удален старый макет: {layout_name_to_remove}")

        # Создаем уникальное имя для нового макета
        from datetime import datetime
        timestamp = datetime.now().strftime("%H%M%S")
        layout_name = f"Графика к запросу_{timestamp}"

        # Путь к шаблону в data/templates
        template_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
            'data', 'templates', 'F_1_4_template.qpt'
        )

        if not os.path.exists(template_path):
            raise RuntimeError(f"Шаблон не найден: {template_path}")


        # Читаем шаблон
        with open(template_path, 'r', encoding='utf-8') as f:
            template_content = f.read()


        # Создаем DOM документ из шаблона
        doc = QDomDocument()
        doc.setContent(template_content)

        # Создаем новую компоновку
        layout = QgsPrintLayout(QgsProject.instance())
        # НЕ устанавливаем имя здесь - оно будет перезаписано при загрузке шаблона

        # Сначала пробуем загрузить шаблон ДО добавления в менеджер
        try:
            # Получаем корневой элемент Layout из документа
            layout_elem = doc.documentElement()
            if layout_elem.tagName() != "Layout":
                # Если это не Layout, ищем его как дочерний элемент
                layout_elem = layout_elem.firstChildElement("Layout")

            if not layout_elem.isNull():
                # Используем readLayoutXml
                result = layout.readLayoutXml(layout_elem, doc, QgsReadWriteContext())
                if not result:
                    # Если не удалось, пробуем альтернативный метод
                    result = layout.loadFromTemplate(doc, QgsReadWriteContext())
                    if not result:
                        raise RuntimeError("Не удалось загрузить шаблон")
            else:
                # Если не нашли Layout, пробуем загрузить весь документ
                result = layout.loadFromTemplate(doc, QgsReadWriteContext())
                if not result:
                    raise RuntimeError("Не удалось загрузить шаблон через loadFromTemplate")

            # ВАЖНО: Устанавливаем имя ПОСЛЕ загрузки шаблона
            layout.setName(layout_name)

            # Только после успешной загрузки добавляем в менеджер
            layout_manager = QgsProject.instance().layoutManager()
            if not layout_manager.addLayout(layout):
                # Если не удалось добавить, очищаем layout
                layout = None
                raise RuntimeError("Не удалось добавить макет в менеджер")

            # Сохраняем имя и ссылку на макет после успешного добавления
            self.layout_name = layout_name
            self._layout_ref = layout  # Сохраняем ссылку чтобы предотвратить удаление сборщиком мусора

        except Exception as e:
            # При любой ошибке обнуляем имя макета
            self.layout_name = None
            self._layout_ref = None
            raise RuntimeError(f"Ошибка создания макета: {str(e)}")

        # Обновляем название объекта в заголовке
        self.update_object_name()

        # Обновляем слои в легенде
        self.update_legend_layers(selected_layer_ids, nspd_layers)

        # Настраиваем фильтры для карт
        self.configure_map_filters(nspd_layers, use_satellite)

        # Программно устанавливаем экстент карт (вместо выражений в шаблоне)
        self._apply_map_extents(layout)

        # Возвращаем True для совместимости
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
        from Daman_QGIS.managers import get_extent_manager
        from Daman_QGIS.managers.M_19_project_structure_manager import get_project_structure_manager
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

        extent_manager = get_extent_manager()

        # Применяем к main_map с адаптивным padding
        result_main = extent_manager.apply_layer_extent_to_map(
            layout,
            map_id='main_map',
            layer=boundaries_layer,
            padding_percent=10.0,
            adaptive_padding=True,
            fit_to_map_ratio=True
        )

        if result_main:
            log_info("Fsm_1_4_5: Экстент main_map установлен программно")
        else:
            log_warning("Fsm_1_4_5: Не удалось установить экстент main_map")

        # === OVERVIEW_MAP: масштаб проекта * 100 для контекста ===
        # Обзорная карта должна показывать место расположения относительно НП

        # Получаем масштаб проекта из метаданных
        overview_scale = None
        try:
            project_home = QgsProject.instance().homePath()
            structure_manager = get_project_structure_manager()
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
        from Daman_QGIS.managers.M_19_project_structure_manager import get_project_structure_manager
        project_home = QgsProject.instance().homePath()
        structure_manager = get_project_structure_manager()
        structure_manager.project_root = project_home
        gpkg_path = structure_manager.get_gpkg_path(create=False)

        # Значения по умолчанию
        metadata_dict = {
            "1_1_full_name": "объекта",
            "1_2_object_type": "Площадной",
            "1_2_1_object_type_value": "-",
            "1_5_doc_type": "ДПТ",
            "1_6_stage": "Первичная"
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
    @staticmethod
    def wrap_legend_text(text: str, max_length: int = 100) -> str:
        """Автоматический перенос строк в тексте легенды

        Разбивает длинный текст на строки по словам, чтобы избежать наложения
        на другие элементы макета (обзорную карту и т.д.).

        Args:
            text: Исходный текст
            max_length: Максимальная длина строки в символах (по умолчанию 100)

        Returns:
            str: Текст с переносами строк (\\n)

        Examples:
            >>> wrap_legend_text("Границы и кадастровые номера существующих земельных участков, учтенных в Едином государственном реестре недвижимости", 100)
            "Границы и кадастровые номера существующих земельных участков, учтенных в Едином\\nгосударственном реестре недвижимости"
        """
        if not text or len(text) <= max_length:
            return text

        # Разбиваем текст на слова
        words = text.split()
        lines = []
        current_line = []
        current_length = 0

        for word in words:
            word_length = len(word)

            # Если добавление слова превысит max_length
            if current_length + word_length + len(current_line) > max_length:
                # Сохраняем текущую строку
                if current_line:
                    lines.append(' '.join(current_line))
                    current_line = [word]
                    current_length = word_length
                else:
                    # Слово само по себе длиннее max_length
                    lines.append(word)
                    current_length = 0
            else:
                # Добавляем слово к текущей строке
                current_line.append(word)
                current_length += word_length

        # Добавляем последнюю строку
        if current_line:
            lines.append(' '.join(current_line))

        return '\n'.join(lines)

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
        # Находим элемент легенды
        legend = None
        for item in layout.items():
            if isinstance(item, QgsLayoutItemLegend) and item.id() == 'legend':
                legend = item
                break

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
        from Daman_QGIS.managers.M_19_project_structure_manager import get_project_structure_manager
        project_home = QgsProject.instance().homePath()
        structure_manager = get_project_structure_manager()
        structure_manager.project_root = project_home
        gpkg_path = structure_manager.get_gpkg_path(create=False)

        # Значения по умолчанию
        metadata_dict = {
            "1_5_doc_type": "ДПТ",
            "1_6_stage": "Первичная"
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

                    # Применяем автоматический перенос строк (max_length=100)
                    legend_title = self.wrap_legend_text(legend_title_base, max_length=100)

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
                        # Применяем автоматический перенос строк для всех слоев
                        wrapped_title = self.wrap_legend_text(legend_title, max_length=100)
                        layer_node.setCustomProperty("legend/title-label", wrapped_title)

        # Обновляем размер легенды
        legend.adjustBoxSize()

        return True
    def configure_map_filters(self, nspd_layers, use_satellite=False):
        """Настройка фильтров слоев для карт через темы (Map Themes)

        Создает две темы карт:
        - F_1_4_1_main_map: выбранные слои + подложка L_1_3_2_Справочный_слой (если use_satellite=False) или L_1_3_1_Google_Satellite (если use_satellite=True)
        - F_1_4_2_overview_map: только слои с 1_1_1 и L_1_3_3_ЦОС (ЦОС всегда включена в обзорной)

        Args:
            nspd_layers: Словарь выбранных слоев НСПД
            use_satellite: Если True - использовать спутник на главной карте, иначе L_1_3_2_Справочный_слой

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
            
            # ГЛАВНАЯ КАРТА: Используем L_1_3_2_Справочный_слой (НСПД)
            # Если use_satellite=True - показываем спутник (L_1_3_1), скрываем подложки НСПД
            # Если use_satellite=False - показываем L_1_3_2_Справочный_слой, скрываем спутник
            if use_satellite:
                # Режим спутника: показываем спутник, скрываем подложки НСПД
                if 'L_1_3_2' in layer_name or 'L_1_3_3' in layer_name:
                    # Скрываем Справочный слой и ЦОС
                    layer_record.isVisible = False
                elif 'L_1_3_1' in layer_name:
                    # Показываем спутник
                    layer_record.isVisible = True
                else:
                    # Все остальное видимо
                    layer_record.isVisible = True
            else:
                # Режим по умолчанию: показываем L_1_3_2_Справочный_слой
                if 'L_1_3_1' in layer_name or 'L_1_3_3' in layer_name:
                    # Скрываем спутник и ЦОС
                    layer_record.isVisible = False
                elif 'L_1_3_2' in layer_name:
                    # Показываем Справочный слой НСПД (подложка по умолчанию для главной карты)
                    layer_record.isVisible = True
                else:
                    # Все остальное видимо
                    layer_record.isVisible = True

            # Добавляем в тему главной карты
            main_theme_layers.append(layer_record)

            # Для обзорной карты - только слои с 1_1_1 или L_1_3_3
            # ЦОС (L_1_3_3) всегда включена независимо от use_satellite
            if '1_1_1' in layer_name or 'L_1_3_3' in layer_name:
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

        # Обновляем макет
        layout.refresh()

        return True
    def export_to_pdf(self, pdf_path):
        """Экспорт компоновки в PDF

        Args:
            pdf_path: Путь для сохранения PDF файла

        Returns:
            tuple: (success, error_msg)
        """
        # Получаем макет из менеджера
        layout = self._get_layout()
        if not layout:
            raise RuntimeError("Макет не создан или удален")

        # КРИТИЧЕСКИ ВАЖНО: Принудительно обновляем все слои перед экспортом
        # Это гарантирует что стили применены корректно
        project = QgsProject.instance()
        for layer_id, layer in project.mapLayers().items():
            if hasattr(layer, 'triggerRepaint'):
                try:
                    layer.triggerRepaint()
                except:
                    pass  # Игнорируем ошибки для проблемных слоев

        # Обновляем все карты в макете для корректного рендеринга
        for item in layout.items():
            if isinstance(item, QgsLayoutItemMap):
                item.refresh()

        # Финальное обновление макета
        layout.refresh()

        exporter = QgsLayoutExporter(layout)

        # Настройки экспорта для РАСТРОВОГО PDF
        settings = QgsLayoutExporter.PdfExportSettings()

        # РАСТРОВЫЙ ЭКСПОРТ с DPI 200
        # Причина: роза ветров "утолщается" в векторном формате и становится нечитаемой
        # Решение: экспортируем весь макет в растре с высоким качеством
        # QGIS API не поддерживает выборочную растеризацию отдельных элементов
        settings.dpi = 200  # Высокое разрешение 200 DPI для качественного растра

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

        log_info(f"Fsm_1_4_5: Схема экспортирована в {pdf_path} с разрешением 200 DPI (растровый режим)")

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
