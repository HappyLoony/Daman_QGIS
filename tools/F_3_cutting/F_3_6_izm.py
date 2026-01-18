# -*- coding: utf-8 -*-
"""
F_3_6_Изм - Перенос ЗУ в слои "Изменяемые"

Позволяет вручную перенести земельные участки из слоёв Раздел
в слои Изм для участков, которые сохраняют границы и КН,
но меняют атрибуты (ВРИ, категория).

ЗУ Изменяемые - это существующие земельные участки, по которым:
- НЕ требуются межевые работы (границы сохраняются)
- НЕ нужно координировать (нет нумерации точек)
- Сохраняется кадастровый номер
- МЕНЯЮТСЯ некоторые атрибуты (ВРИ, категория и т.д.)
- Нужно только присвоить ID для идентификации

ВАЖНО: F_3_6 выполняется ДО F_3_3 (Корректировка)!
Последовательность: F_3_1 -> F_3_2 -> F_3_5 -> F_3_6 -> F_3_3 -> F_3_4

Атрибуты для Изм:
- Услов_КН = КН (копируется, не генерируется)
- Услов_ЕЗ = ЕЗ
- План_категория = Категория (может быть изменена пользователем позже)
- План_ВРИ = ВРИ (может быть изменен пользователем позже)
- Площадь_ОЗУ = Площадь
- Вид_Работ = "Изменение характеристик земельного участка"
- Точки = "" (пустое - нет нумерации)
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
    # Слои Изм (цель)
    LAYER_CUTTING_OKS_IZM,
    LAYER_CUTTING_PO_IZM,
    LAYER_CUTTING_VO_IZM,
)
from Daman_QGIS.utils import log_info, log_warning, log_error

# Импорт субмодулей
from .submodules.Fsm_3_6_1_dialog import Fsm_3_6_1_Dialog
from .submodules.Fsm_3_6_2_transfer import Fsm_3_6_2_Transfer

if TYPE_CHECKING:
    from Daman_QGIS.managers import LayerManager


class F_3_6_Izm(BaseTool):
    """Инструмент переноса ЗУ в слой Изм (Изменяемые)

    Позволяет пользователю выбрать ЗУ из слоёв Раздел и перенести
    их в соответствующие слои Изм (сохранение границ, изменение атрибутов).
    """

    # Вид работ для Изм
    WORK_TYPE_IZM = "Изменение характеристик земельного участка"

    # Маппинг Раздел -> Изм
    RAZDEL_TO_IZM: Dict[str, str] = {
        LAYER_CUTTING_OKS_RAZDEL: LAYER_CUTTING_OKS_IZM,
        LAYER_CUTTING_PO_RAZDEL: LAYER_CUTTING_PO_IZM,
        LAYER_CUTTING_VO_RAZDEL: LAYER_CUTTING_VO_IZM,
    }

    def __init__(self, iface: Any) -> None:
        """Инициализация инструмента

        Args:
            iface: Интерфейс QGIS
        """
        super().__init__(iface)
        self.layer_manager: Optional['LayerManager'] = None
        self.plugin_dir: Optional[str] = None
        self._transfer: Optional[Fsm_3_6_2_Transfer] = None
        self._dialog: Optional[Fsm_3_6_1_Dialog] = None

    def set_plugin_dir(self, plugin_dir: str) -> None:
        """Установка пути к папке плагина"""
        self.plugin_dir = plugin_dir

    def set_layer_manager(self, layer_manager: 'LayerManager') -> None:
        """Установка менеджера слоёв"""
        self.layer_manager = layer_manager

    @staticmethod
    def get_name() -> str:
        """Имя инструмента для cleanup"""
        return "F_3_6_Изм"

    def run(self) -> None:
        """Основной метод запуска инструмента"""
        log_info("F_3_6: Запуск переноса ЗУ в Изм")

        # Проверка открытого проекта
        if not self.check_project_opened():
            return

        # Поиск существующих слоёв Раздел
        available_layers = self._find_razdel_layers()
        if not available_layers:
            self.iface.messageBar().pushMessage(
                PLUGIN_NAME,
                "Не найдены слои Раздел. Сначала выполните нарезку (F_3_1).",
                level=Qgis.Warning,
                duration=MESSAGE_INFO_DURATION
            )
            log_warning("F_3_6: Не найдены слои Раздел для переноса")
            return

        # Инициализация модуля переноса
        structure_manager = get_project_structure_manager()
        gpkg_path = structure_manager.get_gpkg_path(create=False)
        if not gpkg_path:
            log_error("F_3_6: Не удалось получить путь к GPKG")
            return

        self._transfer = Fsm_3_6_2_Transfer(
            gpkg_path=gpkg_path,
            razdel_to_izm=self.RAZDEL_TO_IZM,
            work_type=self.WORK_TYPE_IZM,
            layer_manager=self.layer_manager
        )

        # Показать диалог выбора ЗУ
        self._show_dialog(available_layers)

    def _find_razdel_layers(self) -> List[QgsVectorLayer]:
        """Найти существующие слои Раздел в проекте

        Returns:
            Список найденных слоёв Раздел
        """
        project = QgsProject.instance()
        available_layers = []

        for razdel_name in self.RAZDEL_TO_IZM.keys():
            layers = project.mapLayersByName(razdel_name)
            if layers:
                layer = layers[0]
                if isinstance(layer, QgsVectorLayer) and layer.featureCount() > 0:
                    available_layers.append(layer)
                    log_info(f"F_3_6: Найден слой {razdel_name} "
                            f"({layer.featureCount()} объектов)")

        return available_layers

    def _show_dialog(self, available_layers: List[QgsVectorLayer]) -> None:
        """Показать диалог выбора ЗУ для переноса

        Args:
            available_layers: Доступные слои Раздел
        """
        # Создание диалога
        self._dialog = Fsm_3_6_1_Dialog(
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
        """Callback для выполнения переноса из диалога

        Args:
            source_layer: Слой-источник (Раздел)
            feature_ids: ID объектов для переноса

        Returns:
            Результат переноса
        """
        if not self._transfer:
            log_error("F_3_6: Модуль переноса не инициализирован")
            return {'error': 'Transfer module not initialized'}

        # Выполнение переноса
        result = self._transfer.execute(
            source_layer=source_layer,
            feature_ids=feature_ids
        )

        if result.get('error'):
            log_error(f"F_3_6: Ошибка переноса: {result['error']}")
            QMessageBox.critical(
                self.iface.mainWindow(),
                PLUGIN_NAME,
                f"Ошибка переноса:\n{result['error']}"
            )
        else:
            # Успешный перенос
            transferred = result.get('transferred', 0)
            target_layer = result.get('target_layer', 'Изм')

            log_info(f"F_3_6: Перенесено {transferred} объектов в {target_layer}")
            self.iface.messageBar().pushMessage(
                PLUGIN_NAME,
                f"Перенесено {transferred} объектов в слой {target_layer}",
                level=Qgis.Success,
                duration=MESSAGE_SUCCESS_DURATION
            )

            # Обновить слои в QGIS
            self._refresh_layers(source_layer, result.get('target_layer_obj'))

        return result

    def _refresh_layers(
        self,
        source_layer: QgsVectorLayer,
        target_layer: Optional[QgsVectorLayer]
    ) -> None:
        """Обновить отображение слоёв после переноса

        Args:
            source_layer: Слой-источник
            target_layer: Слой-цель
        """
        # Обновить источник
        source_layer.triggerRepaint()

        # Обновить цель если есть
        if target_layer:
            target_layer.triggerRepaint()

        # Обновить канву
        self.iface.mapCanvas().refresh()
