# -*- coding: utf-8 -*-
"""
Инструмент открытия существующего проекта
"""

import os
from typing import Dict, Any

from qgis.PyQt.QtWidgets import QMessageBox, QFileDialog
from qgis.core import (
    QgsProject,
    QgsCoordinateReferenceSystem,
    Qgis
)

from Daman_QGIS.core.base_tool import BaseTool
from Daman_QGIS.constants import MESSAGE_SUCCESS_DURATION, MESSAGE_INFO_DURATION, PLUGIN_NAME
from Daman_QGIS.utils import log_info, log_error, log_success, log_warning, create_crs_from_string
from Daman_QGIS.managers import get_project_structure_manager


class F_0_2_OpenProject(BaseTool):
    """Инструмент открытия существующего проекта"""
    
    def __init__(self, iface: Any) -> None:
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
        return "F_0_2_Выбор существующего проекта"
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

        # Проверяем не открыт ли уже какой-либо проект в QGIS (проект плагина или обычный)
        if QgsProject.instance().fileName() or self.project_manager.is_project_open():
            # Определяем тип открытого проекта
            is_plugin_project = False
            project_dir = None
            current_project_name = "текущий проект"

            if QgsProject.instance().fileName():
                project_dir = os.path.dirname(QgsProject.instance().fileName())
                # Используем M_19 для проверки структуры проекта
                structure_manager = get_project_structure_manager()
                structure_manager.project_root = project_dir
                gpkg_path = structure_manager.get_gpkg_path(create=False)
                is_plugin_project = gpkg_path is not None and os.path.exists(gpkg_path)

                if is_plugin_project:
                    # Это проект плагина, открытый нативно - пытаемся инициализировать состояние
                    if not self.project_manager.is_project_open():
                        self.project_manager.init_from_native_project()

                # Получаем имя проекта
                if is_plugin_project and self.project_manager.settings:
                    current_project_name = self.project_manager.settings.object_name or os.path.basename(project_dir)
                else:
                    # Обычный QGIS проект
                    current_project_name = os.path.basename(QgsProject.instance().fileName()) or "текущий проект"
            elif self.project_manager.is_project_open():
                # Проект открыт через плагин
                is_plugin_project = True
                if self.project_manager.settings:
                    current_project_name = self.project_manager.settings.object_name or "проект"

            # Проверяем наличие несохранённых изменений
            if QgsProject.instance().isDirty():
                # Есть несохранённые изменения - предлагаем сохранить
                reply = QMessageBox.question(
                    None,
                    "Несохранённые изменения",
                    f"В проекте '{current_project_name}' есть несохранённые изменения.\n\n"
                    f"Сохранить изменения перед открытием нового проекта?",
                    QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                    QMessageBox.Save
                )

                if reply == QMessageBox.Cancel:
                    return
                elif reply == QMessageBox.Save:
                    # Сохраняем проект
                    if not QgsProject.instance().write():
                        QMessageBox.critical(
                            None,
                            "Ошибка",
                            "Не удалось сохранить проект"
                        )
                        return
                    log_info(f"F_0_2: Проект '{current_project_name}' сохранён перед закрытием")
                # Если Discard - просто продолжаем без сохранения
            else:
                # Нет несохранённых изменений - просто спрашиваем подтверждение
                reply = QMessageBox.question(
                    None,
                    "Подтверждение",
                    f"Текущий проект '{current_project_name}' будет закрыт.\n\nПродолжить?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes
                )
                if reply == QMessageBox.No:
                    return

            # Закрываем текущий проект
            if is_plugin_project:
                self.project_manager.close_project()
            else:
                # Для обычных QGIS проектов просто очищаем проект
                QgsProject.instance().clear()
                log_info(f"F_0_2: Обычный QGIS проект '{current_project_name}' закрыт")

        # Открываем диалог выбора рабочей папки проекта
        project_path = QFileDialog.getExistingDirectory(
            None,
            "Выберите рабочую папку проекта",
            "",
            QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks
        )

        if not project_path:
            return  # Пользователь отменил выбор

        # Проверяем наличие project.gpkg (поддержка обеих структур)
        gpkg_path = self._find_gpkg_path(project_path)
        if not gpkg_path:
            QMessageBox.critical(
                None,
                "Ошибка",
                f"В выбранной папке не найден файл project.gpkg.\n\n"
                f"Проверяемые расположения:\n"
                f"  - .project/database/project.gpkg (новая структура)\n"
                f"  - project.gpkg (старая структура)\n\n"
                f"Убедитесь, что выбрана правильная рабочая папка проекта."
            )
            return

        log_info(f"F_0_2: Найден project.gpkg: {gpkg_path}")

        # Открываем проект через менеджер (слои загружаются там)
        success = self.project_manager.open_project(project_path)

        if not success:
            QMessageBox.critical(
                None,
                "Ошибка",
                "Не удалось открыть проект"
            )
            return

        # Получаем метаданные для восстановления СК и отображения информации
        if self.project_manager.project_db:
            metadata = self.project_manager.project_db.get_all_metadata()

            # Восстанавливаем СК из метаданных
            self._restore_crs(metadata)

            # Показываем информацию о проекте
            self._show_project_info(project_path, metadata)
    
    def _restore_crs(self, metadata: Dict[str, Any]) -> None:
        """
        Восстановление системы координат из метаданных

        Args:
            metadata: Словарь метаданных проекта
        """
        try:
            crs = None
            
            # Сначала пытаемся через WKT (для пользовательских СК)
            if '1_4_crs_wkt' in metadata:
                crs = QgsCoordinateReferenceSystem()
                crs.createFromWkt(metadata['1_4_crs_wkt']['value'])
                if crs.isValid():
                    QgsProject.instance().setCrs(crs)
                    log_info(f"F_0_2: Система координат восстановлена из WKT: {crs.description()}")
                    return

            # Если WKT не удалось, пытаемся через EPSG (поддержка USER:XXXXX)
            if '1_4_crs_epsg' in metadata:
                crs = create_crs_from_string(metadata['1_4_crs_epsg']['value'])
                if crs:
                    QgsProject.instance().setCrs(crs)
                    log_info(f"F_0_2: Система координат восстановлена: {crs.authid()} - {crs.description()}")

        except Exception as e:
            log_error(f"F_0_2: Не удалось восстановить СК: {str(e)}")

    def _find_gpkg_path(self, project_path: str) -> str:
        """
        Поиск файла project.gpkg в папке проекта.

        Использует M_19 для получения пути к GPKG.

        Args:
            project_path: Корневая папка проекта

        Returns:
            Путь к найденному gpkg или пустая строка
        """
        # Используем M_19 для получения пути к GPKG
        structure_manager = get_project_structure_manager()
        structure_manager.project_root = project_path
        gpkg_path = structure_manager.get_gpkg_path(create=False)

        if gpkg_path and os.path.exists(gpkg_path):
            log_info(f"F_0_2: Найден project.gpkg: {gpkg_path}")
            return gpkg_path

        return ""

    def _show_project_info(self, project_path: str, metadata: Dict[str, Any]) -> None:
        """
        Показ информации об открытом проекте

        Args:
            project_path: Путь к проекту
            metadata: Метаданные проекта
        """
        # Получаем имя объекта для сообщения
        object_name = None
        if '1_1_full_name' in metadata:
            object_name = metadata['1_1_full_name']['value']
        else:
            object_name = os.path.basename(project_path)
        
        # Показываем только краткое сообщение об успешном открытии
        self.iface.messageBar().pushMessage(
            "Успех",
            f"Проект '{object_name}' открыт",
            level=Qgis.Success,
            duration=MESSAGE_SUCCESS_DURATION
        )
        
        # Логируем для отладки
        log_success(f"F_0_2: Проект открыт: {project_path}")

        # Регистрируем все выражения из Base_expressions.json как переменные проекта
        try:
            from Daman_QGIS.managers import ExpressionManager
            expr_mgr = ExpressionManager()
            count = expr_mgr.register_as_variables()
            log_info(f"F_0_2: Зарегистрировано {count} QGIS выражений как переменных проекта")
        except Exception as e:
            log_error(f"F_0_2: Ошибка регистрации выражений: {str(e)}")
