# -*- coding: utf-8 -*-
"""
Экспортер в формат KML с поддержкой стилей
"""

import os
from typing import List, Dict, Any

from qgis.core import (
    QgsVectorLayer, QgsProject, QgsVectorFileWriter,
    QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsMessageLog, Qgis
)

from .base_exporter import BaseExporter
from Daman_QGIS.constants import PLUGIN_NAME
from Daman_QGIS.utils import log_info, log_warning, log_error


class KMLExporter(BaseExporter):
    """Экспортер в формат KML"""
    
    def __init__(self, iface=None):
        """Инициализация экспортера KML"""
        super().__init__(iface)
        
        # Дополнительные параметры для KML
        self.default_params.update({
            'altitude_mode': 'clampToGround',  # Режим высоты
            'export_labels': True,  # Экспортировать подписи
            'export_description': True,  # Экспортировать описания
        })
    
    def export_layers(self, 
                     layers: List[QgsVectorLayer],
                     output_folder: str,
                     **params) -> Dict[str, bool]:
        """
        Экспорт слоев в KML файлы
        
        Args:
            layers: Список слоев для экспорта
            output_folder: Папка назначения
            **params: Параметры экспорта
            
        Returns:
            Словарь {layer_name: success}
        """
        # Объединяем параметры
        export_params = self.merge_params(**params)
        
        # Сохраняем последнюю папку
        self.set_last_export_folder(output_folder)
        
        results = {}
        total_layers = len(layers)
        
        for idx, layer in enumerate(layers):
            if not isinstance(layer, QgsVectorLayer):
                results[layer.name()] = False
                continue
            
            # Прогресс
            progress = int((idx + 1) * 100 / total_layers)
            self.progress.emit(progress)
            
            # Экспортируем слой
            success = self._export_layer(layer, output_folder, export_params)
            results[layer.name()] = success
            
            if success:
                self.message.emit(f"Экспортирован: {layer.name()}")
            else:
                self.message.emit(f"Ошибка экспорта: {layer.name()}")
        
        return results
    def _export_layer(self,
                     layer: QgsVectorLayer,
                     output_folder: str,
                     params: Dict[str, Any]) -> bool:
        """
        Экспорт одного слоя в KML

        Args:
            layer: Слой для экспорта
            output_folder: Папка назначения
            params: Параметры экспорта

        Returns:
            True если успешно
        """
        # Форматируем имя файла
        filename = self.format_filename(
            layer,
            params.get('filename_pattern') or None
        )

        # KML всегда в WGS-84
        wgs84_crs = QgsCoordinateReferenceSystem("EPSG:4326")

        # Экспортируем в KML
        kml_path = os.path.join(output_folder, f"{filename}.kml")
        success = self._export_to_kml(
            layer,
            kml_path,
            wgs84_crs,
            params
        )

        return success
    def _export_to_kml(self,
                       layer: QgsVectorLayer,
                       output_path: str,
                       target_crs: QgsCoordinateReferenceSystem,
                       params: Dict[str, Any]) -> bool:
        """
        Экспорт в KML

        Args:
            layer: Слой для экспорта
            output_path: Путь к выходному KML файлу
            target_crs: Целевая СК (должна быть WGS-84)
            params: Параметры экспорта

        Returns:
            True если успешно
        """
        # Нормализуем путь
        output_path = os.path.normpath(output_path)

        log_info(
            f"Начинаем экспорт в KML: {output_path}"
        )

        # Настройки экспорта
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "KML"
        options.fileEncoding = "UTF-8"

        # Настройки KML
        datasource_options = []

        # Режим высоты
        altitude_mode = params.get('altitude_mode', 'clampToGround')
        datasource_options.append(f"ALTITUDE_MODE={altitude_mode}")

        # Имя документа
        datasource_options.append(f"NAME_FIELD=NAME")

        # Описание
        if params.get('export_description', True):
            datasource_options.append("DESCRIPTION_FIELD=DESCRIPTION")

        options.datasourceOptions = datasource_options

        # Трансформация в WGS-84 (обязательно для KML)
        if layer.crs() != target_crs:
            transform = QgsCoordinateTransform(
                layer.crs(),
                target_crs,
                QgsProject.instance()
            )
            options.ct = transform

        # Экспортируем с сохранением символики
        options.symbologyExport = QgsVectorFileWriter.FeatureSymbology

        # Экспортируем
        error = QgsVectorFileWriter.writeAsVectorFormatV3(
            layer,
            output_path,
            QgsProject.instance().transformContext(),
            options
        )

        if error[0] != QgsVectorFileWriter.NoError:
            raise RuntimeError(f"Ошибка экспорта в KML: {error[1]}")

        # Постобработка KML для улучшения стилей
        self._enhance_kml_styles(layer, output_path)

        log_info(
            f"KML файл создан: {output_path}"
        )

        return True
    def _enhance_kml_styles(self, layer: QgsVectorLayer, kml_path: str) -> bool:
        """
        Улучшение стилей в KML файле

        Args:
            layer: Слой с стилями
            kml_path: Путь к KML файлу

        Returns:
            True если успешно
        """
        # Получаем рендерер слоя
        renderer = layer.renderer()
        if not renderer:
            return True

        # Получаем символ
        symbol = renderer.symbol() if hasattr(renderer, 'symbol') else None

        if symbol:
            # Читаем KML файл
            with open(kml_path, 'r', encoding='utf-8') as f:
                kml_content = f.read()

            # Получаем цвета из символа
            color = symbol.color()
            if color:
                # KML использует формат AABBGGRR (альфа, синий, зеленый, красный)
                kml_color = f"{color.alpha():02x}{color.blue():02x}{color.green():02x}{color.red():02x}"

                # Заменяем стандартные стили если они есть
                if '<Style>' in kml_content:
                    # Обновляем цвет заливки
                    if '<PolyStyle>' in kml_content:
                        kml_content = kml_content.replace(
                            '<PolyStyle>',
                            f'<PolyStyle><color>{kml_color}</color>'
                        )

                    # Обновляем цвет линии
                    if '<LineStyle>' in kml_content and hasattr(symbol, 'symbolLayer'):
                        symbol_layer = symbol.symbolLayer(0)
                        if hasattr(symbol_layer, 'strokeColor'):
                            stroke_color = symbol_layer.strokeColor()
                            kml_stroke = f"{stroke_color.alpha():02x}{stroke_color.blue():02x}{stroke_color.green():02x}{stroke_color.red():02x}"

                            # Толщина линии
                            width = 1.0
                            if hasattr(symbol_layer, 'strokeWidth'):
                                width = symbol_layer.strokeWidth()

                            kml_content = kml_content.replace(
                                '<LineStyle>',
                                f'<LineStyle><color>{kml_stroke}</color><width>{width}</width>'
                            )

            # Сохраняем обратно
            with open(kml_path, 'w', encoding='utf-8') as f:
                f.write(kml_content)

        return True
