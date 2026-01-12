# -*- coding: utf-8 -*-
"""
Сабмодуль экспорта в KMZ
"""

import os
from qgis.core import QgsMessageLog, Qgis
from qgis.PyQt.QtWidgets import QMessageBox, QProgressDialog
from qgis.PyQt.QtCore import Qt

from Daman_QGIS.constants import PLUGIN_NAME
from Daman_QGIS.utils import log_info, log_warning, log_error
from ..ui.export_dialog import ExportDialog
from ..core.kmz_exporter import KMZExporter


class KMZExportSubmodule:
    """Сабмодуль для экспорта в KMZ формат"""
    
    def __init__(self, iface):
        """
        Инициализация сабмодуля
        
        Args:
            iface: Интерфейс QGIS
        """
        self.iface = iface
        
        # Параметры по умолчанию
        self.default_params = {
            'export_labels': True,  # Экспортировать подписи
            'export_description': True,  # Экспортировать описания
            'show_dialog': True,  # Показывать диалог выбора
            'output_folder': None,  # Папка для экспорта
            'layers': None,  # Список слоев (если не показываем диалог)
        }
    def export(self, **params):
        """
        Экспорт в KMZ с возможностью переопределения параметров

        Args:
            **params: Параметры экспорта (переопределяют default_params)

        Returns:
            dict: Результаты экспорта {layer_name: success}
        """
        # Объединяем параметры
        export_params = self.default_params.copy()
        export_params.update(params)

        # Получаем слои и папку
        if export_params['show_dialog']:
            # Показываем диалог
            dialog = ExportDialog(self.iface.mainWindow(), "KMZ")

            # Добавляем опции для KMZ
            dialog.add_option("export_labels", "Экспортировать подписи", export_params['export_labels'])
            dialog.add_option("export_description", "Экспортировать описания", export_params['export_description'])

            if not dialog.exec_():
                return {}

            layers = dialog.selected_layers
            output_folder = dialog.output_folder
            options = dialog.get_export_options()

            # Обновляем параметры из диалога
            export_params['layers'] = layers
            export_params['output_folder'] = output_folder
            export_params.update(options)
        else:
            # Используем переданные параметры
            layers = export_params['layers']
            output_folder = export_params['output_folder']

            if not layers or not output_folder:
                log_warning("KMZ экспорт: не указаны слои или папка")
                return {}

        # Валидация
        if not layers:
            if export_params['show_dialog']:
                QMessageBox.warning(
                    self.iface.mainWindow(),
                    "Предупреждение",
                    "Не выбрано ни одного слоя для экспорта"
                )
            return {}

        # Создаем прогресс-диалог если нужно
        progress = None
        if export_params.get('show_progress', True):
            progress = QProgressDialog(
                "Экспорт в KMZ...",
                "Отмена",
                0,
                100,
                self.iface.mainWindow()
            )
            progress.setWindowModality(Qt.WindowModal)
            progress.setAutoClose(True)
            progress.show()

        # Создаем экспортер
        exporter = KMZExporter(self.iface)

        # Подключаем сигналы прогресса если есть диалог
        if progress:
            exporter.progress.connect(progress.setValue)
            exporter.message.connect(lambda msg: progress.setLabelText(msg))

        # Экспортируем слои
        results = exporter.export_layers(
            layers,
            output_folder,
            export_labels=export_params['export_labels'],
            export_description=export_params['export_description']
        )

        if progress:
            progress.close()

        # Считаем результаты
        success_count = sum(1 for success in results.values() if success)
        error_count = len(results) - success_count

        # Показываем результат если был диалог
        if export_params['show_dialog']:
            message = f"Экспорт завершен!\n"
            message += f"Успешно экспортировано: {success_count} слоев\n"
            if error_count > 0:
                message += f"Ошибок: {error_count} слоев\n"
            message += f"\nФайлы сохранены в:\n{output_folder}"
            message += f"\n\nВнимание: KMZ файлы всегда экспортируются в WGS-84"
            message += f"\nKMZ - это сжатые KML файлы для Google Earth"

            QMessageBox.information(
                self.iface.mainWindow(),
                "Экспорт в KMZ",
                message
            )

        log_info(f"KMZ экспорт завершен: {success_count} успешно, {error_count} ошибок")

        return results
