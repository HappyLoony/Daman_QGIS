# -*- coding: utf-8 -*-
"""
M_31_MaskManager - Менеджер маскирования для визуального ограничения карты.

Создаёт "маску" - слой с инвертированным полигоном, который затемняет
все области ВНЕ границ работ. Фильтрует подписи других слоёв, показывая
их только внутри маски.

Зависимости:
- Msm_31_1_MaskGeometry - создание геометрии маски
- Msm_31_2_MaskFilter - фильтрация подписей
- Msm_31_3_MaskExpressions - expression функции
"""

import os
from typing import Optional
from enum import Enum

from qgis.core import (
    QgsVectorLayer,
    QgsGeometry,
    QgsProject,
    QgsLayerTreeLayer,
)
from qgis.PyQt.QtCore import QObject, pyqtSignal
from qgis.utils import iface

from Daman_QGIS.utils import log_info, log_error, log_warning
from Daman_QGIS.constants import (
    LAYER_BOUNDARIES_EXACT,
    LAYER_BOUNDARIES_10M,
    LAYER_BOUNDARIES_MINUS2CM,
    LAYER_MASK,
)

from .submodules.Msm_31_1_mask_geometry import MaskGeometryBuilder
from .submodules.Msm_31_2_mask_filter import MaskLabelFilter
from .submodules.Msm_31_3_mask_expressions import MaskExpressionManager


class MaskSource(Enum):
    """Источники геометрии для маски."""
    BOUNDARIES_EXACT = "exact"        # L_1_1_1_Границы_работ
    BOUNDARIES_10M = "10m"            # L_1_1_2_Границы_работ_10_м
    BOUNDARIES_MINUS2CM = "minus2cm"  # L_1_1_4_Границы_работ_-2_см


# Маппинг MaskSource -> имя слоя
_SOURCE_TO_LAYER = {
    MaskSource.BOUNDARIES_EXACT: LAYER_BOUNDARIES_EXACT,
    MaskSource.BOUNDARIES_10M: LAYER_BOUNDARIES_10M,
    MaskSource.BOUNDARIES_MINUS2CM: LAYER_BOUNDARIES_MINUS2CM,
}


# Синглтон
_mask_manager_instance: Optional['MaskManager'] = None


def get_mask_manager() -> 'MaskManager':
    """
    Получить экземпляр MaskManager (синглтон).

    Returns:
        MaskManager: Единственный экземпляр менеджера
    """
    global _mask_manager_instance
    if _mask_manager_instance is None:
        _mask_manager_instance = MaskManager()
    return _mask_manager_instance


def reset_mask_manager() -> None:
    """
    Сбросить синглтон MaskManager.

    Вызывается при выгрузке плагина или для тестов.
    Выполняет cleanup перед удалением экземпляра.
    """
    global _mask_manager_instance
    if _mask_manager_instance is not None:
        _mask_manager_instance.cleanup()
    _mask_manager_instance = None


