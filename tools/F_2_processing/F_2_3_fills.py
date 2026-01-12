# -*- coding: utf-8 -*-
"""
Инструмент F_2_3_Заливки
Фабрикатор: последовательно выполняет распределение по категориям и правам

Использует M_25 FillsManager для выполнения распределения.
Старые субмодули Fsm_2_3_1 и Fsm_2_3_2 сохранены для обратной совместимости,
но логика перенесена в M_25.
"""

from qgis.core import QgsProject, Qgis
from qgis.PyQt.QtWidgets import QMessageBox

from Daman_QGIS.core.base_tool import BaseTool
from Daman_QGIS.constants import MESSAGE_SUCCESS_DURATION, MESSAGE_INFO_DURATION, MESSAGE_WARNING_DURATION
from Daman_QGIS.utils import log_info, log_warning, log_error, log_success
from Daman_QGIS.managers import get_fills_manager


class F_2_3_Fills(BaseTool):
    """Фабрикатор: распределение по категориям земель и правам"""

    def __init__(self, iface) -> None:
        """Инициализация инструмента"""
        super().__init__(iface)
        self.layer_manager = None

    def set_layer_manager(self, layer_manager) -> None:
        """Установка менеджера слоев"""
        self.layer_manager = layer_manager

    def get_name(self) -> str:
        """Получить имя инструмента"""
        return "F_2_3_Заливки"

    def run(self) -> None:
        """Основной метод запуска инструмента"""
        # Автоматическая очистка слоев перед выполнением
        self.auto_cleanup_layers()

        # Проверяем наличие проекта
        project = QgsProject.instance()
        if not project.fileName():
            self.iface.messageBar().pushMessage(
                "Ошибка",
                "Сначала откройте или создайте проект",
                level=Qgis.Critical,
                duration=MESSAGE_INFO_DURATION
            )
            return

        log_info("F_2_3_Fills: Запуск фабрикатора заливок (категории + права)")

        # Получаем FillsManager
        fills_manager = get_fills_manager(self.iface, self.layer_manager)

        # Проверяем наличие данных
        availability = fills_manager.check_data_availability()

        if not availability['can_fill']:
            QMessageBox.critical(
                self.iface.mainWindow(),
                "Ошибка",
                "Не найден слой 'Le_2_1_1_1_Выборка_ЗУ' или он пуст.\n"
                "Сначала выполните 'F_2_1_Выборка'."
            )
            return

        log_info(f"F_2_3_Fills: Найдено {availability['source_count']} объектов для распределения")

        try:
            # Выполняем полное распределение через M_25
            result = fills_manager.auto_fill()

            if result.get('error'):
                raise Exception(result['error'])

            # Подсчитываем результаты
            cat_result = result.get('categories', {})
            rights_result = result.get('rights', {})

            cat_layers = len(cat_result.get('layers_created', []))
            rights_layers = len(rights_result.get('layers_created', []))

            cat_success = cat_result.get('success', False)
            rights_success = rights_result.get('success', False)

            # Итоговое сообщение
            if cat_success and rights_success:
                log_success(
                    f"F_2_3_Fills: Все этапы завершены успешно - "
                    f"категории: {cat_layers} слоёв, права: {rights_layers} слоёв"
                )
                self.iface.messageBar().pushMessage(
                    "Успешно",
                    f"Заливки завершены: категории ({cat_layers}), права ({rights_layers})",
                    level=Qgis.Success,
                    duration=MESSAGE_SUCCESS_DURATION
                )
            elif cat_success or rights_success:
                success_parts = []
                if cat_success:
                    success_parts.append(f"категории ({cat_layers})")
                if rights_success:
                    success_parts.append(f"права ({rights_layers})")

                log_warning(f"F_2_3_Fills: Частично выполнено: {', '.join(success_parts)}")
                self.iface.messageBar().pushMessage(
                    "Частично выполнено",
                    f"Заливки выполнены частично: {', '.join(success_parts)}",
                    level=Qgis.Warning,
                    duration=MESSAGE_WARNING_DURATION
                )
            else:
                log_error("F_2_3_Fills: Не удалось выполнить ни одного этапа")
                self.iface.messageBar().pushMessage(
                    "Ошибка",
                    "Не удалось выполнить заливки",
                    level=Qgis.Critical,
                    duration=MESSAGE_WARNING_DURATION
                )

        except Exception as e:
            log_error(f"F_2_3_Fills: Ошибка: {e}")
            QMessageBox.critical(
                self.iface.mainWindow(),
                "Ошибка",
                f"Ошибка при выполнении заливок:\n{str(e)}"
            )
