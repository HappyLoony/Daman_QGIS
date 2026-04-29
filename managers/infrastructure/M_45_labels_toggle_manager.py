# -*- coding: utf-8 -*-
"""
LabelsToggleManager - Глобальное переключение подписей.

Доминантный флаг видимости подписей для всех векторных слоёв проекта.
Single source of truth: M_12 при apply_labels уважает этот флаг и
выставляет setLabelsEnabled(False) если флаг "скрыто".

Архитектурный принцип:
- _labels_visible: bool — доминантное состояние (дефолт True)
- M_12 lazy-импортит get_labels_toggle() и проверяет is_labels_visible()
- Слушатель layersAdded поддерживает флаг для новых слоёв в скрытом режиме
"""

__all__ = ['LabelsToggleManager', 'get_labels_toggle']

from typing import ClassVar, Optional

from qgis.PyQt.QtCore import QObject, pyqtSignal
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QToolButton
from qgis.core import QgsProject, QgsVectorLayer

from Daman_QGIS.utils import log_info, log_error


class LabelsToggleManager(QObject):
    """Доминантный флаг видимости подписей на всех слоях проекта."""

    # Qt-сигнал об изменении состояния. Параметр True = подписи видимы,
    # False = подписи скрыты.
    labelVisibilityChanged = pyqtSignal(bool)

    # Singleton-инстанс для lazy-доступа из M_12.
    _instance: ClassVar[Optional['LabelsToggleManager']] = None

    def __init__(self, iface):
        super().__init__()
        self.iface = iface
        # Доминантный флаг. True = подписи видимы (дефолт).
        self._labels_visible: bool = True
        self._button: Optional[QToolButton] = None
        # Connection-объект для безопасного disconnect в unload().
        self._layers_added_conn = None

        # Регистрация singleton'а для get_labels_toggle().
        LabelsToggleManager._instance = self

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    def is_labels_visible(self) -> bool:
        """Текущее состояние доминантного флага.

        Returns:
            True если подписи видимы (по умолчанию), False если скрыты.
        """
        return self._labels_visible

    # ------------------------------------------------------------------
    # GUI
    # ------------------------------------------------------------------

    def init_gui(self, toolbar) -> None:
        """Создаёт кнопку на тулбаре и подключает слушатель новых слоёв."""
        toolbar.addSeparator()

        self._button = QToolButton()
        icon = QIcon(':/images/themes/default/labelingSingle.svg')
        if not icon.isNull():
            self._button.setIcon(icon)
        else:
            self._button.setText("Подписи")
        self._button.setCheckable(True)
        self._button.setChecked(False)  # checked = подписи скрыты
        self._button.setToolTip("Скрыть подписи")
        self._button.clicked.connect(self._toggle)
        toolbar.addWidget(self._button)

        # Слушатель новых слоёв: фиксит рассинхрон при добавлении слоёв
        # через F_1_2 в скрытом состоянии.
        try:
            self._layers_added_conn = QgsProject.instance().layersAdded.connect(
                self._on_layers_added
            )
        except Exception as e:
            log_error(f"M_45: Не удалось подключить layersAdded: {str(e)}")

        log_info("M_45: Toggle подписей инициализирован")

    # ------------------------------------------------------------------
    # Внутренняя логика
    # ------------------------------------------------------------------

    def _toggle(self) -> None:
        """Инвертирует доминантный флаг и применяет состояние."""
        self._labels_visible = not self._labels_visible
        self._apply_state()

    def _apply_state(self) -> None:
        """Применяет текущее состояние ко всем векторным слоям проекта.

        - При visible=True: восстанавливает подписи только на слоях,
          сконфигурированных в Base_labels.json (через M_12).
        - При visible=False: setLabelsEnabled(False) на всех векторных слоях.
        """
        try:
            label_manager = None
            if self._labels_visible:
                # Lazy import M_12 — флаг видимости включается обратно,
                # надо узнать какие слои сконфигурированы как "с подписями".
                try:
                    from Daman_QGIS.managers import LabelManager
                    label_manager = LabelManager()
                except Exception as e:
                    log_error(f"M_45: LabelManager недоступен: {str(e)}")
                    label_manager = None

            affected = 0
            for _layer_id, layer in QgsProject.instance().mapLayers().items():
                if not isinstance(layer, QgsVectorLayer):
                    continue
                if self._labels_visible:
                    # Слой должен иметь labelsEnabled=True если в Base_labels.json
                    # есть label_field ИЛИ label_is_obstacle. Obstacle-only слои
                    # (label_field='-', is_obstacle=True) важны для коллизий —
                    # без labelsEnabled их obstacle-эффект в PAL не работает.
                    info = label_manager.get_label_info(layer.name()) \
                        if label_manager is not None else None
                    if info:
                        field = info.get('label_field')
                        has_field = bool(field) and field != '-'
                        is_obstacle = bool(info.get('label_is_obstacle', False))
                        if has_field or is_obstacle:
                            layer.setLabelsEnabled(True)
                            layer.triggerRepaint()
                            affected += 1
                else:
                    layer.setLabelsEnabled(False)
                    layer.triggerRepaint()
                    affected += 1

            # Обновляем UI
            if self._button:
                # checked = подписи скрыты (визуальный индикатор активного
                # режима скрытия)
                self._button.setChecked(not self._labels_visible)
                if self._labels_visible:
                    self._button.setToolTip("Скрыть подписи")
                else:
                    self._button.setToolTip("Показать подписи")

            if self._labels_visible:
                log_info(f"M_45: Подписи восстановлены на {affected} слоях")
            else:
                log_info(f"M_45: Подписи скрыты на {affected} слоях")

            # Эмитим сигнал
            self.labelVisibilityChanged.emit(self._labels_visible)

        except Exception as e:
            log_error(f"M_45: Ошибка применения состояния: {str(e)}")

    def _on_layers_added(self, layers) -> None:
        """Слушатель QgsProject.layersAdded.

        Если флаг "скрыто" — выключает подписи на новых векторных слоях,
        чтобы не было рассинхрона при загрузке слоёв через F_1_2 в режиме
        скрытых подписей.

        Args:
            layers: Список QgsMapLayer (Qt-сигнал передаёт List[QgsMapLayer]).
        """
        if self._labels_visible:
            return
        try:
            for layer in layers:
                if isinstance(layer, QgsVectorLayer):
                    layer.setLabelsEnabled(False)
                    layer.triggerRepaint()
        except Exception as e:
            log_error(f"M_45: Ошибка обработки layersAdded: {str(e)}")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def unload(self) -> None:
        """Очистка при выгрузке плагина.

        - Если подписи скрыты — восстановить (карта не остаётся без подписей).
        - Disconnect от layersAdded.
        - Сброс singleton.
        """
        # Восстановление подписей перед выгрузкой
        if not self._labels_visible:
            self._labels_visible = True
            try:
                self._apply_state()
            except Exception as e:
                log_error(f"M_45: Ошибка восстановления подписей в unload: {str(e)}")

        # Disconnect от layersAdded
        try:
            QgsProject.instance().layersAdded.disconnect(self._on_layers_added)
        except (TypeError, RuntimeError):
            pass
        self._layers_added_conn = None

        self._button = None

        # Сброс singleton
        if LabelsToggleManager._instance is self:
            LabelsToggleManager._instance = None


def get_labels_toggle() -> Optional[LabelsToggleManager]:
    """Singleton-доступ к менеджеру для lazy-импорта из M_12.

    Returns:
        Инстанс LabelsToggleManager или None если плагин ещё не загружен
        / уже выгружен. Вызывающая сторона должна обработать None как
        fallback на дефолт is_visible=True.
    """
    return LabelsToggleManager._instance
