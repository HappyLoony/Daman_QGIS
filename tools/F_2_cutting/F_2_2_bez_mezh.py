# -*- coding: utf-8 -*-
"""
F_2_2_Без_Меж - Перенос ЗУ в слои "Без межевания"

Позволяет вручную перенести земельные участки из слоёв Раздел/Изм
в слои Без_Меж для участков, которые не требуют межевых работ.

НОВАЯ ЛОГИКА (v2):
- GUI показывает исходные ЗУ из Выборки (не нарезанные части)
- Фильтрует по наличию КН в слоях Раздел или Изм
- При выборе:
  1. Удаляет ВСЕ нарезанные части с этим КН из Раздел и Изм
  2. Копирует ИСХОДНЫЙ ЗУ из Выборки в слой Без_Меж
  3. Перенумеровывает ID во всех затронутых слоях (NW->SE)

ЗУ Без межевания - это существующие земельные участки, по которым:
- НЕ требуются межевые работы
- НЕ нужно координировать (нет нумерации точек)
- Нужно только присвоить ID для идентификации

ВАЖНО: F_2_2 выполняется ДО F_2_3 (Корректировка)!
Последовательность: F_2_1 -> F_2_2 -> F_2_3 -> F_2_4

Атрибуты для Без_Меж:
- Услов_КН = КН (копируется, не генерируется)
- План_категория = Категория
- План_ВРИ = ВРИ
- Площадь_ОЗУ = Площадь
- Вид_Работ = "Существующий (сохраняемый) земельный участок"
- Точки = "-" (не применимо - нет нумерации)
"""

from typing import Optional, Dict, List, Any, TYPE_CHECKING

from qgis.PyQt.QtWidgets import QMessageBox
from qgis.core import QgsProject, Qgis, QgsVectorLayer

from Daman_QGIS.core.base_tool import BaseTool
from Daman_QGIS.managers import registry
from Daman_QGIS.constants import (
    PLUGIN_NAME, MESSAGE_SUCCESS_DURATION, MESSAGE_INFO_DURATION,
    WORK_TYPE_BEZ_MEZH,
    # Слой Выборки
    LAYER_SELECTION_ZU,
    # Слои Раздел (источник нарезанных частей)
    LAYER_CUTTING_OKS_RAZDEL,
    LAYER_CUTTING_PO_RAZDEL,
    LAYER_CUTTING_VO_RAZDEL,
    # Слои Изм (источник нарезанных частей)
    LAYER_CUTTING_OKS_IZM,
    LAYER_CUTTING_PO_IZM,
    LAYER_CUTTING_VO_IZM,
    # Слои Без_Меж (цель)
    LAYER_CUTTING_OKS_BEZ_MEZH,
    LAYER_CUTTING_PO_BEZ_MEZH,
    LAYER_CUTTING_VO_BEZ_MEZH,
)
from Daman_QGIS.utils import log_info, log_warning, log_error

# Импорт субмодулей
from .submodules.Fsm_2_2_1_dialog import Fsm_2_2_1_Dialog
from .submodules.Fsm_2_2_2_transfer import Fsm_2_2_2_Transfer

if TYPE_CHECKING:
    from Daman_QGIS.managers import LayerManager


