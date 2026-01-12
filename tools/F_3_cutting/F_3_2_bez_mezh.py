# -*- coding: utf-8 -*-
"""
F_3_2_Без_Меж - Перенос ЗУ в слои "Без межевания"

Позволяет вручную перенести земельные участки из слоёв Раздел
в слои Без_Меж для участков, которые не требуют межевых работ.

ЗУ Без межевания - это существующие земельные участки, по которым:
- НЕ требуются межевые работы
- НЕ нужно координировать (нет нумерации точек)
- Нужно только присвоить ID для идентификации

ВАЖНО: F_3_2 выполняется ДО F_3_3 (Корректировка)!
Последовательность: F_3_1 -> F_3_2 -> F_3_3 -> F_3_4

Атрибуты для Без_Меж:
- Услов_КН = КН (копируется, не генерируется)
- Услов_ЕЗ = ЕЗ
- План_категория = Категория
- План_ВРИ = ВРИ
- Площадь_ОЗУ = Площадь
- Вид_Работ = "Существующий (сохраняемый) земельный участок"
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
    # Слои Без_Меж (цель)
    LAYER_CUTTING_OKS_BEZ_MEZH,
    LAYER_CUTTING_PO_BEZ_MEZH,
    LAYER_CUTTING_VO_BEZ_MEZH,
)
from Daman_QGIS.utils import log_info, log_warning, log_error

# Импорт субмодулей
from .submodules.Fsm_3_2_1_dialog import Fsm_3_2_1_Dialog
from .submodules.Fsm_3_2_2_transfer import Fsm_3_2_2_Transfer

if TYPE_CHECKING:
    from Daman_QGIS.managers import LayerManager


class F_3_2_BezMezh(BaseTool):
    """Инструмент переноса ЗУ в слой Без_Меж

    Позволяет пользователю выбрать ЗУ из слоёв Раздел и перенести
    их в соответствующие слои Без_Меж (без межевания).
    """

    # Вид работ для Без_Меж (из work_types.json)
    WORK_TYPE_BEZ_MEZH = "Существующий (сохраняемый) земельный участок"

    # Маппинг Раздел -> Без_Меж
    RAZDEL_TO_BEZ_MEZH: Dict[str, str] = {
        LAYER_CUTTING_OKS_RAZDEL: LAYER_CUTTING_OKS_BEZ_MEZH,
        LAYER_CUTTING_PO_RAZDEL: LAYER_CUTTING_PO_BEZ_MEZH,
        LAYER_CUTTING_VO_RAZDEL: LAYER_CUTTING_VO_BEZ_MEZH,
        # Рекреационные (если будут добавлены константы):
        # 'Le_3_2_1_1_Раздел_ЗПР_РЕК_АД': 'Le_3_2_1_3_Без_Меж_ЗПР_РЕК_АД',
        # 'Le_3_2_2_1_Раздел_ЗПР_СЕТИ_ПО': 'Le_3_2_2_3_Без_Меж_ЗПР_СЕТИ_ПО',
        # 'Le_3_2_3_1_Раздел_ЗПР_СЕТИ_ВО': 'Le_3_2_3_3_Без_Меж_ЗПР_СЕТИ_ВО',
        # 'Le_3_2_4_1_Раздел_ЗПР_НЭ': 'Le_3_2_4_3_Без_Меж_ЗПР_НЭ',
    }

    def __init__(self, iface: Any) -> None:
        """Инициализация инструмента

        Args:
            iface: Интерфейс QGIS
        """
        super().__init__(iface)
        self.layer_manager: Optional['LayerManager'] = None
        self.plugin_dir: Optional[str] = None
        self._transfer: Optional[Fsm_3_2_2_Transfer] = None
        self._dialog: Optional[Fsm_3_2_1_Dialog] = None

    def set_plugin_dir(self, plugin_dir: str) -> None:
        """Установка пути к папке плагина"""
        self.plugin_dir = plugin_dir

    def set_layer_manager(self, layer_manager: 'LayerManager') -> None:
        """Установка менеджера слоёв"""
        self.layer_manager = layer_manager

    @staticmethod
    def get_name() -> str:
        """Имя инструмента для cleanup"""
        return "F_3_2_Без_Меж"

    def run(self) -> None:
        """Основной метод запуска инструмента"""
        log_info("F_3_2: Запуск переноса ЗУ в Без_Меж")

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
            log_warning("F_3_2: Не найдены слои Раздел для переноса")
            return

        # Инициализация модуля переноса
        structure_manager = get_project_structure_manager()
        gpkg_path = structure_manager.get_gpkg_path(create=False)
        if not gpkg_path:
            log_error("F_3_2: Не удалось получить путь к GPKG")
            return

        self._transfer = Fsm_3_2_2_Transfer(
            gpkg_path=gpkg_path,
            razdel_to_bez_mezh=self.RAZDEL_TO_BEZ_MEZH,
            work_type=self.WORK_TYPE_BEZ_MEZH,
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

        for razdel_name in self.RAZDEL_TO_BEZ_MEZH.keys():
            layers = project.mapLayersByName(razdel_name)
            if layers:
                layer = layers[0]
                if isinstance(layer, QgsVectorLayer) and layer.featureCount() > 0:
                    available_layers.append(layer)
                    log_info(f"F_3_2: Найден слой {razdel_name} "
                            f"({layer.featureCount()} объектов)")

        return available_layers

    def _show_dialog(self, available_layers: List[QgsVectorLayer]) -> None:
        """Показать диалог выбора ЗУ для переноса

        Args:
            available_layers: Доступные слои Раздел
        """
        # Создание диалога
        self._dialog = Fsm_3_2_1_Dialog(
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
            log_error("F_3_2: Модуль переноса не инициализирован")
            return {'error': 'Transfer module not initialized'}

        # Выполнение переноса
        result = self._transfer.execute(
            source_layer=source_layer,
            feature_ids=feature_ids
        )

        if result.get('error'):
            log_error(f"F_3_2: Ошибка переноса: {result['error']}")
            QMessageBox.critical(
                self.iface.mainWindow(),
                PLUGIN_NAME,
                f"Ошибка переноса:\n{result['error']}"
            )
        else:
            # Успешный перенос
            transferred = result.get('transferred', 0)
            target_layer = result.get('target_layer', 'Без_Меж')

            log_info(f"F_3_2: Перенесено {transferred} объектов в {target_layer}")
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
