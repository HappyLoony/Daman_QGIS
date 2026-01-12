# -*- coding: utf-8 -*-
"""
Менеджер проектов Daman_QGIS.
Управление созданием, открытием и сохранением проектов.
"""

import os
import shutil
from datetime import datetime
from typing import Optional, Dict, Any, Tuple

from qgis.core import (
    QgsProject, QgsCoordinateReferenceSystem, Qgis, QgsSnappingConfig
)
from qgis.gui import QgsMessageBar

from Daman_QGIS.constants import (
    MESSAGE_SUCCESS_DURATION, MESSAGE_INFO_DURATION
)
from Daman_QGIS.utils import log_info, log_warning, create_crs_from_string
from Daman_QGIS.database.project_db import ProjectDB
from Daman_QGIS.managers.M_4_reference_manager import get_reference_managers
from Daman_QGIS.managers.M_13_data_cleanup_manager import DataCleanupManager
from Daman_QGIS.managers.M_19_project_structure_manager import (
    get_project_structure_manager, FolderType, PROJECT_FOLDERS
)
from Daman_QGIS.database.schemas import ProjectSettings

class ProjectManager:
    """Менеджер проектов плагина"""
    
    def __init__(self, iface, plugin_dir: str) -> None:
        """
        Инициализация менеджера проектов

        Args:
            iface: Интерфейс QGIS
            plugin_dir: Путь к папке плагина
        """
        self.iface = iface
        self.plugin_dir = plugin_dir
        self.current_project = None  # Текущий проект
        self.project_db = None  # База данных проекта
        self.reference_managers = get_reference_managers()  # Менеджеры справочных данных
        self.settings = None  # Настройки текущего проекта
        self.plugin_version = ""  # Версия плагина (передается из main_plugin)
        self.structure_manager = get_project_structure_manager()  # M_19: координатор структуры
    
    def create_project(self,
                      project_name: str,
                      project_dir: str,
                      crs: Optional[QgsCoordinateReferenceSystem] = None) -> bool:
        """
        Создание нового проекта

        Args:
            project_name: Имя проекта
            project_dir: Папка для проекта
            crs: Система координат

        Returns:
            True если создание успешно
        """
        # Санитизация имени проекта для безопасного использования в путях
        cleanup_manager = DataCleanupManager()
        project_name = cleanup_manager.sanitize_filename(project_name)

        if not project_name:
            raise ValueError("M_1: Имя проекта пустое после санитизации")

        # Создаем структуру папок проекта
        project_path = os.path.join(project_dir, project_name)

        # Проверяем существование (проверка уже есть в диалоге, здесь просто страховка)
        if os.path.exists(project_path):
            return False  # Не выводим сообщение, т.к. это уже обработано в диалоге

        # Инициализируем M_19 для создания структуры
        self.structure_manager.project_root = project_path

        # Создаем полную структуру папок через M_19
        if not self.structure_manager.create_project_structure():
            raise Exception("Не удалось создать структуру папок проекта")

        # Получаем путь к GeoPackage через M_19 (create=True для нового проекта)
        gpkg_path = self.structure_manager.get_gpkg_path(create=True)
        if not gpkg_path:
            raise Exception("Не удалось определить путь к GeoPackage")
        self.project_db = ProjectDB(gpkg_path)

        if not crs:
            # По умолчанию используем WGS84
            crs = QgsCoordinateReferenceSystem("EPSG:4326")

        if not self.project_db.create(crs):
            # Очистка в случае ошибки
            if os.path.exists(project_path):
                try:
                    shutil.rmtree(project_path)
                except OSError as e:
                    log_warning(f"M_1_ProjectManager: Не удалось удалить директорию проекта {project_path}: {e}")
            raise Exception("Не удалось создать GeoPackage")

        # Создаем настройки проекта
        self.settings = ProjectSettings(
            project_name,
            datetime.now(),
            datetime.now()
        )
        # Заполняем дополнительные поля
        self.settings.crs_epsg = crs.postgisSrid()
        self.settings.gpkg_path = gpkg_path
        self.settings.work_dir = project_path
        self.settings.object_name = ""  # Будет заполнено в tool_1_1
        self.settings.object_type = ""  # Будет заполнено в tool_1_1
        self.settings.crs_description = crs.description() if crs else ""

        # Сохраняем настройки
        self.project_db.save_project_settings(self.settings)

        # Создаем файл проекта QGIS
        qgs_path = os.path.join(project_path, f"{project_name}.qgs")
        QgsProject.instance().setFileName(qgs_path)
        QgsProject.instance().setCrs(crs)

        # Диагностика: проверяем что CRS установлена перед сохранением
        current_crs = QgsProject.instance().crs()
        log_info(f"M_1: CRS перед write(): isValid={current_crs.isValid()}, authid={current_crs.authid()}, desc={current_crs.description()}")

        QgsProject.instance().write()

        self.current_project = project_path

        log_info(f"M_1_ProjectManager: Проект '{project_name}' создан: {project_path}")

        self.iface.messageBar().pushMessage(
            "Успех",
            f"Проект '{project_name}' успешно создан",
            level=Qgis.Success,
            duration=MESSAGE_SUCCESS_DURATION
        )

        return True
    
    def open_project(self, project_path: str) -> bool:
        """
        Открытие существующего проекта

        Args:
            project_path: Путь к папке проекта

        Returns:
            True если открытие успешно
        """
        # Проверяем существование проекта
        if not os.path.exists(project_path):
            raise Exception(f"Проект не найден: {project_path}")

        # Инициализируем M_19 для получения путей
        self.structure_manager.project_root = project_path

        # Ищем GeoPackage через M_19 (в .project/database/)
        gpkg_path = self.structure_manager.get_gpkg_path()

        if not gpkg_path or not os.path.exists(gpkg_path):
            raise Exception(f"GeoPackage не найден: {gpkg_path}")

        # Загружаем БД проекта
        self.project_db = ProjectDB(gpkg_path)

        # Загружаем настройки
        self.settings = self.project_db.load_project_settings()
        if not self.settings:
            # Создаем настройки по умолчанию
            project_name = os.path.basename(project_path)
            self.settings = ProjectSettings(
                project_name,
                datetime.now(),
                datetime.now()
            )
            self.settings.gpkg_path = gpkg_path
            self.settings.work_dir = project_path

        # Загружаем метаданные из таблицы project_metadata
        metadata = self.project_db.get_all_metadata()
        self._load_settings_from_metadata(metadata)

        # Ищем файл проекта QGIS
        qgs_files = [f for f in os.listdir(project_path) if f.endswith('.qgs')]
        if qgs_files:
            qgs_path = os.path.join(project_path, qgs_files[0])
            QgsProject.instance().read(qgs_path)
            # Файл проекта уже содержит все слои, дополнительная загрузка не нужна
            log_info(f"M_1_ProjectManager: Проект загружен из {qgs_path}. Слоев в проекте: {len(QgsProject.instance().mapLayers())}")
        else:
            # Если файла проекта нет, загружаем слои из GeoPackage
            log_warning(f"M_1_ProjectManager: Файл проекта .qgs не найден, загружаем слои из GeoPackage")
            layers = self.project_db.list_layers()
            for layer_name in layers:
                if layer_name.startswith('_'):  # Пропускаем служебные
                    continue
                if layer_name == 'project_metadata':  # Пропускаем таблицу метаданных
                    continue
                layer = self.project_db.get_layer(layer_name)
                if layer:
                    QgsProject.instance().addMapLayer(layer)
                    log_info(f"M_1_ProjectManager: Загружен слой {layer_name} из GeoPackage")

        self.current_project = project_path

        log_info(f"M_1_ProjectManager: Проект открыт: {project_path}")

        self.iface.messageBar().pushMessage(
            "Успех",
            f"Проект '{self.settings.name}' успешно открыт",
            level=Qgis.Success,
            duration=MESSAGE_SUCCESS_DURATION
        )

        return True
    
    def save_project(self) -> bool:
        """
        Сохранение текущего проекта

        Returns:
            True если сохранение успешно
        """
        if not self.current_project:
            raise Exception("Нет открытого проекта")

        # Обновляем время модификации
        if self.settings:
            self.settings.modified = datetime.now()
            if self.project_db:
                self.project_db.save_project_settings(self.settings)

        # Сохраняем проект QGIS
        if QgsProject.instance().fileName():
            # Защита от access violation в QgsSnappingConfig::writeProject
            # Очищаем невалидные ссылки на слои в snapping config
            self._cleanup_snapping_config()

            QgsProject.instance().write()

        log_info("M_1_ProjectManager: Проект сохранен")

        return True

    def _cleanup_snapping_config(self) -> None:
        """
        Очистка snapping config от невалидных ссылок на слои

        Предотвращает access violation при QgsProject.write() если
        snapping config содержит ссылки на удалённые слои.
        """
        try:
            project = QgsProject.instance()
            config = project.snappingConfig()

            # Получаем актуальные слои проекта
            valid_layer_ids = set(project.mapLayers().keys())

            # Проверяем индивидуальные настройки слоёв
            individual_configs = config.individualLayerSettings()
            invalid_layers = []

            for layer_id in individual_configs.keys():
                if layer_id not in valid_layer_ids:
                    invalid_layers.append(layer_id)

            # Удаляем невалидные слои из конфигурации
            if invalid_layers:
                for layer_id in invalid_layers:
                    config.removeLayers([layer_id])

                project.setSnappingConfig(config)
                log_warning(f"M_1: Удалено {len(invalid_layers)} невалидных слоёв из snapping config")

        except Exception as e:
            # Если очистка не удалась - логируем, но не блокируем сохранение
            log_warning(f"M_1: Не удалось очистить snapping config: {e}")
    
    def close_project(self, save_changes: bool = False) -> None:
        """Закрытие текущего проекта

        Args:
            save_changes: Если True, сохраняет изменения перед закрытием
        """
        # Сохраняем если есть изменения и это требуется
        if self.current_project and save_changes:
            self.save_project()

        # Закрываем соединение с GeoPackage (освобождает файл в Windows)
        if self.project_db:
            self.project_db.close()

        # Очищаем данные
        self.current_project = None
        self.project_db = None
        self.settings = None

        # Очищаем проект QGIS
        QgsProject.instance().clear()

        log_info("M_1_ProjectManager: Проект закрыт")

    def _load_settings_from_metadata(self, metadata: Dict[str, Any]) -> None:
        """
        Загрузка настроек проекта из метаданных БД

        Обновляет self.settings значениями из таблицы project_metadata.
        Вызывается из open_project() и init_from_native_project().

        Args:
            metadata: Словарь метаданных из project_db.get_all_metadata()
        """
        if not metadata or not self.settings:
            return

        # Полное наименование объекта
        if '1_1_full_name' in metadata:
            self.settings.object_name = metadata['1_1_full_name']['value']

        # Тип объекта
        if '1_2_object_type' in metadata:
            self.settings.object_type = metadata['1_2_object_type']['value']

        # Описание СК
        if '1_4_crs_description' in metadata:
            self.settings.crs_description = metadata['1_4_crs_description']['value']

        # EPSG код СК (поддержка USER:XXXXX для пользовательских CRS)
        if '1_4_crs_epsg' in metadata:
            crs_value = metadata['1_4_crs_epsg']['value']
            # Если это пользовательская CRS (USER:XXXXX), сохраняем как строку
            if isinstance(crs_value, str) and crs_value.upper().startswith('USER:'):
                self.settings.crs_epsg = crs_value
                log_info(f"M_1: Обнаружена пользовательская CRS: {crs_value}")
            else:
                try:
                    self.settings.crs_epsg = int(crs_value)
                except (ValueError, TypeError) as e:
                    log_warning(f"M_1: Не удалось преобразовать EPSG код '{crs_value}': {e}")

    def sync_metadata_to_layers(self, sync_options: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Синхронизация метаданных проекта со слоями

        Args:
            sync_options: Опции синхронизации
                - changed_fields: список измененных полей
                - crs_mode: 'redefine' для переопределения СК
                - new_crs: новая система координат

        Returns:
            tuple: (success: bool, message: str)
        """
        changed_fields = sync_options.get('changed_fields', [])

        # Обработка изменения СК
        if 'crs' in changed_fields:
            crs_mode = sync_options.get('crs_mode', 'redefine')
            new_crs = sync_options.get('new_crs')

            if not new_crs or not new_crs.isValid():
                return False, "Некорректная система координат"

            if crs_mode == 'redefine':
                # Переопределение СК (без трансформации координат)
                layers_updated = 0
                layers_failed = []

                # Обновляем слои в текущем проекте QGIS
                for layer in QgsProject.instance().mapLayers().values():
                    try:
                        # Переопределяем СК без трансформации
                        layer.setCrs(new_crs)
                        layers_updated += 1

                        log_info(f"M_1_ProjectManager: СК переопределена для слоя: {layer.name()}")
                    except Exception as e:
                        layers_failed.append(layer.name())
                        log_warning(f"M_1_ProjectManager: Ошибка переопределения СК для слоя {layer.name()}: {str(e)}")

                # Обновляем СК в слоях GeoPackage
                if self.project_db:
                    gpkg_layers = self.project_db.list_layers()
                    for layer_name in gpkg_layers:
                        if layer_name.startswith('_'):  # Пропускаем служебные
                            continue

                        try:
                            # Обновляем СК в GeoPackage
                            # Примечание: это требует прямого SQL запроса к gpkg_contents
                            with self.project_db.get_connection() as conn:
                                cursor = conn.cursor()
                                # Обновляем srs_id в gpkg_contents
                                cursor.execute(
                                    "UPDATE gpkg_contents SET srs_id = ? WHERE table_name = ?",
                                    (new_crs.postgisSrid(), layer_name)
                                )
                                conn.commit()
                        except Exception as e:
                            log_warning(f"M_1_ProjectManager: Ошибка обновления СК в GeoPackage для {layer_name}: {str(e)}")

                # Формируем результат
                if layers_failed:
                    return True, f"СК переопределена для {layers_updated} слоев. Ошибки: {', '.join(layers_failed)}"
                else:
                    return True, f"СК успешно переопределена для {layers_updated} слоев"

            elif crs_mode == 'reproject':
                # Перепроецирование не реализовано по требованию
                return False, "Перепроецирование не поддерживается в текущей версии"

        # Здесь можно добавить обработку других типов метаданных в будущем

        return True, "Синхронизация завершена"
    
    def get_current_version_path(self) -> Optional[str]:
        """
        Получение пути к папке текущей версии
        
        Returns:
            Путь к папке или None
        """
        if not self.current_project or not self.settings:
            return None
        
        # Используем M_19 для получения пути к рабочей папке
        structure_manager = get_project_structure_manager()
        structure_manager.project_root = self.current_project

        working_path = structure_manager.get_folder(FolderType.WORKING, create=True)

        if working_path:
            # Обновляем settings для консистентности
            working_name = PROJECT_FOLDERS[FolderType.WORKING]["name"]
            if self.settings.current_version != working_name:
                self.settings.current_version = working_name
            return working_path

        return None
    
    def get_import_path(self) -> Optional[str]:
        """
        Получение пути к папке импорта

        Returns:
            Путь к папке Импорт/ или None
        """
        if self.structure_manager.is_active():
            return self.structure_manager.get_folder(FolderType.IMPORT)
        return None

    def get_export_path(self) -> Optional[str]:
        """
        Получение пути к папке экспорта

        Returns:
            Путь к папке Экспорт/ или None
        """
        if self.structure_manager.is_active():
            return self.structure_manager.get_folder(FolderType.EXPORT)
        return None

    def get_rasters_path(self) -> Optional[str]:
        """
        Получение пути к папке растров

        Returns:
            Путь к папке Растры/ или None
        """
        if self.structure_manager.is_active():
            return self.structure_manager.get_folder(FolderType.RASTERS)
        return None
    
    def init_from_native_project(self) -> bool:
        """Инициализация состояния плагина из нативно открытого проекта QGIS

        Returns:
            True если это проект плагина и инициализация успешна
        """
        # Получаем путь к открытому проекту QGIS
        qgs_filename = QgsProject.instance().fileName()
        if not qgs_filename:
            return False

        # Получаем папку проекта
        project_dir = os.path.dirname(qgs_filename)

        # Инициализируем M_19 для управления структурой
        self.structure_manager.project_root = project_dir

        # Ищем GeoPackage через M_19 (в .project/database/)
        gpkg_path = self.structure_manager.get_gpkg_path()

        if not gpkg_path or not os.path.exists(gpkg_path):
            return False  # Не проект плагина

        # Это проект плагина! Инициализируем состояние
        log_info(f"M_1_ProjectManager: Обнаружен нативно открытый проект плагина: {project_dir}")

        # Загружаем БД проекта
        self.project_db = ProjectDB(gpkg_path)

        # Загружаем настройки
        self.settings = self.project_db.load_project_settings()
        if not self.settings:
            # Создаем настройки по умолчанию
            project_name = os.path.basename(project_dir)
            self.settings = ProjectSettings(
                project_name,
                datetime.now(),
                datetime.now()
            )
            self.settings.gpkg_path = gpkg_path
            self.settings.work_dir = project_dir

        # Загружаем метаданные из таблицы project_metadata
        metadata = self.project_db.get_all_metadata()
        self._load_settings_from_metadata(metadata)

        # Устанавливаем текущий проект
        self.current_project = project_dir

        log_info(f"M_1: Состояние плагина инициализировано из нативного проекта")

        return True
    
    def is_project_open(self) -> bool:
        """Проверка открыт ли проект"""
        # Проверяем не только внутреннее состояние, но и реальное состояние QGIS
        if self.current_project is None:
            # Попытка инициализации из нативно открытого проекта
            self.init_from_native_project()
            return self.current_project is not None

        # Проверяем, есть ли загруженный проект QGIS
        qgs_filename = QgsProject.instance().fileName()
        if not qgs_filename:
            # Проект QGIS закрыт, но состояние не очищено - очищаем
            self.current_project = None
            self.project_db = None
            self.settings = None
            return False

        return True
    
    def get_project_info(self) -> Dict[str, Any]:
        """
        Получение информации о текущем проекте
        
        Returns:
            Словарь с информацией о проекте
        """
        if not self.is_project_open():
            return {}
        
        info = {
            'name': self.settings.name if self.settings else 'Unknown',
            'path': self.current_project,
            'created': self.settings.created.isoformat() if self.settings else '',
            'modified': self.settings.modified.isoformat() if self.settings else '',
            'version': self.settings.version if (self.settings and self.settings.version) else self.plugin_version,
            'crs_epsg': self.settings.crs_epsg if self.settings else 0,
            'layers_count': len(self.project_db.list_layers()) if self.project_db else 0
        }
        
        return info
