# -*- coding: utf-8 -*-
"""
Работа с базой данных проекта (GeoPackage).
Управление слоями и данными в GeoPackage.
"""

import os
import re
import json
import sqlite3
from typing import List, Optional, Dict, Any
from datetime import datetime

from qgis.core import (
    QgsVectorLayer, QgsRasterLayer, QgsProject,
    QgsVectorFileWriter, QgsCoordinateReferenceSystem,
    QgsDataSourceUri,
    QgsProviderRegistry
)

from Daman_QGIS.utils import log_info, log_warning, log_error
from Daman_QGIS.constants import (
    PROJECT_METADATA_TABLE, PROVIDER_OGR, DRIVER_GPKG,
    GPKG_SYSTEM_TABLE_PREFIX, GPKG_INIT_LAYER_NAME, GPKG_SETTINGS_SUFFIX
)
from ..database.schemas import LayerInfo, ProjectSettings

class ProjectDB:
    """Менеджер базы данных проекта (GeoPackage)"""
    
    def __init__(self, gpkg_path: str):
        """
        Инициализация БД проекта
        
        Args:
            gpkg_path: Путь к файлу GeoPackage
        """
        self.gpkg_path = gpkg_path
        self.layers = {}  # Кэш загруженных слоев
        
    def create(self, crs: Optional[QgsCoordinateReferenceSystem] = None) -> bool:
        """
        Создание нового GeoPackage

        Args:
            crs: Система координат проекта

        Returns:
            True если создание успешно
        """
        # Создаем папку если не существует
        os.makedirs(os.path.dirname(self.gpkg_path), exist_ok=True)

        # Создаем пустой GeoPackage через создание временного слоя
        # Это стандартный способ в QGIS
        if not crs:
            crs = QgsCoordinateReferenceSystem("EPSG:4326")

        # Создаем временный слой для инициализации GeoPackage
        temp_layer = QgsVectorLayer(
            f"Point?crs={crs.authid()}",
            "init",
            "memory"
        )

        # Сохраняем как GeoPackage
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = DRIVER_GPKG
        options.layerName = GPKG_INIT_LAYER_NAME  # Служебный слой

        error = QgsVectorFileWriter.writeAsVectorFormatV3(
            temp_layer,
            self.gpkg_path,
            QgsProject.instance().transformContext(),
            options
        )

        if error[0] == QgsVectorFileWriter.NoError:
            log_info(f"GeoPackage создан: {self.gpkg_path}")
            # Создаем таблицу метаданных
            self.create_metadata_table()
            return True
        else:
            raise Exception(f"Ошибка создания GeoPackage: {error[1]}")
    
    def exists(self) -> bool:
        """Проверка существования GeoPackage"""
        return os.path.exists(self.gpkg_path)
    
    def add_layer(self, layer: QgsVectorLayer, layer_name: Optional[str] = None) -> bool:
        """
        Добавление слоя в GeoPackage

        Args:
            layer: Слой для добавления
            layer_name: Имя слоя в GeoPackage

        Returns:
            True если добавление успешно
        """
        if not layer_name:
            layer_name = layer.name() if layer.name() else "unnamed_layer"

        # Опции сохранения
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = DRIVER_GPKG
        options.layerName = layer_name
        options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer

        # Сохраняем слой в GeoPackage
        error = QgsVectorFileWriter.writeAsVectorFormatV3(
            layer,
            self.gpkg_path,
            QgsProject.instance().transformContext(),
            options
        )

        if error[0] == QgsVectorFileWriter.NoError:
            log_info(f"Слой '{layer_name}' добавлен в GeoPackage")
            # Добавляем в кэш
            self.layers[layer_name] = layer
            return True
        else:
            raise Exception(f"Ошибка добавления слоя: {error[1]}")
    
    def get_layer(self, layer_name: str) -> Optional[QgsVectorLayer]:
        """
        Получение слоя из GeoPackage

        Args:
            layer_name: Имя слоя

        Returns:
            QgsVectorLayer или None

        Raises:
            ValueError: Если имя слоя содержит недопустимые символы
        """
        # Валидация имени слоя для консистентности с remove_layer()
        try:
            self._validate_layer_name(layer_name)
        except ValueError:
            return None

        # Проверяем кэш
        if layer_name in self.layers:
            return self.layers[layer_name]

        # Загружаем из GeoPackage
        uri = f"{self.gpkg_path}|layername={layer_name}"
        layer = QgsVectorLayer(uri, layer_name, PROVIDER_OGR)

        if layer.isValid():
            self.layers[layer_name] = layer
            return layer
        else:
            log_warning(f"Слой '{layer_name}' не найден в GeoPackage")
            return None
    
    def list_layers(self) -> List[str]:
        """
        Получение списка слоев в GeoPackage

        Returns:
            Список имен слоев
        """
        if not self.exists():
            return []

        # Используем QGIS провайдер для получения списка слоев
        md = QgsProviderRegistry.instance().providerMetadata(PROVIDER_OGR)
        conn = md.createConnection(self.gpkg_path, {})

        layers = []
        for table in conn.tables():
            # Пропускаем служебные таблицы
            if not table.tableName().startswith(GPKG_SYSTEM_TABLE_PREFIX):
                layers.append(table.tableName())

        return layers
    
    # Паттерн для валидации имен слоев (только буквы, цифры, подчеркивания, кириллица)
    # Разрешены: L_1_1_1_Границы_работ, Le_2_1_1_1_Выборка_ЗУ
    _VALID_LAYER_NAME_PATTERN = re.compile(r'^[a-zA-Z0-9_\u0400-\u04FF]+$')

    def _validate_layer_name(self, layer_name: str) -> bool:
        """
        Валидация имени слоя для предотвращения SQL injection.

        Args:
            layer_name: Имя слоя для проверки

        Returns:
            True если имя валидно

        Raises:
            ValueError: Если имя содержит недопустимые символы
        """
        if not layer_name:
            raise ValueError("Имя слоя не может быть пустым")

        if not self._VALID_LAYER_NAME_PATTERN.match(layer_name):
            log_error(f"ProjectDB: Недопустимое имя слоя: {layer_name}")
            raise ValueError(
                f"Недопустимое имя слоя: '{layer_name}'. "
                "Разрешены только буквы, цифры и подчеркивания."
            )
        return True

    def remove_layer(self, layer_name: str) -> bool:
        """
        Удаление слоя из GeoPackage

        Args:
            layer_name: Имя слоя

        Returns:
            True если удаление успешно

        Raises:
            ValueError: Если имя слоя содержит недопустимые символы
        """
        # Валидация имени слоя для предотвращения SQL injection
        self._validate_layer_name(layer_name)

        # Используем SQL для удаления таблицы
        md = QgsProviderRegistry.instance().providerMetadata(PROVIDER_OGR)
        conn = md.createConnection(self.gpkg_path, {})

        # Удаляем таблицу (имя уже провалидировано)
        conn.executeSql(f"DROP TABLE IF EXISTS \"{layer_name}\"")

        # Удаляем из кэша
        if layer_name in self.layers:
            del self.layers[layer_name]

        log_info(f"ProjectDB: Слой '{layer_name}' удален из GeoPackage")
        return True
    
    def get_layer_info(self, layer_name: str) -> Optional[LayerInfo]:
        """
        Получение информации о слое
        
        Args:
            layer_name: Имя слоя
            
        Returns:
            LayerInfo или None
        """
        layer = self.get_layer(layer_name)
        if layer is None:
            return None

        # Получаем метаданные слоя
        info = LayerInfo(
            id=layer.id(),
            name=layer_name,
            type="vector",
            geometry_type=str(layer.geometryType()),
            source_path=self.gpkg_path,
            prefix="",  # Определяется в layer_manager
            created=datetime.now(),
            modified=datetime.now(),
            readonly=layer.isReadOnly() if hasattr(layer, 'isReadOnly') else False,
            visible=True,
            attributes={}
        )
        
        return info
    
    def save_project_settings(self, settings: ProjectSettings) -> bool:
        """
        Сохранение настроек проекта в GeoPackage

        Args:
            settings: Настройки проекта

        Returns:
            True если сохранение успешно
        """
        # Сохраняем настройки в отдельный JSON файл рядом с GeoPackage
        settings_path = self.gpkg_path.replace('.gpkg', GPKG_SETTINGS_SUFFIX)

        settings_dict = {
            'name': settings.name,
            'created': settings.created.isoformat(),
            'modified': settings.modified.isoformat(),
            'version': settings.version,
            'crs_epsg': settings.crs_epsg,
            'gpkg_path': settings.gpkg_path,
            'work_dir': settings.work_dir,
            'object_name': settings.object_name,
            'object_type': settings.object_type,
            'crs_description': settings.crs_description,
            'auto_numbering': settings.auto_numbering,
            'readonly_imports': settings.readonly_imports,
            'versioning_enabled': settings.versioning_enabled,
            'current_version': settings.current_version,
            'custom_settings': settings.custom_settings
        }

        with open(settings_path, 'w', encoding='utf-8') as f:
            json.dump(settings_dict, f, ensure_ascii=False, indent=2)

        return True
    
    def load_project_settings(self) -> Optional[ProjectSettings]:
        """
        Загрузка настроек проекта

        Returns:
            ProjectSettings или None
        """
        settings_path = self.gpkg_path.replace('.gpkg', GPKG_SETTINGS_SUFFIX)

        if not os.path.exists(settings_path):
            return None

        with open(settings_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        settings = ProjectSettings(
            name=data['name'],
            created=datetime.fromisoformat(data['created']),
            modified=datetime.fromisoformat(data['modified']),
            version=data.get('version', '2.0.0'),
            crs_epsg=data.get('crs_epsg', 0),
            gpkg_path=data.get('gpkg_path', self.gpkg_path),
            work_dir=data.get('work_dir', ''),
            object_name=data.get('object_name', ''),
            object_type=data.get('object_type', ''),
            crs_description=data.get('crs_description', ''),
            auto_numbering=data.get('auto_numbering', True),
            readonly_imports=data.get('readonly_imports', True),
            versioning_enabled=data.get('versioning_enabled', True),
            current_version=data.get('current_version', 'Рабочая версия'),
            custom_settings=data.get('custom_settings', {})
        )

        return settings
    
    def create_metadata_table(self) -> bool:
        """
        Создание таблицы метаданных проекта

        Returns:
            True если создание успешно
        """
        # Используем sqlite3 напрямую для создания пользовательской таблицы
        with sqlite3.connect(self.gpkg_path) as conn:
            cursor = conn.cursor()

            # Удаляем таблицу если она уже существует (могла быть создана автоматически QGIS)
            cursor.execute(f"DROP TABLE IF EXISTS {PROJECT_METADATA_TABLE}")

            # Создаем таблицу с правильной структурой
            cursor.execute(f"""
                CREATE TABLE {PROJECT_METADATA_TABLE} (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    description TEXT
                )
            """)
            # commit() вызывается автоматически при выходе из with

        log_info("Таблица метаданных создана")
        return True
    
    def set_metadata(self, key: str, value: str, description: str = "") -> bool:
        """
        Установка значения метаданных

        Args:
            key: Ключ
            value: Значение
            description: Описание

        Returns:
            True если успешно
        """
        # Используем sqlite3 для работы с метаданными
        with sqlite3.connect(self.gpkg_path) as conn:
            cursor = conn.cursor()

            # Вставляем или обновляем значение
            cursor.execute(f"""
                INSERT OR REPLACE INTO {PROJECT_METADATA_TABLE} (key, value, description)
                VALUES (?, ?, ?)
            """, (key, value, description))

        return True
    
    def get_metadata(self, key: str) -> Optional[Dict[str, str]]:
        """
        Получение значения метаданных

        Args:
            key: Ключ

        Returns:
            Словарь с value и description или None
        """
        # Используем sqlite3 для чтения метаданных
        with sqlite3.connect(self.gpkg_path) as conn:
            cursor = conn.cursor()

            # Проверяем существование таблицы
            cursor.execute(f"""
                SELECT name FROM sqlite_master
                WHERE type='table' AND name='{PROJECT_METADATA_TABLE}'
            """)

            if not cursor.fetchone():
                return None

            cursor.execute(
                f"SELECT value, description FROM {PROJECT_METADATA_TABLE} WHERE key = ?",
                (key,)
            )
            result = cursor.fetchone()

            if result:
                return {
                    'value': result[0],
                    'description': result[1] if result[1] else ''
                }
        return None

    def delete_metadata(self, key: str) -> bool:
        """
        Удаление метаданных по ключу

        Args:
            key: Ключ метаданных для удаления

        Returns:
            True если удаление успешно, False если ключ не найден
        """
        with sqlite3.connect(self.gpkg_path) as conn:
            cursor = conn.cursor()

            # Проверяем существование таблицы
            cursor.execute(f"""
                SELECT name FROM sqlite_master
                WHERE type='table' AND name='{PROJECT_METADATA_TABLE}'
            """)

            if not cursor.fetchone():
                log_warning(f"Таблица метаданных не существует")
                return False

            # Удаляем запись
            cursor.execute(
                f"DELETE FROM {PROJECT_METADATA_TABLE} WHERE key = ?",
                (key,)
            )
            conn.commit()

            deleted = cursor.rowcount > 0
            if deleted:
                log_info(f"Метаданные '{key}' удалены")
            else:
                log_warning(f"Метаданные '{key}' не найдены для удаления")

            return deleted

    def get_all_metadata(self) -> Dict[str, Any]:
        """
        Получение всех метаданных проекта

        Returns:
            Словарь метаданных
        """
        # Используем sqlite3 для чтения всех метаданных
        with sqlite3.connect(self.gpkg_path) as conn:
            cursor = conn.cursor()

            # Проверяем существование таблицы
            cursor.execute(f"""
                SELECT name FROM sqlite_master
                WHERE type='table' AND name='{PROJECT_METADATA_TABLE}'
            """)

            if not cursor.fetchone():
                return {}

            # Загружаем все метаданные
            cursor.execute(
                f"SELECT key, value, description FROM {PROJECT_METADATA_TABLE}"
            )
            result = cursor.fetchall()

            metadata = {}
            for row in result:
                metadata[row[0]] = {
                    'value': row[1],
                    'description': row[2]
                }

        return metadata

    def get_connection(self):
        """
        Получение прямого соединения с базой данных

        ВАЖНО: Вызывающий код ОБЯЗАН закрыть соединение!
        Рекомендуется использовать context manager:

            with project_db.get_connection() as conn:
                cursor = conn.cursor()
                # ... операции с БД
                conn.commit()
            # Соединение автоматически закрывается

        Альтернативно, закрыть вручную:
            conn = project_db.get_connection()
            try:
                # ... операции с БД
            finally:
                conn.close()

        Returns:
            sqlite3.Connection: Открытое соединение с GeoPackage
        """
        return sqlite3.connect(self.gpkg_path)

    def close(self) -> None:
        """
        Закрытие соединений с GeoPackage и освобождение ресурсов.

        ВАЖНО: Вызывать перед удалением/перемещением файла GPKG!

        Очищает кэш слоёв, что позволяет:
        - Перемещать/удалять файл GPKG
        - Избежать блокировки файла в Windows
        """
        # Очищаем кэш слоёв - это освобождает файловые дескрипторы
        # QgsVectorLayer при удалении из памяти закрывает соединение с источником
        if self.layers:
            layer_names = list(self.layers.keys())
            for layer_name in layer_names:
                layer = self.layers.pop(layer_name, None)
                # Явно удаляем ссылку на слой
                del layer
            log_info(f"ProjectDB: Закрыто {len(layer_names)} кэшированных слоёв")

        # Принудительный сброс кэша
        self.layers = {}
        log_info("ProjectDB: Соединение закрыто")
