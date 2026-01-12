# -*- coding: utf-8 -*-
"""
Экспортер в формат MapInfo TAB
"""

import os
from typing import List, Dict, Any, Optional
from osgeo import ogr, osr

from qgis.core import (
    QgsVectorLayer, QgsProject, QgsVectorFileWriter,
    QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsMessageLog, Qgis, QgsWkbTypes
)

from .base_exporter import BaseExporter
from Daman_QGIS.managers import get_reference_managers
from Daman_QGIS.constants import PLUGIN_NAME
from Daman_QGIS.utils import log_info, log_warning, log_error


class TabExporter(BaseExporter):
    """Экспортер в формат MapInfo TAB"""
    
    def __init__(self, iface=None):
        """Инициализация экспортера TAB"""
        super().__init__(iface)
        
        # Дополнительные параметры для TAB
        self.default_params.update({
            'create_wgs84': True,  # Создавать ли файл в WGS-84
            'use_non_earth': True,  # Использовать Non-Earth для МСК
            'clean_temp_files': True,  # Удалять временные MIF файлы
        })
        
        # Инициализируем reference_manager для стилей
        self.ref_managers = get_reference_managers()
    
    def export_layers(self, 
                     layers: List[QgsVectorLayer],
                     output_folder: str,
                     **params) -> Dict[str, bool]:
        """
        Экспорт слоев в TAB файлы
        
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
        Экспорт одного слоя в TAB

        Args:
            layer: Слой для экспорта
            output_folder: Папка назначения
            params: Параметры экспорта

        Returns:
            True если успешно
        """
        # Получаем стиль MapInfo из Base_layers.json
        mapinfo_style = None
        layer_info = self.ref_managers.layer.get_layer_by_full_name(layer.name())
        if layer_info and layer_info.get('style_MapInfo') and layer_info['style_MapInfo'] != '-':
            mapinfo_style = layer_info['style_MapInfo']
            log_info(
                f"Найден стиль MapInfo для слоя {layer.name()}: {mapinfo_style}"
            )

        # Получаем информацию о СК
        crs_short_name, project_crs = self.get_project_crs_info()

        # Форматируем имя файла
        filename = self.format_filename(
            layer,
            params.get('filename_pattern')
        )

        # Экспортируем в СК проекта
        tab_path = os.path.join(output_folder, f"{filename}.tab")
        success = self._export_to_tab(
            layer,
            tab_path,
            project_crs,
            params,
            mapinfo_style
        )

        if not success:
            return False

        # Экспортируем в WGS-84 если нужно
        if params.get('create_wgs84', True):
            wgs84_crs = QgsCoordinateReferenceSystem("EPSG:4326")

            # Для WGS84 файла убираем короткое название СК из имени
            # Проверяем, есть ли короткое название СК в имени файла
            if crs_short_name and crs_short_name in filename:
                # Убираем короткое название СК и возможные разделители
                wgs84_filename = filename.replace(f"_{crs_short_name.replace(' ', '_')}", "")
                wgs84_filename = wgs84_filename.replace(f"_{crs_short_name}", "")
                wgs84_filename = wgs84_filename.replace(crs_short_name.replace(' ', '_'), "")
                wgs84_filename = wgs84_filename.replace(crs_short_name, "")
                # Убираем двойные подчеркивания если появились
                wgs84_filename = wgs84_filename.replace("__", "_")
                # Убираем подчеркивание в конце если есть
                if wgs84_filename.endswith("_"):
                    wgs84_filename = wgs84_filename[:-1]
            else:
                wgs84_filename = filename

            # Добавляем суффикс WGS84
            wgs84_filename = f"{wgs84_filename}_WGS84"
            wgs84_path = os.path.join(output_folder, f"{wgs84_filename}.tab")

            success = self._export_to_tab(
                layer,
                wgs84_path,
                wgs84_crs,
                params,
                mapinfo_style
            )

        return success
    def _export_to_tab(self,
                      layer: QgsVectorLayer,
                      output_path: str,
                      target_crs: QgsCoordinateReferenceSystem,
                      params: Dict[str, Any],
                      mapinfo_style: Optional[str] = None) -> bool:
        """
        Экспорт в TAB

        Args:
            layer: Слой для экспорта
            output_path: Путь к выходному TAB файлу
            target_crs: Целевая СК
            params: Параметры экспорта

        Returns:
            True если успешно
        """
        # Нормализуем путь
        output_path = os.path.normpath(output_path)

        log_info(
            f"Начинаем экспорт в TAB: {output_path}"
        )

        # Проверяем является ли СК местной (МСК)
        is_local_crs = self._is_local_crs(target_crs)

        # Если это МСК и нужен Non-Earth - используем GDAL
        if params.get('use_non_earth', True) and is_local_crs:
            return self._export_to_tab_gdal(layer, output_path, target_crs, mapinfo_style)

        # Иначе используем стандартный экспорт QGIS (для WGS-84 и других географических СК)
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "MapInfo File"
        options.fileEncoding = "cp1251"

        # Добавляем трансформацию если нужно
        if layer.crs() != target_crs:
            transform = QgsCoordinateTransform(
                layer.crs(),
                target_crs,
                QgsProject.instance()
            )
            options.ct = transform

        # Экспортируем напрямую в TAB
        error = QgsVectorFileWriter.writeAsVectorFormatV3(
            layer,
            output_path,
            QgsProject.instance().transformContext(),
            options
        )

        if error[0] != QgsVectorFileWriter.NoError:
            raise RuntimeError(f"Ошибка экспорта в TAB: {error[1]}")

        log_info(
            f"TAB файл создан: {output_path}"
        )

        return True
    
    def _is_local_crs(self, crs: QgsCoordinateReferenceSystem) -> bool:
        """
        Проверка является ли СК местной (МСК)
        
        Args:
            crs: Система координат
            
        Returns:
            True если это МСК
        """
        # Проверяем по названию
        description = crs.description().lower() if crs.description() else ""
        auth_id = crs.authid().lower() if crs.authid() else ""
        
        # МСК обычно содержат эти ключевые слова
        msk_keywords = ['мск', 'местная', 'local', 'гск']
        
        for keyword in msk_keywords:
            if keyword in description or keyword in auth_id:
                return True
        
        # Также проверяем что это не стандартная географическая СК
        if crs.isGeographic():
            return False
        
        # Если EPSG код отсутствует или нестандартный - возможно МСК
        if not crs.authid() or not crs.authid().startswith('EPSG:'):
            return True
        
        return False
    def _export_to_tab_gdal(self, layer: QgsVectorLayer, output_path: str, target_crs: QgsCoordinateReferenceSystem, mapinfo_style: Optional[str] = None) -> bool:
        """
        Создает TAB файл с Nonearth проекцией через GDAL

        Args:
            layer: Слой для экспорта (QgsVectorLayer)
            output_path: Путь к выходному TAB файлу
            target_crs: Целевая СК (QgsCoordinateReferenceSystem)
            mapinfo_style: Стиль MapInfo для применения

        Returns:
            bool: Успешно ли создан TAB файл
        """
        # Создаем драйвер MapInfo
        driver = ogr.GetDriverByName('MapInfo File')
        if not driver:
            raise RuntimeError("Драйвер MapInfo File не найден в GDAL")

        # Удаляем существующий файл если есть
        if os.path.exists(output_path):
            driver.DeleteDataSource(output_path)

        # Создаем DataSource
        ds = driver.CreateDataSource(output_path)
        if not ds:
            raise RuntimeError(f"Не удалось создать TAB файл: {output_path}")

        # Создаем Nonearth координатную систему
        srs = osr.SpatialReference()
        srs.SetLocalCS("Nonearth")
        srs.SetLinearUnits("metre", 1.0)

        # Определяем тип геометрии
        geom_type = layer.wkbType()
        if QgsWkbTypes.hasM(geom_type) or QgsWkbTypes.hasZ(geom_type):
            geom_type = QgsWkbTypes.to25D(geom_type)

        # Конвертируем тип геометрии QGIS в OGR
        if geom_type in [QgsWkbTypes.LineString, QgsWkbTypes.MultiLineString]:
            ogr_geom_type = ogr.wkbLineString
        elif geom_type in [QgsWkbTypes.Polygon, QgsWkbTypes.MultiPolygon]:
            ogr_geom_type = ogr.wkbPolygon
        elif geom_type in [QgsWkbTypes.Point, QgsWkbTypes.MultiPoint]:
            ogr_geom_type = ogr.wkbPoint
        else:
            ogr_geom_type = ogr.wkbUnknown

        # Создаем слой с Nonearth и границами
        bounds_str = "-1000000,-1000000,19000000,19000000"
        lyr = ds.CreateLayer(
            'layer1',
            srs,
            ogr_geom_type,
            options=[f'BOUNDS={bounds_str}', 'ENCODING=cp1251']
        )

        if not lyr:
            raise RuntimeError("Не удалось создать слой в TAB файле")

        # Добавляем поля из исходного слоя
        for field in layer.fields():
            field_name = field.name()
            field_type = field.typeName().upper()

            # Конвертируем типы полей QGIS в OGR
            if 'INT' in field_type:
                ogr_field = ogr.FieldDefn(field_name, ogr.OFTInteger)
            elif 'REAL' in field_type or 'DOUBLE' in field_type:
                ogr_field = ogr.FieldDefn(field_name, ogr.OFTReal)
            else:
                ogr_field = ogr.FieldDefn(field_name, ogr.OFTString)
                if field.length() > 0:
                    ogr_field.SetWidth(field.length())

            lyr.CreateField(ogr_field)

        # Создаем трансформацию координат если нужно
        transform = None
        if layer.crs() != target_crs:
            transform = QgsCoordinateTransform(
                layer.crs(),
                target_crs,
                QgsProject.instance()
            )

        # Экспортируем features
        for qgs_feature in layer.getFeatures():
            geom = qgs_feature.geometry()
            if not geom or geom.isEmpty():
                continue

            # Трансформируем геометрию если нужно
            if transform:
                geom.transform(transform)

            # Создаем OGR feature
            ogr_feature = ogr.Feature(lyr.GetLayerDefn())

            # Копируем атрибуты
            for i, attr in enumerate(qgs_feature.attributes()):
                if attr is not None:
                    # Преобразуем значение в строку если нужно
                    if isinstance(attr, (int, float)):
                        ogr_feature.SetField(i, attr)
                    else:
                        ogr_feature.SetField(i, str(attr))

            # Конвертируем геометрию из QGIS в OGR
            wkt = geom.asWkt()
            ogr_geom = ogr.CreateGeometryFromWkt(wkt)

            if ogr_geom:
                ogr_feature.SetGeometry(ogr_geom)

                # Применяем стиль MapInfo если он задан
                if mapinfo_style:
                    ogr_feature.SetStyleString(mapinfo_style)

                # Добавляем feature в слой
                lyr.CreateFeature(ogr_feature)

            # Освобождаем ресурсы
            ogr_feature = None

        # Закрываем DataSource
        ds = None

        if mapinfo_style:
            log_info(
                f"TAB файл с Nonearth и стилем MapInfo создан: {output_path}"
            )
        else:
            log_info(
                f"TAB файл с Nonearth создан через GDAL: {output_path}"
            )

        return True