class MaskManager(QObject):
    """
    Менеджер маскирования.

    Отвечает за:
    - Создание слоя маски из границ работ
    - Применение инвертированного стиля (затемнение вне границ)
    - Регистрацию expression функций ($mask_geometry, in_mask)
    - Фильтрацию подписей всех слоёв
    - Сохранение/восстановление состояния в проекте

    Пример использования:
        from Daman_QGIS.managers import get_mask_manager, MaskSource

        manager = get_mask_manager()
        manager.enable_mask(MaskSource.BOUNDARIES_EXACT)

        if manager.is_enabled():
            layer = manager.get_mask_layer()
            print(f"Маска активна: {layer.name()}")

        manager.disable_mask()
    """

    # Сигналы
    mask_enabled = pyqtSignal(str)    # layer_id
    mask_disabled = pyqtSignal()
    mask_updated = pyqtSignal()

    # Константы для хранения в проекте
    PROJECT_SCOPE = "DamanMask"

    def __init__(self):
        """Инициализация менеджера маски."""
        super().__init__()

        # Субменеджеры
        self._geometry = MaskGeometryBuilder()
        self._filter = MaskLabelFilter()
        self._expressions = MaskExpressionManager(self)

        # Состояние
        self._mask_layer_id: Optional[str] = None
        self._source: Optional[MaskSource] = None
        self._buffer_m: float = 0.0
        self._plugin_dir: Optional[str] = None

        # Подключение к сигналам проекта
        QgsProject.instance().layerWillBeRemoved.connect(self._on_layer_removed)
        QgsProject.instance().readProject.connect(self._on_project_opened)

        log_info("M_31: MaskManager инициализирован")

    def set_plugin_dir(self, plugin_dir: str) -> None:
        """
        Установить путь к директории плагина.

        Необходимо для загрузки QML стиля.

        Args:
            plugin_dir: Путь к корню плагина
        """
        self._plugin_dir = plugin_dir
        self._geometry.set_plugin_dir(plugin_dir)

    # ========================================================================
    # Основные методы управления
    # ========================================================================

    def enable_mask(
        self,
        source: MaskSource = MaskSource.BOUNDARIES_EXACT,
        buffer_m: float = 0.0
    ) -> bool:
        """
        Включить маску.

        Создаёт слой маски из указанного источника границ,
        применяет стиль, регистрирует expression функции
        и добавляет фильтр подписей ко всем слоям.

        Args:
            source: Источник геометрии (exact, 10m, minus2cm)
            buffer_m: Дополнительный буфер в метрах (0 = без буфера)

        Returns:
            True если маска создана успешно
        """
        # 1. Найти слой-источник
        source_layer_name = _SOURCE_TO_LAYER.get(source)
        if source_layer_name is None:
            log_error(f"M_31: Неизвестный источник маски: {source}")
            return False

        source_layers = QgsProject.instance().mapLayersByName(source_layer_name)
        if not source_layers:
            log_error(f"M_31: Слой-источник не найден: {source_layer_name}")
            return False

        source_layer = source_layers[0]
        if not isinstance(source_layer, QgsVectorLayer):
            log_error(f"M_31: Слой-источник не является векторным: {source_layer_name}")
            return False

        # 2. Если маска уже существует - удалить
        if self._mask_layer_id is not None:
            self._remove_mask_layer()

        # 3. Создать слой маски
        mask_layer = self._geometry.create_mask_layer(
            source_layer,
            buffer_m,
            LAYER_MASK
        )
        if mask_layer is None:
            log_error("M_31: Не удалось создать слой маски")
            return False

        # 4. Добавить в проект на верхний уровень
        self._geometry.add_to_project_top(mask_layer)
        self._mask_layer_id = mask_layer.id()

        # 5. Регистрировать expression функции
        self._expressions.register()

        # 6. Применить фильтр ко всем слоям
        self._filter.add_filter_to_all_layers(mask_layer)

        # 7. Сохранить состояние
        self._source = source
        self._buffer_m = buffer_m
        self._save_to_project()

        # 8. Emit сигнал
        self.mask_enabled.emit(mask_layer.id())

        log_info(f"M_31: Маска включена (источник: {source.value}, буфер: {buffer_m}м)")
        return True

    def disable_mask(self) -> bool:
        """
        Отключить маску.

        Удаляет слой маски, снимает фильтры подписей
        и отменяет регистрацию expression функций.

        Returns:
            True если успешно
        """
        if self._mask_layer_id is None:
            log_warning("M_31: Маска не активна")
            return False

        # 1. Удалить фильтры со всех слоёв
        self._filter.remove_filter_from_all_layers()

        # 2. Отменить регистрацию expression функций
        self._expressions.unregister()

        # 3. Удалить слой маски
        self._remove_mask_layer()

        # 4. Очистить состояние
        self._mask_layer_id = None
        self._source = None
        self._buffer_m = 0.0
        self._save_to_project()

        # 5. Emit сигнал
        self.mask_disabled.emit()

        log_info("M_31: Маска отключена")
        return True

    def toggle_visibility(self, visible: bool) -> None:
        """
        Переключить видимость маски (без удаления).

        Args:
            visible: True для показа, False для скрытия
        """
        mask_layer = self.get_mask_layer()
        if mask_layer is None:
            return

        root = QgsProject.instance().layerTreeRoot()
        node = root.findLayer(mask_layer.id())
        if node is not None:
            node.setItemVisibilityChecked(visible)
            log_info(f"M_31: Видимость маски: {visible}")

    def update_mask(self) -> bool:
        """
        Обновить маску (пересчитать геометрию).

        Использует текущий источник и буфер.

        Returns:
            True если обновлено
        """
        if self._source is None:
            log_warning("M_31: Нет источника для обновления маски")
            return False

        mask_layer = self.get_mask_layer()
        if mask_layer is None:
            log_warning("M_31: Слой маски не найден")
            return False

        # Получить слой-источник
        source_layer_name = _SOURCE_TO_LAYER.get(self._source)
        source_layers = QgsProject.instance().mapLayersByName(source_layer_name)
        if not source_layers:
            log_error(f"M_31: Слой-источник не найден: {source_layer_name}")
            return False

        source_layer = source_layers[0]

        # Получить новую геометрию
        new_geom = self._geometry.get_combined_geometry(source_layer, self._buffer_m)
        if new_geom is None:
            log_error("M_31: Не удалось получить геометрию для обновления")
            return False

        # Обновить геометрию слоя
        if not self._geometry.update_geometry(mask_layer, new_geom):
            log_error("M_31: Не удалось обновить геометрию маски")
            return False

        # Emit сигнал
        self.mask_updated.emit()

        log_info("M_31: Маска обновлена")
        return True

    # ========================================================================
    # Информационные методы
    # ========================================================================

    def is_enabled(self) -> bool:
        """
        Проверить, включена ли маска.

        Returns:
            True если маска активна
        """
        if self._mask_layer_id is None:
            return False

        # Проверяем, существует ли слой
        layer = QgsProject.instance().mapLayer(self._mask_layer_id)
        return layer is not None

    def get_mask_layer(self) -> Optional[QgsVectorLayer]:
        """
        Получить слой маски.

        Returns:
            QgsVectorLayer маски или None
        """
        if self._mask_layer_id is None:
            return None

        layer = QgsProject.instance().mapLayer(self._mask_layer_id)
        if layer is None or not isinstance(layer, QgsVectorLayer):
            return None

        return layer

    def get_mask_geometry(self, use_simplification: bool = True) -> Optional[QgsGeometry]:
        """
        Получить геометрию маски.

        Используется expression функциями.
        При включённом упрощении возвращает упрощённую геометрию
        для текущего масштаба карты (оптимизация производительности).

        Args:
            use_simplification: Использовать упрощение (по умолчанию True)

        Returns:
            QgsGeometry маски или None
        """
        mask_layer = self.get_mask_layer()
        if mask_layer is None:
            return None

        # Пытаемся получить упрощённую геометрию
        if use_simplification:
            map_units_per_pixel = self._get_map_units_per_pixel()
            if map_units_per_pixel is not None:
                simplified = self._geometry.get_simplified_geometry(map_units_per_pixel)
                if simplified is not None:
                    return simplified

        # Fallback: оригинальная геометрия из слоя
        for feature in mask_layer.getFeatures():
            return QgsGeometry(feature.geometry())

        return None

    def _get_map_units_per_pixel(self) -> Optional[float]:
        """
        Получить единиц карты на пиксель из текущего MapCanvas.

        Returns:
            float или None если canvas недоступен
        """
        try:
            if iface is None:
                return None

            canvas = iface.mapCanvas()
            if canvas is None:
                return None

            return canvas.mapSettings().mapUnitsPerPixel()

        except Exception:
            return None

    def get_source(self) -> Optional[MaskSource]:
        """
        Получить текущий источник маски.

        Returns:
            MaskSource или None
        """
        return self._source

    def get_buffer(self) -> float:
        """
        Получить текущий буфер маски.

        Returns:
            Буфер в метрах
        """
        return self._buffer_m

    # ========================================================================
    # Управление упрощением геометрии
    # ========================================================================

    def set_simplification_enabled(self, enabled: bool) -> None:
        """
        Включить/выключить упрощение геометрии маски.

        Упрощение повышает производительность при работе
        с большими датасетами и сложными границами.

        Args:
            enabled: True для включения упрощения
        """
        self._geometry.set_simplify_enabled(enabled)

    def set_simplification_tolerance(self, tolerance_pixels: float) -> None:
        """
        Установить tolerance для упрощения геометрии.

        Args:
            tolerance_pixels: Tolerance в пикселях (по умолчанию 1.0)
        """
        self._geometry.set_simplify_tolerance(tolerance_pixels)

    def clear_geometry_cache(self) -> None:
        """
        Очистить кэш упрощённых геометрий.

        Вызывается автоматически при изменении геометрии маски.
        Может быть вызван вручную если нужно принудительно
        пересчитать упрощённые геометрии.
        """
        self._geometry.clear_cache()

    # ========================================================================
    # Сохранение состояния
    # ========================================================================

    def _save_to_project(self) -> None:
        """Сохранить состояние маски в проект."""
        project = QgsProject.instance()

        enabled = self._mask_layer_id is not None
        project.writeEntry(self.PROJECT_SCOPE, "enabled", enabled)

        if enabled:
            project.writeEntry(self.PROJECT_SCOPE, "layer_id", self._mask_layer_id)
            project.writeEntry(
                self.PROJECT_SCOPE, "source",
                self._source.value if self._source else ""
            )
            project.writeEntryDouble(self.PROJECT_SCOPE, "buffer_m", self._buffer_m)
        else:
            project.writeEntry(self.PROJECT_SCOPE, "layer_id", "")
            project.writeEntry(self.PROJECT_SCOPE, "source", "")
            project.writeEntryDouble(self.PROJECT_SCOPE, "buffer_m", 0.0)

    def _load_from_project(self) -> bool:
        """
        Загрузить состояние маски из проекта.

        Returns:
            True если маска была активна и восстановлена
        """
        project = QgsProject.instance()

        enabled, ok = project.readBoolEntry(self.PROJECT_SCOPE, "enabled", False)
        if not ok or not enabled:
            return False

        layer_id, ok = project.readEntry(self.PROJECT_SCOPE, "layer_id", "")
        if not ok or not layer_id:
            return False

        source_str, _ = project.readEntry(self.PROJECT_SCOPE, "source", "")
        buffer_m, _ = project.readDoubleEntry(self.PROJECT_SCOPE, "buffer_m", 0.0)

        # Проверяем, существует ли слой
        layer = project.mapLayer(layer_id)
        if layer is None:
            log_warning("M_31: Слой маски из проекта не найден")
            return False

        # Восстанавливаем состояние
        self._mask_layer_id = layer_id
        self._buffer_m = buffer_m

        # Восстанавливаем source
        for src in MaskSource:
            if src.value == source_str:
                self._source = src
                break

        # Регистрируем expression функции
        self._expressions.register()

        # Применяем фильтры
        if isinstance(layer, QgsVectorLayer):
            self._filter.add_filter_to_all_layers(layer)

        log_info(f"M_31: Маска восстановлена из проекта (layer_id: {layer_id})")
        return True

    # ========================================================================
    # Обработчики сигналов
    # ========================================================================

    def _on_layer_removed(self, layer_id: str) -> None:
        """
        Обработчик удаления слоя.

        Если удаляется слой маски - сбрасываем состояние.

        Args:
            layer_id: ID удаляемого слоя
        """
        if self._mask_layer_id is not None and layer_id == self._mask_layer_id:
            log_info("M_31: Слой маски удалён извне")

            # Удаляем фильтры
            self._filter.remove_filter_from_all_layers()

            # Отменяем регистрацию expression функций
            self._expressions.unregister()

            # Сбрасываем состояние
            self._mask_layer_id = None
            self._source = None
            self._buffer_m = 0.0
            self._save_to_project()

            # Emit сигнал
            self.mask_disabled.emit()

    def _on_project_opened(self) -> None:
        """Обработчик открытия проекта."""
        self._load_from_project()

    # ========================================================================
    # Вспомогательные методы
    # ========================================================================

    def _remove_mask_layer(self) -> None:
        """Удалить слой маски из проекта."""
        if self._mask_layer_id is None:
            return

        layer = QgsProject.instance().mapLayer(self._mask_layer_id)
        if layer is not None:
            QgsProject.instance().removeMapLayer(self._mask_layer_id)

    # ========================================================================
    # Cleanup
    # ========================================================================

    def cleanup(self) -> None:
        """
        Очистка при выгрузке плагина.

        Отключает маску и отсоединяет сигналы.
        """
        # Отключить маску если активна
        if self.is_enabled():
            self.disable_mask()

        # Отсоединить сигналы
        try:
            QgsProject.instance().layerWillBeRemoved.disconnect(self._on_layer_removed)
            QgsProject.instance().readProject.disconnect(self._on_project_opened)
        except Exception:
            pass  # Сигналы могут быть уже отсоединены

        log_info("M_31: MaskManager очищен")
