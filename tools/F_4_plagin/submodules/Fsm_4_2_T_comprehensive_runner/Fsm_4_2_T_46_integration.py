# -*- coding: utf-8 -*-
"""
Fsm_4_2_T_46_integration — End-to-end интеграционный тест M_46 pipeline.

Отличие от Fsm_4_2_T_46 (unit-like с synthetic config_provider):
здесь используется РЕАЛЬНЫЙ LegendManager без подмены сабов — чтение
реального Base_layout.json через M_34. Проверяется склейка всех слоёв:
collect → calculate → plan → apply → customProperty.

Покрытие:
- 5 слоёв, A4 landscape DPT → inline success, predicted_height_mm > 0
- 30 слоёв, smoke (OPT-4 концессия: OverflowPlacement stub → fallback inline
  без крашей)
- Пустая легенда → штатный empty_content (no crash)

Crash-first: исключения из суб-менеджеров НЕ глотаются, всплывают в logger.fail.
"""

from typing import Any, List


class TestFsm4246Integration:
    """End-to-end интеграционный тест M_46 с реальным Base_layout config."""

    def __init__(self, iface: Any, logger: Any) -> None:
        self.iface = iface
        self.logger = logger
        self._created_layer_ids: List[str] = []

    def run_all_tests(self) -> None:
        """Entry point для comprehensive runner."""
        self.logger.section(
            "ТЕСТ M_46 integration: end-to-end pipeline с реальным config"
        )

        try:
            self.test_01_pipeline_5_layers_fits_inline()
            self.test_02_pipeline_overflow_smoke_30_layers()
            self.test_03_pipeline_empty_legend_no_crash()
        except Exception as e:
            self.logger.error(
                f"Критическая ошибка интеграционных тестов M_46: {str(e)}"
            )
            import traceback
            self.logger.data("Traceback", traceback.format_exc())
        finally:
            self._cleanup_layers()

        self.logger.summary()

    # === Helpers ===

    def _build_layout_with_n_layers(
        self, n: int, title_prefix: str = "Слой границ"
    ):
        """Создать QgsPrintLayout с legend (id='legend') + main_map + N слоёв."""
        from qgis.core import (
            QgsPrintLayout, QgsProject, QgsVectorLayer,
            QgsLayoutItemLegend, QgsLayoutItemMap,
        )

        project = QgsProject.instance()
        layout = QgsPrintLayout(project)
        layout.initializeDefaults()

        mmap = QgsLayoutItemMap(layout)
        mmap.setId('main_map')
        layout.addLayoutItem(mmap)

        layers = []
        for i in range(n):
            layer = QgsVectorLayer(
                "Point?crs=EPSG:4326",
                f"test_T46_int_layer_{i}",
                "memory",
            )
            project.addMapLayer(layer)
            self._created_layer_ids.append(layer.id())
            layers.append(layer)

        legend = QgsLayoutItemLegend(layout)
        legend.setId('legend')
        legend.setAutoUpdateModel(False)
        root = legend.model().rootGroup()
        root.removeAllChildren()
        for i, layer in enumerate(layers):
            node = root.addLayer(layer)
            node.setCustomProperty(
                "legend/title-label", f"{title_prefix} №{i}"
            )
        layout.addLayoutItem(legend)

        return layout, legend, layers

    def _cleanup_layers(self) -> None:
        """Удалить все memory-слои созданные тестами."""
        from qgis.core import QgsProject
        project = QgsProject.instance()
        for layer_id in self._created_layer_ids:
            try:
                project.removeMapLayer(layer_id)
            except Exception:
                pass
        self._created_layer_ids = []

    # === Тесты ===

    def test_01_pipeline_5_layers_fits_inline(self) -> None:
        """ТЕСТ 1: 5 слоёв средней длины → inline success, predicted_height > 0."""
        self.logger.section(
            "1. Pipeline 5 слоёв → inline + predicted_height_mm"
        )
        try:
            from Daman_QGIS.managers.styling.M_46_legend_manager import (
                LegendManager,
            )
            from Daman_QGIS.managers.styling.submodules.Msm_46_types import (
                LegendResult,
            )

            layout, _legend, _layers = self._build_layout_with_n_layers(5)

            mgr = LegendManager()
            result = mgr.plan_and_apply(
                layout, config_key='A4_landscape_DPT'
            )

            predicted = layout.customProperty(
                'legend/predicted_height_mm', 0.0
            )
            mode_ok = result.mode_applied in (
                'inline', 'overflow_fallback_inline',
            )

            self.logger.check(
                isinstance(result, LegendResult)
                and result.success is True
                and mode_ok
                and float(predicted) > 0.0,
                f"success={result.success}, mode={result.mode_applied}, "
                f"predicted_h={float(predicted):.1f} мм",
                f"Неуспех: success={result.success}, "
                f"mode={result.mode_applied}, predicted={predicted}, "
                f"warning={result.warning}",
            )
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")

    def test_02_pipeline_overflow_smoke_30_layers(self) -> None:
        """ТЕСТ 2: OPT-4 smoke — 30 слоёв, pipeline завершается без крашей.

        Замена убранного unit-теста OverflowPlacement stub: верифицируем
        что при числе слоёв, которое заведомо не влезет inline, цепочка
        корректно делает fallback (mode='overflow_fallback_inline' или
        'inline' с reason='tight_inline_may_overflow_visually').
        """
        self.logger.section("2. Overflow smoke (30 слоёв) — no crash")
        try:
            from Daman_QGIS.managers.styling.M_46_legend_manager import (
                LegendManager,
            )
            from Daman_QGIS.managers.styling.submodules.Msm_46_types import (
                LegendResult,
            )

            layout, _legend, _layers = self._build_layout_with_n_layers(
                30,
                title_prefix="Очень длинное название слоя границ работ",
            )

            mgr = LegendManager()
            # Не должно бросать исключение — OPT-4 концессия.
            result = mgr.plan_and_apply(
                layout, config_key='A4_landscape_DPT'
            )

            mode_ok = result.mode_applied in (
                'inline', 'overflow_fallback_inline',
            )
            completed = isinstance(result, LegendResult) and mode_ok

            self.logger.check(
                completed,
                f"Pipeline завершился: mode={result.mode_applied}, "
                f"success={result.success}, warning='{result.warning}'",
                f"Pipeline вернул неожиданный mode: "
                f"{result.mode_applied} (success={result.success})",
            )
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")

    def test_03_pipeline_empty_legend_no_crash(self) -> None:
        """ТЕСТ 3: Пустая легенда → штатный empty_content, pipeline не крашится."""
        self.logger.section("3. Пустая легенда → empty_content (no crash)")
        try:
            from qgis.core import (
                QgsPrintLayout, QgsProject,
                QgsLayoutItemLegend, QgsLayoutItemMap,
            )
            from Daman_QGIS.managers.styling.M_46_legend_manager import (
                LegendManager,
            )
            from Daman_QGIS.managers.styling.submodules.Msm_46_types import (
                LegendResult,
            )

            project = QgsProject.instance()
            layout = QgsPrintLayout(project)
            layout.initializeDefaults()

            mmap = QgsLayoutItemMap(layout)
            mmap.setId('main_map')
            layout.addLayoutItem(mmap)

            legend = QgsLayoutItemLegend(layout)
            legend.setId('legend')
            legend.setAutoUpdateModel(False)
            legend.model().rootGroup().removeAllChildren()
            layout.addLayoutItem(legend)

            mgr = LegendManager()
            result = mgr.plan_and_apply(
                layout, config_key='A4_landscape_DPT'
            )

            self.logger.check(
                isinstance(result, LegendResult)
                and result.success is False
                and result.mode_applied == 'empty_content'
                and result.warning is not None,
                f"success=False, mode='empty_content', "
                f"warning='{result.warning}'",
                f"Ожидался empty_content: success={result.success}, "
                f"mode={result.mode_applied}, warning={result.warning}",
            )
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")
