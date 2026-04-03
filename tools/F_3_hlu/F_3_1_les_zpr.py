# -*- coding: utf-8 -*-
"""
F_3_1_ЛЕС ЗПР - Нарезка ЗПР по лесным выделам

Нарезка слоёв Le_2_1_* (стандартные ЗПР) и Le_2_2_* (РЕК ЗПР)
по границам лесных выделов из Le_3_1_1_1_Лес_Ред_Выделы.

Создаёт слои:
- Le_3_2_X_Y - лесная нарезка стандартных ЗПР (ОКС/ПО/ВО)
- Le_3_3_X_Y - лесная нарезка РЕК ЗПР (РЕК_АД/СЕТИ_ПО/СЕТИ_ВО/НЭ)

Примечание:
    Выполняется ПОСЛЕ F_2_1 и F_2_2.
    Слои Изм (X_5) не обрабатываются.
    Объекты вне лесного фонда игнорируются.
"""

from typing import Optional, Dict, List, Any, TYPE_CHECKING

from qgis.PyQt.QtWidgets import QMessageBox
from qgis.core import QgsProject, Qgis, QgsVectorLayer

from Daman_QGIS.core.base_tool import BaseTool
from Daman_QGIS.constants import (
    PLUGIN_NAME, MESSAGE_SUCCESS_DURATION, MESSAGE_INFO_DURATION,
    # Слой лесных выделов
    LAYER_FOREST_VYDELY,
    # Входные слои Le_2_1_* (стандартные ЗПР, без Изм)
    LAYER_CUTTING_OKS_RAZDEL, LAYER_CUTTING_OKS_NGS,
    LAYER_CUTTING_OKS_BEZ_MEZH, LAYER_CUTTING_OKS_PS,
    LAYER_CUTTING_PO_RAZDEL, LAYER_CUTTING_PO_NGS,
    LAYER_CUTTING_PO_BEZ_MEZH, LAYER_CUTTING_PO_PS,
    LAYER_CUTTING_VO_RAZDEL, LAYER_CUTTING_VO_NGS,
    LAYER_CUTTING_VO_BEZ_MEZH, LAYER_CUTTING_VO_PS,
    # Входные слои Le_2_2_* (РЕК ЗПР, без Изм)
    LAYER_CUTTING_REK_AD_RAZDEL, LAYER_CUTTING_REK_AD_NGS,
    LAYER_CUTTING_REK_AD_BEZ_MEZH, LAYER_CUTTING_REK_AD_PS,
    LAYER_CUTTING_SETI_PO_RAZDEL, LAYER_CUTTING_SETI_PO_NGS,
    LAYER_CUTTING_SETI_PO_BEZ_MEZH, LAYER_CUTTING_SETI_PO_PS,
    LAYER_CUTTING_SETI_VO_RAZDEL, LAYER_CUTTING_SETI_VO_NGS,
    LAYER_CUTTING_SETI_VO_BEZ_MEZH, LAYER_CUTTING_SETI_VO_PS,
    LAYER_CUTTING_NE_RAZDEL, LAYER_CUTTING_NE_NGS,
    LAYER_CUTTING_NE_BEZ_MEZH, LAYER_CUTTING_NE_PS,
    # Выходные слои Le_3_2_* (стандартные ЗПР)
    LAYER_FOREST_STD_OKS_RAZDEL, LAYER_FOREST_STD_OKS_NGS,
    LAYER_FOREST_STD_OKS_BEZ_MEZH, LAYER_FOREST_STD_OKS_PS,
    LAYER_FOREST_STD_PO_RAZDEL, LAYER_FOREST_STD_PO_NGS,
    LAYER_FOREST_STD_PO_BEZ_MEZH, LAYER_FOREST_STD_PO_PS,
    LAYER_FOREST_STD_VO_RAZDEL, LAYER_FOREST_STD_VO_NGS,
    LAYER_FOREST_STD_VO_BEZ_MEZH, LAYER_FOREST_STD_VO_PS,
    # Выходные слои Le_3_3_* (РЕК ЗПР)
    LAYER_FOREST_REK_AD_RAZDEL, LAYER_FOREST_REK_AD_NGS,
    LAYER_FOREST_REK_AD_BEZ_MEZH, LAYER_FOREST_REK_AD_PS,
    LAYER_FOREST_SETI_PO_RAZDEL, LAYER_FOREST_SETI_PO_NGS,
    LAYER_FOREST_SETI_PO_BEZ_MEZH, LAYER_FOREST_SETI_PO_PS,
    LAYER_FOREST_SETI_VO_RAZDEL, LAYER_FOREST_SETI_VO_NGS,
    LAYER_FOREST_SETI_VO_BEZ_MEZH, LAYER_FOREST_SETI_VO_PS,
    LAYER_FOREST_NE_RAZDEL, LAYER_FOREST_NE_NGS,
    LAYER_FOREST_NE_BEZ_MEZH, LAYER_FOREST_NE_PS,
)
from Daman_QGIS.utils import log_info, log_warning, log_error

