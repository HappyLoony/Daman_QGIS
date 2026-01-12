# -*- coding: utf-8 -*-
"""
F_3_5_Изъятие - Ручной отбор ЗУ для изъятия под гос./муниц. нужды

Позволяет вручную выбрать земельные участки из слоёв нарезки (Раздел, НГС)
и скопировать их в слой L_3_3_1_Изъятие_ЗУ.

Особенности:
- Операция КОПИРОВАНИЯ (источник не изменяется)
- Проверка дубликатов по КН + Услов_КН
- Режим ДОБАВЛЕНИЯ (слой не очищается)
- Структура полей строго из Base_cutting.json

ВАЖНО: Определение участков для изъятия - ВНЕШНЯЯ информация.
Автоматическое определение пока невозможно.

Последовательность: F_3_1 -> F_3_2 -> F_3_5 -> F_3_3 -> F_3_4
"""

from typing import Optional, Dict, List, Any, TYPE_CHECKING

from qgis.PyQt.QtWidgets import QMessageBox
from qgis.core import QgsProject, Qgis, QgsVectorLayer

from Daman_QGIS.core.base_tool import BaseTool
from Daman_QGIS.managers import get_project_structure_manager
from Daman_QGIS.constants import (
    PLUGIN_NAME, MESSAGE_SUCCESS_DURATION, MESSAGE_INFO_DURATION,
    # Слои Раздел (источник)
    LAYER_CUTTING_OKS_RAZDEL,
    LAYER_CUTTING_PO_RAZDEL,
    LAYER_CUTTING_VO_RAZDEL,
    # Слои НГС (источник)
    LAYER_CUTTING_OKS_NGS,
    LAYER_CUTTING_PO_NGS,
    LAYER_CUTTING_VO_NGS,
    # Слой изъятия (цель)
    LAYER_IZYATIE_ZU,
)
from Daman_QGIS.utils import log_info, log_warning, log_error

# Импорт субмодулей
from .submodules.Fsm_3_5_1_dialog import Fsm_3_5_1_Dialog
from .submodules.Fsm_3_5_2_transfer import Fsm_3_5_2_Transfer

if TYPE_CHECKING:
    from Daman_QGIS.managers import LayerManager


