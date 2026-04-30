# -*- coding: utf-8 -*-
"""
Сабмодуль экспорта таблицы атрибутов в Excel
Экспортирует таблицу атрибутов слоев "как есть" со всеми полями
"""

import os
from typing import List, Dict, Any
from qgis.core import (
    QgsMessageLog, Qgis, QgsProject, QgsVectorLayer,
    QgsFeature
)
from qgis.PyQt.QtWidgets import QMessageBox, QProgressDialog
from qgis.PyQt.QtCore import Qt

from Daman_QGIS.constants import PLUGIN_NAME
from Daman_QGIS.managers import DataCleanupManager
from Daman_QGIS.utils import log_info, log_warning, log_error, path_for_display
from Daman_QGIS.managers import AttributeProcessor
from Daman_QGIS.managers import (
    registry, FolderType
)


class ExcelTableExportSubmodule:
    """Сабмодуль для экспорта таблицы атрибутов в Excel"""
    
    def __init__(self, iface):
        """
        Инициализация сабмодуля

        Args:
            iface: Интерфейс QGIS
        """
        self.iface = iface
        self.attribute_processor = AttributeProcessor()
        self.data_cleanup_manager = DataCleanupManager()
        
    def export(self, **params):
        """
        Экспорт таблицы атрибутов в Excel
        
        Args:
            **params: Параметры экспорта:
                - layer: слой для экспорта (если один)
                - layers: список слоев (для пакетного экспорта)
                - show_dialog: показывать ли диалог выбора
                - output_folder: папка для сохранения (опционально)
                - show_progress: показывать ли прогресс-диалог
            
        Returns:
            dict: Результаты экспорта {layer_name: success}
        """
        # Проверяем наличие xlsxwriter
        try:
            import xlsxwriter
        except RuntimeError:
            if params.get('show_dialog', True):
                QMessageBox.critical(
                    self.iface.mainWindow(),
                    "Ошибка",
                    "Библиотека xlsxwriter не установлена!\n\n"
                    "Для установки используйте инструмент:\n"
                    "5_1 Проверка зависимостей"
                )
            log_error("Fsm_1_5_9: Библиотека xlsxwriter не установлена")
            return {}
            
        # Получаем слои для экспорта
        if params.get('show_dialog', True):
            layers = self._show_dialog()
            if not layers:
                return {}
        else:
            # Используем переданные параметры
            if 'layer' in params:
                layers = [params['layer']]
            elif 'layers' in params:
                layers = params['layers']
            else:
                return {}
                
        # Папка для сохранения
        if params.get('output_folder'):
            output_folder = params['output_folder']
        else:
            project_path = os.path.normpath(QgsProject.instance().homePath())
            if not project_path:
                QMessageBox.critical(
                    self.iface.mainWindow(),
                    "Ошибка",
                    "Сначала сохраните проект QGIS"
                )
                return {}
            structure_manager = registry.get('M_19')
            structure_manager.project_root = project_path
            output_folder = structure_manager.get_folder(FolderType.TABLES, create=True)
            
        os.makedirs(output_folder, exist_ok=True)
        
        # Результаты экспорта
        results = {}
        
        # Создаем прогресс-диалог
        if params.get('show_progress', True):
            progress = QProgressDialog(
                "Экспорт таблиц атрибутов...",
                "Отмена",
                0,
                len(layers),
                self.iface.mainWindow()
            )
            progress.setWindowModality(Qt.WindowModality.WindowModal)
            progress.setAutoClose(True)
            progress.show()
        else:
            progress = None
            
        # Экспортируем каждый слой
        for idx, layer in enumerate(layers):
            if progress:
                if progress.wasCanceled():
                    break
                progress.setValue(idx)
                progress.setLabelText(f"Экспорт: {layer.name()}")
                
            if not isinstance(layer, QgsVectorLayer):
                results[layer.name()] = False
                continue
                
            # Экспортируем слой
            success = self._export_layer(layer, output_folder)
            results[layer.name()] = success
            
        if progress:
            progress.close()
            
        # Показываем результаты
        if params.get('show_dialog', True):
            self._show_results(results, output_folder)
            
        return results
        
    def _show_dialog(self):
        """Показать диалог выбора слоев"""
        from qgis.PyQt.QtWidgets import QDialog, QVBoxLayout, QListWidget, QListWidgetItem, QDialogButtonBox, QLabel
        
        dialog = QDialog(self.iface.mainWindow())
        dialog.setWindowTitle("Экспорт таблиц атрибутов в Excel")
        dialog.setMinimumWidth(400)
        
        layout = QVBoxLayout()
        
        # Информация
        info_label = QLabel("Выберите слои для экспорта таблицы атрибутов:")
        layout.addWidget(info_label)
        
        # Список слоев
        list_widget = QListWidget()
        
        # Добавляем все векторные слои с атрибутами
        for layer in QgsProject.instance().mapLayers().values():
            if isinstance(layer, QgsVectorLayer) and layer.featureCount() > 0:
                item = QListWidgetItem(layer.name())
                item.setData(Qt.ItemDataRole.UserRole, layer)
                item.setCheckState(Qt.CheckState.Unchecked)
                list_widget.addItem(item)
                
        list_widget.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        layout.addWidget(list_widget)
        
        # Кнопки
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        
        dialog.setLayout(layout)
        
        if dialog.exec():
            # Собираем выбранные слои
            selected_layers = []
            for i in range(list_widget.count()):
                item = list_widget.item(i)
                if item.checkState() == Qt.CheckState.Checked:
                    layer = item.data(Qt.ItemDataRole.UserRole)
                    selected_layers.append(layer)
            return selected_layers
        
        return []
        
    def _export_layer(self, layer: QgsVectorLayer, output_folder: str) -> bool:
        """
        Экспорт одного слоя в Excel

        Args:
            layer: Слой для экспорта
            output_folder: Папка для сохранения

        Returns:
            bool: Успешность экспорта
        """
        import xlsxwriter

        # Формируем имя файла
        safe_name = self.data_cleanup_manager.sanitize_filename(layer.name())
        filename = f"{safe_name}.xlsx"
        filepath = os.path.join(output_folder, filename)

        # Создаем Excel файл
        workbook = xlsxwriter.Workbook(filepath)
        worksheet = workbook.add_worksheet('Атрибуты')

        # Форматы
        header_format = workbook.add_format({
            'font_name': 'Times New Roman',
            'font_size': 11,
            'bold': True,
            'align': 'center',
            'valign': 'vcenter',
            'border': 1,
            'text_wrap': True,
            'bg_color': '#D9D9D9'
        })

        data_format = workbook.add_format({
            'font_name': 'Times New Roman',
            'font_size': 11,
            'align': 'center',
            'valign': 'vcenter',
            'border': 1,
            'text_wrap': True
        })

        number_format = workbook.add_format({
            'font_name': 'Times New Roman',
            'font_size': 11,
            'align': 'center',
            'valign': 'vcenter',
            'border': 1,
            'num_format': '#,##0'
        })

        current_row = 0

        # Получаем поля слоя
        fields = layer.fields()
        field_names = [field.name() for field in fields]

        # Заголовки колонок (оригинальные названия полей)
        for col_idx, field_name in enumerate(field_names):
            worksheet.write(current_row, col_idx, field_name, header_format)

        worksheet.set_row(current_row, 30)  # Высота строки заголовков
        current_row += 1

        # Данные
        for feature in layer.getFeatures():
            for col_idx, field in enumerate(fields):
                value = feature.attribute(field.name())

                # Обрабатываем NULL значения через процессор таблиц
                processed_value = self.attribute_processor.normalize_null_value(value, field.name())

                # Форматируем значение
                if value is not None and isinstance(value, (int, float)):
                    worksheet.write(current_row, col_idx, value, number_format)
                else:
                    worksheet.write(current_row, col_idx, processed_value, data_format)

            current_row += 1

        # Автоподбор ширины колонок
        for col_idx, field_name in enumerate(field_names):
            # Базовая ширина на основе названия поля
            width = max(15, len(field_name) * 1.2)

            # Ограничиваем максимальную ширину
            if width > 50:
                width = 50

            worksheet.set_column(col_idx, col_idx, width)

        # Закрываем файл
        workbook.close()

        log_info(f"Fsm_1_5_9: Экспорт таблицы атрибутов завершен: {filepath}")
        return True
            
    def _show_results(self, results: Dict[str, bool], output_folder: str):
        """Показать результаты экспорта"""
        success_count = sum(1 for success in results.values() if success)
        error_count = len(results) - success_count
        
        message = f"Экспорт таблиц атрибутов завершен!\n\n"
        message += f"Успешно: {success_count} слоев\n"
        if error_count > 0:
            message += f"Ошибок: {error_count} слоев\n"
        message += f"\nФайлы сохранены в:\n{path_for_display(output_folder)}"
        
        QMessageBox.information(
            self.iface.mainWindow(),
            "Экспорт таблиц атрибутов",
            message
        )
