# -*- coding: utf-8 -*-
"""
Экспортер в формат Shapefile (всегда в WGS-84) с отдельным экспортом стилей
"""

import os
from typing import List, Dict, Any

from qgis.core import (
    QgsVectorLayer, QgsProject, QgsVectorFileWriter,
    QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsMessageLog, Qgis, QgsField, QgsFields
)

from .base_exporter import BaseExporter
from Daman_QGIS.constants import PLUGIN_NAME
from Daman_QGIS.utils import log_info, log_warning, log_error


class ShapefileExporter(BaseExporter):
    """Экспортер в формат ESRI Shapefile (всегда WGS-84)"""
    
    def __init__(self, iface=None):
        """Инициализация экспортера Shapefile"""
        super().__init__(iface)
        
        # Дополнительные параметры для Shapefile
        self.default_params.update({
            'export_style': True,  # Экспортировать стиль в .qml файл
            'truncate_fields': True,  # Обрезать имена полей до 10 символов
            'encoding': 'UTF-8',  # Кодировка для атрибутов
        })
        
        # Shapefile всегда экспортируется в WGS-84
        self.target_crs = QgsCoordinateReferenceSystem("EPSG:4326")
    
    def export_layers(self, 
                     layers: List[QgsVectorLayer],
                     output_folder: str,
                     **params) -> Dict[str, bool]:
        """
        Экспорт слоев в Shapefile (WGS-84)
        
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
        Экспорт одного слоя в Shapefile (WGS-84)

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

        # Экспортируем в WGS-84 (Shapefile всегда в WGS-84)
        shp_path = os.path.join(output_folder, f"{filename}.shp")
        success = self._export_to_shapefile(
            layer,
            shp_path,
            self.target_crs,  # Всегда WGS-84
            params
        )

        if not success:
            return False

        # Экспортируем стиль если нужно
        if params.get('export_style', True):
            self._export_layer_style(layer, shp_path)

        return success
    def _export_to_shapefile(self,
                            layer: QgsVectorLayer,
                            output_path: str,
                            target_crs: QgsCoordinateReferenceSystem,
                            params: Dict[str, Any]) -> bool:
        """
        Экспорт в Shapefile (WGS-84)

        Args:
            layer: Слой для экспорта
            output_path: Путь к выходному Shapefile
            target_crs: Целевая СК (всегда WGS-84)
            params: Параметры экспорта

        Returns:
            True если успешно
        """
        # Нормализуем путь
        output_path = os.path.normpath(output_path)

        log_info(
            f"Начинаем экспорт в Shapefile (WGS-84): {output_path}"
        )

        # Настройки экспорта
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "ESRI Shapefile"
        options.fileEncoding = params.get('encoding', 'UTF-8')

        # Обработка полей (Shapefile ограничивает имена до 10 символов)
        if params.get('truncate_fields', True):
            options.attributes = []
            truncated_fields = QgsFields()
            field_mapping = {}

            for field in layer.fields():
                original_name = field.name()
                # Обрезаем до 10 символов
                truncated_name = original_name[:10]

                # Проверяем уникальность
                counter = 1
                temp_name = truncated_name
                while temp_name in field_mapping.values():
                    # Если имя уже есть, добавляем цифру
                    suffix = str(counter)
                    temp_name = truncated_name[:(10-len(suffix))] + suffix
                    counter += 1

                truncated_name = temp_name
                field_mapping[original_name] = truncated_name

                # Создаем новое поле с обрезанным именем
                new_field = QgsField(truncated_name, field.type())
                truncated_fields.append(new_field)
                options.attributes.append(layer.fields().indexOf(original_name))

            # Логируем изменения имен полей
            if field_mapping:
                log_info(
                    f"Имена полей обрезаны для Shapefile: {field_mapping}"
                )

        # Добавляем трансформацию если нужно
        if layer.crs() != target_crs:
            transform = QgsCoordinateTransform(
                layer.crs(),
                target_crs,
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
            raise RuntimeError(f"Ошибка экспорта в Shapefile: {error[1]}")

        # Создаем файл кодировки .cpg для корректного отображения кириллицы
        cpg_path = output_path.replace('.shp', '.cpg')
        with open(cpg_path, 'w') as cpg_file:
            cpg_file.write(params.get('encoding', 'UTF-8'))

        log_info(
            f"Shapefile создан (WGS-84): {output_path}"
        )

        return True
    def _export_layer_style(self, layer: QgsVectorLayer, shapefile_path: str) -> bool:
        """
        Экспорт стиля слоя в .qml файл

        Args:
            layer: Слой со стилем
            shapefile_path: Путь к Shapefile

        Returns:
            True если успешно
        """
        # Путь к файлу стиля (заменяем .shp на .qml)
        qml_path = shapefile_path.replace('.shp', '.qml')

        # Сохраняем стиль
        layer.saveNamedStyle(qml_path)

        log_info(
            f"Стиль сохранен: {qml_path}"
        )

        # Также создаем .sld файл для совместимости с другими ГИС
        sld_path = shapefile_path.replace('.shp', '.sld')
        layer.saveSldStyle(sld_path)

        log_info(
            f"SLD стиль сохранен: {sld_path}"
        )

        return True