class F_3_5_Izyatie(BaseTool):
    """Инструмент отбора ЗУ для изъятия

    Позволяет пользователю выбрать ЗУ из слоёв нарезки (Раздел, НГС)
    и скопировать их в слой L_3_3_1_Изъятие_ЗУ.
    """

    # Слои-источники для изъятия (Раздел + НГС)
    SOURCE_LAYERS: List[str] = [
        # Раздел
        LAYER_CUTTING_OKS_RAZDEL,
        LAYER_CUTTING_PO_RAZDEL,
        LAYER_CUTTING_VO_RAZDEL,
        # НГС
        LAYER_CUTTING_OKS_NGS,
        LAYER_CUTTING_PO_NGS,
        LAYER_CUTTING_VO_NGS,
    ]

    def __init__(self, iface: Any) -> None:
        """Инициализация инструмента

        Args:
            iface: Интерфейс QGIS
        """
        super().__init__(iface)
        self.layer_manager: Optional['LayerManager'] = None
        self.plugin_dir: Optional[str] = None
        self._transfer: Optional[Fsm_3_5_2_Transfer] = None
        self._dialog: Optional[Fsm_3_5_1_Dialog] = None

    def set_plugin_dir(self, plugin_dir: str) -> None:
        """Установка пути к папке плагина"""
        self.plugin_dir = plugin_dir

    def set_layer_manager(self, layer_manager: 'LayerManager') -> None:
        """Установка менеджера слоёв"""
        self.layer_manager = layer_manager

    @staticmethod
    def get_name() -> str:
        """Имя инструмента для cleanup"""
        return "F_3_5_Изъятие"

    def run(self) -> None:
        """Основной метод запуска инструмента"""
        log_info("F_3_5: Запуск отбора ЗУ для изъятия")

        # Проверка открытого проекта
        if not self.check_project_opened():
            return

        # Поиск существующих слоёв-источников
        available_layers = self._find_source_layers()
        if not available_layers:
            self.iface.messageBar().pushMessage(
                PLUGIN_NAME,
                "Не найдены слои нарезки. Сначала выполните нарезку (F_3_1).",
                level=Qgis.Warning,
                duration=MESSAGE_INFO_DURATION
            )
            log_warning("F_3_5: Не найдены слои нарезки для отбора")
            return

        # Инициализация модуля переноса
        structure_manager = get_project_structure_manager()
        gpkg_path = structure_manager.get_gpkg_path(create=False)
        if not gpkg_path:
            log_error("F_3_5: Не удалось получить путь к GPKG")
            return

        if not self.plugin_dir:
            log_error("F_3_5: Не установлен plugin_dir")
            return

        self._transfer = Fsm_3_5_2_Transfer(
            gpkg_path=gpkg_path,
            plugin_dir=self.plugin_dir,
            target_layer_name=LAYER_IZYATIE_ZU,
            layer_manager=self.layer_manager
        )

        # Показать диалог выбора ЗУ
        self._show_dialog(available_layers)

    def _find_source_layers(self) -> List[QgsVectorLayer]:
        """Найти существующие слои-источники в проекте

        Returns:
            Список найденных слоёв (Раздел + НГС)
        """
        project = QgsProject.instance()
        available_layers = []

        for layer_name in self.SOURCE_LAYERS:
            layers = project.mapLayersByName(layer_name)
            if layers:
                layer = layers[0]
                if isinstance(layer, QgsVectorLayer) and layer.featureCount() > 0:
                    available_layers.append(layer)
                    log_info(f"F_3_5: Найден слой {layer_name} "
                            f"({layer.featureCount()} объектов)")

        return available_layers

    def _show_dialog(self, available_layers: List[QgsVectorLayer]) -> None:
        """Показать диалог выбора ЗУ для изъятия

        Args:
            available_layers: Доступные слои-источники
        """
        # Создание диалога
        self._dialog = Fsm_3_5_1_Dialog(
            parent=self.iface.mainWindow(),
            layers=available_layers,
            transfer_callback=self._on_transfer
        )
        self._dialog.exec_()

    def _on_transfer(
        self,
        source_layer: QgsVectorLayer,
        feature_ids: List[int]
    ) -> Dict[str, Any]:
        """Callback для выполнения копирования из диалога

        Args:
            source_layer: Слой-источник (Раздел или НГС)
            feature_ids: ID объектов для копирования

        Returns:
            Результат копирования
        """
        if not self._transfer:
            log_error("F_3_5: Модуль переноса не инициализирован")
            return {'error': 'Transfer module not initialized'}

        # Выполнение копирования
        result = self._transfer.execute(
            source_layer=source_layer,
            feature_ids=feature_ids
        )

        if result.get('error'):
            log_error(f"F_3_5: Ошибка копирования: {result['error']}")
            QMessageBox.critical(
                self.iface.mainWindow(),
                PLUGIN_NAME,
                f"Ошибка копирования:\n{result['error']}"
            )
        else:
            # Успешное копирование
            copied = result.get('copied', 0)
            duplicates = result.get('duplicates', 0)
            target_layer = result.get('target_layer', LAYER_IZYATIE_ZU)

            msg = f"Скопировано {copied} объектов в слой {target_layer}"
            if duplicates > 0:
                msg += f" (пропущено дубликатов: {duplicates})"

            log_info(f"F_3_5: {msg}")
            self.iface.messageBar().pushMessage(
                PLUGIN_NAME,
                msg,
                level=Qgis.Success,
                duration=MESSAGE_SUCCESS_DURATION
            )

            # Обновить слои в QGIS
            self._refresh_layers(result.get('target_layer_obj'))

        return result

    def _refresh_layers(
        self,
        target_layer: Optional[QgsVectorLayer]
    ) -> None:
        """Обновить отображение слоёв после копирования

        Args:
            target_layer: Слой-цель (Изъятие_ЗУ)
        """
        # Обновить цель если есть
        if target_layer is not None:
            target_layer.triggerRepaint()

        # Обновить канву
        self.iface.mapCanvas().refresh()
