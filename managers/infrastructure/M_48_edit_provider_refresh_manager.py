# -*- coding: utf-8 -*-
"""
EditProviderRefreshManager (M_48) — восстановление OGR-провайдера GPKG-слоя
после РУЧНОГО редактирования.

Баг QGIS/GDAL (воспроизведён на QGIS 3.40.15 / GDAL 3.12.2, transactions
Disabled): нативный toggle editing GeoPackage-слоя оставляет его in-memory
OGR-провайдер со СБРОШЕННОЙ СХЕМОЙ — `dataProvider().fields()` пусто,
`featureCount()`=-1, при `isValid()`=true. Геометрия рисуется (из кэша), но
атрибуты читаются как None → поле подписи (ID) пустое → подписи слоя пропадают
до перезапуска. Файл при этом ЦЕЛ (OGR читает напрямую), и СОСЕДНИЕ слои не
затронуты (их рассинхрон путей уже устранён в M_19.get_gpkg_path).

Диагностика (2026-06-03): не файл, не кэш отрисовки, не коллизия подписей, не
плагинные хуки (их нет в production), не транзакционные группы (Disabled).
Программные `startEditing`/`commitChanges` НЕ ломают провайдер — только нативный
GUI-toggle. Recovery — пересоздать провайдер `setDataSource`; `reload()` и
`dataProvider().reloadData()` недостаточны (схему не пересоздают).

Почему НЕ transaction groups (BufferedGroups): они чинят симптом, но переводят
всю gpkg-группу (~50 слоёв) в edit при правке одного слоя → ломают логику
программного по-слойного редактирования плагина (нарезка/нормализация/импорт).
Отклонено как высокорисковое.

Решение (точечное, безопасное): хук на `iface.actionToggleEditing().triggered`
— ТОЛЬКО пользовательское действие (программные правки плагина его не вызывают
→ инструменты не затрагиваются). Отложенно проверяем активный слой и, ТОЛЬКО
если провайдер реально сломан (нет полей), пересоздаём data source с сохранением
стиля/подписей (`loadDefaultStyleFlag=False`).
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
