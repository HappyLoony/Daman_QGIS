# -*- coding: utf-8 -*-
"""
M_34: LayoutManager - Менеджер макетов печати

Централизованное управление макетами (Print Layouts) в QGIS:
- Программная генерация макетов из JSON конфигурации (Base_layout.json)
- Поддержка разных типов макетов (F_1_4, F_5_1, F_5_2 и др.)
- Получение формата и ориентации листа из метаданных проекта
- Получение размеров листа в миллиметрах
- Управление элементами макета (карты, легенды, подписи)
- Экспорт в PDF и изображения

Типы макетов:
- F_1_4: Графика к запросу (схема расположения)
- F_5_1: Чертёж планировки территории (будущее)
- F_5_2: Чертёж межевания территории (будущее)

Используется: F_1_4, F_5_*
"""

import os
from typing import Optional, Tuple, Dict, Any
from enum import Enum

from qgis.core import (
    QgsProject, QgsPrintLayout,
    QgsLayoutItemMap, QgsLayoutItemLegend, QgsLayoutItemLabel,
    QgsRectangle, QgsLayoutExporter
)

from Daman_QGIS.database.project_db import ProjectDB
from Daman_QGIS.constants import (
    PAGE_SIZES, PAGE_ORIENTATIONS,
    DEFAULT_PAGE_FORMAT, DEFAULT_PAGE_ORIENTATION,
    EXPORT_DPI_ROSREESTR
)
from Daman_QGIS.utils import log_info, log_warning, log_error

__all__ = ['PageFormat', 'PageOrientation', 'LayoutManager']


class PageFormat(Enum):
    """Форматы листа ISO 216"""
    A4 = "A4"
    A3 = "A3"
    A2 = "A2"
    A1 = "A1"


class PageOrientation(Enum):
    """Ориентация листа"""
    LANDSCAPE = "landscape"  # Альбомная
    PORTRAIT = "portrait"    # Книжная


