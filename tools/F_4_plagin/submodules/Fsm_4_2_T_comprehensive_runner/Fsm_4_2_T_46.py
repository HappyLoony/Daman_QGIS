# -*- coding: utf-8 -*-
"""
Fsm_4_2_T_46 — Интеграционный тест M_46 LegendManager (координатор).

End-to-end pipeline:
    collect → calculate → plan → apply

Crash-first модель:
- plan_and_apply возвращает LegendResult(success=False) ТОЛЬКО при штатных
  ранних return: no_legend / no_main_map / empty_content.
- Любые исключения из суб-менеджеров (unknown config_key, неизвестный
  placement mode и т.п.) ВСПЛЫВАЮТ наверх — НЕ конвертируются в success=False.

Покрытие:
- Импорт LegendManager
- 5 слоёв на валидном макете → inline success
- customProperty 'legend/predicted_height_mm' проставляется
- Нет legend → no_legend (не crash)
- Нет main_map → no_main_map (не crash)
- Пустая легенда → empty_content (не crash)
- Unknown config_key → RuntimeError ВСПЛЫВАЕТ (crash-first проверка)
- OPT-4 smoke: 30 слоёв → pipeline завершается
- _collect_content читает title из customProperty
"""

from typing import Any


class TestFsm4246:
    """Интеграционный тест M_46 LegendManager (facade pipeline, crash-first)."""

    def __init__(self, iface: Any, logger: Any) -> None:
        self.iface = iface
        self.logger = logger
        self._created_layer_ids: list = []

    def run_all_tests(self) -> None:
        """Entry point для comprehensive runner."""
        self.logger.section("ТЕСТ M_46: LegendManager (интеграция, crash-first)")

        try:
            self.test_01_import()
            self.test_02_pipeline_5_layers_fits_inline()
            self.test_03_predicted_height_in_custom_property()
            self.test_04_missing_legend_returns_no_legend()
            self.test_05_missing_main_map_returns_no_main_map()
            self.test_06_empty_legend_returns_empty_content()
            self.test_07_unknown_config_key_raises()
            self.test_08_overflow_smoke_30_layers()
            self.test_09_collect_reads_title_from_custom_property()
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

    def _new_layout(self):
        """Пустой QgsPrintLayout с initialized defaults."""
        from qgis.core import QgsPrintLayout, QgsProject
        layout = QgsPrintLayout(QgsProject.instance())
        layout.initializeDefaults()
        return layout

    def _add_main_map(self, layout):
        """Добавить QgsLayoutItemMap с id='main_map' в layout."""
        from qgis.core import QgsLayoutItemMap
        mmap = QgsLayoutItemMap(layout)
        mmap.setId('main_map')
        layout.addLayoutItem(mmap)
        return mmap

    def _add_legend_with_layers(self, layout, n: int, title_prefix: str):
        """
        Создать QgsLayoutItemLegend (id='legend') с n memory-слоями.

        Returns: (legend, layers) для последующей очистки.
        """
        from qgis.core import (
            QgsLayoutItemLegend, QgsProject, QgsVectorLayer,
        )

        legend = QgsLayoutItemLegend(layout)
        legend.setId('legend')
        legend.setAutoUpdateModel(False)

        model = legend.model()
        root = model.rootGroup()
        root.removeAllChildren()

        layers = []
        for i in range(n):
            layer = QgsVectorLayer(
                "Point?crs=EPSG:4326",
                f"test_T46_layer_{i}",
                "memory",
            )
            QgsProject.instance().addMapLayer(layer)
            self._created_layer_ids.append(layer.id())
            node = root.addLayer(layer)
            node.setCustomProperty(
                "legend/title-label", f"{title_prefix} №{i}"
            )
            layers.append(layer)

        layout.addLayoutItem(legend)
        return legend, layers

    def _synthetic_config_provider(self):
        """
        Возвращает callable (config_key) -> dict с синтетическим Base_layout.

        OPT-5 consensus: избегаем зависимости от реальных чисел Base_layout.json.
        Провайдер возвращает config для ЛЮБОГО ключа — для тестов штатных
        путей. Для негативного теста unknown_config_key используется
        отдельный провайдер, возвращающий None.
        """
        synthetic = {
            'legend_x': 20,
            'legend_y': 205,
            'legend_ref_point': 1,
            'overview_map_x': 250,
            'overview_map_y': 205,
            'overview_map_width': 40,
            'overview_map_height': 40,
            'overview_map_ref_point': 3,
            'legend_overlay_gap_mm': 5,
            'main_map_height': 180,
            'legend_max_height_ratio': 0.45,
            'page_width': 297,
            'margin_right_mm': 5,
            'legend_placement_mode': 'inline',
            'legend_min_symbol_width': 10,
            'legend_min_symbol_height': 3.5,
            'legend_min_wrap_length': 40,
            'font_family': 'GOST 2.304',
            'font_size_pt': 14,
            # legend_layout_modes refactoring (v0.4): M_46.facade._build_space
            # читает явные legend_dynamic_* по legend_layout_mode из Excel.
            # overview_map_x=250, ref=3 → overview_left=210; legend_dynamic_x=20,
            # width=180, gap=5 → legend_right+gap=205 < 210 (sanity OK).
            'legend_layout_mode': 'dynamic',
            'legend_dynamic_x': 20,
            'legend_dynamic_y': 205,
            'legend_dynamic_width_mm': 180,
            'legend_dynamic_height_max_mm': 81,
            'legend_dynamic_ref_point': 1,
            'legend_dynamic_overlay_gap_mm': 5,
        }
        return lambda key: synthetic

    def _apply_synthetic_pipeline(
        self,
        layout,
        config_key: str = 'synthetic_A4_DPT',
        provider=None,
    ):
        """
        Запустить mgr.plan_and_apply с monkey-patched _default_config_provider.

        M_46.facade.plan_and_apply вызывает Msm_46_2._default_config_provider
        напрямую (минуя _calculator/_planner), поэтому DI через
        SpaceCalculator/LayoutPlanner недостаточно — Base_layout.json требует
        реального M_34 в registry. Тест должен подменить и facade-уровень.
        """
        from unittest.mock import patch
        from Daman_QGIS.managers.styling.submodules import (
            Msm_46_2_space_calculator as scm,
        )
        if provider is None:
            provider = self._synthetic_config_provider()
        mgr = self._build_manager_with_synthetic_config(provider=provider)
        with patch.object(
            scm, '_default_config_provider', side_effect=provider,
        ):
            return mgr.plan_and_apply(layout, config_key=config_key)

    def _build_manager_with_synthetic_config(self, provider=None):
        """
        LegendManager с подменённым config_provider у суб-менеджеров.

        Не читаем Base_layout.json — тест полностью изолирован.

        Args:
            provider: опциональный config_provider; по умолчанию —
                _synthetic_config_provider(). Для негативных тестов
                передавать lambda k: None.
        """
        from Daman_QGIS.managers.styling.M_46_legend_manager import (
            LegendManager,
        )
        from Daman_QGIS.managers.styling.submodules.Msm_46_2_space_calculator import (
            SpaceCalculator,
        )
        from Daman_QGIS.managers.styling.submodules.Msm_46_3_layout_planner import (
            LayoutPlanner,
        )

        if provider is None:
            provider = self._synthetic_config_provider()
        mgr = LegendManager()
        mgr._calculator = SpaceCalculator(config_provider=provider)
        mgr._planner = LayoutPlanner(config_provider=provider)
        return mgr

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

    # === Группа 1: Импорт ===

    def test_01_import(self) -> None:
        """ТЕСТ 1: Импорт LegendManager и корректные атрибуты."""
        self.logger.section("1. Импорт LegendManager")
        try:
            from Daman_QGIS.managers.styling.M_46_legend_manager import (
                LegendManager,
            )
            from Daman_QGIS.managers.styling.submodules.Msm_46_types import (
                LegendResult,
            )
            mgr = LegendManager()
            has_api = (
                hasattr(mgr, 'plan_and_apply')
                and callable(mgr.plan_and_apply)
                and hasattr(mgr, '_collect_content')
            )
            self.logger.check(
                has_api and LegendResult is not None,
                "LegendManager импортирован, plan_and_apply доступен",
                "Импорт/атрибуты провалились",
            )
        except Exception as e:
            self.logger.fail(f"Ошибка импорта: {e}")

    # === Группа 2: Основной pipeline ===

    def test_02_pipeline_5_layers_fits_inline(self) -> None:
        """ТЕСТ 2: 5 слоёв средней длины → inline success."""
        self.logger.section("2. Pipeline 5 слоёв → inline")
        try:
            from Daman_QGIS.managers.styling.submodules.Msm_46_types import (
                LegendResult, LegendLayoutMode,
            )

            layout = self._new_layout()
            self._add_main_map(layout)
            self._add_legend_with_layers(layout, 5, "Слой границ")

            result = self._apply_synthetic_pipeline(layout)

            self.logger.check(
                isinstance(result, LegendResult)
                and result.success is True
                and result.mode_applied == LegendLayoutMode.DYNAMIC,
                f"success={result.success}, mode={result.mode_applied}",
                f"Неуспех: success={result.success}, "
                f"mode={result.mode_applied}, warning={result.warning}",
            )
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")

    def test_03_predicted_height_in_custom_property(self) -> None:
        """ТЕСТ 3: predicted_height_mm проставлен в customProperty layout."""
        self.logger.section("3. predicted_height_mm в customProperty")
        try:
            layout = self._new_layout()
            self._add_main_map(layout)
            self._add_legend_with_layers(layout, 3, "Слой")

            self._apply_synthetic_pipeline(layout)

            predicted = layout.customProperty(
                'legend/predicted_height_mm', 0.0
            )
            self.logger.check(
                float(predicted) > 0.0,
                f"predicted_height_mm={float(predicted):.1f} мм",
                f"predicted_height_mm не проставлен или <=0: {predicted}",
            )
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")

    # === Группа 3: Штатные ранние return (success=False, mode_applied) ===

    def test_04_missing_legend_returns_no_legend(self) -> None:
        """ТЕСТ 4: Нет QgsLayoutItemLegend → mode_applied='no_legend'."""
        self.logger.section("4. Missing legend → no_legend")
        try:
            from Daman_QGIS.managers.styling.submodules.Msm_46_types import (
                LegendResult,
            )

            layout = self._new_layout()
            self._add_main_map(layout)
            # Легенда НЕ добавлена

            mgr = self._build_manager_with_synthetic_config()
            result = mgr.plan_and_apply(layout, config_key='synthetic_A4_DPT')

            self.logger.check(
                isinstance(result, LegendResult)
                and result.success is False
                and result.mode_applied == 'no_legend'
                and result.warning is not None,
                f"success=False, mode='no_legend', warning='{result.warning}'",
                f"Ожидался no_legend: success={result.success}, "
                f"mode={result.mode_applied}",
            )
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")

    def test_05_missing_main_map_returns_no_main_map(self) -> None:
        """ТЕСТ 5: Нет QgsLayoutItemMap id='main_map' → no_main_map."""
        self.logger.section("5. Missing main_map → no_main_map")
        try:
            from Daman_QGIS.managers.styling.submodules.Msm_46_types import (
                LegendResult,
            )

            layout = self._new_layout()
            # main_map НЕ добавлен
            self._add_legend_with_layers(layout, 2, "Слой")

            mgr = self._build_manager_with_synthetic_config()
            result = mgr.plan_and_apply(layout, config_key='synthetic_A4_DPT')

            self.logger.check(
                isinstance(result, LegendResult)
                and result.success is False
                and result.mode_applied == 'no_main_map'
                and result.warning is not None,
                f"success=False, mode='no_main_map', "
                f"warning='{result.warning}'",
                f"Ожидался no_main_map: success={result.success}, "
                f"mode={result.mode_applied}",
            )
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")

    def test_06_empty_legend_returns_empty_content(self) -> None:
        """ТЕСТ 6: Легенда без слоёв → mode_applied='empty_content'."""
        self.logger.section("6. Пустая легенда → empty_content")
        try:
            from qgis.core import QgsLayoutItemLegend
            from Daman_QGIS.managers.styling.submodules.Msm_46_types import (
                LegendResult,
            )

            layout = self._new_layout()
            self._add_main_map(layout)

            legend = QgsLayoutItemLegend(layout)
            legend.setId('legend')
            legend.setAutoUpdateModel(False)
            legend.model().rootGroup().removeAllChildren()
            layout.addLayoutItem(legend)

            result = self._apply_synthetic_pipeline(layout)

            self.logger.check(
                isinstance(result, LegendResult)
                and result.success is False
                and result.mode_applied == 'empty_content'
                and result.warning is not None,
                f"success=False, mode='empty_content'",
                f"Ожидался empty_content: success={result.success}, "
                f"mode={result.mode_applied}, warning={result.warning}",
            )
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")

    # === Группа 4: Crash-first (исключения ВСПЛЫВАЮТ) ===

    def test_07_unknown_config_key_raises(self) -> None:
        """ТЕСТ 7: Unknown config_key → RuntimeError ВСПЛЫВАЕТ (crash-first)."""
        self.logger.section("7. Unknown config_key → RuntimeError всплывает")
        try:
            layout = self._new_layout()
            self._add_main_map(layout)
            self._add_legend_with_layers(layout, 2, "Слой")

            # provider возвращает None для любого ключа —
            # Msm_46_2.SpaceCalculator бросит RuntimeError.
            # plan_and_apply НЕ должен его глотать (crash-first).
            none_provider = lambda k: None
            mgr = self._build_manager_with_synthetic_config(
                provider=none_provider
            )

            raised = False
            exc_type = None
            exc_msg = ""
            try:
                mgr.plan_and_apply(layout, config_key='A2_unknown')
            except RuntimeError as e:
                raised = True
                exc_type = type(e).__name__
                exc_msg = str(e)
            except Exception as e:
                # Любое другое исключение также подтверждает crash-first,
                # но ожидаем именно RuntimeError от Msm_46_2.
                raised = True
                exc_type = type(e).__name__
                exc_msg = str(e)

            self.logger.check(
                raised and 'A2_unknown' in exc_msg,
                f"Исключение всплыло: {exc_type}: {exc_msg}",
                f"Исключение НЕ всплыло (crash-first нарушен): "
                f"raised={raised}, type={exc_type}, msg={exc_msg}",
            )
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")

    # === Группа 5: Граничные случаи ===

    def test_08_overflow_smoke_30_layers(self) -> None:
        """ТЕСТ 8: 30 слоёв с длинными именами → pipeline завершается."""
        self.logger.section("8. Overflow smoke (30 слоёв)")
        try:
            from Daman_QGIS.managers.styling.submodules.Msm_46_types import (
                LegendResult,
            )

            layout = self._new_layout()
            self._add_main_map(layout)
            self._add_legend_with_layers(
                layout, 30,
                "Очень длинное название слоя границ работ и планировки",
            )

            result = self._apply_synthetic_pipeline(layout)

            # LayoutPlanner вернул dynamic tight с reason warning либо
            # OutsidePlacement stub (success=False, mode_applied='outside_stub').
            # Crash-first: исключений быть не должно, иначе тест упадёт
            # выше через except блок.
            mode_ok = result.mode_applied in (
                'dynamic', 'outside_stub',
            )
            self.logger.check(
                isinstance(result, LegendResult) and mode_ok,
                f"Pipeline завершился: mode={result.mode_applied}, "
                f"success={result.success}, warning='{result.warning}'",
                f"Pipeline вернул неизвестный mode: {result.mode_applied}",
            )
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")

    def test_09_collect_reads_title_from_custom_property(self) -> None:
        """ТЕСТ 9: _collect_content читает title из customProperty, fallback на name()."""
        self.logger.section("9. _collect_content title priority")
        try:
            from qgis.core import (
                QgsLayoutItemLegend, QgsProject, QgsVectorLayer,
            )
            from Daman_QGIS.managers.styling.M_46_legend_manager import (
                LegendManager,
            )

            layout = self._new_layout()
            self._add_main_map(layout)

            legend = QgsLayoutItemLegend(layout)
            legend.setId('legend')
            legend.setAutoUpdateModel(False)
            root = legend.model().rootGroup()
            root.removeAllChildren()

            # Слой 1: с customProperty
            layer_a = QgsVectorLayer(
                "Point?crs=EPSG:4326", "layer_name_A", "memory",
            )
            QgsProject.instance().addMapLayer(layer_a)
            self._created_layer_ids.append(layer_a.id())
            node_a = root.addLayer(layer_a)
            node_a.setCustomProperty(
                "legend/title-label", "Custom Заголовок A",
            )

            # Слой 2: без customProperty
            layer_b = QgsVectorLayer(
                "Point?crs=EPSG:4326", "layer_name_B", "memory",
            )
            QgsProject.instance().addMapLayer(layer_b)
            self._created_layer_ids.append(layer_b.id())
            root.addLayer(layer_b)

            layout.addLayoutItem(legend)

            mgr = LegendManager()
            content = mgr._collect_content(layout)

            titles = [it.title for it in content.items]
            has_custom = "Custom Заголовок A" in titles
            has_fallback = "layer_name_B" in titles
            self.logger.check(
                content.count == 2 and has_custom and has_fallback,
                f"Titles OK: {titles}",
                f"Неверный сбор title: count={content.count}, titles={titles}",
            )
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")