class F_2_2_BezMezh(BaseTool):
    """Инструмент переноса ЗУ в слой Без_Меж

    Позволяет пользователю выбрать исходные ЗУ из Выборки и перенести
    их в соответствующие слои Без_Меж (без межевания).
    Нарезанные части удаляются из слоёв Раздел и Изм.
    """

    # Вид работ для Без_Меж
    WORK_TYPE_BEZ_MEZH = WORK_TYPE_BEZ_MEZH

    # Маппинг слой -> тип ЗПР
    LAYER_TO_ZPR_TYPE: Dict[str, str] = {
        LAYER_CUTTING_OKS_RAZDEL: 'ОКС',
        LAYER_CUTTING_PO_RAZDEL: 'ПО',
        LAYER_CUTTING_VO_RAZDEL: 'ВО',
        LAYER_CUTTING_OKS_IZM: 'ОКС',
        LAYER_CUTTING_PO_IZM: 'ПО',
        LAYER_CUTTING_VO_IZM: 'ВО',
    }

    # Маппинг тип ЗПР -> слой Без_Меж
    ZPR_TYPE_TO_BEZ_MEZH: Dict[str, str] = {
        'ОКС': LAYER_CUTTING_OKS_BEZ_MEZH,
        'ПО': LAYER_CUTTING_PO_BEZ_MEZH,
        'ВО': LAYER_CUTTING_VO_BEZ_MEZH,
    }

    # Список имён слоёв Раздел
    RAZDEL_LAYER_NAMES: List[str] = [
        LAYER_CUTTING_OKS_RAZDEL,
        LAYER_CUTTING_PO_RAZDEL,
        LAYER_CUTTING_VO_RAZDEL,
    ]

    # Список имён слоёв Изм
    IZM_LAYER_NAMES: List[str] = [
        LAYER_CUTTING_OKS_IZM,
        LAYER_CUTTING_PO_IZM,
        LAYER_CUTTING_VO_IZM,
    ]

    def __init__(self, iface: Any) -> None:
        """Инициализация инструмента

        Args:
            iface: Интерфейс QGIS
        """
        super().__init__(iface)
        self.layer_manager: Optional['LayerManager'] = None
        self.plugin_dir: Optional[str] = None
        self._transfer: Optional[Fsm_2_2_2_Transfer] = None
        self._dialog: Optional[Fsm_2_2_1_Dialog] = None

    def set_plugin_dir(self, plugin_dir: str) -> None:
        """Установка пути к папке плагина"""
        self.plugin_dir = plugin_dir

    def set_layer_manager(self, layer_manager: 'LayerManager') -> None:
        """Установка менеджера слоёв"""
        self.layer_manager = layer_manager

    @staticmethod
    def get_name() -> str:
        """Имя инструмента для cleanup"""
        return "F_2_2_Без_Меж"

    def run(self) -> None:
        """Основной метод запуска инструмента"""
        log_info("F_2_2: Запуск переноса ЗУ в Без_Меж")

        # Проверка открытого проекта
        if not self.check_project_opened():
            return

        # Найти слой Выборки
        selection_layer = self._find_selection_layer()
        if not selection_layer:
            self.iface.messageBar().pushMessage(
                PLUGIN_NAME,
                "Не найден слой Выборки ЗУ. Сначала выполните выборку (F_2_1).",
                level=Qgis.Warning,
                duration=MESSAGE_INFO_DURATION
            )
            log_warning("F_2_2: Не найден слой Выборки ЗУ")
            return

        # Найти слои Раздел и Изм
        cutting_layers = self._find_cutting_layers()
        razdel_layers = cutting_layers['razdel']
        izm_layers = cutting_layers['izm']

        if not razdel_layers and not izm_layers:
            self.iface.messageBar().pushMessage(
                PLUGIN_NAME,
                "Не найдены слои Раздел или Изм. Сначала выполните нарезку (F_2_1).",
                level=Qgis.Warning,
                duration=MESSAGE_INFO_DURATION
            )
            log_warning("F_2_2: Не найдены слои Раздел/Изм для переноса")
            return

        # Инициализация модуля переноса
        structure_manager = registry.get('M_19')
        gpkg_path = structure_manager.get_gpkg_path(create=False)
        if not gpkg_path:
            log_error("F_2_2: Не удалось получить путь к GPKG")
            return

        self._transfer = Fsm_2_2_2_Transfer(
            gpkg_path=gpkg_path,
            selection_layer=selection_layer,
            razdel_layers=razdel_layers,
            izm_layers=izm_layers,
            layer_to_zpr_type=self.LAYER_TO_ZPR_TYPE,
            zpr_type_to_bez_mezh=self.ZPR_TYPE_TO_BEZ_MEZH,
            work_type=WORK_TYPE_BEZ_MEZH,
            layer_manager=self.layer_manager
        )

        # Показать диалог выбора ЗУ
        self._show_dialog(selection_layer, razdel_layers, izm_layers)

    def _find_selection_layer(self) -> Optional[QgsVectorLayer]:
        """Найти слой Выборки ЗУ в проекте

        Returns:
            QgsVectorLayer или None
        """
        project = QgsProject.instance()

        layers = project.mapLayersByName(LAYER_SELECTION_ZU)
        if layers:
            layer = layers[0]
            if isinstance(layer, QgsVectorLayer) and layer.isValid():
                log_info(f"F_2_2: Найден слой Выборки ЗУ ({layer.featureCount()} объектов)")
                return layer

        return None

    def _find_cutting_layers(self) -> Dict[str, List[QgsVectorLayer]]:
        """Найти существующие слои Раздел и Изм в проекте

        Returns:
            Dict с ключами 'razdel' и 'izm', содержащие списки слоёв
        """
        project = QgsProject.instance()
        result = {
            'razdel': [],
            'izm': []
        }

        # Поиск слоёв Раздел
        for layer_name in self.RAZDEL_LAYER_NAMES:
            layers = project.mapLayersByName(layer_name)
            if layers:
                layer = layers[0]
                if isinstance(layer, QgsVectorLayer) and layer.featureCount() > 0:
                    result['razdel'].append(layer)
                    log_info(f"F_2_2: Найден слой {layer_name} ({layer.featureCount()} объектов)")

        # Поиск слоёв Изм
        for layer_name in self.IZM_LAYER_NAMES:
            layers = project.mapLayersByName(layer_name)
            if layers:
                layer = layers[0]
                if isinstance(layer, QgsVectorLayer) and layer.featureCount() > 0:
                    result['izm'].append(layer)
                    log_info(f"F_2_2: Найден слой {layer_name} ({layer.featureCount()} объектов)")

        return result

    def _show_dialog(
        self,
        selection_layer: QgsVectorLayer,
        razdel_layers: List[QgsVectorLayer],
        izm_layers: List[QgsVectorLayer]
    ) -> None:
        """Показать диалог выбора ЗУ для переноса

        Args:
            selection_layer: Слой Выборки ЗУ
            razdel_layers: Слои Раздел
            izm_layers: Слои Изм
        """
        # Создание диалога
        self._dialog = Fsm_2_2_1_Dialog(
            parent=self.iface.mainWindow(),
            selection_layer=selection_layer,
            razdel_layers=razdel_layers,
            izm_layers=izm_layers,
            layer_to_zpr_type=self.LAYER_TO_ZPR_TYPE,
            transfer_callback=self._on_transfer
        )
        self._dialog.exec()

    def _on_transfer(self, kn_list: List[str]) -> Dict[str, Any]:
        """Callback для выполнения переноса из диалога

        Args:
            kn_list: Список КН для переноса

        Returns:
            Результат переноса
        """
        if not self._transfer:
            log_error("F_2_2: Модуль переноса не инициализирован")
            return {'errors': ['Transfer module not initialized']}

        # Выполнение переноса
        result = self._transfer.execute(kn_list=kn_list)

        if result.get('errors'):
            errors = result['errors']
            log_error(f"F_2_2: Ошибки переноса: {errors}")
            QMessageBox.critical(
                self.iface.mainWindow(),
                PLUGIN_NAME,
                f"Ошибки переноса:\n" + "\n".join(errors[:5])
            )
        else:
            # Успешный перенос
            transferred = result.get('transferred', 0)
            deleted_razdel = result.get('deleted_from_razdel', 0)
            deleted_izm = result.get('deleted_from_izm', 0)
            target_layers = result.get('target_layers', [])

            log_info(
                f"F_2_2: Перенесено {transferred} ЗУ. "
                f"Удалено из Раздел: {deleted_razdel}, из Изм: {deleted_izm}"
            )

            # Финализация целевых слоёв
            for layer_name in target_layers:
                project = QgsProject.instance()
                layers = project.mapLayersByName(layer_name)
                if layers:
                    self._finalize_layer(layers[0], layer_name)

            self.iface.messageBar().pushMessage(
                PLUGIN_NAME,
                f"Перенесено {transferred} ЗУ в слои Без_Меж. "
                f"Запустите F_2_3 (Корректировка) для пересчёта точек.",
                level=Qgis.Success,
                duration=MESSAGE_SUCCESS_DURATION
            )

            # Обновить слои в QGIS
            self._refresh_all_layers()

        return result

    def _finalize_layer(
        self,
        layer: QgsVectorLayer,
        layer_name: str
    ) -> None:
        """Финализация слоя - заполнение пустых полей и капитализация

        Args:
            layer: Целевой слой
            layer_name: Имя слоя для логирования
        """
        try:
            from Daman_QGIS.managers.processing.submodules.Msm_13_2_attribute_processor import AttributeProcessor

            processor = AttributeProcessor()
            processor.finalize_layer_processing(
                layer=layer,
                layer_name=layer_name,
                capitalize=True
            )
            log_info(f"F_2_2: Финализация слоя {layer_name} завершена")
        except Exception as e:
            log_warning(f"F_2_2: Ошибка финализации слоя: {e}")

    def _refresh_all_layers(self) -> None:
        """Обновить отображение всех затронутых слоёв"""
        from Daman_QGIS.utils import safe_refresh_layer, safe_refresh_canvas, REFRESH_MEDIUM

        project = QgsProject.instance()

        # Обновить слои Раздел
        for layer_name in self.RAZDEL_LAYER_NAMES:
            layers = project.mapLayersByName(layer_name)
            if layers:
                safe_refresh_layer(layers[0])

        # Обновить слои Изм
        for layer_name in self.IZM_LAYER_NAMES:
            layers = project.mapLayersByName(layer_name)
            if layers:
                safe_refresh_layer(layers[0])

        # Обновить слои Без_Меж
        for layer_name in self.ZPR_TYPE_TO_BEZ_MEZH.values():
            layers = project.mapLayersByName(layer_name)
            if layers:
                safe_refresh_layer(layers[0])

        # Обновить канву
        safe_refresh_canvas(REFRESH_MEDIUM)
