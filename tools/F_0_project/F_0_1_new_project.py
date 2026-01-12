# -*- coding: utf-8 -*-
"""
Инструмент создания нового проекта
"""

import os
from datetime import datetime
from typing import Dict, Any

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QMessageBox
from qgis.core import (
    QgsProject,
    QgsCoordinateReferenceSystem,
    Qgis
)

from Daman_QGIS.core.base_tool import BaseTool
from .submodules.Fsm_0_1_1_new_project_dialog import NewProjectDialog
from Daman_QGIS.database.schemas import ProjectSettings
from Daman_QGIS.constants import MESSAGE_SUCCESS_DURATION, MESSAGE_INFO_DURATION, COORDINATE_PRECISION
from Daman_QGIS.utils import log_success, log_info, log_error
from Daman_QGIS.managers import DataCleanupManager


class F_0_1_NewProject(BaseTool):
    """Инструмент создания нового проекта"""
    
    def __init__(self, iface) -> None:
        """
        Инициализация инструмента

        Args:
            iface: Интерфейс QGIS
        """
        super().__init__(iface)
        self.project_manager = None
        self.reference_manager = None
        self.plugin_version = ""

    def set_project_manager(self, project_manager) -> None:
        """Установка менеджера проектов"""
        self.project_manager = project_manager

    def set_reference_manager(self, reference_manager) -> None:
        """Установка менеджера справочных данных"""
        self.reference_manager = reference_manager

    def set_plugin_version(self, version: str) -> None:
        """Установка версии плагина"""
        self.plugin_version = version

    @property
    def name(self) -> str:
        """Имя инструмента"""
        return "F_0_1_Создание нового проекта"
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

        # Проверяем не открыт ли уже проект
        if self.project_manager.is_project_open():
            reply = QMessageBox.question(
                None,
                "Подтверждение",
                "Текущий проект будет закрыт. Продолжить?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.No:
                return

            # Закрываем текущий проект
            self.project_manager.close_project()

        # Создаем и показываем диалог
        dialog = NewProjectDialog(None, self.reference_manager)

        if dialog.exec_():
            # Получаем данные из диалога
            project_data = dialog.get_project_data()

            # Создаем проект
            self.create_project(project_data)
    def _save_required_metadata(self, db, project_data: Dict[str, Any], safe_name: str) -> None:
        """Сохранение обязательных метаданных проекта"""
        db.set_metadata('1_0_working_name', project_data['working_name'],
                       'Рабочее название (для папок и файлов)')
        db.set_metadata('1_1_full_name', project_data['full_name'],
                       'Полное наименование объекта')
        db.set_metadata('1_2_object_type', project_data['object_type'],
                       'Тип объекта (area - площадной, linear - линейный)')
        db.set_metadata('1_2_object_type_name', project_data['object_type_name'],
                       'Наименование типа объекта')

        # Сохраняем значение линейного объекта только если оно задано
        if project_data.get('object_type_value'):
            db.set_metadata('1_2_1_object_type_value', project_data['object_type_value'],
                           'Значение линейного объекта (federal/regional/local)')
            db.set_metadata('1_2_1_object_type_value_name', project_data['object_type_value_name'],
                           'Наименование значения линейного объекта')

        full_project_path = os.path.join(project_data['project_path'], safe_name)
        db.set_metadata('1_3_project_folder', full_project_path,
                       'Путь к папке проекта')

        db.set_metadata('1_4_crs_epsg', str(project_data['crs_epsg']),
                       'Код системы координат (EPSG или USER)')

        if project_data['crs']:
            db.set_metadata('1_4_crs_wkt', project_data['crs'].toWkt(),
                           'WKT определение системы координат')

        db.set_metadata('1_4_crs_description', project_data['crs_description'],
                       'Описание системы координат')
        db.set_metadata('1_4_crs_short_name', project_data['crs_short_name'],
                       'Короткое название СК для приложений')

        # Код региона (обязательное поле)
        db.set_metadata('1_4_1_code_region', project_data.get('code_region', ''),
                       'Код региона для CRS')

        # Код региона:района (условное поле - только если указан район)
        if project_data.get('code_region_district'):
            db.set_metadata('1_4_2_code_region_district', project_data['code_region_district'],
                           'Полный код региона:района для CRS')

        db.set_metadata('1_5_doc_type', project_data['doc_type'],
                       'Тип документации (dpt - ДПТ, masterplan - Мастер-План)')
        db.set_metadata('1_5_doc_type_name', project_data['doc_type_name'],
                       'Наименование типа документации')

        db.set_metadata('1_6_stage', project_data['stage'],
                       'Этап разработки (initial - первичная, changes - внесение изменений)')
        db.set_metadata('1_6_stage_name', project_data['stage_name'],
                       'Наименование этапа разработки')

    def _save_optional_metadata(self, db, project_data: Dict[str, Any]) -> None:
        """Сохранение необязательных метаданных проекта"""
        optional_fields = {
            'code': ('2_1_code', 'Шифр (внутренняя кодировка объекта)'),
            'release_date': ('2_2_date', 'Дата выпуска для титулов, обложек, и штампов'),
            'company': ('2_3_company', 'Компания выполняющая договор'),
            'city': ('2_4_city', 'Город'),
            'customer': ('2_5_customer', 'Заказчик'),
            'general_director': ('2_6_general_director', 'Генеральный директор'),
            'technical_director': ('2_7_technical_director', 'Технический директор'),
            'cover': ('2_8_cover', 'Обложка обычно не наша'),
            'title_start': ('2_9_title_start', 'С какого листа начинается наш титул'),
            'main_scale': ('2_10_main_scale', 'Основной масштаб'),
            'developer': ('2_11_developer', 'Разаботал'),
            'examiner': ('2_12_examiner', 'Проверил'),
        }

        for field, (key, desc) in optional_fields.items():
            if field in project_data and project_data[field]:
                db.set_metadata(key, project_data[field], desc)

    def _configure_qgis_project(self, project_data: Dict[str, Any]) -> None:
        """Конфигурация параметров проекта QGIS"""
        from qgis.core import QgsProject, QgsUnitTypes, QgsSnappingConfig, QgsTolerance
        from Daman_QGIS.constants import COORDINATE_PRECISION
        from Daman_QGIS.utils import log_info

        QgsProject.instance().setDistanceUnits(QgsUnitTypes.DistanceMeters)
        QgsProject.instance().setAreaUnits(QgsUnitTypes.AreaSquareMeters)

        snapping_config = QgsProject.instance().snappingConfig()
        snapping_config.setEnabled(True)
        snapping_config.setMode(QgsSnappingConfig.AllLayers)
        snapping_config.setTolerance(COORDINATE_PRECISION)
        snapping_config.setUnits(QgsTolerance.ProjectUnits)
        snapping_config.setIntersectionSnapping(True)
        QgsProject.instance().setSnappingConfig(snapping_config)

        crs = project_data['crs']
        log_info(f"F_0_1: _configure_qgis_project входящая CRS: isValid={crs.isValid() if crs else False}, authid={crs.authid() if crs else 'None'}")

        QgsProject.instance().setCrs(crs)

        # Проверка что CRS установлена
        current_crs = QgsProject.instance().crs()
        log_info(f"F_0_1: После setCrs: isValid={current_crs.isValid()}, authid={current_crs.authid()}, desc={current_crs.description()}")
    def create_project(self, project_data: Dict[str, Any]) -> None:
        """Создание проекта с метаданными"""
        # Подготовка безопасного имени проекта (заменяем запрещённые символы, не удаляем)
        project_name = project_data['working_name']
        safe_name = DataCleanupManager().sanitize_filename(project_name)

        # Создание структуры проекта
        if not self.project_manager:
            raise ValueError("Менеджер проектов не инициализирован")

        success = self.project_manager.create_project(
            project_name=safe_name,
            project_dir=project_data['project_path'],
            crs=project_data['crs']
        )

        if not success:
            raise ValueError("Не удалось создать структуру проекта")

        # Сохранение метаданных
        if self.project_manager and self.project_manager.project_db:
            db = self.project_manager.project_db
            self._save_required_metadata(db, project_data, safe_name)
            self._save_optional_metadata(db, project_data)

            db.set_metadata('created_date', datetime.now().isoformat(),
                           'Дата создания проекта')
            db.set_metadata('modified_date', datetime.now().isoformat(),
                           'Дата последнего изменения проекта')

        # Конфигурация QGIS проекта
        self._configure_qgis_project(project_data)

        # Сохранение проекта
        if self.project_manager:
            self.project_manager.save_project()

        # Регистрируем все выражения из Base_expressions.json как переменные проекта
        try:
            from Daman_QGIS.managers import ExpressionManager
            expr_mgr = ExpressionManager()
            count = expr_mgr.register_as_variables()
            log_info(f"F_0_1: Зарегистрировано {count} QGIS выражений как переменных проекта")
        except Exception as e:
            log_error(f"F_0_1: Ошибка регистрации выражений: {str(e)}")

        # Сообщение об успехе в messageBar
        self.iface.messageBar().pushMessage(
            "Успех", f"Проект '{safe_name}' успешно создан",
            level=Qgis.Success, duration=MESSAGE_SUCCESS_DURATION
        )

    def create_dialog(self) -> NewProjectDialog:
        """Создание диалога (для совместимости с BaseTool)"""
        return NewProjectDialog(None, self.reference_manager)
