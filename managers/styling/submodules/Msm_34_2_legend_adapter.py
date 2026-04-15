# -*- coding: utf-8 -*-
"""
Msm_34_2: LegendAdapter — Адаптация размера легенды под доступное пространство.

Измеряет реальный размер легенды после рендера и адаптирует
column_count / symbol_size если легенда слишком высокая.
Позиция и ref_point легенды остаются из Base_layout.json.

Используется: M_34_layout_manager.py
"""

from typing import Optional

from qgis.core import (
    QgsPrintLayout, QgsLayoutItemMap, QgsLayoutItemLegend
)

from Daman_QGIS.utils import log_info, log_warning


class LegendAdapter:
    """
    Адаптация размера легенды в макете.

    Алгоритм: refresh → measure → увеличить колонки → повторить.
    adjustBoxSize() не работает до первого рендера (mInitialMapScaleCalculated),
    поэтому используем layout.refresh() + sizeWithUnits().
    """

    # Начальные значения символов (до адаптации)
    DEFAULT_SYMBOL_WIDTH = 15
    DEFAULT_SYMBOL_HEIGHT = 5

    # Уменьшенные символы (при нехватке места)
    REDUCED_SYMBOL_WIDTH = 10
    REDUCED_SYMBOL_HEIGHT = 3.5

    # Максимальное количество колонок
    MAX_COLUMNS = 3

    def adapt(
        self,
        layout: QgsPrintLayout,
        max_height_ratio: float = 0.45
    ) -> bool:
        """
        Адаптировать размер легенды под доступное пространство.

        Вызывать ПОСЛЕ заполнения легенды слоями.

        Args:
            layout: Макет с заполненной легендой
            max_height_ratio: Макс. высота легенды как доля высоты main_map

        Returns:
            True при успехе
        """
        legend = self._find_legend(layout)
        main_map = self._find_main_map(layout)

        if not legend or not main_map:
            log_warning("Msm_34_2: legend или main_map не найдены")
            return False

        from qgis.PyQt.QtWidgets import QApplication

        map_height = main_map.rect().height()
        max_legend_height = map_height * max_height_ratio

        # Принудительный рендер для измерения легенды.
        # sizeWithUnits() возвращает 0 до первого paint.
        # Решение: рендер в QImage через QgsLayoutExporter запускает полный paint cycle.
        legend.setResizeToContents(True)
        legend.updateLegend()
        legend.adjustBoxSize()
        layout.refresh()
        QApplication.processEvents()

        # Рендер-проход: exportToImage в /dev/null запускает полный paint pipeline
        import tempfile, os
        from qgis.core import QgsLayoutExporter
        exporter = QgsLayoutExporter(layout)
        tmp_path = os.path.join(tempfile.gettempdir(), '_legend_measure.png')
        settings = QgsLayoutExporter.ImageExportSettings()
        settings.dpi = 72  # Низкое разрешение для скорости
        exporter.exportToImage(tmp_path, settings)
        try:
            os.remove(tmp_path)
        except OSError:
            pass

        legend.adjustBoxSize()
        leg_h = self._measure_height(legend)

        if leg_h <= 0:
            log_warning(f"Msm_34_2: Легенда 0x0 после рендер-прохода — пропуск адаптации")
            return False

        log_info(f"Msm_34_2: Измерение после рендера: {self._measure_width(legend):.0f}x{leg_h:.0f} мм")

        # Адаптивный column_count
        col_count = 1
        while leg_h > max_legend_height and col_count < self.MAX_COLUMNS:
            col_count += 1
            legend.setColumnCount(col_count)
            layout.refresh()
            legend.adjustBoxSize()
            leg_h = self._measure_height(legend)
            log_info(
                f"Msm_34_2: {col_count} колонок, "
                f"высота {leg_h:.0f} мм (макс. {max_legend_height:.0f})"
            )

        # Уменьшение символов если всё ещё большая
        if leg_h > max_legend_height:
            legend.setSymbolWidth(self.REDUCED_SYMBOL_WIDTH)
            legend.setSymbolHeight(self.REDUCED_SYMBOL_HEIGHT)
            layout.refresh()
            legend.adjustBoxSize()
            leg_h = self._measure_height(legend)
            log_info(f"Msm_34_2: Символы уменьшены, высота {leg_h:.0f} мм")

        legend.adjustBoxSize()
        leg_h = self._measure_height(legend)
        leg_w = self._measure_width(legend)
        log_info(f"Msm_34_2: Итог: {leg_w:.0f}x{leg_h:.0f} мм")

        # Сдвиг экстента вверх чтобы территория не попала под легенду
        self._shift_extent_for_legend(layout, main_map, leg_h)

        return True

    def _shift_extent_for_legend(
        self,
        layout: QgsPrintLayout,
        main_map: QgsLayoutItemMap,
        legend_height: float
    ) -> None:
        """
        Сдвинуть экстент main_map вверх, чтобы территория
        не перекрывалась легендой.

        safe_fraction = (map_height - legend_height - gap) / map_height
        Территория размещается в верхней safe_fraction карты,
        нижняя часть — подложка под легендой.
        """
        from qgis.core import QgsRectangle

        map_height = main_map.rect().height()
        gap = 10  # мм запаса между территорией и легендой

        safe_fraction = (map_height - legend_height - gap) / map_height
        safe_fraction = max(0.3, min(safe_fraction, 0.95))  # ограничения

        current_extent = main_map.extent()
        extent_height = current_extent.height()

        # Расширяем экстент на юг: территория остаётся вверху
        total_height = extent_height / safe_fraction
        extra_south = total_height - extent_height

        new_extent = QgsRectangle(
            current_extent.xMinimum(),
            current_extent.yMinimum() - extra_south,
            current_extent.xMaximum(),
            current_extent.yMaximum()
        )

        main_map.setExtent(new_extent)
        main_map.refresh()

        log_info(
            f"Msm_34_2: Экстент сдвинут (safe_fraction={safe_fraction:.2f}, "
            f"extra_south={extra_south:.0f} м)"
        )

    def _measure_height(self, legend: QgsLayoutItemLegend) -> float:
        """Измерить высоту легенды. sizeWithUnits → fallback rect()."""
        h = legend.sizeWithUnits().height()
        if h > 0:
            return h
        return legend.rect().height()

    def _measure_width(self, legend: QgsLayoutItemLegend) -> float:
        """Измерить ширину легенды. sizeWithUnits → fallback rect()."""
        w = legend.sizeWithUnits().width()
        if w > 0:
            return w
        return legend.rect().width()

    def _find_legend(self, layout: QgsPrintLayout) -> Optional[QgsLayoutItemLegend]:
        for item in layout.items():
            if isinstance(item, QgsLayoutItemLegend) and item.id() == 'legend':
                return item
        return None

    def _find_main_map(self, layout: QgsPrintLayout) -> Optional[QgsLayoutItemMap]:
        for item in layout.items():
            if isinstance(item, QgsLayoutItemMap) and item.id() == 'main_map':
                return item
        return None
