# -*- coding: utf-8 -*-
"""
Инструмент 6_3: Экспорт документов по шаблону

Назначение:
    Экспорт ведомостей и перечней координат в Excel по шаблонам из базы данных.
    Документы формируются согласно требованиям проектной документации.

Описание:
    - Ведомости атрибутов (Base_excel_list_styles.json)
    - Перечни координат (Base_excel_export_styles.json)
    - Автоматический выбор шаблона по имени слоя
    - Поддержка WGS-84 для перечней координат
"""

from typing import List, Dict, Any, Optional
import os

from qgis.core import QgsVectorLayer, QgsProject
from qgis.PyQt.QtWidgets import QMessageBox, QProgressDialog
from qgis.PyQt.QtCore import Qt

from Daman_QGIS.core.base_tool import BaseTool
from Daman_QGIS.managers import get_reference_managers, get_project_structure_manager, FolderType
from Daman_QGIS.utils import log_info, log_error, log_warning, log_success

from .ui.document_export_dialog import DocumentExportDialog
from .submodules.Fsm_6_3_1_coordinate_list import Fsm_6_3_1_CoordinateList
from .submodules.Fsm_6_3_2_attribute_list import Fsm_6_3_2_AttributeList


class F_6_3_DocumentExport(BaseTool):
    """Экспорт документов по шаблону (ведомости и перечни координат)"""

    # Типы документов
    DOC_TYPES = {
        'coordinate_list': 'Перечень координат',
        'attribute_list': 'Ведомость'
    }

    @property
    def name(self) -> str:
        """Имя инструмента"""
        return "6_3 Перечни и ведомости"

    @property
    def icon(self) -> str:
        """Иконка инструмента"""
        return "mActionFileSave.svg"

    def run(self) -> None:
        """Запуск экспорта с диалогом выбора"""
        log_info("F_6_3: Запуск экспорта документов")

        # Получаем reference managers
        ref_managers = get_reference_managers()

        # Определяем папку для сохранения
        output_folder = self._get_output_folder()
        if not output_folder:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Предупреждение",
                "Не удалось определить папку проекта.\n"
                "Убедитесь, что проект QGIS сохранён."
            )
            return

        # Создаём папку если её нет
        os.makedirs(output_folder, exist_ok=True)
        log_info(f"F_6_3: Папка для сохранения: {output_folder}")

        # Создаём диалог выбора
        dialog = DocumentExportDialog(
            self.iface.mainWindow(),
            ref_managers,
            output_folder
        )

        if dialog.exec_():
            selected_items = dialog.get_selected_items()
            create_wgs84 = dialog.get_create_wgs84()

            if not selected_items:
                QMessageBox.warning(
                    self.iface.mainWindow(),
                    "Предупреждение",
                    "Не выбрано ни одного документа для экспорта"
                )
                return

            # Экспортируем выбранные документы
            self._export_documents(selected_items, output_folder, create_wgs84, ref_managers)

    def _get_output_folder(self) -> Optional[str]:
        """
        Определить папку для сохранения документов

        Returns:
            Путь к папке "Документы" или None
        """
        try:
            # Используем M_19 для получения пути
            structure_manager = get_project_structure_manager()

            # Инициализируем project_root если не установлен
            if not structure_manager.is_active():
                project = QgsProject.instance()
                project_path = project.homePath()
                if project_path:
                    structure_manager.project_root = project_path

            if structure_manager.is_active():
                output_folder = structure_manager.get_folder(FolderType.DOCUMENTS)
                if output_folder:
                    return os.path.normpath(output_folder)

            log_error("F_6_3: M_19 не активен, невозможно определить папку")
            return None

        except Exception as e:
            log_error(f"F_6_3: Ошибка определения папки: {str(e)}")
            return None

    def _export_documents(
        self,
        selected_items: List[Dict[str, Any]],
        output_folder: str,
        create_wgs84: bool,
        ref_managers
    ) -> None:
        """
        Экспорт выбранных документов

        Args:
            selected_items: Список выбранных элементов [{layer, doc_type, style}, ...]
            output_folder: Папка для сохранения
            create_wgs84: Создавать версию WGS-84 для перечней координат
            ref_managers: Reference managers
        """
        log_info(f"F_6_3: Экспорт {len(selected_items)} документов")

        # Создаём прогресс-диалог
        progress = QProgressDialog(
            "Экспорт документов...",
            "Отмена",
            0,
            len(selected_items),
            self.iface.mainWindow()
        )
        progress.setWindowModality(Qt.WindowModal)
        progress.setAutoClose(True)
        progress.show()

        # Инициализируем экспортёры
        coordinate_exporter = Fsm_6_3_1_CoordinateList(self.iface, ref_managers)
        attribute_exporter = Fsm_6_3_2_AttributeList(self.iface, ref_managers)

        results = {}
        current = 0

        for item in selected_items:
            if progress.wasCanceled():
                log_warning("F_6_3: Экспорт отменён пользователем")
                break

            current += 1
            layer = item['layer']
            doc_type = item['doc_type']
            style = item['style']

            progress.setValue(current)
            progress.setLabelText(f"Экспорт: {layer.name()} ({self.DOC_TYPES.get(doc_type, doc_type)})")

            # Выбираем экспортёр по типу документа
            if doc_type == 'coordinate_list':
                success = coordinate_exporter.export_layer(
                    layer, style, output_folder, create_wgs84
                )
            elif doc_type == 'attribute_list':
                success = attribute_exporter.export_layer(
                    layer, style, output_folder
                )
            else:
                log_warning(f"F_6_3: Неизвестный тип документа: {doc_type}")
                success = False

            results[f"{layer.name()} ({self.DOC_TYPES.get(doc_type, doc_type)})"] = success

        progress.close()

        # Показываем результаты
        self._show_results(results, output_folder, create_wgs84)

    def _show_results(
        self,
        results: Dict[str, bool],
        output_folder: str,
        create_wgs84: bool
    ) -> None:
        """
        Показать результаты экспорта

        Args:
            results: Словарь {document_name: success}
            output_folder: Папка сохранения
            create_wgs84: Был ли запрошен экспорт в WGS-84
        """
        success_count = sum(1 for success in results.values() if success)
        error_count = len(results) - success_count

        message = "Экспорт документов завершён!\n\n"
        message += f"Успешно: {success_count}\n"

        if error_count > 0:
            message += f"Ошибок: {error_count}\n\n"
            message += "Документы с ошибками:\n"
            for doc_name, success in results.items():
                if not success:
                    message += f"  - {doc_name}\n"
            message += "\n"

        message += f"Файлы сохранены в:\n{output_folder}"

        if create_wgs84:
            message += "\n\nДля перечней координат созданы версии в WGS-84"

        if error_count > 0:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Экспорт документов",
                message
            )
        else:
            QMessageBox.information(
                self.iface.mainWindow(),
                "Экспорт документов",
                message
            )

        log_info(f"F_6_3: Экспорт завершён: {success_count} успешно, {error_count} ошибок")
