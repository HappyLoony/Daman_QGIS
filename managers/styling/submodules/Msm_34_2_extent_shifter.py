# -*- coding: utf-8 -*-
"""
Msm_34_2: ExtentShifter — Сдвиг экстента main_map под overlay легенды.

Назначение: после применения плана M_46 (LegendManager) измеряет
фактическую геометрию легенды и сдвигает экстент main_map так, чтобы
область легенды приходилась на подложку, а не на данные территории.

Разделение обязанностей (Task 7 в плане M_46):
- Msm_34_2 (этот файл): measurement pass + shift extent (один проход).
- M_46 / Msm_46_3 (LayoutPlanner): column_count 1/2/3, symbol_size fallback,
  расчёт ширины легенды.

Используется: M_34_layout_manager.py
"""

from typing import Optional

from qgis.core import (
    QgsPrintLayout, QgsLayoutItemMap, QgsLayoutItemLegend
)

from Daman_QGIS.utils import log_info, log_warning


class ExtentShifter:
    """
    Сдвиг экстента main_map под overlay легенды.

    Алгоритм (один проход, без итераций):
    1. Forced render (exportToImage в tmp) для инициализации paint pipeline.
       sizeWithUnits() возвращает 0 до первого paint — workaround QGIS.
    2. Измерение фактического bbox легенды.
    3. Пересчёт экстента через M_18.add_padding_south_extended с
       safe_fraction = (map_h - leg_h) / map_h, clamp [0.3, 0.95].
    """

    def shift_extent_for_legend(
        self,
        layout: QgsPrintLayout,
    ) -> bool:
        """
        Измерить легенду после плана M_46 и сдвинуть экстент main_map.

        Вызывать ПОСЛЕ:
        - M_46.plan_and_apply (легенда заполнена, column_count / symbol_size
          и позиция применены Msm_46_4).

        Args:
            layout: Макет с заполненной легендой и применённым планом M_46.

        Returns:
            True при успехе, False при отсутствии legend/main_map или
            при нулевом bbox легенды.
        """
        legend = self._find_legend(layout)
        main_map = self._find_main_map(layout)

        if not legend:
            log_warning("Msm_34_2: legend не найден")
            return False

        if not main_map:
            log_warning("Msm_34_2: main_map не найден")
            return False

        from qgis.PyQt.QtWidgets import QApplication

        # Подготовка к измерению.
        # sizeWithUnits() возвращает 0 до первого paint — нужен forced render.
        legend.setResizeToContents(True)
        legend.updateLegend()
        legend.adjustBoxSize()
        layout.refresh()
        QApplication.processEvents()

        # Forced render pass: exportToImage в tmp PNG запускает полный
        # paint pipeline, после чего sizeWithUnits() возвращает реальные мм.
        import tempfile
        import os
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
        leg_w = self._measure_width(legend)

        if leg_h <= 0:
            log_warning("Msm_34_2: Легенда 0 высоты после рендер-прохода")
            return False

        log_info(
            f"Msm_34_2: Измерение легенды: {leg_w:.0f}x{leg_h:.0f} мм"
        )

        # Сдвиг экстента: территория сверху, подложка снизу под легендой
        self._shift_extent(layout, main_map, leg_h)
        return True

    def _shift_extent(
        self,
        layout: QgsPrintLayout,
        main_map: QgsLayoutItemMap,
        legend_height: float
    ) -> None:
        """
        Пересчитать экстент main_map: территория сверху, подложка снизу.

        Использует M_18.add_padding_south_extended с safe_fraction
        рассчитанным из реального размера легенды.
        """
        from Daman_QGIS.managers import registry
        from qgis.core import QgsLayoutSize, QgsLayoutPoint, Qgis, QgsProject

        map_height = main_map.rect().height()
        map_width = main_map.rect().width()

        # safe_fraction: территория в верхней части, легенда в нижней
        safe_fraction = (map_height - legend_height) / map_height
        safe_fraction = max(0.3, min(safe_fraction, 0.95))

        # Найти слой границ работ
        boundaries_layer = None
        for layer in QgsProject.instance().mapLayers().values():
            if layer.name() == 'L_1_1_1_Границы_работ':
                boundaries_layer = layer
                break

        if not boundaries_layer:
            log_warning("Msm_34_2: L_1_1_1 не найден для сдвига экстента")
            return

        extent_manager = registry.get('M_18')

        # Пересчёт экстента от территории с south-extend
        extent = extent_manager.calculator.calculate_from_layer(boundaries_layer)
        extent = extent_manager.calculator.add_padding_south_extended(
            extent, padding_percent=5.0, safe_fraction=safe_fraction
        )
        extent = extent_manager.fitter.fit_extent_to_ratio(
            extent, map_width, map_height
        )

        # Сохранить размер и позицию map item — setExtent может их изменить
        original_width = main_map.rect().width()
        original_height = main_map.rect().height()
        original_x = main_map.pagePos().x()
        original_y = main_map.pagePos().y()

        main_map.setExtent(extent)

        # Восстановить фрейм карты
        main_map.attemptResize(QgsLayoutSize(
            original_width, original_height, Qgis.LayoutUnit.Millimeters
        ))
        main_map.attemptMove(QgsLayoutPoint(
            original_x, original_y, Qgis.LayoutUnit.Millimeters
        ))
        main_map.refresh()

        log_info(
            f"Msm_34_2: Экстент пересчитан (safe_fraction={safe_fraction:.2f}, "
            f"legend={legend_height:.0f} мм, "
            f"размер {original_width:.0f}x{original_height:.0f} мм)"
        )

    def _measure_height(self, legend: QgsLayoutItemLegend) -> float:
        """Измерить высоту легенды: sizeWithUnits -> fallback rect()."""
        h = legend.sizeWithUnits().height()
        if h > 0:
            return h
        return legend.rect().height()

    def _measure_width(self, legend: QgsLayoutItemLegend) -> float:
        """Измерить ширину легенды: sizeWithUnits -> fallback rect()."""
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
