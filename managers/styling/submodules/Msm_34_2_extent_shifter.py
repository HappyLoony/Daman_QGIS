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

from typing import Optional, Tuple

from qgis.core import (
    QgsPrintLayout, QgsLayoutItemMap, QgsLayoutItemLegend, QgsLayoutItem
)

from Daman_QGIS.utils import log_info, log_warning

from .Msm_46_types import LegendLayoutMode


# Tolerance для bbox-intersection: компенсирует frame-stroke padding
# в QGraphicsItem.sceneBoundingRect() (~0.3-0.5 мм при frame=True) +
# Qt sub-pixel jitter (~0.1 мм) + safety margin (~0.4 мм) = 1 мм.
# Реальные overlap'ы в F_1_4 dynamic режиме > 5 мм — детектируются.
BBOX_TOLERANCE_MM = 1.0


class ExtentShifter:
    """
    Сдвиг экстента main_map под overlay легенды.

    Алгоритм (один проход, без итераций):
    0. Bbox-intersection: получить bbox main_map / legend / overview_map в
       page coords. Если legend / overview не пересекают main_map — соответ-
       ствующая safe-фракция = 1.0 (shift в эту сторону не применяется).
       Поддерживает макеты с overlay (A4_DPT) и с правой полосой (A3_MP).
    1. Forced render (exportToImage в tmp) для инициализации paint pipeline.
       sizeWithUnits() возвращает 0 до первого paint — workaround QGIS.
    2. Измерение фактического bbox легенды.
    3. Пересчёт экстента через M_18.add_padding_overlay_safe с
       safe_fraction = (map_h - leg_h) / map_h, clamp [0.3, 0.95]
       (clamp применяется только при наличии overlap).
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
        # Routing по режиму через customProperty (установлено Msm_34_1.build).
        # RuntimeError если customProperty отсутствует — означает что layout
        # создан минуя Msm_34_1 (consistency с §7.5 crash-first).
        config_key = layout.customProperty('layout/config_key')
        if not config_key:
            raise RuntimeError(
                "Msm_34_2: layout без customProperty 'layout/config_key' — "
                "макет должен быть создан через Msm_34_1.create_layout(). "
                "Тесты, создающие QgsPrintLayout напрямую, должны устанавливать "
                "customProperty вручную либо моки M_34.adapt_legend."
            )

        from Daman_QGIS.managers import registry
        layout_mgr = registry.get('M_34')
        config = (
            layout_mgr.get_layout_config_by_key(config_key)
            if layout_mgr is not None else None
        )
        mode = config.get('legend_layout_mode') if config else None

        if mode != LegendLayoutMode.DYNAMIC:
            log_info(
                f"Msm_34_2: режим {mode} для config_key={config_key} — "
                f"extent shift не требуется (skip)"
            )
            return True

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
        Пересчитать экстент main_map с адаптивным выбором safe-зоны.

        Три режима выбираются по aspect ratio объекта (boundaries layer):
        - A (horizontal_band): широкие низкие объекты — safe = верхняя полоса
          полной ширины высотой (map_h - max(legend_h, overview_h + buf))
        - B (vertical_column): узкие высокие / квадратные — safe = левая колонка
          полной высоты шириной (map_w - overview_w - buf)
        - V3 (combo): промежуточные — пересечение A и B (верхне-левый угол)

        Выбор максимизирует используемое место для данной формы объекта.
        """
        from Daman_QGIS.managers import registry
        from qgis.core import QgsLayoutSize, QgsLayoutPoint, Qgis, QgsProject

        map_height = main_map.rect().height()
        map_width = main_map.rect().width()
        overlay_buf = 5.0  # мм буфер между safe-зоной и overlay

        # Найти слой границ работ (нужен для aspect ratio объекта)
        boundaries_layer = None
        for layer in QgsProject.instance().mapLayers().values():
            if layer.name() == 'L_1_1_1_Границы_работ':
                boundaries_layer = layer
                break

        if not boundaries_layer:
            log_warning("Msm_34_2: L_1_1_1 не найден для сдвига экстента")
            return

        obj_extent = boundaries_layer.extent()
        if obj_extent.height() <= 0:
            log_warning("Msm_34_2: нулевая высота границ — сдвиг экстента пропущен")
            return
        obj_aspect = obj_extent.width() / obj_extent.height()

        overview_width = self._measure_overview_width(layout)
        overview_height = self._measure_overview_height(layout)

        # === Bbox-intersection: определить какие overlay реально пересекают main_map ===
        main_bbox = self._get_item_page_bbox(layout, 'main_map')
        legend_bbox = self._get_item_page_bbox(layout, 'legend')
        overview_bbox = self._get_item_page_bbox(layout, 'overview_map')

        if main_bbox is None:
            log_warning("Msm_34_2: main_map bbox не получен — сдвиг экстента пропущен")
            return

        log_info(
            f"Msm_34_2: bbox main_map = "
            f"({main_bbox[0]:.1f}, {main_bbox[1]:.1f}, "
            f"{main_bbox[2]:.1f}, {main_bbox[3]:.1f}) мм"
        )
        if legend_bbox is not None:
            log_info(
                f"Msm_34_2: bbox legend = "
                f"({legend_bbox[0]:.1f}, {legend_bbox[1]:.1f}, "
                f"{legend_bbox[2]:.1f}, {legend_bbox[3]:.1f}) мм"
            )
        if overview_bbox is not None:
            log_info(
                f"Msm_34_2: bbox overview = "
                f"({overview_bbox[0]:.1f}, {overview_bbox[1]:.1f}, "
                f"{overview_bbox[2]:.1f}, {overview_bbox[3]:.1f}) мм"
            )

        legend_overlaps = (
            legend_bbox is not None
            and self._bbox_intersects(main_bbox, legend_bbox)
        )
        overview_overlaps = (
            overview_bbox is not None
            and self._bbox_intersects(main_bbox, overview_bbox)
        )

        log_info(
            f"Msm_34_2: legend пересекает main_map = {legend_overlaps} "
            f"(tolerance={BBOX_TOLERANCE_MM}), "
            f"overview пересекает main_map = {overview_overlaps}"
        )

        # Early return: если ни legend, ни overview не пересекают main_map —
        # extent остаётся как был установлен apply_main_map_extent (стабильный
        # для всех схем при одинаковом bbox main_map). Не вызываем
        # add_padding_overlay_safe чтобы runtime legend_height (разная для каждой
        # схемы из-за разного количества пунктов) не влиял на масштаб main_map.
        if not legend_overlaps and not overview_overlaps:
            log_info(
                "Msm_34_2: legend и overview оба вне main_map — extent не "
                "пересчитывается, остаётся как после apply_main_map_extent "
                "(масштаб стабильный)"
            )
            return

        # Safe-зоны (без overlay_buf в мм считаются по реальным размерам main_map)
        top_band_h = map_height - max(legend_height, overview_height + overlay_buf)
        left_col_w = map_width - overview_width - overlay_buf if overview_width > 0 else map_width

        # Aspect ratio safe-зон (для сравнения с obj_aspect)
        # Защита от деления на 0: если safe-зона вырождена, считаем aspect = inf/0
        top_band_aspect = map_width / top_band_h if top_band_h > 0 else float('inf')
        left_col_aspect = left_col_w / map_height if map_height > 0 else 0

        # Выбор режима
        if overview_width <= 0:
            # Нет overview — только south по legend
            mode = 'A_no_overview'
            safe_south = (map_height - legend_height) / map_height
            safe_east = 1.0
        elif obj_aspect >= top_band_aspect:
            # Широкий низкий объект — используем верхнюю полосу полной ширины
            mode = 'A_horizontal'
            safe_south = top_band_h / map_height
            safe_east = 1.0
        elif obj_aspect <= left_col_aspect:
            # Узкий высокий / квадратный — используем левую колонку полной высоты
            mode = 'B_vertical'
            safe_south = (map_height - legend_height) / map_height
            safe_east = left_col_w / map_width
        else:
            # Промежуточный aspect — комбо (пересечение A и B)
            mode = 'V3_combo'
            safe_south = (map_height - legend_height) / map_height
            safe_east = left_col_w / map_width

        # Clamp применяем только при наличии overlap (safe < 1.0).
        # При safe == 1.0 (нет overlap) — оставляем 1.0 как маркер «без shift».
        if legend_overlaps:
            safe_south = max(0.3, min(safe_south, 0.95))
        # else: safe_south остаётся как посчитан adaptive mode'ом — дальше override

        if overview_overlaps:
            safe_east = max(0.3, min(safe_east, 0.95)) if safe_east < 1.0 else 1.0
        # else: override ниже

        log_info(
            f"Msm_34_2: Adaptive mode={mode} (obj_aspect={obj_aspect:.2f}, "
            f"top_band_aspect={top_band_aspect:.2f}, left_col_aspect={left_col_aspect:.2f})"
        )

        # === Override: если элемент вне main_map, safe = 1.0 (shift не нужен) ===
        if not legend_overlaps:
            safe_south = 1.0
            log_info(
                "Msm_34_2: legend вне main_map → safe_south=1.0 "
                "(сдвиг экстента на юг не требуется)"
            )

        if not overview_overlaps:
            safe_east = 1.0
            log_info(
                "Msm_34_2: overview вне main_map → safe_east=1.0 "
                "(сдвиг экстента на восток не требуется)"
            )

        extent_manager = registry.get('M_18')

        # Пересчёт экстента
        extent = extent_manager.calculator.calculate_from_layer(boundaries_layer)
        extent = extent_manager.calculator.add_padding_overlay_safe(
            extent,
            padding_percent=5.0,
            safe_fraction_south=safe_south,
            safe_fraction_east=safe_east
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
            f"Msm_34_2: Экстент пересчитан "
            f"(safe_south={safe_south:.2f}, safe_east={safe_east:.2f}, "
            f"legend_overlap={legend_overlaps}, overview_overlap={overview_overlaps}, "
            f"legend={legend_height:.0f} мм, overview={overview_width:.0f}x{overview_height:.0f} мм, "
            f"размер {original_width:.0f}x{original_height:.0f} мм)"
        )

    def _get_item_page_bbox(
        self, layout: QgsPrintLayout, item_id: str
    ) -> Optional[Tuple[float, float, float, float]]:
        """Вернуть (left, top, right, bottom) элемента в page coords (мм).

        Использует Qt-метод sceneBoundingRect() — это детерминированный bbox
        в scene coords без необходимости учитывать referencePoint(). В layout
        с одной страницей scene = page, в multi-page — координата top отражает
        смещение страниц, но для нас достаточно относительного пересечения
        внутри одной страницы (main_map / legend / overview всегда на одной
        странице A3/A4 макета).

        Возвращает None если элемент не найден.
        """
        for item in layout.items():
            if not isinstance(item, QgsLayoutItem):
                continue
            if item.id() != item_id:
                continue
            rect = item.sceneBoundingRect()
            return (rect.left(), rect.top(), rect.right(), rect.bottom())
        return None

    @staticmethod
    def _bbox_intersects(
        a: Tuple[float, float, float, float],
        b: Tuple[float, float, float, float],
        tol: float = BBOX_TOLERANCE_MM,
    ) -> bool:
        """Проверка пересечения двух bbox (left, top, right, bottom) с tolerance.

        Tolerance компенсирует frame-stroke padding в sceneBoundingRect()
        при math-touching layout (см. §13 R6 плана). По умолчанию 1.0 мм —
        выше уровня rounding error, ниже минимального cartographic overlap'а.

        Args:
            a, b: bbox в формате (left, top, right, bottom) мм
            tol: терпимость в мм (default = BBOX_TOLERANCE_MM)

        Returns:
            True если bbox пересекаются с превышением tol по обоим осям.
        """
        a_left, a_top, a_right, a_bottom = a
        b_left, b_top, b_right, b_bottom = b
        if a_right - tol <= b_left or b_right - tol <= a_left:
            return False
        if a_bottom - tol <= b_top or b_bottom - tol <= a_top:
            return False
        return True

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

    def _measure_overview_width(self, layout: QgsPrintLayout) -> float:
        """
        Получить ширину overview_map (в мм) для east-extend экстента.

        Возвращает 0 если overview_map отсутствует.
        """
        for item in layout.items():
            if isinstance(item, QgsLayoutItemMap) and item.id() == 'overview_map':
                return item.rect().width()
        return 0.0

    def _measure_overview_height(self, layout: QgsPrintLayout) -> float:
        """
        Получить высоту overview_map (в мм) для south-extend при adaptive выборе.

        Возвращает 0 если overview_map отсутствует.
        """
        for item in layout.items():
            if isinstance(item, QgsLayoutItemMap) and item.id() == 'overview_map':
                return item.rect().height()
        return 0.0
