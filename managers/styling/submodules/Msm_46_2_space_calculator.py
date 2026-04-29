# -*- coding: utf-8 -*-
"""
Msm_46_2: SpaceCalculator — Тонкий wrapper для построения AvailableSpace.

После рефакторинга legend_layout_modes (v0.4) основная логика построения
AvailableSpace переехала в M_46.facade._build_space(). Этот модуль сохранён
как legacy entry point для обратной совместимости — фактически в pipeline
M_46.plan_and_apply не используется.

config_provider (DI для тестов): callable `(config_key) -> dict | None`.
В production — default provider берёт через
`registry.get('M_34').get_layout_config_by_key`.

Также экспортирует `_default_config_provider` — используется facade M_46
напрямую (избегаем дублирования логики чтения конфига).

Используется (legacy entry): внешний код, который мог импортировать
SpaceCalculator до v0.4. Внутри Daman_QGIS pipeline M_46 не зависит от
этого класса — facade сам строит AvailableSpace через _build_space.
"""

from typing import Any, Callable, Dict, Optional

from qgis.core import QgsPrintLayout

from .Msm_46_types import AvailableSpace, LegendLayoutMode

MODULE_ID = "Msm_46_2"


def _default_config_provider(config_key: str) -> Optional[Dict[str, Any]]:
    """Default provider: читает конфиг через M_34.get_layout_config_by_key."""
    from Daman_QGIS.managers import registry  # lazy: избегаем цикла при тестах
    layout_mgr = registry.get('M_34')
    if layout_mgr is None:
        return None
    return layout_mgr.get_layout_config_by_key(config_key)


class SpaceCalculator:
    """Тонкий wrapper для построения AvailableSpace из Base_layout (legacy API).

    После рефакторинга legend_layout_modes (v0.4) основная логика построения
    AvailableSpace переехала в M_46.facade._build_space(). Этот класс сохранён
    как legacy entry point для обратной совместимости — фактически в pipeline
    M_46 не используется.

    Внутри: читает legend_layout_mode из config, делегирует на
    LegendManager._build_space (DRY с facade).
    """

    def __init__(
        self,
        config_provider: Optional[
            Callable[[str], Optional[Dict[str, Any]]]
        ] = None,
    ) -> None:
        """
        Args:
            config_provider: callable `(config_key) -> dict | None` для DI.
                Если None — используется default из M_34.
        """
        self._provider = config_provider or _default_config_provider

    def calculate(
        self,
        layout: QgsPrintLayout,
        config_key: str,
    ) -> AvailableSpace:
        """Вычислить AvailableSpace для легенды (legacy entry).

        Раньше использовала neighbour-detection. После v0.4 — читает явные
        поля legend_dynamic_* / legend_panel_* по legend_layout_mode из config.

        Args:
            layout: Макет (не используется, оставлен в сигнатуре для
                обратной совместимости).
            config_key: Ключ Base_layout (например 'A4_landscape_DPT').

        Returns:
            AvailableSpace с явными max_width_mm / max_height_mm и anchor.

        Raises:
            RuntimeError: config_key не найден или legend_layout_mode
                невалиден / outside.
            KeyError: отсутствуют обязательные поля legend_*_x/y/width_mm/
                height_max_mm/ref_point в Base_layout.
        """
        config = self._provider(config_key)
        if config is None:
            raise RuntimeError(
                f"{MODULE_ID}: config_key '{config_key}' не найден в Base_layout.json"
            )
        mode = config.get('legend_layout_mode')
        if mode == LegendLayoutMode.OUTSIDE or not LegendLayoutMode.is_valid(mode):
            raise RuntimeError(
                f"{MODULE_ID}: некорректный или outside legend_layout_mode='{mode}' "
                f"для legacy SpaceCalculator.calculate"
            )
        # Делегирование на M_46._build_space для DRY
        from ..M_46_legend_manager import LegendManager
        return LegendManager()._build_space(config, mode)