class LayoutManager:
    """
    Менеджер макетов печати

    Предоставляет унифицированный API для:
    - Программной генерации макетов из JSON конфигурации
    - Определения формата и ориентации листа из метаданных проекта
    - Получения размеров листа в миллиметрах
    - Управления элементами макета
    """

    def __init__(self):
        """Инициализация менеджера"""
        self._current_layout: Optional[QgsPrintLayout] = None
        self._current_layout_name: Optional[str] = None

    # =========================================================================
    # Метаданные проекта
    # =========================================================================

    def get_page_format_from_metadata(self) -> Tuple[str, str]:
        """
        Получить формат и ориентацию листа из метаданных текущего проекта

        Returns:
            Tuple[str, str]: (формат: A4/A3/A2/A1, ориентация: Альбомная/Книжная)
        """
        try:
            from Daman_QGIS.managers import registry
            structure_manager = registry.get('M_19')
            gpkg_path = structure_manager.get_gpkg_path(create=False)

            if gpkg_path and os.path.exists(gpkg_path):
                db = ProjectDB(gpkg_path)
                format_data = db.get_metadata('2_13_sheet_format')
                orientation_data = db.get_metadata('2_14_sheet_orientation')

                page_format = format_data.get('value') if format_data else DEFAULT_PAGE_FORMAT
                page_orientation = orientation_data.get('value') if orientation_data else DEFAULT_PAGE_ORIENTATION
                log_info(f"M_34: Метаданные листа: формат={page_format}, ориентация={page_orientation}")
                return page_format, page_orientation

            log_warning("M_34: GeoPackage не найден, используются значения по умолчанию")
        except Exception as e:
            log_warning(f"M_34: Не удалось прочитать метаданные: {e}")

        log_info(f"M_34: Используются значения по умолчанию: формат={DEFAULT_PAGE_FORMAT}, ориентация={DEFAULT_PAGE_ORIENTATION}")
        return DEFAULT_PAGE_FORMAT, DEFAULT_PAGE_ORIENTATION

    def get_orientation_code(self, orientation_name: str) -> str:
        """
        Конвертировать русское название ориентации в код

        Args:
            orientation_name: 'Альбомная' или 'Книжная'

        Returns:
            str: 'landscape' или 'portrait'
        """
        return PAGE_ORIENTATIONS.get(orientation_name, 'landscape')

    # =========================================================================
    # Размеры листа
    # =========================================================================

    def get_page_size_mm(self, page_format: str = None, orientation: str = None) -> Tuple[float, float]:
        """
        Получить размеры листа в миллиметрах

        Args:
            page_format: Формат (A4/A3/A2/A1). Если None - из метаданных
            orientation: Ориентация (Альбомная/Книжная). Если None - из метаданных

        Returns:
            Tuple[float, float]: (ширина, высота) в мм
        """
        if page_format is None or orientation is None:
            meta_format, meta_orientation = self.get_page_format_from_metadata()
            page_format = page_format or meta_format
            orientation = orientation or meta_orientation

        # Базовые размеры (portrait: ширина < высота)
        base_width, base_height = PAGE_SIZES.get(page_format, PAGE_SIZES['A4'])

        # Для landscape меняем местами
        orientation_code = self.get_orientation_code(orientation)
        if orientation_code == 'landscape':
            return float(base_height), float(base_width)
        else:
            return float(base_width), float(base_height)

    def get_page_size_for_format(self, page_format: PageFormat, orientation: PageOrientation) -> Tuple[float, float]:
        """
        Получить размеры листа по enum значениям

        Args:
            page_format: PageFormat enum
            orientation: PageOrientation enum

        Returns:
            Tuple[float, float]: (ширина, высота) в мм
        """
        base_width, base_height = PAGE_SIZES.get(page_format.value, PAGE_SIZES['A4'])

        if orientation == PageOrientation.LANDSCAPE:
            return float(base_height), float(base_width)
        else:
            return float(base_width), float(base_height)

    # =========================================================================
    # Управление макетами в проекте
    # =========================================================================

    def add_layout_to_project(self, layout: QgsPrintLayout) -> bool:
        """
        Добавить макет в проект QGIS

        Args:
            layout: Макет для добавления

        Returns:
            bool: True если успешно
        """
        try:
            layout_manager = QgsProject.instance().layoutManager()

            # Удаляем существующий макет с таким именем
            existing = layout_manager.layoutByName(layout.name())
            if existing:
                layout_manager.removeLayout(existing)
                log_info(f"M_34: Удалён существующий макет: {layout.name()}")

            # Добавляем новый
            if layout_manager.addLayout(layout):
                log_info(f"M_34: Макет добавлен в проект: {layout.name()}")
                return True
            else:
                log_error(f"M_34: Не удалось добавить макет: {layout.name()}")
                return False

        except Exception as e:
            log_error(f"M_34: Ошибка добавления макета: {e}")
            return False

    def remove_layouts_by_prefix(self, prefix: str) -> int:
        """
        Удалить все макеты с заданным префиксом

        Args:
            prefix: Префикс имени макета

        Returns:
            int: Количество удалённых макетов
        """
        layout_manager = QgsProject.instance().layoutManager()
        removed_count = 0

        layouts_to_remove = []
        for layout in layout_manager.layouts():
            if layout.name().startswith(prefix):
                layouts_to_remove.append(layout)

        for layout in layouts_to_remove:
            name = layout.name()
            layout_manager.removeLayout(layout)
            log_info(f"M_34: Удалён макет: {name}")
            removed_count += 1

        return removed_count

    # =========================================================================
    # Управление элементами макета
    # =========================================================================

    def get_map_item(self, layout: QgsPrintLayout, item_id: str) -> Optional[QgsLayoutItemMap]:
        """
        Получить элемент карты по ID

        Args:
            layout: Макет
            item_id: ID элемента (например 'main_map', 'overview_map')

        Returns:
            QgsLayoutItemMap или None
        """
        item = layout.itemById(item_id)
        if isinstance(item, QgsLayoutItemMap):
            return item
        return None

    def get_legend_item(self, layout: QgsPrintLayout, item_id: str = 'legend') -> Optional[QgsLayoutItemLegend]:
        """
        Получить элемент легенды по ID

        Args:
            layout: Макет
            item_id: ID элемента

        Returns:
            QgsLayoutItemLegend или None
        """
        item = layout.itemById(item_id)
        if isinstance(item, QgsLayoutItemLegend):
            return item
        return None

    def get_label_item(self, layout: QgsPrintLayout, item_id: str) -> Optional[QgsLayoutItemLabel]:
        """
        Получить элемент подписи по ID

        Args:
            layout: Макет
            item_id: ID элемента (например 'title_label')

        Returns:
            QgsLayoutItemLabel или None
        """
        item = layout.itemById(item_id)
        if isinstance(item, QgsLayoutItemLabel):
            return item
        return None

    def set_map_extent(self, map_item: QgsLayoutItemMap, extent: QgsRectangle) -> None:
        """
        Установить экстент карты

        Args:
            map_item: Элемент карты
            extent: Прямоугольник экстента
        """
        if map_item:
            map_item.setExtent(extent)
            map_item.refresh()
            log_info(f"M_34: Установлен экстент для {map_item.id()}")

    def set_label_text(self, label_item: QgsLayoutItemLabel, text: str) -> None:
        """
        Установить текст подписи

        Args:
            label_item: Элемент подписи
            text: Текст
        """
        if label_item:
            label_item.setText(text)
            log_info(f"M_34: Установлен текст для {label_item.id()}")

    # =========================================================================
    # Экспорт
    # =========================================================================

    def export_to_pdf(self, layout: QgsPrintLayout, output_path: str,
                      dpi: int = EXPORT_DPI_ROSREESTR) -> bool:
        """
        Экспортировать макет в PDF

        Args:
            layout: Макет
            output_path: Путь к выходному файлу
            dpi: Разрешение экспорта (по умолчанию 300 DPI согласно Приказу Росреестра П/0148)

        Returns:
            bool: True если успешно
        """
        try:
            exporter = QgsLayoutExporter(layout)
            settings = QgsLayoutExporter.PdfExportSettings()
            settings.dpi = dpi

            result = exporter.exportToPdf(output_path, settings)

            if result == QgsLayoutExporter.Success:
                log_info(f"M_34: Экспортировано в PDF: {output_path} (DPI={dpi})")
                return True
            else:
                log_error(f"M_34: Ошибка экспорта в PDF: {result}")
                return False

        except Exception as e:
            log_error(f"M_34: Ошибка экспорта в PDF: {e}")
            return False

    def export_to_image(
        self,
        layout: QgsPrintLayout,
        output_path: str,
        dpi: int = EXPORT_DPI_ROSREESTR
    ) -> bool:
        """
        Экспортировать макет в изображение

        Args:
            layout: Макет
            output_path: Путь к выходному файлу (PNG, JPG)
            dpi: Разрешение (по умолчанию 300 DPI согласно Приказу Росреестра П/0148)

        Returns:
            bool: True если успешно
        """
        try:
            exporter = QgsLayoutExporter(layout)
            settings = QgsLayoutExporter.ImageExportSettings()
            settings.dpi = dpi

            result = exporter.exportToImage(output_path, settings)

            if result == QgsLayoutExporter.Success:
                log_info(f"M_34: Экспортировано в изображение: {output_path}")
                return True
            else:
                log_error(f"M_34: Ошибка экспорта в изображение: {result}")
                return False

        except Exception as e:
            log_error(f"M_34: Ошибка экспорта в изображение: {e}")
            return False

    # =========================================================================
    # Программная генерация макетов из JSON
    # =========================================================================

    def build_layout(
        self,
        layout_name: str,
        page_format: str = None,
        orientation: str = None,
        doc_type: str = 'ДПТ'
    ) -> Optional[QgsPrintLayout]:
        """
        Создать макет программно из JSON конфигурации

        Конфигурация загружается из Base_layout.json через API.
        Ключ выбирается по формату и ориентации: "{format}_{orientation}"
        (например A4_landscape, A3_landscape).

        Args:
            layout_name: Имя создаваемого макета
            page_format: Формат страницы (A4, A3, A2, A1). Если None - из метаданных
            orientation: 'landscape' или 'portrait'. Если None - из метаданных проекта
            doc_type: Тип документации для выбора шрифта (DOC_TYPE_FONTS)

        Returns:
            QgsPrintLayout или None при ошибке
        """
        from .submodules.Msm_34_1_layout_builder import LayoutBuilder

        # Определяем формат и ориентацию из метаданных если не указаны
        if page_format is None or orientation is None:
            meta_format, meta_orientation = self.get_page_format_from_metadata()
            if page_format is None:
                page_format = meta_format
            if orientation is None:
                orientation = self.get_orientation_code(meta_orientation)

        # Суффикс типа документации
        _DOC_TYPE_SUFFIX = {
            'ДПТ': 'DPT',
            'Мастер-план': 'MP',
        }
        suffix = _DOC_TYPE_SUFFIX.get(doc_type, 'DPT')
        config_key = f"{page_format}_{orientation}_{suffix}"

        try:
            builder = LayoutBuilder()

            if not builder.load_config():
                log_error("M_34: Не удалось загрузить конфигурацию Base_layout.json")
                return None

            layout = builder.build(config_key=config_key, layout_name=layout_name, doc_type=doc_type)

            if layout:
                self._current_layout = layout
                self._current_layout_name = layout_name
                log_info(f"M_34: Макет '{layout_name}' создан ({config_key})")
                return layout
            else:
                log_error(f"M_34: Не удалось создать макет ({config_key})")
                return None

        except Exception as e:
            log_error(f"M_34: Ошибка создания макета ({config_key}): {e}")
            return None

    def get_layout_config(
        self,
        page_format: str = None,
        orientation: str = None,
        doc_type: str = 'ДПТ'
    ) -> Optional[Dict[str, Any]]:
        """
        Получить параметры макета из JSON конфигурации

        Args:
            page_format: Формат страницы (A4, A3, A2, A1). Если None - из метаданных
            orientation: 'landscape' или 'portrait'. Если None - из метаданных
            doc_type: Тип документации (ДПТ, Мастер-план)

        Returns:
            Dict с параметрами или None
        """
        from .submodules.Msm_34_1_layout_builder import LayoutBuilder

        if page_format is None or orientation is None:
            meta_format, meta_orientation = self.get_page_format_from_metadata()
            if page_format is None:
                page_format = meta_format
            if orientation is None:
                orientation = self.get_orientation_code(meta_orientation)

        _DOC_TYPE_SUFFIX = {'ДПТ': 'DPT', 'Мастер-план': 'MP'}
        suffix = _DOC_TYPE_SUFFIX.get(doc_type, 'DPT')
        config_key = f"{page_format}_{orientation}_{suffix}"

        builder = LayoutBuilder()
        if builder.load_config():
            return builder.get_config(config_key)
        return None

    def adapt_legend(
        self,
        layout: 'QgsPrintLayout',
        max_height_ratio: float = 0.45
    ) -> bool:
        """
        Адаптировать размер легенды под доступное пространство.
        Делегирует Msm_34_2_legend_adapter.

        Вызывать ПОСЛЕ заполнения легенды слоями (update_legend).

        Args:
            layout: Макет с заполненной легендой
            max_height_ratio: Макс. высота легенды как доля высоты main_map

        Returns:
            True при успехе
        """
        from .submodules.Msm_34_2_legend_adapter import LegendAdapter
        adapter = LegendAdapter()
        return adapter.adapt(layout, max_height_ratio)
