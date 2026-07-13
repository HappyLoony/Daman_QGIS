# -*- coding: utf-8 -*-
"""
EditProviderRefreshManager (M_48) — восстановление OGR-провайдера GPKG-слоя
после РУЧНОГО редактирования.

================================================================================
ДВА НЕЗАВИСИМЫХ КОРНЯ ОДНОГО СИМПТОМА («после edit-toggle пропадает отрисовка»)
================================================================================
При ручном входе/выходе в режим редактирования GeoPackage-слоя наблюдались ДВА
разных дефекта с РАЗНЫМИ механизмами и РАЗНЫМИ фиксами:

  • Корень A — СОСЕДНИЕ слои (границы/геометрия). Слои нарезки и исходные
    указывали на один project.gpkg РАЗНЫМ написанием пути (backslash vs
    forward-slash) → QGIS видел ДВА datasource → две SQLite-связи → write-lock
    при редактировании одной связи блокировал ЧТЕНИЕ слоёв на другой
    (`getFeatures()`→0). Фикс — `M_19.get_gpkg_path` нормализует путь в
    forward-slash (одна связь). Это НЕ домен M_48.

  • Корень B — РЕДАКТИРУЕМЫЙ слой (его подписи). ← ЭТО ЧИНИТ M_48.
    Нативный toggle editing GPKG-слоя оставляет его in-memory OGR-провайдер со
    СБРОШЕННОЙ СХЕМОЙ: `dataProvider().fields()` пусто, `featureCount()`=-1, при
    `isValid()`=true. Геометрия рисуется из кэша (границы есть), но атрибуты
    читаются как None → поле подписи (ID) пустое → подписи ИМЕННО этого слоя
    пропадают до перезапуска. Файл при этом ЦЕЛ (прямой `ogr.Open` читает все
    поля/строки).

ПОЧЕМУ M_19 НЕ ЧИНИТ ДО КОНЦА (и M_48 точно нужен):
M_19 (forward-slash) устраняет дву-связь → лечит корень A (чтение СОСЕДЕЙ). Но
корень B — это потеря схемы у провайдера САМОГО редактируемого слоя, отдельный
механизм, к написанию пути отношения не имеющий. Нормализация путей его не
касается. ЭМПИРИЧЕСКИ ПОДТВЕРЖДЕНО (чистый тест 2026-06-03, M_48 отключён):
свежая нарезка + нативный вход/выход в редактирование `Le_2_1_1_1` → подписи
контуров (поле ID) этого слоя пропали, `fields()`==0; у остальных слоёв подписи
в норме. То есть корень B воспроизводится на ЧИСТОМ редактировании (не артефакт
диагностики) и НЕ снимается фиксом путей → без M_48 баг B возвращается.

Что ИСКЛЮЧЕНО при диагностике (2026-06-03): не файл (OGR читает), не кэш
отрисовки (redrawAllLayers не помог), не коллизия подписей (displayAll не помог),
не плагинные хуки (production-хуков на editing-сигналы НЕТ — только тесты), не
транзакционные группы (`transactionMode = Disabled`). Программные
`startEditing`/`commitChanges` провайдер НЕ ломают — ТОЛЬКО нативный GUI-toggle
(баг GUI-only, скриптом / `action.trigger()` не воспроизводится). Recovery —
пересоздать провайдер `setDataSource`; `reload()` / `reloadData()` недостаточны
(схему не пересоздают).

ПОЧЕМУ НЕ transaction groups (BufferedGroups): они чинят симптом B, но переводят
всю gpkg-группу (~50 слоёв) в edit при правке одного слоя → ломают по-слойное
программное редактирование плагина (нарезка/нормализация/импорт). Отклонено как
высокорисковое.

ДОМЕННЫЙ СОСЕД — M_2 LayerManager («здоровье слоёв на канве»): тематически M_48
из его семьи. M_2 уже борется с «исчезновением слоёв» (в `add_layer` выключает
scale-visibility и упрощение геометрии именно ради корректной отрисовки); починка
провайдера после правки — тот же дух «слой должен оставаться рабочим на канве».
Но M_2 — пассивная core-утилита (`add_layer(...)`) БЕЗ сигнального lifecycle
(нет `init_gui`/`unload`/`.connect`), а M_19 — резолв путей без iface. Вешать
QGIS-сигнал в любой из них = тащить iface + connect/disconnect-lifecycle в место,
где его нет, и размывать ответственность. В этом проекте «нечто, что хукает
QGIS-сигнал/действие» намеренно вынесено в отдельный небольшой infrastructure-
менеджер (прецеденты: M_16 CadnumSearch — `action.triggered`, M_45 LabelsToggle —
`layersAdded`). M_48 следует ровно этому паттерну (а не `Msm_19_*`/`Msm_2_*`:
суб-менеджер оркестрируется родителем — ни M_19, ни M_2 не «двигают» M_48).
Связь доменов (M_2 здоровье слоёв ↔ M_19 пути ↔ M_48 провайдер) чтится
doc-кросс-ссылками, не слиянием кода.

Решение (точечное, безопасное): хук на `iface.actionToggleEditing().triggered`
— ТОЛЬКО пользовательское действие (программные правки плагина его не вызывают
→ инструменты не затрагиваются). Отложенно (QTimer) проверяем активный слой и,
ТОЛЬКО если провайдер реально сломан (`fields()`==0) и слой уже не editable,
пересоздаём data source с сохранением стиля/подписей (`loadDefaultStyleFlag=False`).

См. также: M_2 LayerManager (доменный сосед — здоровье слоёв на канве),
M_19 (корень A — пути .gpkg), память `reference_qgis_canvas_edit_render`,
план `documentation/plans/2026-06-02-M_48-render-refresh-on-edit.md`.
"""

