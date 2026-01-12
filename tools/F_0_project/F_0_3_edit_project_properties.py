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
from Daman_QGIS.managers import get_reference_managers, get_project_structure_manager
from .submodules.Fsm_0_3_1_edit_project_dialog import EditProjectDialog
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
                structure_manager = get_project_structure_manager()
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

        if dialog.exec_():
            # Получаем обновленные данные
            updated_data = dialog.get_updated_data()

            # Применяем изменения
            self.apply_changes(updated_data)
    

    def _move_project_folder(self, old_path: str, new_path: str) -> bool:
        """Перемещение папки проекта. Возвращает True если перемещена.

        Использует try-except вместо предварительных проверок os.path.exists()
        для избежания TOCTOU race condition.
        """
        if not old_path or old_path == new_path:
            return False

        try:
            # Сохраняем проект перед перемещением
            if self.project_manager:
                self.project_manager.save_project()

            # Перемещаем папку (shutil.move выбросит исключение если new_path существует
            # или old_path не существует)
            shutil.move(old_path, new_path)
            log_info(f"F_0_3: Папка проекта перемещена: {old_path} -> {new_path}")
            return True

        except FileNotFoundError as e:
            # old_path не существует
            raise ValueError(f"Исходная папка проекта не найдена: {old_path}") from e
        except FileExistsError as e:
            # new_path уже существует (Windows)
            raise ValueError(f"Папка {new_path} уже существует") from e
        except shutil.Error as e:
            # shutil.move может выбросить shutil.Error если new_path существует (Unix)
            # или при других ошибках перемещения
            error_msg = str(e)
            if "already exists" in error_msg.lower() or "destination path" in error_msg.lower():
                raise ValueError(f"Папка {new_path} уже существует") from e
            raise ValueError(f"Не удалось переместить папку проекта: {error_msg}") from e
        except OSError as e:
            raise ValueError(f"Ошибка файловой системы при перемещении: {e}") from e

    def _update_core_metadata(self, db, updated_data: Dict[str, Any], changed_fields: list) -> None:
        """Обновление основных метаданных проекта"""
        if 'working_name' in changed_fields:
            db.set_metadata('1_0_working_name', updated_data['working_name'],
                          'Рабочее название (для папок и файлов)')
            log_info(f"F_0_3: Изменено рабочее название: {updated_data['working_name']}")

        if 'full_name' in changed_fields:
            db.set_metadata('1_1_full_name', updated_data['full_name'],
                          'Полное наименование объекта')
            log_info(f"F_0_3: Изменено полное наименование: {updated_data['full_name']}")

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
                          'Тип документации (dpt - ДПТ, masterplan - Мастер-План)')
            db.set_metadata('1_5_doc_type_name', updated_data['doc_type_name'],
                          'Наименование типа документации')
            log_info(f"F_0_3: Изменен тип документации: {updated_data['doc_type_name']}")

        if 'stage' in changed_fields:
            db.set_metadata('1_6_stage', updated_data['stage'],
                          'Этап разработки (initial - первичная, changes - внесение изменений)')
            db.set_metadata('1_6_stage_name', updated_data['stage_name'],
                          'Наименование этапа разработки')
            log_info(f"F_0_3: Изменен этап разработки: {updated_data['stage_name']}")

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
            db.set_metadata('1_4_crs_epsg', str(updated_data['crs_epsg']),
                          'Код системы координат (EPSG или USER)')
            db.set_metadata('1_4_crs_wkt', updated_data['crs_wkt'],
                          'WKT определение системы координат')
            db.set_metadata('1_4_crs_description', updated_data['crs_description'],
                          'Описание системы координат')
            crs_changed = True
            log_info(f"F_0_3: Изменена система координат: {updated_data['crs_description']}")

        if 'crs_short_name' in changed_fields:
            db.set_metadata('1_4_crs_short_name', updated_data['crs_short_name'],
                          'Короткое название СК для приложений')
            log_info(f"F_0_3: Изменено короткое название СК: {updated_data['crs_short_name']}")

        return crs_changed

    def _update_additional_metadata(self, db, updated_data: Dict[str, Any], changed_fields: list) -> None:
        """Обновление дополнительных метаданных проекта"""
        metadata_map = {
            'company': ('2_3_company', 'Компания выполняющая договор', 'компания'),
            'city': ('2_4_city', 'Город', 'город'),
            'customer': ('2_5_customer', 'Заказчик', 'заказчик'),
            'general_director': ('2_6_general_director', 'Генеральный директор', 'генеральный директор'),
            'technical_director': ('2_7_technical_director', 'Технический директор', 'технический директор'),
            'cover': ('2_8_cover', 'Обложка обычно не наша', 'обложка'),
            'title_start': ('2_9_title_start', 'С какого листа начинается наш титул, так как перед нами могут быть еще подрядчики', 'начальный лист титула'),
            'main_scale': ('2_10_main_scale', 'Основной масштаб, основной массы чертежей (прописано в ТЗ)', 'основной масштаб'),
            'developer': ('2_11_developer', 'Разаботал', 'разработчик'),
            'examiner': ('2_12_examiner', 'Проверил', 'проверяющий'),
        }

        for field, (key, desc, log_name) in metadata_map.items():
            if field in changed_fields:
                db.set_metadata(key, updated_data[field], desc)
                log_info(f"F_0_3: Изменен {log_name}: {updated_data[field]}")

    def _update_project_manager_settings(self, updated_data: Dict[str, Any], changed_fields: list) -> None:
        """Обновление настроек в менеджере проектов"""
        if not self.project_manager or not self.project_manager.settings:
            return

        if 'full_name' in changed_fields:
            self.project_manager.settings.object_name = updated_data['full_name']
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
        if 'full_name' in changed_fields:
            changes.append(f"• Полное наименование: {updated_data['full_name']}")
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
        if 'code' in changed_fields:
            changes.append(f"• Шифр: {updated_data['code']}")
        if 'release_date' in changed_fields:
            changes.append(f"• Дата выпуска: {updated_data['release_date']}")
        if 'crs' in changed_fields:
            changes.append(f"• СК: {updated_data['crs_description']}")
            if crs_changed:
                changes.append("• СК переопределена для всех слоев")
        return changes
    def apply_changes(self, updated_data: Dict[str, Any]) -> None:
        """Применение изменений к проекту"""
        if not self.project_manager or not self.project_manager.project_db:
            raise ValueError("База данных проекта не инициализирована")

        db = self.project_manager.project_db
        changed_fields = updated_data.get('changed_fields', [])

        # 1. Перенос папки проекта
        project_folder_changed = False
        if 'project_folder' in changed_fields:
            old_path = self.project_manager.current_project if self.project_manager else None
            new_path = updated_data['project_folder']
            if old_path is not None:
                project_folder_changed = self._move_project_folder(old_path, new_path)

        # 2. Обновление основных метаданных
        self._update_core_metadata(db, updated_data, changed_fields)

        # 3. Обновление метаданных СК
        crs_changed = self._update_crs_metadata(db, updated_data, changed_fields)

        # 4. Обновление дополнительных метаданных
        self._update_additional_metadata(db, updated_data, changed_fields)

        # 5. Сохранение пути к папке проекта
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

        # 10. Переоткрытие проекта если папка была перемещена
        if project_folder_changed and self.project_manager:
            self.project_manager.close_project()
            self.project_manager.open_project(updated_data['project_folder'])
            QMessageBox.information(
                None, "Проект перемещен",
                f"Проект успешно перемещен в:\n{updated_data['project_folder']}\n\n"
                "Проект автоматически переоткрыт из нового расположения."
            )
            return

        # 11. Сохранение проекта
        if self.project_manager:
            self.project_manager.save_project()

        # 12. Показ сообщения об успехе
        changes_text = self._build_changes_summary(updated_data, changed_fields, crs_changed)

        if changes_text:
            QMessageBox.information(
                None, "Свойства проекта изменены",
                "Успешно применены изменения:\n\n" + "\n".join(changes_text)
            )
            self.iface.messageBar().pushMessage(
                "Успех", "Свойства проекта успешно изменены",
                level=Qgis.Success, duration=MESSAGE_INFO_DURATION
            )
        else:
            self.iface.messageBar().pushMessage(
                "Информация", "Изменений не обнаружено",
                level=Qgis.Info, duration=MESSAGE_SUCCESS_DURATION
            )

