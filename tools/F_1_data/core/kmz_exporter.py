# -*- coding: utf-8 -*-
"""
Экспортер в формат KMZ (сжатый KML)
"""

import os
import zipfile
from typing import List, Dict, Any

from qgis.core import (
    QgsVectorLayer, QgsMessageLog, Qgis
)

from .kml_exporter import KMLExporter
from Daman_QGIS.constants import PLUGIN_NAME
from Daman_QGIS.utils import log_info, log_warning, log_error


class KMZExporter(KMLExporter):
    """Экспортер в формат KMZ (наследует KMLExporter)"""
    
    def __init__(self, iface=None):
        """Инициализация экспортера KMZ"""
        super().__init__(iface)
        
        # Дополнительные параметры для KMZ
        self.default_params.update({
            'compression': zipfile.ZIP_DEFLATED,  # Метод сжатия
            'include_icons': False,  # Включать ли иконки (если есть)
        })
    def _export_layer(self,
                     layer: QgsVectorLayer,
                     output_folder: str,
                     params: Dict[str, Any]) -> bool:
        """
        Экспорт одного слоя в KMZ

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

        # Сначала экспортируем в KML во временный файл
        import tempfile
        temp_dir = tempfile.mkdtemp()
        kml_path = os.path.join(temp_dir, "doc.kml")

        # KML всегда в WGS-84
        from qgis.core import QgsCoordinateReferenceSystem
        wgs84_crs = QgsCoordinateReferenceSystem("EPSG:4326")

        # Экспортируем в KML
        success = self._export_to_kml(
            layer,
            kml_path,
            wgs84_crs,
            params
        )

        if not success:
            # Удаляем временную директорию
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)
            return False

        # Создаем KMZ архив
        kmz_path = os.path.join(output_folder, f"{filename}.kmz")
        success = self._create_kmz(kml_path, kmz_path, params)

        # Удаляем временную директорию
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)

        if success:
            self.message.emit(f"Экспортирован в KMZ: {layer.name()}")

        return success
    def _create_kmz(self, kml_path: str, kmz_path: str, params: Dict[str, Any]) -> bool:
        """
        Создание KMZ архива из KML файла

        Args:
            kml_path: Путь к KML файлу
            kmz_path: Путь к выходному KMZ файлу
            params: Параметры экспорта

        Returns:
            True если успешно
        """
        log_info(
            f"Создаем KMZ архив: {kmz_path}"
        )

        # Создаем ZIP архив с расширением .kmz
        compression = params.get('compression', zipfile.ZIP_DEFLATED)

        with zipfile.ZipFile(kmz_path, 'w', compression=compression) as kmz:
            # Добавляем KML файл как doc.kml (стандартное имя для KMZ)
            kmz.write(kml_path, arcname='doc.kml')

            # Если нужно добавить иконки или другие ресурсы
            if params.get('include_icons', False):
                # Здесь можно добавить логику для включения иконок
                # Например, из папки resources/icons/
                pass

        log_info(
            f"KMZ файл создан: {kmz_path}"
        )

        return True