__all__ = ['EditProviderRefreshManager']

from Daman_QGIS.utils import log_error, log_info

# Задержка после toggle: дать нативному commit/выходу из edit завершиться.
_REFRESH_DELAY_MS = 500


class EditProviderRefreshManager:
    """Пересоздаёт сломанный OGR-провайдер слоя после ручного toggle editing."""

    def __init__(self, iface):
        self.iface = iface
        self._action = None
        self._connected = False

    def init(self) -> None:
        """Подключает хук на нативное действие toggle-editing (guard от reload)."""
        if self._connected:
            return
        try:
            self._action = self.iface.actionToggleEditing()
            self._action.triggered.connect(self._on_toggle)
            self._connected = True
        except Exception as e:
            log_error(f"M_48: не удалось подключить actionToggleEditing: {e}")

    def _on_toggle(self, checked: bool = False) -> None:
        """Слот ручного toggle. Откладываем проверку до завершения commit/выхода.

        Захватываем id активного слоя (не ссылку — слой мог быть удалён к моменту
        проверки) и проверяем его отложенно.
        """
        layer = self.iface.activeLayer()
        if layer is None:
            return
        lid = layer.id()
        from qgis.PyQt.QtCore import QTimer
        QTimer.singleShot(_REFRESH_DELAY_MS, lambda: self._refresh_if_broken(lid))

    def _refresh_if_broken(self, layer_id: str) -> None:
        """Пересоздать провайдер слоя, ТОЛЬКО если он реально сломан (нет полей)."""
        from qgis.core import QgsProject, QgsVectorLayer, QgsDataProvider
        layer = QgsProject.instance().mapLayer(layer_id)
        if not isinstance(layer, QgsVectorLayer):
            return
        # НЕ трогать активную edit-сессию: setDataSource на editable слое
        # потеряет edit-буфер. Чиним только ПОСЛЕ выхода из редактирования.
        if layer.isEditable():
            return
        dp = layer.dataProvider()
        if dp is None or dp.name() != 'ogr':
            return
        # Сигнатура поломки: провайдер потерял схему (нет полей). featureCount=-1
        # сам по себе ненадёжен (бывает транзиентно у здорового слоя), поэтому
        # критерий — именно отсутствие полей.
        if len(layer.fields()) != 0:
            return
        try:
            uri = layer.source()
            name = layer.name()
            # loadDefaultStyleFlag=False → сохранить текущий стиль/подписи.
            layer.setDataSource(uri, name, "ogr", QgsDataProvider.ProviderOptions(), False)
            log_info(
                f"M_48: пересоздан провайдер '{name}' после ручного редактирования "
                f"(восстановлена схема: {len(layer.fields())} полей)"
            )
        except Exception as e:
            log_error(f"M_48: setDataSource не удался для слоя {layer_id}: {e}")

    def unload(self) -> None:
        """Отсоединяет хук при выгрузке плагина (disconnect по слоту в узком except)."""
        if self._connected and self._action is not None:
            try:
                self._action.triggered.disconnect(self._on_toggle)
            except (TypeError, RuntimeError):
                pass
            self._connected = False
            self._action = None
