# -*- coding: utf-8 -*-
"""
Базовый класс для всех экспортеров с поддержкой параметров-якорей
"""

import os
from typing import List, Dict, Any, Optional
from qgis.core import (
    QgsVectorLayer, QgsProject, QgsMessageLog, Qgis,
    QgsCoordinateReferenceSystem
)
from qgis.PyQt.QtCore import QObject, pyqtSignal, QSettings

from Daman_QGIS.managers import DataCleanupManager
from Daman_QGIS.utils import log_info, log_warning, log_error, create_crs_from_string
from Daman_QGIS.constants import PLUGIN_NAME


class BaseExporter(QObject):
    """Базовый класс для экспортеров с параметрами-якорями"""
    
    # Сигналы для отслеживания прогресса
    progress = pyqtSignal(int)  # Процент выполнения
    message = pyqtSignal(str)   # Сообщения процесса
    
    def __init__(self, iface=None):
        """
        Инициализация экспортера

        Args:
            iface: Интерфейс QGIS
        """
        super().__init__()
        self.iface = iface
        self.settings = QSettings(PLUGIN_NAME, 'Exporter')
        self.data_cleanup_manager = DataCleanupManager()

        # Параметры по умолчанию (якоря)
        self.default_params = {
            'filename_pattern': '{layer_name}',  # Шаблон имени файла
            'output_folder': None,  # Папка назначения
            'style_overrides': None,  # Переопределение стилей
            'export_settings': {},  # Специфичные настройки экспорта
            'filter_prefix': True,  # Фильтровать по префиксам
            'separate_files': True,  # Отдельный файл для каждого слоя
        }
    
    def get_last_export_folder(self) -> Optional[str]:
        """Получить последнюю использованную папку экспорта"""
        return self.settings.value('last_export_folder', None)
    
    def set_last_export_folder(self, folder: str) -> None:
        """Сохранить последнюю использованную папку экспорта"""
        self.settings.setValue('last_export_folder', folder)
    
    def filter_layers_by_prefix(self, layers: List[QgsVectorLayer]) -> List[QgsVectorLayer]:
        """
        Фильтрация слоев по префиксам нумерации
        
        Args:
            layers: Список слоев
            
        Returns:
            Отфильтрованные слои с префиксами X_Y_Z_
        """
        filtered = []
        for layer in layers:
            if isinstance(layer, QgsVectorLayer):
                name = layer.name()
                # Проверяем префикс вида X_Y_Z_ где X,Y,Z - цифры
                parts = name.split('_')
                if len(parts) >= 3:
                    try:
                        # Проверяем что первые три части - цифры
                        int(parts[0])
                        int(parts[1])
                        int(parts[2])
                        filtered.append(layer)
                    except ValueError:
                        continue
        return filtered
    def get_project_crs_info(self) -> tuple[Optional[str], QgsCoordinateReferenceSystem]:
        """
        Получение информации о системе координат проекта

        Returns:
            tuple: (crs_short_name, project_crs)
        """
        # Находим GeoPackage
        from Daman_QGIS.managers.M_19_project_structure_manager import get_project_structure_manager
        project_home = QgsProject.instance().homePath()
        structure_manager = get_project_structure_manager()
        structure_manager.project_root = project_home
        gpkg_path = structure_manager.get_gpkg_path(create=False)

        if not gpkg_path or not os.path.exists(gpkg_path):
            return None, QgsProject.instance().crs()

        # Получаем данные из метаданных
        from Daman_QGIS.database.project_db import ProjectDB
        project_db = ProjectDB(gpkg_path)

        # Короткое название СК
        crs_short_name_data = project_db.get_metadata('1_4_crs_short_name')
        crs_short_name = crs_short_name_data['value'] if crs_short_name_data else None

        # Получаем СК проекта
        project_crs = None

        # Сначала пытаемся через WKT
        crs_wkt_data = project_db.get_metadata('1_4_crs_wkt')
        if crs_wkt_data and crs_wkt_data['value']:
            project_crs = QgsCoordinateReferenceSystem()
            project_crs.createFromWkt(crs_wkt_data['value'])

        # Если не получилось, пробуем через EPSG
        if not project_crs or not project_crs.isValid():
            crs_epsg_data = project_db.get_metadata('1_4_crs_epsg')
            if crs_epsg_data and crs_epsg_data['value']:
                project_crs = create_crs_from_string(crs_epsg_data['value'])

        # Если всё ещё не получилось, берём СК текущего проекта
        if not project_crs or not project_crs.isValid():
            project_crs = QgsProject.instance().crs()

        return crs_short_name, project_crs
    
    def format_filename(self, layer: QgsVectorLayer, pattern: Optional[str] = None, **kwargs) -> str:
        """
        Форматирование имени файла по шаблону
        
        Args:
            layer: Слой для экспорта
            pattern: Шаблон имени (если None, используется default)
            **kwargs: Дополнительные переменные для шаблона
            
        Returns:
            Отформатированное имя файла
        """
        if pattern is None:
            pattern = self.default_params.get('filename_pattern')

        # Если шаблон все еще None, используем имя слоя
        # КРИТИЧНО: 2025-10-28 - Добавлена очистка имени через sanitize_filename()
        # Раньше имя слоя использовалось БЕЗ ОЧИСТКИ
        if not pattern:
            # DEPRECATED: return layer.name()
            return self.data_cleanup_manager.sanitize_filename(layer.name())

        # Получаем информацию о СК
        crs_short_name, _ = self.get_project_crs_info()

        # Переменные для подстановки
        variables = {
            'layer_name': layer.name(),
            'layer_name_clean': layer.name().replace('_', ' '),
            'crs_short': crs_short_name or 'unknown',
            'crs_short_underscore': (crs_short_name or 'unknown').replace(' ', '_'),
        }

        # Добавляем пользовательские переменные
        variables.update(kwargs)

        # Форматируем имя
        try:
            filename = pattern.format(**variables)
        except KeyError as e:
            log_warning(
                f"Ошибка форматирования имени файла: {str(e)}"
            )
            # DEPRECATED: filename = layer.name()
            filename = self.data_cleanup_manager.sanitize_filename(layer.name())

        # КРИТИЧНО: 2025-10-28 - Применяем очистку к результату форматирования
        # Даже если pattern не содержит запрещённых символов, layer_name может содержать
        filename = self.data_cleanup_manager.sanitize_filename(filename)

        return filename
    
    def export_layers(self, 
                     layers: List[QgsVectorLayer],
                     output_folder: str,
                     **params) -> Dict[str, bool]:
        """
        Экспорт списка слоев (должен быть переопределен в наследниках)
        
        Args:
            layers: Список слоев для экспорта
            output_folder: Папка назначения
            **params: Параметры экспорта (переопределяют defaults)
            
        Returns:
            Словарь {layer_name: success}
        """
        raise NotImplementedError("Метод должен быть реализован в наследнике")
    
    def merge_params(self, **params) -> Dict[str, Any]:
        """
        Объединение параметров с учетом переопределений
        
        Args:
            **params: Переданные параметры
            
        Returns:
            Объединенные параметры
        """
        merged = self.default_params.copy()
        merged.update(params)
        return merged
