# -*- coding: utf-8 -*-
"""
Инструмент 6_1: Экспорт векторных слоев в TAB с MapInfo стилями

Назначение:
    Экспорт векторных слоев в формат MapInfo TAB со стилями из Base_layers.json.
    Для DPT_* слоев (регион 78, СПб) применяет региональную схему полей
    по требованиям КГА (Fsm_5_1_2, Fsm_5_1_3).

Описание:
    - Обычные слои: экспорт as-is с MapInfo стилями
    - DPT_* слои (L_4_1_*): создание memory layer с DPT полями,
      копирование геометрии, экспорт с bounds 0,0,200000,200000
"""

import os
from typing import List, Dict, Any, Optional

from qgis.core import QgsVectorLayer, QgsWkbTypes
from qgis.PyQt.QtWidgets import QMessageBox, QProgressDialog
from qgis.PyQt.QtCore import Qt

from Daman_QGIS.core.base_tool import BaseTool
from Daman_QGIS.tools.F_1_data.ui.export_dialog import ExportDialog
from Daman_QGIS.tools.F_1_data.core.tab_exporter import TabExporter
from .submodules.Fsm_5_1_1_mapinfo_translator import Fsm_5_1_1_MapInfoTranslator
from .submodules.Fsm_5_1_3_region78_tab_exporter import Fsm_5_1_3_Region78TabExporter
from Daman_QGIS.utils import log_info, log_error, log_warning, log_success


class F_5_1_VectorExport(BaseTool):
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
        log_info("F_5_1: Запуск экспорта векторных слоев")

        # Создаем диалог выбора слоев (как в F_1_5)
        dialog = ExportDialog(self.iface.mainWindow(), "TAB (MapInfo)")

        if dialog.exec():
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
                                   options: Dict[str, Any],
                                   bounds: Optional[str] = None) -> None:
        """
        Экспорт слоев с применением MapInfo стилей.

        Для DPT_* слоев (регион 78): создает memory layer с DPT полями,
        экспортирует в подпапку с bounds КГА.

        Args:
            layers: Список слоев для экспорта
            output_folder: Папка назначения
            options: Параметры экспорта из диалога
            bounds: Bounds для NonEarth проекции (None = default TabExporter)
        """
        log_info(f"F_5_1: Экспорт {len(layers)} слоев в {output_folder}")

        # Создаем экспортер, транслятор и региональный экспортер
        exporter = TabExporter(self.iface)
        translator = Fsm_5_1_1_MapInfoTranslator()
        region78 = Fsm_5_1_3_Region78TabExporter()

        # Создаем прогресс-диалог
        progress = QProgressDialog(
            "Экспорт векторных слоев...",
            "Отмена",
            0,
            len(layers),
            self.iface.mainWindow()
        )
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setAutoClose(True)
        progress.show()

        results = {}
        current = 0
        dpt_count = 0

        for layer in layers:
            if progress.wasCanceled():
                log_warning("F_5_1: Экспорт отменен пользователем")
                break

            current += 1
            progress.setValue(current)
            progress.setLabelText(f"Экспорт слоя {layer.name()}...")

            try:
                # Определяем эффективные параметры экспорта
                effective_layer = layer
                effective_folder = output_folder
                effective_bounds = bounds
                is_dpt = False

                if region78.is_dpt_layer(layer.name()):
                    mem_layer, dpt_name = region78.prepare_dpt_layer(layer)
                    if mem_layer:
                        effective_layer = mem_layer
                        effective_folder = os.path.join(
                            output_folder,
                            region78.get_output_subfolder()
                        )
                        os.makedirs(effective_folder, exist_ok=True)
                        effective_bounds = region78.get_tab_bounds()
                        is_dpt = True
                        dpt_count += 1
                        log_info(
                            f"F_5_1: DPT экспорт: "
                            f"{layer.name()} -> {dpt_name}"
                        )

                # Получаем стиль для исходного слоя из Base_layers.json
                mapinfo_style_string = translator.get_style_for_layer(
                    layer.name()
                )

                if not mapinfo_style_string and not is_dpt:
                    log_warning(
                        f"F_5_1: Стиль MapInfo не найден для слоя "
                        f"{layer.name()}, экспорт без стиля"
                    )

                # Парсим и конвертируем стиль в OGR StyleString
                if mapinfo_style_string:
                    parsed = translator.parse_mapinfo_style(
                        mapinfo_style_string
                    )
                    if parsed:
                        geom_type = self._get_geometry_type_name(layer)
                        ogr_style = translator.convert_to_ogr_style(
                            parsed, geom_type
                        )
                        log_info(
                            f"F_5_1: Стиль для {layer.name()}: "
                            f"{mapinfo_style_string} -> {ogr_style}"
                        )

                # Экспортируем через TabExporter
                export_options = dict(options)
                if effective_bounds:
                    export_options['bounds'] = effective_bounds
                if is_dpt:
                    export_options['create_wgs84'] = False

                export_results = exporter.export_layers(
                    [effective_layer],
                    effective_folder,
                    **export_options
                )

                result_key = layer.name()
                export_name = effective_layer.name()
                results[result_key] = export_results.get(export_name, False)

                if results[result_key]:
                    log_success(
                        f"F_5_1: Слой {export_name} экспортирован успешно"
                    )
                else:
                    log_error(
                        f"F_5_1: Ошибка экспорта слоя {export_name}"
                    )

            except Exception as e:
                log_error(
                    f"F_5_1: Ошибка экспорта слоя {layer.name()}: {str(e)}"
                )
                results[layer.name()] = False

        progress.close()

        if dpt_count > 0:
            log_info(
                f"F_5_1: DPT слоев экспортировано: {dpt_count} "
                f"(в подпапку '{region78.get_output_subfolder()}')"
            )

        # Показываем результаты
        self._show_results(results, output_folder)

    def _get_geometry_type_name(self, layer: QgsVectorLayer) -> str:
        """
        Получить имя типа геометрии для конвертации стиля

        Args:
            layer: Векторный слой

        Returns:
            Имя типа ('Point', 'LineString', 'Polygon', 'Mixed', 'Unknown')
        """
        from qgis.core import QgsWkbTypes, Qgis

        # Mixed — содержит разные типы геометрий в одном слое
        # Custom property (надёжно) + fallback на wkbType
        if layer.customProperty('daman_mixed_geometry', False):
            return 'Mixed'
        flat_type = QgsWkbTypes.flatType(layer.wkbType())
        if flat_type in (Qgis.WkbType.GeometryCollection, Qgis.WkbType.Unknown):
            return 'Mixed'

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

        log_info(f"F_5_1: Экспорт завершен: {success_count} успешно, {error_count} ошибок")
