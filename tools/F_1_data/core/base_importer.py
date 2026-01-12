# -*- coding: utf-8 -*-
"""
Базовый класс для всех импортеров
Содержит общие методы и интерфейс для сабмодулей
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List, Tuple
from qgis.core import (
    QgsProject, QgsMessageLog, Qgis,
    QgsCoordinateReferenceSystem, QgsVectorLayer
)

from Daman_QGIS.constants import PLUGIN_NAME
from Daman_QGIS.utils import log_info, log_warning, log_error, create_crs_from_string


class BaseImporter(ABC):
    """Абстрактный базовый класс для всех импортеров"""
    
    def __init__(self, iface):
        """
        Инициализация базового импортера
        
        Args:
            iface: Интерфейс QGIS
        """
        self.iface = iface
        self.project_manager = None
        self.layer_manager = None
        self.default_params = {}  # Переопределяется в наследниках
        
    def set_project_manager(self, project_manager):
        """Установка менеджера проектов"""
        self.project_manager = project_manager
        
    def set_layer_manager(self, layer_manager):
        """Установка менеджера слоев"""
        self.layer_manager = layer_manager
    def get_project_crs(self) -> Optional[QgsCoordinateReferenceSystem]:
        """
        Получение СК из метаданных проекта

        Returns:
            QgsCoordinateReferenceSystem или None
        """
        # Получаем СК из метаданных проекта
        if self.project_manager and self.project_manager.project_db:
            # Сначала пытаемся получить WKT (для пользовательских СК)
            crs_wkt = self.project_manager.project_db.get_metadata('1_4_crs_wkt')
            if crs_wkt and 'value' in crs_wkt:
                crs = QgsCoordinateReferenceSystem()
                crs.createFromWkt(crs_wkt['value'])
                if crs.isValid():
                    log_info(
                        f"BaseImporter: Используется СК из WKT: {crs.description()}"
                    )
                    return crs

            # Если WKT нет, пытаемся через EPSG код (поддержка USER:XXXXX)
            crs_epsg = self.project_manager.project_db.get_metadata('1_4_crs_epsg')
            if crs_epsg and 'value' in crs_epsg:
                crs = create_crs_from_string(crs_epsg['value'])
                if crs:
                    log_info(f"BaseImporter: Используется СК из проекта: {crs.authid()} - {crs.description()}")
                    return crs

        # Если не удалось получить из метаданных, используем СК текущего проекта QGIS
        project_crs = QgsProject.instance().crs()
        if project_crs.isValid():
            log_info(
                f"BaseImporter: Используется СК текущего проекта QGIS: {project_crs.authid()} - {project_crs.description()}"
            )
            return project_crs

        return None
    
    def merge_params(self, custom_params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Объединение параметров по умолчанию с пользовательскими
        
        Args:
            custom_params: Пользовательские параметры
            
        Returns:
            Объединенные параметры
        """
        params = self.default_params.copy()
        if custom_params:
            params.update(custom_params)
        return params
    
    @abstractmethod
    def import_file(self, file_path: str, **custom_params) -> Dict[str, Any]:
        """
        Абстрактный метод импорта файла
        
        Args:
            file_path: Путь к файлу
            **custom_params: Дополнительные параметры
            
        Returns:
            Словарь с результатами:
            {
                'success': bool,
                'layers': List[QgsVectorLayer],
                'message': str,
                'errors': List[str]
            }
        """
        pass
    
    @abstractmethod
    def supports_format(self, file_extension: str) -> bool:
        """
        Проверка поддержки формата файла
        
        Args:
            file_extension: Расширение файла (например, '.dxf')
            
        Returns:
            True если формат поддерживается
        """
        pass
    
    def validate_import(self, file_path: str) -> Tuple[bool, str]:
        """
        Валидация возможности импорта
        
        Args:
            file_path: Путь к файлу
            
        Returns:
            (success, message)
        """
        import os
        
        # Проверка существования файла
        if not os.path.exists(file_path):
            return False, f"Файл не найден: {file_path}"
        
        # Проверка расширения
        ext = os.path.splitext(file_path)[1].lower()
        if not self.supports_format(ext):
            return False, f"Формат {ext} не поддерживается данным импортером"
        
        # Проверка открытого проекта
        if self.project_manager and not self.project_manager.is_project_open():
            return False, "Сначала откройте или создайте проект"
        
        return True, "OK"
    
    def log_result(self, success: bool, message: str, layer_name: Optional[str] = None):
        """
        Логирование результата импорта
        
        Args:
            success: Успешность операции
            message: Сообщение
            layer_name: Имя слоя (опционально)
        """
        prefix = f"[{layer_name}] " if layer_name else ""

        if success:
            log_info(f"BaseImporter: {prefix}{message}")
        else:
            log_error(f"BaseImporter: {prefix}{message}")
