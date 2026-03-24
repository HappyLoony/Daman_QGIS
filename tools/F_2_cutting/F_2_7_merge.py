# -*- coding: utf-8 -*-
"""
F_2_7_Объединение - Ручное объединение контуров нарезки

Позволяет вручную выбрать земельные участки из слоёв Раздел или Без_Меж
и объединить их в единый земельный участок (Polygon или MultiPolygon).
При объединении из Без_Меж результат попадает в слой Раздел (cross-layer).

Особенности:
- Объединение геометрий через QgsGeometry.unaryUnion()
- Смежные геометрии -> Polygon, разнесённые -> MultiPolygon
- Полная перенумерация ID и характерных точек
- Пересоздание точечного слоя (Т_*)
- Самодостаточная функция (F_2_3 не требуется)

Последовательность: F_2_1 -> F_2_2 -> F_2_5 -> F_2_7 -> F_2_3 -> F_2_4

Атрибуты объединённого:
- Услов_КН = новый (генерируется)
- Вид_Работ = "Образование ЗУ путём объединения ... с условными номерами X, Y"
- Состав_контуров = "ID (КН), ID, ID (КН)" - расширенный формат
- Площадь_ОЗУ = area() объединённой геометрии
- Многоконтурный = "Да" / "Нет"
"""

from typing import Optional, Dict, List, Any, TYPE_CHECKING

from qgis.PyQt.QtWidgets import QMessageBox
from qgis.core import QgsProject, Qgis, QgsVectorLayer

from Daman_QGIS.core.base_tool import BaseTool
from Daman_QGIS.managers import registry
from Daman_QGIS.constants import (
    PLUGIN_NAME, MESSAGE_SUCCESS_DURATION, MESSAGE_INFO_DURATION,
    # Слои Раздел (источник для объединения)
    LAYER_CUTTING_OKS_RAZDEL,
    LAYER_CUTTING_PO_RAZDEL,
    LAYER_CUTTING_VO_RAZDEL,
    # Слои Без_Меж (источник для объединения -> результат в Раздел)
    LAYER_CUTTING_OKS_BEZ_MEZH,
    LAYER_CUTTING_PO_BEZ_MEZH,
    LAYER_CUTTING_VO_BEZ_MEZH,
)
from Daman_QGIS.utils import log_info, log_warning, log_error, safe_refresh_layer

# Импорт субмодулей
from .submodules.Fsm_2_7_1_merge_dialog import Fsm_2_7_1_MergeDialog
from .submodules.Fsm_2_7_2_merge_processor import Fsm_2_7_2_MergeProcessor

if TYPE_CHECKING:
    from Daman_QGIS.managers import LayerManager


