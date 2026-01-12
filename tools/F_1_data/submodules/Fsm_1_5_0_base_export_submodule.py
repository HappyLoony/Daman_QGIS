# -*- coding: utf-8 -*-
"""
Базовый класс для всех сабмодулей экспорта.

Устраняет дублирование кода в Fsm_1_5_* модулях.
"""

from typing import Dict, Any, Optional, Type, List
from qgis.core import QgsVectorLayer
from qgis.PyQt.QtWidgets import QMessageBox, QProgressDialog
from qgis.PyQt.QtCore import Qt

from Daman_QGIS.utils import log_info, log_warning
from ..ui.export_dialog import ExportDialog
from ..core.base_exporter import BaseExporter


class BaseExportSubmodule:
    """
    Базовый класс для сабмодулей экспорта.

    Наследники должны определить:
    - FORMAT_NAME: str - название формата для UI
    - EXPORTER_CLASS: Type[BaseExporter] - класс экспортера
    - default_params: dict - параметры по умолчанию
    - _get_dialog_options(): список опций для диалога
    - _get_exporter_params(): параметры для вызова экспортера
    - _get_success_message(): сообщение об успехе (опционально)
    """

    FORMAT_NAME: str = "Unknown"
    EXPORTER_CLASS: Type[BaseExporter] = BaseExporter

    def __init__(self, iface):
        """
        Инициализация сабмодуля

        Args:
            iface: Интерфейс QGIS
        """
        self.iface = iface

        # Параметры по умолчанию (переопределяются в наследниках)
        self.default_params = {
            'show_dialog': True,
            'show_progress': True,
            'output_folder': None,
            'layers': None,
        }

    def _get_dialog_options(self, export_params: Dict[str, Any]) -> List[tuple]:
        """
        Получить список опций для диалога.

        Args:
            export_params: Текущие параметры экспорта

        Returns:
            Список кортежей (key, label, default_value)
        """
        return []

    def _get_exporter_params(self, export_params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Получить параметры для вызова экспортера.

        Args:
            export_params: Параметры из диалога/default

        Returns:
            Параметры для exporter.export_layers()
        """
        return {}

    def _get_success_message(self, export_params: Dict[str, Any],
                             success_count: int, error_count: int,
                             output_folder: str) -> str:
        """
        Сформировать сообщение об успешном экспорте.

        Args:
            export_params: Параметры экспорта
            success_count: Количество успешных
            error_count: Количество ошибок
            output_folder: Папка экспорта

        Returns:
            Текст сообщения
        """
        message = f"Экспорт завершен!\n"
        message += f"Успешно экспортировано: {success_count} слоев\n"
        if error_count > 0:
            message += f"Ошибок: {error_count} слоев\n"
        message += f"\nФайлы сохранены в:\n{output_folder}"
        return message

    def _show_pre_export_warning(self, export_params: Dict[str, Any]) -> bool:
        """
        Показать предупреждение перед экспортом (если нужно).

        Args:
            export_params: Параметры экспорта

        Returns:
            True если продолжать экспорт, False для отмены
        """
        return True

    def export(self, **params) -> Dict[str, bool]:
        """
        Экспорт с возможностью переопределения параметров.

        Args:
            **params: Параметры экспорта (переопределяют default_params)

        Returns:
            dict: Результаты экспорта {layer_name: success}
        """
        # 1. Объединяем параметры
        export_params = self.default_params.copy()
        export_params.update(params)

        # 2. Получаем слои и папку (через диалог или параметры)
        if export_params['show_dialog']:
            dialog = ExportDialog(self.iface.mainWindow(), self.FORMAT_NAME)

            # Добавляем опции формата
            for option in self._get_dialog_options(export_params):
                dialog.add_option(option[0], option[1], option[2])

            if not dialog.exec_():
                return {}

            layers = dialog.selected_layers
            output_folder = dialog.output_folder
            options = dialog.get_export_options()

            export_params['layers'] = layers
            export_params['output_folder'] = output_folder
            export_params.update(options)

            # Предупреждение перед экспортом
            if not self._show_pre_export_warning(export_params):
                return {}
        else:
            layers = export_params['layers']
            output_folder = export_params['output_folder']

            if not layers or not output_folder:
                log_warning(f"{self.FORMAT_NAME} экспорт: не указаны слои или папка")
                return {}

        # 3. Валидация
        if not layers:
            if export_params['show_dialog']:
                QMessageBox.warning(
                    self.iface.mainWindow(),
                    "Предупреждение",
                    "Не выбрано ни одного слоя для экспорта"
                )
            return {}

        # 4. Прогресс-диалог
        progress = None
        if export_params.get('show_progress', True):
            progress = QProgressDialog(
                f"Экспорт в {self.FORMAT_NAME}...",
                "Отмена",
                0, 100,
                self.iface.mainWindow()
            )
            progress.setWindowModality(Qt.WindowModal)
            progress.setAutoClose(True)
            progress.show()

        # 5. Создаём экспортер и подключаем сигналы
        exporter = self.EXPORTER_CLASS(self.iface)

        if progress:
            exporter.progress.connect(progress.setValue)
            exporter.message.connect(lambda msg: progress.setLabelText(msg))

        # 6. Экспортируем
        exporter_params = self._get_exporter_params(export_params)
        results = exporter.export_layers(layers, output_folder, **exporter_params)

        if progress:
            progress.close()

        # 7. Подсчёт результатов
        success_count = sum(1 for success in results.values() if success)
        error_count = len(results) - success_count

        # 8. Показываем результат
        if export_params['show_dialog']:
            message = self._get_success_message(
                export_params, success_count, error_count, output_folder
            )
            QMessageBox.information(
                self.iface.mainWindow(),
                f"Экспорт в {self.FORMAT_NAME}",
                message
            )

        log_info(f"{self.FORMAT_NAME} экспорт завершен: {success_count} успешно, {error_count} ошибок")

        return results
