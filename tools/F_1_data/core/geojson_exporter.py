# -*- coding: utf-8 -*-
"""
Экспортер в формат GeoJSON (всегда в WGS-84)
"""

import os
import json
from typing import List, Dict, Any

from qgis.core import (
    QgsVectorLayer, QgsProject, QgsVectorFileWriter,
    QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsMessageLog, Qgis, QgsFeature
)

from .base_exporter import BaseExporter

from Daman_QGIS.constants import PLUGIN_NAME
from Daman_QGIS.utils import log_info, log_warning, log_error


class GeoJSONExporter(BaseExporter):
    """Экспортер в формат GeoJSON (всегда WGS-84)"""
    
    def __init__(self, iface=None):
        """Инициализация экспортера GeoJSON"""
        super().__init__(iface)
        
        # Дополнительные параметры для GeoJSON
        self.default_params.update({
            'include_style': True,  # Включать ли стили в properties
            'precision': 8,  # Точность координат (знаков после запятой)
        })
        
        # GeoJSON всегда в WGS-84 по спецификации
        self.target_crs = QgsCoordinateReferenceSystem("EPSG:4326")
    
    def export_layers(self, 
                     layers: List[QgsVectorLayer],
                     output_folder: str,
                     **params) -> Dict[str, bool]:
        """
        Экспорт слоев в GeoJSON файлы (WGS-84)
        
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
        Экспорт одного слоя в GeoJSON (WGS-84)

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

        # Экспортируем в WGS-84 (GeoJSON всегда в WGS-84)
        geojson_path = os.path.join(output_folder, f"{filename}.geojson")
        success = self._export_to_geojson(
            layer,
            geojson_path,
            params
        )

        return success
    def _export_to_geojson(self,
                          layer: QgsVectorLayer,
                          output_path: str,
                          params: Dict[str, Any]) -> bool:
        """
        Экспорт в GeoJSON (WGS-84)

        Args:
            layer: Слой для экспорта
            output_path: Путь к выходному GeoJSON файлу
            params: Параметры экспорта

        Returns:
            True если успешно
        """
        # Нормализуем путь
        output_path = os.path.normpath(output_path)

        log_info(
            f"Начинаем экспорт в GeoJSON (WGS-84): {output_path}"
        )

        # Настройки экспорта
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GeoJSON"
        options.fileEncoding = "UTF-8"  # Для поддержки кириллицы

        # Настройка точности координат
        precision = params.get('precision', 8)
        options.datasourceOptions = [f"COORDINATE_PRECISION={precision}"]

        # Всегда трансформируем в WGS-84
        if layer.crs() != self.target_crs:
            transform = QgsCoordinateTransform(
                layer.crs(),
                self.target_crs,
                QgsProject.instance()
            )
            options.ct = transform

        # Экспортируем
        error = QgsVectorFileWriter.writeAsVectorFormatV3(
            layer,
            output_path,
            QgsProject.instance().transformContext(),
            options
        )

        if error[0] != QgsVectorFileWriter.NoError:
            raise RuntimeError(f"Ошибка экспорта в GeoJSON: {error[1]}")

        # Добавляем стили если нужно
        if params.get('include_style', True):
            self._add_style_properties(layer, output_path)

        log_info(
            f"GeoJSON файл создан (WGS-84): {output_path}"
        )

        return True
    
    def _add_style_properties(self, layer: QgsVectorLayer, geojson_path: str) -> bool:
        """
        Добавление базовых стилей в properties GeoJSON
        
        Args:
            layer: Слой со стилями
            geojson_path: Путь к GeoJSON файлу
            
        Returns:
            True если успешно
        """
        try:
            # Получаем рендерер слоя
            renderer = layer.renderer()
            if not renderer:
                return True
            
            # Читаем существующий GeoJSON
            with open(geojson_path, 'r', encoding='utf-8') as f:
                geojson_data = json.load(f)
            
            # Получаем символ
            symbol = renderer.symbol() if hasattr(renderer, 'symbol') else None
            
            if symbol:
                # Получаем базовые свойства стиля
                style_props = {}
                
                # Цвет
                color = symbol.color()
                if color:
                    style_props['fill'] = color.name()
                    style_props['fill-opacity'] = color.alphaF()
                
                # Обводка
                if hasattr(symbol, 'symbolLayer') and symbol.symbolLayer(0):
                    symbol_layer = symbol.symbolLayer(0)
                    
                    # Цвет обводки
                    if hasattr(symbol_layer, 'strokeColor'):
                        stroke_color = symbol_layer.strokeColor()
                        style_props['stroke'] = stroke_color.name()
                        style_props['stroke-opacity'] = stroke_color.alphaF()
                    
                    # Толщина линии
                    if hasattr(symbol_layer, 'strokeWidth'):
                        style_props['stroke-width'] = symbol_layer.strokeWidth()
                
                # Добавляем стили ко всем features
                if 'features' in geojson_data and style_props:
                    for feature in geojson_data['features']:
                        if 'properties' not in feature:
                            feature['properties'] = {}
                        feature['properties'].update(style_props)
            
            # Сохраняем обратно
            with open(geojson_path, 'w', encoding='utf-8') as f:
                json.dump(geojson_data, f, ensure_ascii=False, indent=2)
            
            return True

        except Exception as e:
            log_warning(
                f"Не удалось добавить стили в GeoJSON: {str(e)}"
            )
            # Не критичная ошибка - файл уже создан
            return True