class F_2_7_Merge(BaseTool):
    """Инструмент объединения контуров нарезки

    Позволяет пользователю выбрать несколько контуров из слоёв Раздел
    или Без_Меж и объединить их в единый земельный участок.
    При объединении из Без_Меж результат помещается в слой Раздел.
    """

    # Слои-источники для объединения (Раздел + Без_Меж)
    SOURCE_LAYERS: List[str] = [
        LAYER_CUTTING_OKS_RAZDEL,
        LAYER_CUTTING_PO_RAZDEL,
        LAYER_CUTTING_VO_RAZDEL,
        LAYER_CUTTING_OKS_BEZ_MEZH,
        LAYER_CUTTING_PO_BEZ_MEZH,
        LAYER_CUTTING_VO_BEZ_MEZH,
    ]

    # Маппинг Без_Меж -> Раздел (для cross-layer объединения)
    BEZ_MEZH_TO_RAZDEL: Dict[str, str] = {
        LAYER_CUTTING_OKS_BEZ_MEZH: LAYER_CUTTING_OKS_RAZDEL,
        LAYER_CUTTING_PO_BEZ_MEZH: LAYER_CUTTING_PO_RAZDEL,
        LAYER_CUTTING_VO_BEZ_MEZH: LAYER_CUTTING_VO_RAZDEL,
    }

    def __init__(self, iface: Any) -> None:
        """Инициализация инструмента

        Args:
            iface: Интерфейс QGIS
        """
        super().__init__(iface)
        self.layer_manager: Optional['LayerManager'] = None
        self.plugin_dir: Optional[str] = None
        self._processor: Optional[Fsm_2_7_2_MergeProcessor] = None
        self._dialog: Optional[Fsm_2_7_1_MergeDialog] = None

    def set_plugin_dir(self, plugin_dir: str) -> None:
        """Установка пути к папке плагина"""
        self.plugin_dir = plugin_dir

    def set_layer_manager(self, layer_manager: 'LayerManager') -> None:
        """Установка менеджера слоёв"""
        self.layer_manager = layer_manager

    @staticmethod
    def get_name() -> str:
        """Имя инструмента для cleanup"""
        return "F_2_7_Объединение"

    def run(self) -> None:
        """Основной метод запуска инструмента"""
        log_info("F_2_7: Запуск объединения контуров")

        # Проверка открытого проекта
        if not self.check_project_opened():
            return

        # Поиск существующих слоёв для объединения (Раздел + Без_Меж)
        available_layers = self._find_source_layers()
        if not available_layers:
            self.iface.messageBar().pushMessage(
                PLUGIN_NAME,
                "Не найдены слои для объединения. Сначала выполните нарезку (F_2_1).",
                level=Qgis.Warning,
                duration=MESSAGE_INFO_DURATION
            )
            log_warning("F_2_7: Не найдены слои Раздел/Без_Меж для объединения")
            return

        # Инициализация процессора
        structure_manager = registry.get('M_19')
        gpkg_path = structure_manager.get_gpkg_path(create=False)
        if not gpkg_path:
            log_error("F_2_7: Не удалось получить путь к GPKG")
            return

        if not self.plugin_dir:
            log_error("F_2_7: Не установлен plugin_dir")
            return

        self._processor = Fsm_2_7_2_MergeProcessor(
            gpkg_path=gpkg_path,
            plugin_dir=self.plugin_dir,
            layer_manager=self.layer_manager
        )

        # Показать диалог выбора контуров
        self._show_dialog(available_layers)

    def _find_source_layers(self) -> List[QgsVectorLayer]:
        """Найти существующие слои для объединения (Раздел + Без_Меж)

        Returns:
            Список найденных слоёв с минимум 2 объектами
        """
        project = QgsProject.instance()
        available_layers = []

        for layer_name in self.SOURCE_LAYERS:
            layers = project.mapLayersByName(layer_name)
            if layers:
                layer = layers[0]
                # Для объединения нужно минимум 2 объекта
                if isinstance(layer, QgsVectorLayer) and layer.featureCount() >= 2:
                    available_layers.append(layer)
                    log_info(f"F_2_7: Найден слой {layer_name} "
                            f"({layer.featureCount()} объектов)")

        return available_layers

    def _show_dialog(self, available_layers: List[QgsVectorLayer]) -> None:
        """Показать диалог выбора контуров для объединения

        Args:
            available_layers: Доступные слои Раздел
        """
        # Создание диалога
        self._dialog = Fsm_2_7_1_MergeDialog(
            parent=self.iface.mainWindow(),
            layers=available_layers,
            merge_callback=self._on_merge
        )
        self._dialog.exec()

    def _on_merge(
        self,
        source_layer: QgsVectorLayer,
        feature_ids: List[int]
    ) -> Dict[str, Any]:
        """Callback для выполнения объединения из диалога

        Args:
            source_layer: Слой-источник (Раздел или Без_Меж)
            feature_ids: ID объектов для объединения

        Returns:
            Результат объединения
        """
        if not self._processor:
            log_error("F_2_7: Процессор не инициализирован")
            return {'error': 'Processor not initialized'}

        # Определить целевой слой Раздел (если source = Без_Меж)
        target_razdel_name = self.BEZ_MEZH_TO_RAZDEL.get(source_layer.name())

        # Выполнение объединения
        result = self._processor.execute(
            source_layer=source_layer,
            feature_ids=feature_ids,
            target_razdel_name=target_razdel_name
        )

        if result.get('error'):
            log_error(f"F_2_7: Ошибка объединения: {result['error']}")
            QMessageBox.critical(
                self.iface.mainWindow(),
                PLUGIN_NAME,
                f"Ошибка объединения:\n{result['error']}"
            )
        else:
            # Успешное объединение
            merged_count = result.get('merged_count', 0)
            is_multipart = result.get('is_multipart', False)
            new_area = result.get('new_area', 0)

            geom_type = "многоконтурный" if is_multipart else "единый"
            msg = (f"Объединено {merged_count} контуров в {geom_type} участок. "
                   f"Площадь: {new_area:.0f} м2")

            log_info(f"F_2_7: {msg}")
            self.iface.messageBar().pushMessage(
                PLUGIN_NAME,
                msg,
                level=Qgis.Success,
                duration=MESSAGE_SUCCESS_DURATION
            )

            # Обновить слои в QGIS (source может быть удалён если опустел)
            self._refresh_layers(
                source_layer if not result.get('source_removed') else None,
                result.get('points_layer'),
                result.get('razdel_layer'),
                result.get('razdel_points_layer')
            )

        return result

    def _refresh_layers(
        self,
        source_layer: QgsVectorLayer,
        points_layer: Optional[QgsVectorLayer],
        razdel_layer: Optional[QgsVectorLayer] = None,
        razdel_points_layer: Optional[QgsVectorLayer] = None
    ) -> None:
        """Обновить отображение слоёв после объединения

        Args:
            source_layer: Слой-источник (Раздел или Без_Меж)
            points_layer: Точечный слой источника (если пересоздан)
            razdel_layer: Целевой слой Раздел (при cross-layer объединении)
            razdel_points_layer: Точечный слой Раздел (при cross-layer)
        """
        # Безопасное обновление через QTimer (предотвращает проблемы с отрисовкой)
        if source_layer is not None:
            safe_refresh_layer(source_layer)

        if points_layer is not None:
            safe_refresh_layer(points_layer)

        # Обновить слой Раздел если cross-layer
        if razdel_layer is not None:
            safe_refresh_layer(razdel_layer)
        if razdel_points_layer is not None:
            safe_refresh_layer(razdel_points_layer)

        # Обновить канву
        self.iface.mapCanvas().refresh()
