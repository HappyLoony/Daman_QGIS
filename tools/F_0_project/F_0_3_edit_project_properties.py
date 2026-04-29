# -*- coding: utf-8 -*-
"""
Инструмент изменения свойств проекта
"""

import os
import shutil
from datetime import datetime
from typing import Dict, Any

from qgis.PyQt.QtWidgets import QMessageBox
from qgis.core import (
    QgsProject, Qgis,
    QgsCoordinateReferenceSystem
)

from Daman_QGIS.core.base_tool import BaseTool
from Daman_QGIS.utils import log_info, log_error, log_warning, log_success
from Daman_QGIS.managers import get_reference_managers, registry
from .submodules.Fsm_0_3_1_edit_project_dialog import EditProjectDialog
from .submodules.base_metadata_dialog import OPTIONAL_METADATA_DESCRIPTIONS
from Daman_QGIS.constants import MESSAGE_SUCCESS_DURATION, MESSAGE_INFO_DURATION


class F_0_3_EditProjectProperties(BaseTool):
    """Инструмент изменения свойств проекта"""
    
    def __init__(self, iface) -> None:
        """
        Инициализация инструмента

        Args:
            iface: Интерфейс QGIS
        """
        super().__init__(iface)
        self.project_manager = None
        
    def set_project_manager(self, project_manager) -> None:
        """Установка менеджера проектов"""
        self.project_manager = project_manager
        
    @property
    def name(self) -> str:
        """Имя инструмента"""
        return "F_0_3_Изменение свойств проекта"
    def run(self) -> None:
        """Запуск инструмента"""
        # Проверяем наличие менеджера проектов
        if not self.project_manager:
            QMessageBox.critical(
                None,
                "Ошибка",
                "Менеджер проектов не инициализирован"
            )
            return

        # Проверяем открыт ли проект
        if not self.project_manager.is_project_open():
            # Добавляем диагностическую информацию
            qgs_filename = QgsProject.instance().fileName()
            if qgs_filename:
                project_dir = os.path.dirname(qgs_filename)
                # Используем M_19 для проверки структуры проекта
                structure_manager = registry.get('M_19')
                structure_manager.project_root = project_dir
                gpkg_path = structure_manager.get_gpkg_path(create=False)

                if not gpkg_path or not os.path.exists(gpkg_path):
                    QMessageBox.warning(
                        None,
                        "Внимание",
                        f"Открытый проект QGIS не является проектом плагина.\n\n"
                        f"Путь: {project_dir}\n\n"
                        f"Файл project.gpkg не найден.\n\n"
                        f"Создайте новый проект через F_0_1."
                    )
                else:
                    QMessageBox.warning(
                        None,
                        "Внимание",
                        f"Не удалось инициализировать проект плагина.\n\n"
                        f"Путь: {project_dir}\n\n"
                        f"Попробуйте закрыть и открыть проект заново."
                    )
            else:
                QMessageBox.warning(
                    None,
                    "Внимание",
                    "Сначала откройте или создайте проект"
                )
            return

        # Получаем текущие метаданные
        current_metadata = {}
        if self.project_manager.project_db:
            current_metadata = self.project_manager.project_db.get_all_metadata()

        # Добавляем путь к проекту в метаданные
        if self.project_manager.current_project:
            current_metadata['project_path'] = {
                'value': self.project_manager.current_project,
                'description': 'Путь к проекту'
            }

        # Получаем справочную БД
        reference_managers = get_reference_managers()

        # Создаем и показываем диалог
        dialog = EditProjectDialog(None, current_metadata, reference_managers)

        if dialog.exec():
            # Получаем обновленные данные
            updated_data = dialog.get_updated_data()

            # Применяем изменения
            self.apply_changes(updated_data)
    

    def _move_project_folder(self, old_path: str, new_path: str) -> bool:
        """Перемещение папки проекта. Возвращает True если перемещена.

        Стратегия: copytree -> удаление источника (с допуском заблокированных файлов).
        Освобождает GPKG перед перемещением: закрывает ProjectDB и удаляет
        все слои из QGIS (иначе Windows блокирует файл).
        """
        if not old_path or old_path == new_path:
            return False

        # Проверяем что назначение не существует (до тяжёлых операций)
        if os.path.exists(new_path):
            raise ValueError(f"Папка {new_path} уже существует")

        try:
            # Сохраняем проект перед перемещением
            if self.project_manager:
                self.project_manager.save_project()

            # Закрываем соединение с GPKG (освобождает кэш слоёв)
            if self.project_manager and self.project_manager.project_db:
                self.project_manager.project_db.close()

            # Удаляем все слои из QGIS — они держат файловые дескрипторы GPKG
            QgsProject.instance().removeAllMapLayers()
            root = QgsProject.instance().layerTreeRoot()
            root.removeAllChildren()

            # Копируем в новое расположение
            shutil.copytree(old_path, new_path)
            log_info(f"F_0_3: Папка проекта скопирована: {old_path} -> {new_path}")

            # Удаляем источник; если некоторые файлы заблокированы — предупреждаем
            locked_files = self._try_remove_tree(old_path)
            if locked_files:
                names = [os.path.basename(f) for f in locked_files]
                log_warning(
                    f"F_0_3: Не удалось удалить {len(locked_files)} файлов "
                    f"из старой папки (заняты другим процессом): {', '.join(names)}"
                )
                self.iface.messageBar().pushMessage(
                    "Внимание",
                    f"Проект скопирован в новое расположение, но {len(locked_files)} "
                    f"файл(ов) в старой папке заблокирован(ы) другим процессом. "
                    f"Удалите старую папку вручную после закрытия программ.",
                    level=Qgis.MessageLevel.Warning,
                    duration=MESSAGE_INFO_DURATION
                )

            return True

        except FileNotFoundError as e:
            raise ValueError(f"Исходная папка проекта не найдена: {old_path}") from e
        except OSError as e:
            # Если copytree упал — удаляем частичную копию
            if os.path.exists(new_path):
                shutil.rmtree(new_path, ignore_errors=True)
            raise ValueError(f"Ошибка файловой системы при перемещении: {e}") from e

    @staticmethod
    def _try_remove_tree(path: str) -> list:
        """Удаление дерева папок с пропуском заблокированных файлов.

        Returns:
            Список путей файлов, которые не удалось удалить.
        """
        locked = []
        for root_dir, dirs, files in os.walk(path, topdown=False):
            for name in files:
                filepath = os.path.join(root_dir, name)
                try:
                    os.unlink(filepath)
                except PermissionError:
                    locked.append(filepath)
            for name in dirs:
                dirpath = os.path.join(root_dir, name)
                try:
                    os.rmdir(dirpath)
                except OSError:
                    pass  # Не пустая (содержит locked файлы)
        # Пробуем удалить корневую папку
        try:
            os.rmdir(path)
        except OSError:
            pass
        return locked

    def _update_core_metadata(self, db, updated_data: Dict[str, Any], changed_fields: list) -> None:
        """Обновление основных метаданных проекта"""
        if 'working_name' in changed_fields:
            db.set_metadata('1_0_working_name', updated_data['working_name'],
                          'Рабочее название (для папок и файлов)')
            log_info(f"F_0_3: Изменено рабочее название: {updated_data['working_name']}")

        if 'object_full_name' in changed_fields:
            db.set_metadata('1_1_object_full_name', updated_data['object_full_name'],
                          'Полное наименование объекта')
            log_info(f"F_0_3: Изменено полное наименование: {updated_data['object_full_name']}")

        if 'object_type' in changed_fields:
            db.set_metadata('1_2_object_type', updated_data['object_type'],
                          'Тип объекта (area - площадной, linear - линейный)')
            db.set_metadata('1_2_object_type_name', updated_data['object_type_name'],
                          'Наименование типа объекта')
            log_info(f"F_0_3: Изменен тип объекта: {updated_data['object_type_name']}")

        if 'object_type_value' in changed_fields:
            # Сохраняем только если значение задано
            if updated_data.get('object_type_value'):
                db.set_metadata('1_2_1_object_type_value', updated_data['object_type_value'],
                              'Значение линейного объекта (federal/regional/local)')
                db.set_metadata('1_2_1_object_type_value_name', updated_data['object_type_value_name'],
                              'Наименование значения линейного объекта')
                log_info(f"F_0_3: Изменено значение линейного объекта: {updated_data['object_type_value_name']}")
            else:
                # Если поле отключено (площадной объект), удаляем значение
                db.delete_metadata('1_2_1_object_type_value')
                db.delete_metadata('1_2_1_object_type_value_name')
                log_info("F_0_3: Значение линейного объекта удалено (тип объекта: площадной)")

        if 'doc_type' in changed_fields:
            db.set_metadata('1_5_doc_type', updated_data['doc_type'],
                          'Тип документации (dpt - ДПТ, masterplan - Мастер-план)')
            db.set_metadata('1_5_doc_type_name', updated_data['doc_type_name'],
                          'Наименование типа документации')
            log_info(f"F_0_3: Изменен тип документации: {updated_data['doc_type_name']}")

        if 'stage' in changed_fields:
            db.set_metadata('1_6_stage', updated_data['stage'],
                          'Этап разработки (initial - первичная, changes - внесение изменений)')
            db.set_metadata('1_6_stage_name', updated_data['stage_name'],
                          'Наименование этапа разработки')
            log_info(f"F_0_3: Изменен этап разработки: {updated_data['stage_name']}")

        if 'is_single_object' in changed_fields:
            is_single = "Да" if updated_data.get('is_single_object', True) else "Нет"
            db.set_metadata('1_7_is_single_object', is_single,
                          'Единственный объект (влияет на склонение в наименованиях)')
            label = is_single
            log_info(f"F_0_3: Изменен признак единственного объекта: {label}")

        if 'code' in changed_fields:
            db.set_metadata('2_1_code', updated_data['code'],
                          'Шифр (внутренняя кодировка объекта)')
            log_info(f"F_0_3: Изменен шифр: {updated_data['code']}")

        if 'release_date' in changed_fields:
            db.set_metadata('2_2_date', updated_data['release_date'],
                          'Дата выпуска для титулов, обложек, и штампов')
            log_info(f"F_0_3: Изменена дата выпуска: {updated_data['release_date']}")

    def _update_crs_metadata(self, db, updated_data: Dict[str, Any], changed_fields: list) -> bool:
        """Обновление метаданных системы координат. Возвращает True если СК изменена."""
        crs_changed = False

        if 'crs' in changed_fields:
            db.set_metadata('1_4_2_crs_epsg', str(updated_data['crs_epsg']),
                          'Код системы координат (EPSG или USER)')
            db.set_metadata('1_4_2_crs_wkt', updated_data['crs_wkt'],
                          'WKT определение системы координат')
            db.set_metadata('1_4_2_crs_description', updated_data['crs_description'],
                          'Описание системы координат')
            crs_changed = True
            log_info(f"F_0_3: Изменена система координат: {updated_data['crs_description']}")

        if 'region_code' in changed_fields:
            db.set_metadata('1_4_region_code', updated_data['region_code'],
                          'Код региона')
            log_info(f"F_0_3: Изменен код региона: {updated_data['region_code']}")

        if 'zone_code' in changed_fields:
            db.set_metadata('1_4_1_zone_code', updated_data['zone_code'],
                          'Код зоны')
            log_info(f"F_0_3: Изменен код зоны: {updated_data['zone_code']}")

        return crs_changed

    def _update_additional_metadata(self, db, updated_data: Dict[str, Any], changed_fields: list) -> None:
        """Обновление дополнительных метаданных проекта"""
        for field, (key, desc) in OPTIONAL_METADATA_DESCRIPTIONS.items():
            if field in changed_fields:
                db.set_metadata(key, updated_data[field], desc)
                log_info(f"F_0_3: Изменен {field}: {updated_data[field]}")

    def _update_project_manager_settings(self, updated_data: Dict[str, Any], changed_fields: list) -> None:
        """Обновление настроек в менеджере проектов"""
        if not self.project_manager or not self.project_manager.settings:
            return

        if 'object_full_name' in changed_fields:
            self.project_manager.settings.object_name = updated_data['object_full_name']
        if 'object_type' in changed_fields:
            self.project_manager.settings.object_type = updated_data['object_type']
        if 'crs' in changed_fields:
            self.project_manager.settings.crs_epsg = updated_data['crs_epsg']
            self.project_manager.settings.crs_description = updated_data['crs_description']

        self.project_manager.settings.modified = datetime.now()
        if self.project_manager.project_db:
            self.project_manager.project_db.save_project_settings(self.project_manager.settings)

    def _sync_crs_to_layers(self, updated_data: Dict[str, Any]) -> None:
        """Синхронизация системы координат со слоями"""
        sync_options = {
            'changed_fields': ['crs'],
            'crs_mode': 'redefine',
            'new_crs': updated_data['crs']
        }

        if self.project_manager:
            success, message = self.project_manager.sync_metadata_to_layers(sync_options)
        else:
            success, message = False, "Менеджер проектов не инициализирован"

        if success:
            log_success(message)
        else:
            log_warning(f"F_0_3: Предупреждение при синхронизации: {message}")

    def _build_changes_summary(self, updated_data: Dict[str, Any], changed_fields: list, crs_changed: bool) -> list:
        """Создание текстового резюме изменений"""
        changes = []
        if 'working_name' in changed_fields:
            changes.append(f"• Рабочее название: {updated_data['working_name']}")
        if 'object_full_name' in changed_fields:
            changes.append(f"• Полное наименование: {updated_data['object_full_name']}")
        if 'object_type' in changed_fields:
            changes.append(f"• Тип: {updated_data['object_type_name']}")
        if 'object_type_value' in changed_fields:
            if updated_data.get('object_type_value'):
                changes.append(f"• Значение линейного объекта: {updated_data['object_type_value_name']}")
            else:
                changes.append("• Значение линейного объекта: удалено")
        if 'doc_type' in changed_fields:
            changes.append(f"• Тип документации: {updated_data['doc_type_name']}")
        if 'stage' in changed_fields:
            changes.append(f"• Этап разработки: {updated_data['stage_name']}")
        if 'is_single_object' in changed_fields:
            label = "Да" if updated_data.get('is_single_object', True) else "Нет"
            changes.append(f"• Единственный объект: {label}")
        if 'code' in changed_fields:
            changes.append(f"• Шифр: {updated_data['code']}")
        if 'release_date' in changed_fields:
            changes.append(f"• Дата выпуска: {updated_data['release_date']}")
        if 'crs' in changed_fields:
            changes.append(f"• СК: {updated_data['crs_description']}")
            if crs_changed:
                changes.append("• СК переопределена для всех слоев")
        if 'region_code' in changed_fields:
            changes.append(f"• Код региона: {updated_data['region_code']}")
        if 'zone_code' in changed_fields:
            changes.append(f"• Код зоны: {updated_data['zone_code']}")
        if 'company' in changed_fields:
            changes.append(f"• Компания: {updated_data['company']}")
        if 'city' in changed_fields:
            changes.append(f"• Город: {updated_data['city']}")
        if 'customer' in changed_fields:
            changes.append(f"• Заказчик: {updated_data['customer']}")
        if 'general_director' in changed_fields:
            changes.append(f"• Генеральный директор: {updated_data['general_director']}")
        if 'technical_director' in changed_fields:
            changes.append(f"• Технический директор: {updated_data['technical_director']}")
        if 'cover' in changed_fields:
            changes.append(f"• Обложка: {updated_data['cover']}")
        if 'title_start' in changed_fields:
            changes.append(f"• Начальный лист титула: {updated_data['title_start']}")
        if 'main_scale' in changed_fields:
            changes.append(f"• Основной масштаб: {updated_data['main_scale']}")
        if 'developer' in changed_fields:
            changes.append(f"• Разработчик: {updated_data['developer']}")
        if 'examiner' in changed_fields:
            changes.append(f"• Проверяющий: {updated_data['examiner']}")
        if 'quality_control' in changed_fields:
            changes.append(f"• Н.Контроль: {updated_data['quality_control']}")
        if 'sheet_format' in changed_fields:
            changes.append(f"• Формат листа: {updated_data['sheet_format']}")
        if 'sheet_orientation' in changed_fields:
            changes.append(f"• Ориентация листа: {updated_data['sheet_orientation']}")
        return changes
    def apply_changes(self, updated_data: Dict[str, Any]) -> None:
        """Применение изменений к проекту"""
        if not self.project_manager or not self.project_manager.project_db:
            raise ValueError("База данных проекта не инициализирована")

        changed_fields = updated_data.get('changed_fields', [])

        # 1. Перенос папки проекта (до обновления метаданных!)
        project_folder_changed = False
        if 'project_folder' in changed_fields:
            old_path = self.project_manager.current_project if self.project_manager else None
            new_path = updated_data['project_folder']
            if old_path is not None:
                project_folder_changed = self._move_project_folder(old_path, new_path)

        # Если папка перемещена — переоткрываем проект для актуального db
        if project_folder_changed and self.project_manager:
            self.project_manager.close_project()
            self.project_manager.open_project(updated_data['project_folder'])

        # Получаем актуальную ссылку на БД (после возможного переоткрытия)
        db = self.project_manager.project_db
        if not db:
            raise ValueError("База данных проекта не инициализирована")

        # 2. Обновление основных метаданных
        self._update_core_metadata(db, updated_data, changed_fields)

        # 3. Обновление метаданных СК
        crs_changed = self._update_crs_metadata(db, updated_data, changed_fields)

        # 4. Обновление дополнительных метаданных
        self._update_additional_metadata(db, updated_data, changed_fields)

        # 5. Сохранение пути к папке проекта (только если не было перемещения)
        if 'project_folder' in changed_fields and not project_folder_changed:
            db.set_metadata('1_3_project_folder', updated_data['project_folder'],
                          'Путь к папке проекта')

        # 6. Обновление даты модификации
        db.set_metadata('modified_date', datetime.now().isoformat(),
                       'Дата последнего изменения проекта')

        # 7. Обновление настроек менеджера
        self._update_project_manager_settings(updated_data, changed_fields)

        # 8. Синхронизация СК со слоями
        if crs_changed:
            self._sync_crs_to_layers(updated_data)

        # 9. Установка СК для проекта QGIS
        if 'crs' in changed_fields and updated_data.get('crs'):
            QgsProject.instance().setCrs(updated_data['crs'])

        # 10. Сохранение проекта
        if self.project_manager:
            self.project_manager.save_project()

        # 11. Показ сообщения об успехе
        changes_text = self._build_changes_summary(updated_data, changed_fields, crs_changed)

        if project_folder_changed:
            msg = f"Проект успешно перемещен в:\n{updated_data['project_folder']}\n\n" \
                  "Проект автоматически переоткрыт из нового расположения."
            if changes_text:
                msg += "\n\nДополнительные изменения:\n" + "\n".join(changes_text)
            QMessageBox.information(None, "Проект перемещен", msg)
            log_info(f"F_0_3: Проект перемещен + {len(changes_text)} изменений")
        elif changes_text:
            QMessageBox.information(
                None, "Свойства проекта изменены",
                "Успешно применены изменения:\n\n" + "\n".join(changes_text)
            )
            log_info(f"F_0_3: Свойства проекта изменены ({len(changes_text)} изменений)")
        else:
            log_info("F_0_3: Изменений не обнаружено")

