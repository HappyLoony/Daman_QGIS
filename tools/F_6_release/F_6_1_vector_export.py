# -*- coding: utf-8 -*-
"""
Инструмент 6_1: Экспорт векторных слоев в TAB с MapInfo стилями

Назначение:
    Сохранение кода конвертации MapInfo стилей перед рефакторингом системы стилей.
    В будущем apply_mapinfo_style() из style_manager.py будет переработан для AutoCAD,
    а MapInfo стили останутся только для экспорта TAB.

Описание:
    Экспорт векторных слоев в формат MapInfo TAB со стилями из Base_layers.json.
    Использует транслятор MapInfo стилей (Fsm_6_1_1_mapinfo_translator) для конвертации
    стилей из базы данных в формат OGR StyleString.
"""

from typing import List, Dict, Any, Optional

from qgis.core import QgsVectorLayer, QgsProject, QgsWkbTypes
from qgis.PyQt.QtWidgets import QMessageBox, QProgressDialog
from qgis.PyQt.QtCore import Qt

from Daman_QGIS.core.base_tool import BaseTool
from Daman_QGIS.tools.F_1_data.ui.export_dialog import ExportDialog
from Daman_QGIS.tools.F_1_data.core.tab_exporter import TabExporter
from .submodules.Fsm_6_1_1_mapinfo_translator import Fsm_6_1_1_MapInfoTranslator
from Daman_QGIS.utils import log_info, log_error, log_warning, log_success


class F_6_1_VectorExport(BaseTool):
    """Экспорт векторных слоев в TAB с MapInfo стилями из Base_layers"""

    @property
    def name(self) -> str:
        """Имя инструмента"""
        return "6_1 Векторные слои"

    @property
    def icon(self) -> str:
        """Иконка инструмента"""
        return "mActionFileSave.svg"

    def run(self) -> None:
        """Запуск экспорта с диалогом выбора слоев"""
        log_info("F_6_1: Запуск экспорта векторных слоев")

        # Создаем диалог выбора слоев (как в F_1_5)
        dialog = ExportDialog(self.iface.mainWindow(), "TAB (MapInfo)")

        if dialog.exec_():
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

            # Экспортируем слои с применением MapInfo стилей
            self._export_layers_with_styles(layers, output_folder, options)

    def _export_layers_with_styles(self,
                                   layers: List[QgsVectorLayer],
                                   output_folder: str,
                                   options: Dict[str, Any]) -> None:
        """
        Экспорт слоев с применением MapInfo стилей

        Args:
            layers: Список слоев для экспорта
            output_folder: Папка назначения
            options: Параметры экспорта из диалога
        """
        log_info(f"F_6_1: Экспорт {len(layers)} слоев в {output_folder}")

        # Создаем экспортер и транслятор
        exporter = TabExporter(self.iface)
        translator = Fsm_6_1_1_MapInfoTranslator()

        # Создаем прогресс-диалог
        progress = QProgressDialog(
            "Экспорт векторных слоев...",
            "Отмена",
            0,
            len(layers),
            self.iface.mainWindow()
        )
        progress.setWindowModality(Qt.WindowModal)
        progress.setAutoClose(True)
        progress.show()

        results = {}
        current = 0

        for layer in layers:
            if progress.wasCanceled():
                log_warning("F_6_1: Экспорт отменен пользователем")
                break

            current += 1
            progress.setValue(current)
            progress.setLabelText(f"Экспорт слоя {layer.name()}...")

            try:
                # Получаем стиль для слоя из Base_layers.json
                mapinfo_style_string = translator.get_style_for_layer(layer.name())

                if not mapinfo_style_string:
                    log_warning(
                        f"F_6_1: Стиль MapInfo не найден для слоя {layer.name()}, "
                        f"экспорт без стиля"
                    )

                # Парсим и конвертируем стиль в OGR StyleString
                ogr_style = None
                if mapinfo_style_string:
                    parsed = translator.parse_mapinfo_style(mapinfo_style_string)
                    if parsed:
                        geom_type = self._get_geometry_type_name(layer)
                        ogr_style = translator.convert_to_ogr_style(parsed, geom_type)
                        log_info(
                            f"F_6_1: Стиль для {layer.name()}: {mapinfo_style_string} -> {ogr_style}"
                        )

                # Экспортируем через TabExporter
                # TabExporter автоматически применит стиль через SetStyleString()
                export_results = exporter.export_layers(
                    [layer],
                    output_folder,
                    **options
                )

                results[layer.name()] = export_results.get(layer.name(), False)

                if results[layer.name()]:
                    log_success(f"F_6_1: Слой {layer.name()} экспортирован успешно")
                else:
                    log_error(f"F_6_1: Ошибка экспорта слоя {layer.name()}")

            except Exception as e:
                log_error(f"F_6_1: Ошибка экспорта слоя {layer.name()}: {str(e)}")
                results[layer.name()] = False

        progress.close()

        # Показываем результаты
        self._show_results(results, output_folder)

    def _get_geometry_type_name(self, layer: QgsVectorLayer) -> str:
        """
        Получить имя типа геометрии для конвертации стиля

        Args:
            layer: Векторный слой

        Returns:
            Имя типа ('Point', 'LineString', 'Polygon', 'Unknown')
        """
        geom_type = layer.geometryType()

        if geom_type == 0:  # QgsWkbTypes.PointGeometry
            return 'Point'
        elif geom_type == 1:  # QgsWkbTypes.LineGeometry
            return 'LineString'
        elif geom_type == 2:  # QgsWkbTypes.PolygonGeometry
            return 'Polygon'
        else:
            return 'Unknown'

    def _show_results(self, results: Dict[str, bool], output_folder: str) -> None:
        """
        Показать результаты экспорта в диалоге

        Args:
            results: Словарь {layer_name: success}
            output_folder: Папка сохранения
        """
        success_count = sum(1 for success in results.values() if success)
        error_count = len(results) - success_count

        message = "Экспорт векторных слоев завершен!\n\n"
        message += f"Успешно: {success_count}\n"

        if error_count > 0:
            message += f"Ошибок: {error_count}\n\n"
            message += "Слои с ошибками:\n"
            for layer_name, success in results.items():
                if not success:
                    message += f"  • {layer_name}\n"
            message += "\n"

        message += f"Файлы сохранены в:\n{output_folder}"

        if error_count > 0:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Экспорт векторных слоев",
                message
            )
        else:
            QMessageBox.information(
                self.iface.mainWindow(),
                "Экспорт векторных слоев",
                message
            )

        log_info(f"F_6_1: Экспорт завершен: {success_count} успешно, {error_count} ошибок")
