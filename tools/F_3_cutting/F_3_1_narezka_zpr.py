# -*- coding: utf-8 -*-
"""
F_3_1_Нарезка ЗПР - Нарезка зон планируемого размещения

Нарезка ВСЕХ типов ЗПР (стандартные и рекреационные) по границам
земельных участков и других слоёв (НП, МО, Лес, Вода).

Типы ЗПР:
- Стандартные: ОКС, ПО (площадные объекты), ВО -> Le_3_1_*
- Рекреационные: РЕК_АД, СЕТИ_ПО, СЕТИ_ВО, НЭ -> Le_3_2_*

Создаёт слои:
- Le_3_X_Y_1_Раздел_* - части ЗПР внутри границ ЗУ
- Le_3_X_Y_2_НГС_* - части ЗПР вне границ ЗУ (незанятые земли)

Примечание:
    Логика нарезки делегируется в M_26_CuttingManager.
    F_3_1 является единой UI-точкой входа для всех типов нарезки.
"""

from typing import Optional, Dict, List, Any, TYPE_CHECKING

from qgis.PyQt.QtWidgets import QMessageBox
from qgis.core import QgsProject, Qgis, QgsVectorLayer

from Daman_QGIS.core.base_tool import BaseTool
from Daman_QGIS.constants import (
    PLUGIN_NAME, MESSAGE_SUCCESS_DURATION, MESSAGE_INFO_DURATION,
    # Слои границ нарезки
    LAYER_SELECTION_ZU, LAYER_SELECTION_ZU_10M,
    # Слой кадастровых кварталов (для привязки НГС)
    LAYER_SELECTION_KK,
    # Слои ЗПР
    LAYER_ZPR_OKS, LAYER_ZPR_PO, LAYER_ZPR_VO,
    # Слои границ (overlay)
    LAYER_SELECTION_NP, LAYER_ATD_MO, LAYER_EGRN_LES, LAYER_SELECTION_VODA,
    # Выходные слои
    LAYER_CUTTING_OKS_RAZDEL, LAYER_CUTTING_OKS_NGS,
    LAYER_CUTTING_PO_RAZDEL, LAYER_CUTTING_PO_NGS,
    LAYER_CUTTING_VO_RAZDEL, LAYER_CUTTING_VO_NGS,
)
from Daman_QGIS.utils import log_info, log_warning, log_error
from Daman_QGIS.managers import get_cutting_manager

if TYPE_CHECKING:
    from Daman_QGIS.managers import LayerManager


class F_3_1_NarezkaZPR(BaseTool):
    """Инструмент нарезки ЗПР по границам ЗУ и других слоёв

    UI-точка входа. Логика делегируется в M_26_CuttingManager.
    """

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
        return "F_3_1_Нарезка ЗПР"

    def run(self) -> None:
        """Основной метод запуска инструмента

        Делегирует логику нарезки в M_26_CuttingManager.
        """
        log_info("F_3_1: Запуск нарезки ЗПР")

        # Проверка открытого проекта
        if not self.check_project_opened():
            return

        # Автоматическая очистка слоев перед выполнением
        self.auto_cleanup_layers()

        # Делегирование в M_26_CuttingManager
        self._execute_via_m26()

    def _execute_via_m26(self) -> None:
        """Выполнение нарезки через M_26_CuttingManager

        Выполняет нарезку ВСЕХ доступных типов ЗПР:
        - Стандартные (ОКС, ЛО, ВО)
        - Рекреационные (РЕК_АД, СЕТИ_ПО, СЕТИ_ВО, НЭ)
        """
        try:
            # Получаем менеджер нарезки
            cutting_manager = get_cutting_manager(self.iface, self.layer_manager)

            # Устанавливаем необходимые зависимости
            cutting_manager.set_plugin_dir(self.plugin_dir)
            cutting_manager.set_project_manager(self.project_manager)

            # Проверка доступности данных для обоих типов
            avail_std = cutting_manager.check_data_availability('standard')
            avail_rek = cutting_manager.check_data_availability('rek')

            # Строгая проверка: если есть невалидные ЗПР - блокируем нарезку
            invalid_std = avail_std.get('invalid_zpr', [])
            invalid_rek = avail_rek.get('invalid_zpr', [])
            all_invalid = invalid_std + invalid_rek

            if all_invalid:
                error_msg = "Слои ЗПР имеют невалидную структуру:\n\n"
                for inv in all_invalid:
                    error_msg += f"- {inv['layer']}: отсутствуют поля {', '.join(inv['missing_fields'])}\n"
                error_msg += "\nДобавьте недостающие поля в DXF файл ЗПР."
                self._show_error(error_msg)
                return

            # Нужен хотя бы один тип ЗПР
            if not avail_std['can_cut'] and not avail_rek['can_cut']:
                self._show_error(
                    "Не найдены данные для нарезки.\n\n"
                    "Убедитесь что:\n"
                    "- Слой Выборка_ЗУ содержит объекты\n"
                    "- Есть хотя бы один слой ЗПР"
                )
                return

            total_zpr = len(avail_std.get('available_zpr', [])) + len(avail_rek.get('available_zpr', []))
            log_info(f"F_3_1: Доступно {total_zpr} типов ЗПР для нарезки")

            # Выполняем нарезку ВСЕХ типов
            result = cutting_manager.cut_all()

            # Показываем результат
            total_razdel = result.get('total_razdel', 0)
            total_ngs = result.get('total_ngs', 0)

            if total_razdel == 0 and total_ngs == 0:
                self._show_error("Нарезка не создала объектов. Проверьте входные данные.")
                return

            log_info(f"F_3_1: Нарезка завершена. Создано: {total_razdel} Раздел, {total_ngs} НГС")

            self.iface.messageBar().pushMessage(
                PLUGIN_NAME,
                f"Нарезка ЗПР завершена. Создано: {total_razdel} Раздел, {total_ngs} НГС",
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
