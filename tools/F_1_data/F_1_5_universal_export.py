# -*- coding: utf-8 -*-
"""
Инструмент 1_5: Универсальный экспорт (пакетный)
Главный контроллер экспорта во все форматы используя сабмодули
"""

import os
from typing import Dict, Any, List, Optional

from qgis.core import Qgis, QgsProject, QgsVectorLayer
from qgis.PyQt.QtWidgets import QMessageBox, QProgressDialog, QCheckBox
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon

from Daman_QGIS.core.base_tool import BaseTool
from Daman_QGIS.constants import PLUGIN_NAME
from Daman_QGIS.utils import log_info, log_warning, log_error
from .ui.export_dialog import ExportDialog

# Импортируем все сабмодули с новыми именами
# Примечание: ExcelExportSubmodule и ExcelListExportSubmodule перенесены в F_6_3
from .submodules import (
    DxfExportSubmodule,
    GeoJSONExportSubmodule,
    KMLExportSubmodule,
    KMZExportSubmodule,
    ShapefileExportSubmodule,
    TabExportSubmodule,
    ExcelTableExportSubmodule
)


class F_1_5_UniversalExport(BaseTool):
    """Инструмент универсального экспорта во все форматы"""
    
    # Маппинг форматов на сабмодули
    # Примечание: excel и excel_list перенесены в F_6_3 (экспорт по шаблону)
    FORMAT_MODULES = {
        'dxf': DxfExportSubmodule,
        'geojson': GeoJSONExportSubmodule,
        'kml': KMLExportSubmodule,
        'kmz': KMZExportSubmodule,
        'shapefile': ShapefileExportSubmodule,
        'tab': TabExportSubmodule,
        'excel_table': ExcelTableExportSubmodule
    }

    # Имена форматов для отображения
    FORMAT_NAMES = {
        'dxf': 'DXF (AutoCAD)',
        'geojson': 'GeoJSON',
        'kml': 'KML (Google Earth)',
        'kmz': 'KMZ (сжатый KML)',
        'shapefile': 'Shapefile (ESRI)',
        'tab': 'TAB (MapInfo)',
        'excel_table': 'Excel (таблица атрибутов)'
    }
    
    @property
    def name(self) -> str:
        """Имя инструмента"""
        return "1_5_Экспорт"

    def get_name(self) -> str:
        """Получить полное имя инструмента"""
        return "F_1_5_Экспорт"

    @property
    def icon(self) -> str:
        """Иконка инструмента"""
        return "mActionFileSaveAs.svg"
    
    def create_dialog(self) -> None:
        """Создание диалога не требуется - используем модифицированный ExportDialog"""
        return None

    def run(self) -> None:
        """Запуск инструмента для пакетного экспорта"""
        self.export_batch()
    
    def export_single_format(self, format_name: str) -> None:
        """
        Экспорт в один конкретный формат

        Args:
            format_name: Имя формата ('dxf', 'excel', 'geojson', 'kml', 'kmz', 'shapefile', 'tab')
        """
        format_lower = format_name.lower()
        
        # Проверяем существование формата
        if format_lower not in self.FORMAT_MODULES:
            QMessageBox.critical(
                self.iface.mainWindow(),
                "Ошибка",
                f"Неизвестный формат экспорта: {format_name}"
            )
            return
        
        # Создаем соответствующий сабмодуль
        submodule_class = self.FORMAT_MODULES[format_lower]
        submodule = submodule_class(self.iface)
        
        # Запускаем экспорт с диалогом
        submodule.export(show_dialog=True)
    def export_batch(self) -> None:
        """Пакетный экспорт во множество форматов"""
        # Создаем диалог выбора слоев
        dialog = ExportDialog(self.iface.mainWindow(), "Batch (все форматы)")

        # Добавляем чекбоксы для выбора форматов
        self._add_format_checkboxes(dialog)

        if dialog.exec_():
            # Получаем выбранные слои и папку
            layers = dialog.selected_layers
            output_folder = dialog.output_folder
            options = dialog.get_export_options()

            if not layers:
                QMessageBox.warning(
                    self.iface.mainWindow(),
                    "Предупреждение",
                    "Не выбрано ни одного слоя для экспорта"
                )
                return

            # Собираем выбранные форматы
            selected_formats = {}
            for format_key in self.FORMAT_MODULES:
                checkbox_name = f'{format_key}_check'
                if hasattr(dialog, checkbox_name) and getattr(dialog, checkbox_name).isChecked():
                    # Сохраняем format_key для идентификации
                    format_folder_name = self.FORMAT_NAMES[format_key].split(' ')[0]
                    selected_formats[format_folder_name] = (format_key, self.FORMAT_MODULES[format_key](self.iface))

            if not selected_formats:
                QMessageBox.warning(
                    self.iface.mainWindow(),
                    "Предупреждение",
                    "Не выбран ни один формат для экспорта"
                )
                return

            # Создаем подпапки для каждого формата
            folders = {}
            for format_name in selected_formats.keys():
                folder_path = os.path.join(output_folder, format_name)
                os.makedirs(folder_path, exist_ok=True)
                folders[format_name] = folder_path

            # Создаем прогресс-диалог
            total_operations = len(layers) * len(selected_formats)
            progress = QProgressDialog(
                "Универсальный экспорт...",
                "Отмена",
                0,
                total_operations,
                self.iface.mainWindow()
            )
            progress.setWindowModality(Qt.WindowModal)
            progress.setAutoClose(True)
            progress.show()

            # Результаты экспорта
            results = {format_name: {} for format_name in selected_formats.keys()}
            current_operation = 0

            # Экспортируем в каждый формат
            for format_name, (format_key, submodule) in selected_formats.items():
                if progress.wasCanceled():
                    break

                progress.setLabelText(f"Экспорт в {format_name}...")

                # Специальная обработка для Excel (один слой за раз)
                if format_key == 'excel_table':
                    for layer in layers:
                        if progress.wasCanceled():
                            break

                        current_operation += 1
                        progress.setValue(current_operation)

                        # excel_table не поддерживает create_wgs84
                        export_params = {
                            'layer': layer,
                            'output_folder': folders[format_name],
                            'show_dialog': False,
                            'show_progress': False
                        }

                        layer_results = submodule.export(**export_params)
                        results[format_name].update(layer_results)
                else:
                    # Для остальных форматов - пакетный экспорт
                    format_results = submodule.export(
                        layers=layers,
                        output_folder=folders[format_name],
                        show_dialog=False,
                        show_progress=False,
                        **self._get_format_params(format_key, options)
                    )
                    results[format_name] = format_results

                    # Обновляем прогресс
                    current_operation += len(layers)
                    progress.setValue(current_operation)

            progress.close()

            # Формируем отчет
            self._show_batch_results(results, output_folder, options)
    
    def _get_format_params(self, format_key: str, base_options: Dict[str, Any]) -> Dict[str, Any]:
        """
        Получить параметры для конкретного формата

        Args:
            format_key: Ключ формата
            base_options: Базовые опции из диалога

        Returns:
            dict: Параметры для формата
        """
        params = base_options.copy()
        
        # Добавляем специфичные параметры для форматов
        if format_key == 'dxf':
            params['width'] = 1.0  # Глобальная ширина линий
        elif format_key == 'tab':
            params['use_non_earth'] = True
            params['clean_temp_files'] = True
        elif format_key == 'geojson':
            params['precision'] = 8
            params['include_style'] = True
        elif format_key == 'shapefile':
            params['encoding'] = 'UTF-8'
            params['export_style'] = True
            params['truncate_fields'] = True

        return params
    
    def _add_format_checkboxes(self, dialog) -> None:
        """Добавление чекбоксов выбора форматов в диалог"""
        from qgis.PyQt.QtWidgets import QGroupBox, QVBoxLayout
        
        # Находим место для вставки (после опций экспорта)
        layout = dialog.layout()
        
        # Создаем группу выбора форматов
        formats_group = QGroupBox("Форматы для экспорта")
        formats_layout = QVBoxLayout()
        
        # Добавляем чекбоксы для форматов
        # Примечание: excel и excel_list перенесены в F_6_3 (экспорт по шаблону)
        dialog.dxf_check = QCheckBox(self.FORMAT_NAMES['dxf'])
        dialog.dxf_check.setChecked(False)
        formats_layout.addWidget(dialog.dxf_check)

        dialog.geojson_check = QCheckBox(f"{self.FORMAT_NAMES['geojson']} (Росреестр, rTIM, Google Earth)")
        dialog.geojson_check.setChecked(False)
        formats_layout.addWidget(dialog.geojson_check)

        dialog.kml_check = QCheckBox(self.FORMAT_NAMES['kml'])
        dialog.kml_check.setChecked(False)
        formats_layout.addWidget(dialog.kml_check)

        dialog.kmz_check = QCheckBox(self.FORMAT_NAMES['kmz'])
        dialog.kmz_check.setChecked(False)
        formats_layout.addWidget(dialog.kmz_check)

        dialog.shapefile_check = QCheckBox(self.FORMAT_NAMES['shapefile'])
        dialog.shapefile_check.setChecked(False)
        formats_layout.addWidget(dialog.shapefile_check)

        dialog.tab_check = QCheckBox(self.FORMAT_NAMES['tab'])
        dialog.tab_check.setChecked(False)
        formats_layout.addWidget(dialog.tab_check)

        dialog.excel_table_check = QCheckBox(self.FORMAT_NAMES['excel_table'])
        dialog.excel_table_check.setChecked(False)
        formats_layout.addWidget(dialog.excel_table_check)
        
        formats_group.setLayout(formats_layout)
        
        # Вставляем перед информационным лейблом
        layout.insertWidget(layout.count() - 2, formats_group)
    
    def _show_batch_results(self, results: Dict[str, Dict[str, bool]], output_folder: str, options: Dict[str, Any]) -> None:
        """
        Показать результаты пакетного экспорта

        Args:
            results: Словарь результатов {format: {layer: success}}
            output_folder: Папка экспорта
            options: Опции экспорта
        """
        message = "Универсальный экспорт завершен!\n\n"

        # Показываем результаты в порядке сабмодулей
        # Примечание: Excel (координаты) и Excel (ведомости) перенесены в F_6_3
        format_order = ['DXF', 'GeoJSON', 'KML', 'KMZ', 'Shapefile', 'TAB', 'Excel']

        for format_name in format_order:
            if format_name in results:
                format_results = results[format_name]
                if format_results:
                    success_count = sum(1 for success in format_results.values() if success)
                    error_count = len(format_results) - success_count

                    message += f"{format_name}: {success_count} успешно"
                    if error_count > 0:
                        message += f", {error_count} ошибок"
                    message += "\n"

        message += f"\nФайлы сохранены в:\n{output_folder}"

        if options.get('create_wgs84', True):
            message += "\n\nДля поддерживающих форматов созданы файлы в двух СК:"
            message += "\n• Основные - в СК проекта"
            message += "\n• С суффиксом _WGS84 - в WGS-84"

        # Создаем диалог с кнопкой открытия папки
        msg_box = QMessageBox(self.iface.mainWindow())
        msg_box.setWindowTitle("Универсальный экспорт")
        msg_box.setText(message)
        msg_box.setIcon(QMessageBox.Information)

        # Добавляем кнопки
        open_btn = msg_box.addButton("Открыть расположение", QMessageBox.ActionRole)
        msg_box.addButton("Закрыть", QMessageBox.RejectRole)

        msg_box.exec_()

        # Обработка нажатия кнопки
        if msg_box.clickedButton() == open_btn:
            self._open_folder(output_folder)

        log_info("F_1_5: Универсальный экспорт завершен")

    def _open_folder(self, folder_path: str) -> None:
        """
        Открыть папку в проводнике

        Args:
            folder_path: Путь к папке
        """
        import subprocess

        if folder_path and os.path.exists(folder_path):
            # Windows
            if os.name == 'nt':
                os.startfile(folder_path)
            # macOS
            elif os.sys.platform == 'darwin':
                subprocess.run(['open', folder_path])
            # Linux
            else:
                subprocess.run(['xdg-open', folder_path])
