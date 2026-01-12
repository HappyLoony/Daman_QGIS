# -*- coding: utf-8 -*-
"""
Сабмодуль экспорта в DXF (AutoCAD)
Обеспечивает экспорт с поддержкой стилей AutoCAD
"""

import os
from qgis.core import QgsMessageLog, Qgis, QgsProject, QgsCoordinateReferenceSystem
from qgis.PyQt.QtWidgets import QMessageBox, QProgressDialog
from qgis.PyQt.QtCore import Qt

from Daman_QGIS.managers import StyleManager, DataCleanupManager
from Daman_QGIS.constants import PLUGIN_NAME
from Daman_QGIS.utils import log_info, log_warning, log_error
from ..ui.export_dialog import ExportDialog
from ..core.dxf_exporter import DxfExporter


class DxfExportSubmodule:
    """Сабмодуль для экспорта в DXF формат"""
    
    def __init__(self, iface):
        """
        Инициализация сабмодуля

        Args:
            iface: Интерфейс QGIS
        """
        self.iface = iface
        self.data_cleanup_manager = DataCleanupManager()

        # Параметры по умолчанию
        self.default_params = {
            'width': 1.0,  # Глобальная ширина линий в мм
            'create_wgs84': True,  # Создавать версию в WGS-84
            'show_dialog': True,  # Показывать диалог выбора
            'output_folder': None,  # Папка для экспорта
            'layers': None,  # Список слоев (если не показываем диалог)
        }
    def export(self, **params):
        """
        Экспорт в DXF с возможностью переопределения параметров

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
            dialog = ExportDialog(self.iface.mainWindow(), "DXF")

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
                log_warning("DXF экспорт: не указаны слои или папка")
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
                "Экспорт в DXF...",
                "Отмена",
                0,
                100,
                self.iface.mainWindow()
            )
            progress.setWindowModality(Qt.WindowModal)
            progress.setAutoClose(True)
            progress.show()

        # Создаем менеджер стилей
        style_manager = StyleManager()

        # Создаем экспортер с style_manager
        exporter = DxfExporter(self.iface, style_manager)

        # Подключаем сигналы прогресса если есть диалог
        if progress:
            exporter.progress.connect(progress.setValue)
            exporter.message.connect(lambda msg: progress.setLabelText(msg))

        # Получаем СК проекта
        project_crs = QgsProject.instance().crs()

        # Результаты
        results = {}
        success_count = 0
        error_count = 0

        # Экспортируем каждый слой
        for idx, layer in enumerate(layers):
            if progress and progress.wasCanceled():
                break

            # Обновляем прогресс
            if progress:
                progress_value = int((idx + 1) * 100 / len(layers))
                progress.setValue(progress_value)
                progress.setLabelText(f"Экспорт слоя: {layer.name()}")

            # Формируем имя файла
            # КРИТИЧНО: 2025-10-28 - Добавлена очистка имени через sanitize_filename()
            # Раньше имя слоя использовалось БЕЗ ОЧИСТКИ, что могло вызывать ошибки Windows
            # при наличии запрещённых символов в имени слоя (например : / \ < > | ? *)
            layer_name = layer.name()
            if layer_name.startswith('1_1_1_Границы_работ'):
                # Для границ работ используем фиксированное имя (уже безопасное)
                filename = 'Границы_работ.dxf'
            else:
                # DEPRECATED: filename = f"{layer_name}.dxf"  # БЕЗ ОЧИСТКИ - опасно!
                safe_layer_name = self.data_cleanup_manager.sanitize_filename(layer_name)
                filename = f"{safe_layer_name}.dxf"

            filepath = os.path.join(output_folder, filename)

            # Экспортируем в СК проекта
            success = exporter.export_layers(
                layers=[layer],
                target_crs=project_crs,
                output_path=filepath,
                export_settings={'width': export_params['width']}
            )

            results[layer.name()] = success

            if success:
                success_count += 1

                # Экспортируем в WGS-84 если нужно
                if export_params['create_wgs84']:
                    wgs84_crs = QgsCoordinateReferenceSystem("EPSG:4326")

                    wgs84_filename = filename.replace('.dxf', '_WGS84.dxf')
                    wgs84_filepath = os.path.join(output_folder, wgs84_filename)

                    exporter.export_layers(
                        layers=[layer],
                        target_crs=wgs84_crs,
                        output_path=wgs84_filepath,
                        export_settings={'width': 0}  # Без глобальной ширины для WGS
                    )
            else:
                error_count += 1

        if progress:
            progress.close()

        # Показываем результат если был диалог
        if export_params['show_dialog']:
            message = f"Экспорт завершен!\n"
            message += f"Успешно экспортировано: {success_count} слоев\n"
            if error_count > 0:
                message += f"Ошибок: {error_count} слоев\n"
            message += f"\nФайлы сохранены в:\n{output_folder}"

            QMessageBox.information(
                self.iface.mainWindow(),
                "Экспорт в DXF",
                message
            )

        log_info(f"DXF экспорт завершен: {success_count} успешно, {error_count} ошибок")

        return results