from .submodules import Fsm_3_1_1_ForestCutter, Fsm_3_1_2_AttributeMapper

if TYPE_CHECKING:
    from Daman_QGIS.managers import LayerManager


class F_3_1_LesZPR(BaseTool):
    """Инструмент нарезки ЗПР по лесным выделам"""

    # Маппинг: входной слой Le_2_* -> выходной слой Le_3_*
    LAYER_MAPPING = {
        # Le_2_1_* -> Le_3_2_* (стандартные ЗПР)
        # ОКС
        LAYER_CUTTING_OKS_RAZDEL: LAYER_FOREST_STD_OKS_RAZDEL,
        LAYER_CUTTING_OKS_NGS: LAYER_FOREST_STD_OKS_NGS,
        LAYER_CUTTING_OKS_BEZ_MEZH: LAYER_FOREST_STD_OKS_BEZ_MEZH,
        LAYER_CUTTING_OKS_PS: LAYER_FOREST_STD_OKS_PS,
        # ПО
        LAYER_CUTTING_PO_RAZDEL: LAYER_FOREST_STD_PO_RAZDEL,
        LAYER_CUTTING_PO_NGS: LAYER_FOREST_STD_PO_NGS,
        LAYER_CUTTING_PO_BEZ_MEZH: LAYER_FOREST_STD_PO_BEZ_MEZH,
        LAYER_CUTTING_PO_PS: LAYER_FOREST_STD_PO_PS,
        # ВО
        LAYER_CUTTING_VO_RAZDEL: LAYER_FOREST_STD_VO_RAZDEL,
        LAYER_CUTTING_VO_NGS: LAYER_FOREST_STD_VO_NGS,
        LAYER_CUTTING_VO_BEZ_MEZH: LAYER_FOREST_STD_VO_BEZ_MEZH,
        LAYER_CUTTING_VO_PS: LAYER_FOREST_STD_VO_PS,
        # Le_2_2_* -> Le_3_3_* (РЕК ЗПР)
        # РЕК_АД
        LAYER_CUTTING_REK_AD_RAZDEL: LAYER_FOREST_REK_AD_RAZDEL,
        LAYER_CUTTING_REK_AD_NGS: LAYER_FOREST_REK_AD_NGS,
        LAYER_CUTTING_REK_AD_BEZ_MEZH: LAYER_FOREST_REK_AD_BEZ_MEZH,
        LAYER_CUTTING_REK_AD_PS: LAYER_FOREST_REK_AD_PS,
        # СЕТИ_ПО
        LAYER_CUTTING_SETI_PO_RAZDEL: LAYER_FOREST_SETI_PO_RAZDEL,
        LAYER_CUTTING_SETI_PO_NGS: LAYER_FOREST_SETI_PO_NGS,
        LAYER_CUTTING_SETI_PO_BEZ_MEZH: LAYER_FOREST_SETI_PO_BEZ_MEZH,
        LAYER_CUTTING_SETI_PO_PS: LAYER_FOREST_SETI_PO_PS,
        # СЕТИ_ВО
        LAYER_CUTTING_SETI_VO_RAZDEL: LAYER_FOREST_SETI_VO_RAZDEL,
        LAYER_CUTTING_SETI_VO_NGS: LAYER_FOREST_SETI_VO_NGS,
        LAYER_CUTTING_SETI_VO_BEZ_MEZH: LAYER_FOREST_SETI_VO_BEZ_MEZH,
        LAYER_CUTTING_SETI_VO_PS: LAYER_FOREST_SETI_VO_PS,
        # НЭ
        LAYER_CUTTING_NE_RAZDEL: LAYER_FOREST_NE_RAZDEL,
        LAYER_CUTTING_NE_NGS: LAYER_FOREST_NE_NGS,
        LAYER_CUTTING_NE_BEZ_MEZH: LAYER_FOREST_NE_BEZ_MEZH,
        LAYER_CUTTING_NE_PS: LAYER_FOREST_NE_PS,
    }

    def __init__(self, iface) -> None:
        """Инициализация инструмента"""
        super().__init__(iface)
        self.layer_manager: Optional['LayerManager'] = None
        self.plugin_dir: Optional[str] = None
        self.project_manager = None

    def set_plugin_dir(self, plugin_dir: str) -> None:
        """Установка пути к папке плагина"""
        self.plugin_dir = plugin_dir

    def set_layer_manager(self, layer_manager: 'LayerManager') -> None:
        """Установка менеджера слоев"""
        self.layer_manager = layer_manager

    def set_project_manager(self, project_manager) -> None:
        """Установка менеджера проектов"""
        self.project_manager = project_manager

    def get_name(self) -> str:
        """Получить имя инструмента для cleanup"""
        return "F_3_1_ЛЕС ЗПР"

    def run(self) -> None:
        """Основной метод запуска инструмента"""
        log_info("F_3_1: Запуск нарезки ЗПР по лесным выделам")

        # Проверка открытого проекта
        if not self.check_project_opened():
            return

        # Автоматическая очистка слоев Le_3_* перед выполнением
        self.auto_cleanup_layers()

        # Валидация данных
        forest_layer = self._get_forest_layer()
        if forest_layer is None:
            return

        le3_layers = self._get_le3_layers()
        if not le3_layers:
            self._show_error(
                "Не найдены слои нарезки Le_2_1_* или Le_2_2_*.\n\n"
                "Сначала выполните:\n"
                "1. F_2_1 (Нарезка ЗПР)\n"
                "2. F_2_2 (Нарезка ЗПР РЕК)"
            )
            return

        # Валидация полей лесного слоя
        if not self._validate_forest_fields(forest_layer):
            return

        # Получаем путь к GPKG
        gpkg_path = self._get_gpkg_path()
        if not gpkg_path:
            self._show_error("Не удалось определить путь к GeoPackage проекта")
            return

        # Выполняем нарезку
        self._execute_cutting(forest_layer, le3_layers, gpkg_path)

    def _get_forest_layer(self) -> Optional[QgsVectorLayer]:
        """Получить слой лесных выделов

        Returns:
            QgsVectorLayer или None
        """
        layers = QgsProject.instance().mapLayersByName(LAYER_FOREST_VYDELY)
        if not layers:
            self._show_error(
                f"Не найден слой лесных выделов:\n{LAYER_FOREST_VYDELY}\n\n"
                "Добавьте слой в проект перед выполнением функции."
            )
            return None

        layer = layers[0]
        if layer.featureCount() == 0:
            self._show_error(
                f"Слой {LAYER_FOREST_VYDELY} не содержит объектов."
            )
            return None

        return layer

    def _get_le3_layers(self) -> Dict[str, QgsVectorLayer]:
        """Получить все доступные слои Le_2_*

        Returns:
            Dict[str, QgsVectorLayer]: {имя_входного: слой}
        """
        result = {}

        for le3_name in self.LAYER_MAPPING.keys():
            layers = QgsProject.instance().mapLayersByName(le3_name)
            if layers and layers[0].featureCount() > 0:
                result[le3_name] = layers[0]

        log_info(f"F_3_1: Найдено {len(result)} слоёв Le_2_* для обработки")
        return result

    def _validate_forest_fields(self, forest_layer: QgsVectorLayer) -> bool:
        """Проверка наличия всех полей в слое лесных выделов

        Args:
            forest_layer: Слой лесных выделов

        Returns:
            bool: Валидность структуры
        """
        mapper = Fsm_3_1_2_AttributeMapper()
        layer_fields = [f.name() for f in forest_layer.fields()]

        is_valid, missing = mapper.validate_forest_layer_fields(layer_fields)

        if not is_valid:
            self._show_error(
                f"Слой {LAYER_FOREST_VYDELY} имеет неполную структуру.\n\n"
                f"Отсутствуют поля:\n{', '.join(missing)}"
            )
            return False

        return True

    def _get_gpkg_path(self) -> Optional[str]:
        """Получить путь к GeoPackage проекта

        Returns:
            str: Путь к GPKG или None
        """
        if self.project_manager and self.project_manager.current_project:
            from Daman_QGIS.managers import registry
            structure_manager = registry.get('M_19')
            structure_manager.project_root = self.project_manager.current_project
            return structure_manager.get_gpkg_path(create=False)

        log_error("F_3_1: project_manager не инициализирован, невозможно определить GPKG")
        return None

    def _execute_cutting(
        self,
        forest_layer: QgsVectorLayer,
        le3_layers: Dict[str, QgsVectorLayer],
        gpkg_path: str
    ) -> None:
        """Выполнение нарезки

        Args:
            forest_layer: Слой лесных выделов
            le3_layers: Словарь слоёв Le_2_*
            gpkg_path: Путь к GeoPackage
        """
        try:
            cutter = Fsm_3_1_1_ForestCutter(gpkg_path)

            # CRS из проекта (после калибровки F_0_5 может отличаться от CRS слоёв)
            crs = QgsProject.instance().crs()

            total_created = 0
            layers_created = 0

            for le3_name, le3_layer in le3_layers.items():
                output_name = self.LAYER_MAPPING.get(le3_name)
                if not output_name:
                    continue

                # Обработка слоя
                result_layer = cutter.process_layer(
                    le3_layer, forest_layer, output_name, crs
                )

                if result_layer:
                    # Добавляем через LayerManager (стили, подписи, метаданные)
                    if self.layer_manager:
                        self.layer_manager.add_layer(result_layer)
                    else:
                        QgsProject.instance().addMapLayer(result_layer)

                    total_created += result_layer.featureCount()
                    layers_created += 1

                    log_info(f"F_3_1: Создан {output_name} ({result_layer.featureCount()} объектов)")

            # Очистка кэша
            cutter.clear_cache()

            # Сортировка слоёв
            if self.layer_manager:
                self.layer_manager.sort_all_layers()

            # Результат
            if layers_created == 0:
                self._show_warning(
                    "Не создано ни одного слоя.\n\n"
                    "Возможные причины:\n"
                    "- Слои Le_2_* не пересекаются с лесными выделами\n"
                    "- Площадь пересечений слишком мала"
                )
            else:
                log_info(f"F_3_1: Завершено. Создано {layers_created} слоёв, "
                        f"{total_created} объектов")

                self.iface.messageBar().pushMessage(
                    PLUGIN_NAME,
                    f"Нарезка по лесу завершена. Создано: {total_created} объектов "
                    f"в {layers_created} слоях",
                    level=Qgis.Success,
                    duration=MESSAGE_SUCCESS_DURATION
                )

        except Exception as e:
            log_error(f"F_3_1: Ошибка при нарезке: {e}")
            import traceback
            log_error(traceback.format_exc())
            self._show_error(f"Ошибка при нарезке: {e}")

    def _show_error(self, message: str) -> None:
        """Показать сообщение об ошибке

        Args:
            message: Текст сообщения
        """
        QMessageBox.critical(
            self.iface.mainWindow(),
            f"{PLUGIN_NAME} - Ошибка",
            message
        )

    def _show_warning(self, message: str) -> None:
        """Показать предупреждение

        Args:
            message: Текст сообщения
        """
        QMessageBox.warning(
            self.iface.mainWindow(),
            f"{PLUGIN_NAME} - Предупреждение",
            message
        )
