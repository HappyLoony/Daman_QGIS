# -*- coding: utf-8 -*-
"""
Менеджер проектов Daman_QGIS.
Управление созданием, открытием и сохранением проектов.
"""

import os
import shutil
from datetime import datetime
from typing import Optional, Dict, Any, Tuple, Set

from qgis.core import (
    QgsProject, QgsCoordinateReferenceSystem, Qgis, QgsSnappingConfig
)
from qgis.gui import QgsMessageBar

from Daman_QGIS.constants import (
    MESSAGE_SUCCESS_DURATION, MESSAGE_INFO_DURATION
)
from Daman_QGIS.utils import log_info, log_warning, create_crs_from_string
from Daman_QGIS.database.project_db import ProjectDB
from .M_19_project_structure_manager import FolderType, PROJECT_FOLDERS
from Daman_QGIS.database.schemas import ProjectSettings

# Lazy imports для избежания циклических зависимостей
# get_reference_managers, DataCleanupManager, get_project_structure_manager
# импортируются внутри методов

__all__ = ['ProjectManager']


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
        self.settings = None  # Настройки текущего проекта
        self.plugin_version = ""  # Версия плагина (передается из main_plugin)
        # Lazy init для избежания циклических импортов
        self._reference_managers = None

    @property
    def reference_managers(self):
        """Ленивая инициализация менеджеров справочных данных"""
        if self._reference_managers is None:
            from Daman_QGIS.managers import get_reference_managers
            self._reference_managers = get_reference_managers()
        return self._reference_managers

    @property
    def structure_manager(self):
        """Получение координатора структуры (M_19) из реестра"""
        from Daman_QGIS.managers import registry
        return registry.get('M_19')
    
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
        from Daman_QGIS.managers import DataCleanupManager
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

        # Регистрируем pipeline CRS (REMARK или server cache)
        self._register_pipeline_for_project()

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
            read_success = QgsProject.instance().read(qgs_path)
            if not read_success:
                log_warning(f"M_1_ProjectManager: Не удалось загрузить файл проекта {qgs_path}")
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

        # Подсчитываем слои
        layer_count = len(QgsProject.instance().mapLayers())
        log_info(f"M_1_ProjectManager: Проект открыт: {project_path}")

        # Показываем сообщение с количеством слоёв
        if layer_count == 0:
            self.iface.messageBar().pushMessage(
                "Успех",
                f"Проект '{self.settings.name}' открыт (пустой проект, слои не добавлены)",
                level=Qgis.Success,
                duration=MESSAGE_SUCCESS_DURATION
            )
        else:
            self.iface.messageBar().pushMessage(
                "Успех",
                f"Проект '{self.settings.name}' успешно открыт ({layer_count} слоев)",
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

            # individualLayerSettings() возвращает Dict[QgsVectorLayer, IndividualLayerSettings]
            individual_configs = config.individualLayerSettings()
            invalid_layers = []

            for layer in individual_configs.keys():
                if layer.id() not in valid_layer_ids:
                    invalid_layers.append(layer)

            # Удаляем невалидные слои из конфигурации
            if invalid_layers:
                names = []
                for layer in invalid_layers:
                    config.removeLayers([layer])
                    names.append(layer.name() or layer.id()[:12])

                project.setSnappingConfig(config)
                log_info(f"M_1: Очистка snapping config: удалено {len(invalid_layers)} "
                         f"осиротевших ссылок на удалённые слои ({', '.join(names)})")

        except Exception as e:
            # Если очистка не удалась - логируем, но не блокируем сохранение
            log_warning(f"M_1: Не удалось очистить snapping config: {e}")

    def _get_wfs_layer_names(self) -> Set[str]:
        """
        Получить имена WFS слоёв, которые не должны менять CRS.

        Динамически загружает из Base_layers.json слои с creating_function="F_1_2_Загрузка Web карт".
        Эти слои хранятся в EPSG:3857 и не должны менять CRS при переопределении проекции.

        Returns:
            Set[str]: Множество имён слоёв для исключения
        """
        try:
            from Daman_QGIS.managers import LayerReferenceManager

            layer_ref_manager = LayerReferenceManager()
            excluded = layer_ref_manager.get_layer_names_by_creating_function(
                "F_1_2_Загрузка Web карт"
            )
            return set(excluded)
        except Exception:
            return set()

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

        # Сбрасываем project_root чтобы structure_manager.is_active() вернул False
        if hasattr(self, 'structure_manager') and self.structure_manager:
            self.structure_manager.project_root = None

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

                # WFS слои (EPSG:3857) не должны менять CRS
                excluded_layers = self._get_wfs_layer_names()

                # Получаем слои проекта для фильтрации GPKG
                project_layer_names = set()

                # Обновляем слои в текущем проекте QGIS
                for layer in QgsProject.instance().mapLayers().values():
                    try:
                        if layer.name() in excluded_layers:
                            continue

                        project_layer_names.add(layer.name())

                        # Переопределяем СК без трансформации
                        layer.setCrs(new_crs)
                        layers_updated += 1
                    except Exception as e:
                        layers_failed.append(layer.name())
                        log_warning(f"M_1_ProjectManager: Ошибка переопределения СК для слоя {layer.name()}: {str(e)}")

                # Обновляем СК в слоях GeoPackage (только для слоёв, присутствующих в проекте)
                gpkg_skipped = 0
                if self.project_db:
                    gpkg_layers = self.project_db.list_layers()
                    srid = new_crs.postgisSrid()

                    # Для кастомных CRS (МСК) postgisSrid() == 0
                    # Регистрируем в gpkg_spatial_ref_sys с srs_id >= 100000
                    if srid <= 0:
                        srid = self._register_custom_crs_in_gpkg(new_crs)
                        if srid <= 0:
                            log_warning(f"M_1_ProjectManager: Не удалось зарегистрировать кастомную CRS в GPKG")

                    if srid > 0:
                        for layer_name in gpkg_layers:
                            if layer_name.startswith('_'):  # Пропускаем служебные
                                continue
                            if layer_name in excluded_layers:
                                continue
                            # Пропускаем таблицы-призраки (нет в проекте)
                            if layer_name not in project_layer_names:
                                gpkg_skipped += 1
                                continue

                            try:
                                with self.project_db.get_connection() as conn:
                                    cursor = conn.cursor()

                                    # Check if SRID exists in gpkg_spatial_ref_sys
                                    cursor.execute(
                                        "SELECT srs_id FROM gpkg_spatial_ref_sys WHERE srs_id = ?",
                                        (srid,)
                                    )
                                    if not cursor.fetchone():
                                        layers_failed.append(layer_name)
                                        continue

                                    # Update srs_id in gpkg_contents
                                    cursor.execute(
                                        "UPDATE gpkg_contents SET srs_id = ? WHERE table_name = ?",
                                        (srid, layer_name)
                                    )
                                    # Update srs_id in gpkg_geometry_columns
                                    cursor.execute(
                                        "UPDATE gpkg_geometry_columns SET srs_id = ? WHERE table_name = ?",
                                        (srid, layer_name)
                                    )

                                    conn.commit()

                            except Exception as e:
                                layers_failed.append(layer_name)

                    if gpkg_skipped:
                        log_info(f"M_1_ProjectManager: Пропущено {gpkg_skipped} таблиц GPKG (нет в проекте)")

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
    
    def _register_custom_crs_in_gpkg(self, crs) -> int:
        """
        Регистрация кастомной CRS (МСК) в gpkg_spatial_ref_sys.

        Для CRS без EPSG-кода (postgisSrid() == 0) генерирует srs_id >= 100000
        на основе хеша WKT-определения (детерминированный ID).

        Returns:
            srs_id > 0 при успехе, 0 при ошибке
        """
        import hashlib

        wkt = crs.toWkt()
        if not wkt:
            log_warning("M_1_ProjectManager: Пустое WKT для кастомной CRS")
            return 0

        # Детерминированный srs_id из хеша WKT (диапазон 100000-999999)
        wkt_hash = int(hashlib.md5(wkt.encode('utf-8')).hexdigest()[:6], 16)
        srid = 100000 + (wkt_hash % 900000)

        srs_name = crs.description() or "Custom CRS"

        try:
            with self.project_db.get_connection() as conn:
                cursor = conn.cursor()

                # Проверяем, не зарегистрирована ли уже эта CRS
                cursor.execute(
                    "SELECT srs_id FROM gpkg_spatial_ref_sys WHERE srs_id = ?",
                    (srid,)
                )
                if cursor.fetchone():
                    log_info(f"M_1_ProjectManager: Кастомная CRS уже зарегистрирована (srs_id={srid})")
                    return srid

                cursor.execute(
                    "INSERT INTO gpkg_spatial_ref_sys "
                    "(srs_name, srs_id, organization, organization_coordsys_id, definition) "
                    "VALUES (?, ?, 'QGIS', ?, ?)",
                    (srs_name, srid, srid, wkt)
                )
                conn.commit()

            log_info(f"M_1_ProjectManager: Кастомная CRS зарегистрирована в GPKG (srs_id={srid}, {srs_name})")
            return srid

        except Exception as e:
            log_warning(f"M_1_ProjectManager: Ошибка регистрации кастомной CRS: {e}")
            return 0

    def get_current_version_path(self) -> Optional[str]:
        """
        Получение пути к папке текущей версии

        Returns:
            Путь к папке или None
        """
        if not self.current_project or not self.settings:
            return None
        
        # Используем M_19 для получения пути к рабочей папке
        # Используем self.structure_manager (lazy property)
        self.structure_manager.project_root = self.current_project

        working_path = self.structure_manager.get_folder(FolderType.WORKING, create=True)

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

        # Регистрируем pipeline CRS (REMARK или server cache)
        self._register_pipeline_for_project()

        log_info(f"M_1: Состояние плагина инициализировано из нативного проекта")

        return True
    
    def _register_pipeline_for_project(self):
        """Register coordinate pipeline for the project CRS.

        Priority chain:
        1. REMARK in CRS WKT2 (author's F_0_5 calibration)
        2. PipelineCache from /validate response (licensed users)
        3. Absent -- silent return, CRS works with towgs84 accuracy

        Both directions registered (horner does not support +inv).
        """
        try:
            project_crs = QgsProject.instance().crs()
            if not project_crs.isValid():
                return

            pipeline_str = None
            source = None

            # Priority 1: REMARK in CRS (author's calibration)
            wkt = project_crs.toWkt(Qgis.CrsWktVariant.Wkt2_2019)
            marker = 'DAMAN_PIPELINE:'
            idx = wkt.find(marker)
            if idx != -1:
                start = idx + len(marker)
                end = wkt.find('"', start)
                if end != -1:
                    candidate = wkt[start:end]
                    if candidate and '+proj=pipeline' in candidate:
                        pipeline_str = candidate
                        source = "REMARK"

            # Priority 2: PipelineCache (server-delivered)
            if not pipeline_str:
                region_code = self._get_region_code_from_metadata()
                if region_code:
                    from Daman_QGIS.managers.infrastructure.submodules.Msm_29_5_pipeline_cache import PipelineCache
                    pipeline_str = PipelineCache.get_instance().get_pipeline(region_code)
                    if pipeline_str:
                        source = "server cache"

            if not pipeline_str:
                return

            # Register for both directions (horner doesn't support +inv)
            epsg_3857 = QgsCoordinateReferenceSystem("EPSG:3857")
            ctx = QgsProject.instance().transformContext()
            ctx.addCoordinateOperation(epsg_3857, project_crs, pipeline_str, allowFallback=True)
            ctx.addCoordinateOperation(project_crs, epsg_3857, pipeline_str, allowFallback=True)
            QgsProject.instance().setTransformContext(ctx)

            log_info(f"M_1: Pipeline зарегистрирован для {project_crs.authid()} (source: {source})")

        except Exception as e:
            log_warning(f"M_1: Ошибка регистрации pipeline: {e}")

    def _get_region_code_from_metadata(self) -> Optional[str]:
        """Get region code from project metadata for pipeline lookup."""
        if not self.project_db:
            return None
        try:
            data = self.project_db.get_metadata('1_4_1_code_region')
            if data:
                return data.get('value')
        except Exception:
            pass
        return None

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
            if self.project_db:
                self.project_db.close()
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
