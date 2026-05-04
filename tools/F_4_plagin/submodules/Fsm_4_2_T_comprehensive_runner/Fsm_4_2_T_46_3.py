# -*- coding: utf-8 -*-
"""
Fsm_4_2_T_46_3 — Тесты Msm_46_3_LayoutPlanner.

Детерминированный планнер без рендера QGIS: проверка через
QFontMetrics + формульное предсказание высоты.

Покрытие:
- Импорт модуля
- wrap_text: base cases (short, many words, long unbreakable word)
- wrap_text: сохранение короткого текста без \\n
- plan: 1 короткий item → col=1
- plan: много items → col >= 2
- plan: overflow mode → LegendPlan.mode='overflow'
- plan: inline mode + не fits → tight plan с reason
- plan: empty content → валидный план
- plan: RuntimeError на unknown config_key
"""

from typing import Any


class TestMsm463:
    """Тесты Msm_46_3 LayoutPlanner."""

    def __init__(self, iface: Any, logger: Any) -> None:
        self.iface = iface
        self.logger = logger

    def run_all_tests(self) -> None:
        """Entry point для comprehensive runner."""
        self.logger.section("ТЕСТ Msm_46_3: LayoutPlanner")

        try:
            self.test_01_import()
            self.test_02_wrap_text_short_unchanged()
            self.test_03_wrap_text_many_words_inserts_newline()
            self.test_04_wrap_text_long_unbreakable_word()
            self.test_05_wrap_text_preserves_sentence()
            self.test_06_plan_single_short_item_col1()
            self.test_07_plan_many_items_col_ge_2()
            self.test_08_plan_extreme_overflow_smoke()
            self.test_09_plan_inline_tight_when_doesnt_fit()
            self.test_10_plan_empty_content()
            self.test_11_plan_raises_on_unknown_config()
        except Exception as e:
            self.logger.error(f"Критическая ошибка тестов Msm_46_3: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

        self.logger.summary()

    # === Helpers ===

    def _make_content(self, titles):
        from Daman_QGIS.managers.styling.submodules.Msm_46_types import (
            LegendContent, LegendItem,
        )
        return LegendContent(items=[
            LegendItem(layer_name=f"L_{i}", title=t)
            for i, t in enumerate(titles)
        ])

    def _make_space(self, w: float = 192, h: float = 76.5):
        from Daman_QGIS.managers.styling.submodules.Msm_46_types import (
            AvailableSpace,
        )
        return AvailableSpace(
            max_width_mm=w, max_height_mm=h,
            legend_anchor_x=20, legend_anchor_y=205, legend_ref_point=1,
        )

    def _config_inline(self):
        return {
            'legend_placement_mode': 'dynamic',
            'legend_min_symbol_width': 10,
            'legend_min_symbol_height': 3.5,
            'legend_min_wrap_length': 40,
            'font_family': 'GOST 2.304',
            'font_size_pt': 14,
        }

    # _config_overflow удалён: поле `legend_placement_mode` планнер
    # больше не использует. OUTSIDE-routing выполняется в M_46.facade
    # (early return ДО planner.plan), поэтому planner всегда возвращает
    # mode=LegendLayoutMode.DYNAMIC. Для тестов overflow-сценариев
    # используется тот же _config_inline + extreme content/space.

    def _planner_with(self, config):
        from Daman_QGIS.managers.styling.submodules.Msm_46_3_layout_planner import (
            LayoutPlanner,
        )
        return LayoutPlanner(config_provider=lambda k: config)

    # === Группа 1: Импорт ===

    def test_01_import(self) -> None:
        """ТЕСТ 1: Импорт Msm_46_3_LayoutPlanner."""
        self.logger.section("1. Импорт модуля")
        try:
            from Daman_QGIS.managers.styling.submodules.Msm_46_3_layout_planner import (
                LayoutPlanner,
            )
            self.logger.check(
                callable(LayoutPlanner) and hasattr(LayoutPlanner, 'plan')
                and hasattr(LayoutPlanner, 'wrap_text'),
                "LayoutPlanner импортирован с plan и wrap_text",
                "Один из методов отсутствует",
            )
        except Exception as e:
            self.logger.fail(f"Ошибка импорта: {e}")

    # === Группа 2: wrap_text ===

    def _font_metrics(self):
        """Helper: QFontMetricsF на тестовом шрифте Arial 14pt."""
        from qgis.PyQt.QtGui import QFont, QFontMetricsF
        return QFontMetricsF(QFont("Arial", 14))

    def test_02_wrap_text_short_unchanged(self) -> None:
        """ТЕСТ 2: wrap_text короткого текста не вставляет \\n."""
        self.logger.section("2. wrap_text: короткий текст")
        try:
            from Daman_QGIS.managers.styling.submodules.Msm_46_3_layout_planner import (
                LayoutPlanner,
            )
            # 200 мм — заведомо больше длины 'short'
            result = LayoutPlanner.wrap_text("short", 200.0, self._font_metrics())
            self.logger.check(
                result == "short" and '\n' not in result,
                f"'short' в 200 мм → '{result}'",
                f"Неожиданный результат: '{result}'",
            )
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")

    def test_03_wrap_text_many_words_inserts_newline(self) -> None:
        """ТЕСТ 3: wrap_text разбивает длинный текст на строки."""
        self.logger.section("3. wrap_text: длинный текст")
        try:
            from Daman_QGIS.managers.styling.submodules.Msm_46_3_layout_planner import (
                LayoutPlanner,
            )
            # 15 мм — узко, 12 однобуквенных слов не поместятся в одну строку
            result = LayoutPlanner.wrap_text(
                "a b c d e f g h i j k l", 15.0, self._font_metrics()
            )
            self.logger.check(
                '\n' in result,
                f"Вставлен хотя бы один \\n: '{result}'",
                f"Перенос не сработал: '{result}'",
            )
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")

    def test_04_wrap_text_long_unbreakable_word(self) -> None:
        """ТЕСТ 4: Слово шире max_width_mm остаётся на своей строке."""
        self.logger.section("4. wrap_text: неразбиваемое слово")
        try:
            from Daman_QGIS.managers.styling.submodules.Msm_46_3_layout_planner import (
                LayoutPlanner,
            )
            # 10 мм — узко, длинное слово точно не поместится
            result = LayoutPlanner.wrap_text(
                "supercalifragilistic", 10.0, self._font_metrics()
            )
            self.logger.check(
                "supercalifragilistic" in result,
                f"Неразбиваемое слово сохранено целиком: '{result}'",
                f"Слово было разрезано: '{result}'",
            )
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")

    def test_05_wrap_text_preserves_sentence(self) -> None:
        """ТЕСТ 5: Фраза влезающая в max_width возвращается без \\n."""
        self.logger.section("5. wrap_text: фраза в пределах max_width")
        try:
            from Daman_QGIS.managers.styling.submodules.Msm_46_3_layout_planner import (
                LayoutPlanner,
            )
            text = "Границы работ"
            # 100 мм — заведомо больше реальной ширины текста
            result = LayoutPlanner.wrap_text(text, 100.0, self._font_metrics())
            self.logger.check(
                result == text,
                f"Фраза сохранена: '{result}'",
                f"Неожиданный перенос: '{result}'",
            )
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")

    # === Группа 3: plan() базовые ===

    def test_06_plan_single_short_item_col1(self) -> None:
        """ТЕСТ 6: 1 короткий item → col=1, plan.mode='inline'."""
        self.logger.section("6. plan: 1 короткий item → col=1")
        try:
            planner = self._planner_with(self._config_inline())
            plan = planner.plan(
                content=self._make_content(["Границы работ"]),
                space=self._make_space(),
                config_key='synthetic_A4',
            )
            self.logger.check(
                plan.mode == 'dynamic' and plan.column_count == 1,
                f"mode={plan.mode}, col={plan.column_count}",
                f"Ожидалось dynamic/col=1, получено {plan.mode}/{plan.column_count}",
            )
            self.logger.check(
                plan.symbol_width >= 10 and plan.predicted_height_mm >= 0,
                f"symbol_w={plan.symbol_width}, h_pred={plan.predicted_height_mm:.1f}",
                "Некорректные symbol/height",
            )
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")

    def test_07_plan_many_items_col_ge_2(self) -> None:
        """ТЕСТ 7: Много длинных items → col >= 2."""
        self.logger.section("7. plan: много items → col >= 2")
        try:
            titles = [
                "Границы земельных участков (ЕГРН)",
                "Зоны с особыми условиями использования территорий",
                "Красные линии планировочных элементов",
                "Границы населённых пунктов",
                "Границы кадастровых округов",
                "Границы территориальных зон",
            ] * 2
            planner = self._planner_with(self._config_inline())
            plan = planner.plan(
                content=self._make_content(titles),
                space=self._make_space(),
                config_key='synthetic_A4',
            )
            self.logger.check(
                plan.column_count >= 2,
                f"col={plan.column_count} (>=2)",
                f"Ожидалось col>=2, получено {plan.column_count}",
            )
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")

    def test_08_plan_extreme_overflow_smoke(self) -> None:
        """ТЕСТ 8: Extreme overflow (50 длинных titles) — planner не падает,
        возвращает dynamic + reason + predicted_h > space.max_h.

        Контракт планнера (Msm_46_3): mode всегда LegendLayoutMode.DYNAMIC
        ("planner-internal" значение для логов). OUTSIDE-routing выполняется
        в M_46.facade (early return ДО вызова planner.plan), поэтому planner
        НЕ может вернуть mode='outside'. Этот тест проверяет worst-case
        smoke: planner возвращает валидный план с reason при extreme overflow.
        Отличается от test_09 объёмом (50 vs 30 items) и проверкой
        predicted_h vs space.max_height_mm.
        """
        self.logger.section("8. plan: extreme overflow smoke")
        try:
            titles = [
                "Очень длинное название слоя границ земельных участков " * 3
            ] * 50
            planner = self._planner_with(self._config_inline())
            space = self._make_space(w=192, h=50)
            plan = planner.plan(
                content=self._make_content(titles),
                space=space,
                config_key='synthetic_A4',
            )
            self.logger.check(
                plan.mode == 'dynamic'
                and plan.reason is not None
                and plan.predicted_height_mm > space.max_height_mm,
                f"mode={plan.mode}, reason={plan.reason}, "
                f"h_pred={plan.predicted_height_mm:.1f} > h_max={space.max_height_mm:.0f}",
                f"Ожидался dynamic+reason+overflow, получено "
                f"{plan.mode}/{plan.reason}/h_pred={plan.predicted_height_mm:.1f}",
            )
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")

    def test_09_plan_inline_tight_when_doesnt_fit(self) -> None:
        """ТЕСТ 9: dynamic mode + не fits → tight plan, mode='dynamic', reason!=None."""
        self.logger.section("9. plan: dynamic tight с reason")
        try:
            titles = ["Длинное название слоя границ " * 3] * 30
            planner = self._planner_with(self._config_inline())
            plan = planner.plan(
                content=self._make_content(titles),
                space=self._make_space(w=192, h=40),  # принудит не fits
                config_key='synthetic_A4',
            )
            self.logger.check(
                plan.mode == 'dynamic' and plan.reason is not None,
                f"mode={plan.mode}, reason={plan.reason}",
                f"Ожидался dynamic+reason, получено {plan.mode}/{plan.reason}",
            )
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")

    def test_10_plan_empty_content(self) -> None:
        """ТЕСТ 10: Пустой content → валидный план c height минимальный."""
        self.logger.section("10. plan: пустой content")
        try:
            planner = self._planner_with(self._config_inline())
            plan = planner.plan(
                content=self._make_content([]),
                space=self._make_space(),
                config_key='synthetic_A4',
            )
            self.logger.check(
                plan.mode == 'dynamic' and plan.predicted_height_mm >= 0
                and plan.column_count == 1,
                f"mode={plan.mode}, h={plan.predicted_height_mm:.1f}, col={plan.column_count}",
                "Пустой content дал некорректный план",
            )
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")

    # === Группа 4: Ошибки и граничные ===

    def test_11_plan_raises_on_unknown_config(self) -> None:
        """ТЕСТ 11: RuntimeError при config_provider → None."""
        self.logger.section("11. plan: RuntimeError на unknown config")
        try:
            from Daman_QGIS.managers.styling.submodules.Msm_46_3_layout_planner import (
                LayoutPlanner,
            )
            planner = LayoutPlanner(config_provider=lambda k: None)
            raised = False
            msg = ""
            try:
                planner.plan(
                    content=self._make_content(["x"]),
                    space=self._make_space(),
                    config_key='unknown_A0',
                )
            except RuntimeError as e:
                raised = True
                msg = str(e)
            self.logger.check(
                raised and 'Msm_46_3' in msg,
                f"RuntimeError брошен: {msg}",
                f"Исключение не брошено/без префикса: raised={raised}, msg={msg}",
            )
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")

