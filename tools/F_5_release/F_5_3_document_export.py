# -*- coding: utf-8 -*-
"""
Инструмент 6_3: Экспорт документов по шаблону

Назначение:
    Экспорт ведомостей и перечней координат в Excel по шаблонам из кода.
    Документы формируются согласно требованиям проектной документации.

Описание:
    - Шаблоны документов из TemplateRegistry (Fsm_5_3_8_template_registry.py)
    - Экспорт через DocumentFactory (Fsm_5_3_3_document_factory.py)
    - Автоматический выбор шаблона по имени слоя
    - Поддержка WGS-84 для перечней координат
"""

from typing import List, Dict, Any, Optional
import os

from qgis.core import QgsProject
from qgis.PyQt.QtWidgets import QMessageBox, QProgressDialog
from qgis.PyQt.QtCore import Qt

from Daman_QGIS.core.base_tool import BaseTool
from Daman_QGIS.managers import get_reference_managers, registry, FolderType
from Daman_QGIS.utils import log_info, log_error, log_warning

from .ui.document_export_dialog import DocumentExportDialog
from .submodules.Fsm_5_3_3_document_factory import DocumentFactory
from .submodules.Fsm_5_3_5_export_utils import ExportUtils


class F_5_3_DocumentExport(BaseTool):
    """Экспорт документов по шаблону (ведомости и перечни координат)"""

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
        log_info("F_5_3: Запуск экспорта документов")

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
        log_info(f"F_5_3: Папка для сохранения: {output_folder}")

        # Создаём диалог выбора (без ref_managers - диалог использует TemplateRegistry)
        dialog = DocumentExportDialog(
            self.iface.mainWindow(),
            output_folder
        )

        if dialog.exec():
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
            self._export_documents(selected_items, output_folder, create_wgs84)

    def _get_output_folder(self) -> Optional[str]:
        """
        Определить папку для сохранения документов

        Returns:
            Путь к папке "Документы" или None
        """
        try:
            structure_manager = registry.get('M_19')

            # Инициализируем project_root если не установлен
            if not structure_manager.is_active():
                project = QgsProject.instance()
                project_path = project.homePath()
                if project_path:
                    structure_manager.project_root = project_path

            if structure_manager.is_active():
                folder = structure_manager.get_folder(FolderType.DOCUMENTS)
                if folder:
                    return os.path.normpath(folder)

            log_error("F_5_3: M_19 не активен, невозможно определить папку")
            return None

        except Exception as e:
            log_error(f"F_5_3: Ошибка определения папки: {str(e)}")
            return None

    def _export_documents(
        self,
        selected_items: List[Dict[str, Any]],
        output_folder: str,
        create_wgs84: bool
    ) -> None:
        """
        Экспорт выбранных документов через DocumentFactory

        Args:
            selected_items: Список [{layer, template: DocumentTemplate}, ...]
            output_folder: Папка для сохранения
            create_wgs84: Создавать версию WGS-84 для перечней координат
        """
        log_info(f"F_5_3: Экспорт {len(selected_items)} документов")

        # Получаем ref_managers для передачи в фабрику (нужны для column_source)
        ref_managers = get_reference_managers()

        # Применяем региональные модификаторы (M_44)
        try:
            regional_mgr = registry.get('M_44')
        except KeyError:
            regional_mgr = None

        if regional_mgr is not None:
            try:
                metadata = ExportUtils.get_project_metadata()
                selected_items = regional_mgr.apply_export_modifiers(
                    selected_items, metadata
                )
            except Exception as e:
                log_warning(f"F_5_3: Ошибка региональных модификаторов, "
                            f"экспорт без модификаций: {e}")

        # Создаём прогресс-диалог
        progress = QProgressDialog(
            "Экспорт документов...",
            "Отмена",
            0,
            len(selected_items),
            self.iface.mainWindow()
        )
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setAutoClose(True)
        progress.show()

        # Создаём фабрику
        factory = DocumentFactory(self.iface, ref_managers)

        results: Dict[str, bool] = {}
        appendix_counter = 1
        current = 0

        for item in selected_items:
            if progress.wasCanceled():
                log_warning("F_5_3: Экспорт отменён пользователем")
                break

            current += 1
            layer = item['layer']
            template = item['template']

            doc_type_name = DocumentFactory.get_doc_type_name(template.doc_type)
            progress.setValue(current)
            progress.setLabelText(f"Экспорт: {layer.name()} ({doc_type_name})")

            # Автонумерация приложений для перечней координат
            appendix_num = str(appendix_counter)
            if template.doc_type == 'coordinate_list':
                appendix_counter += 1

            # Экспорт через фабрику
            extra_context = item.get('extra_context', {})
            try:
                success = factory.export(
                    layer=layer,
                    template=template,
                    output_folder=output_folder,
                    create_wgs84=create_wgs84,
                    appendix_num=appendix_num,
                    extra_context=extra_context,
                )
            except Exception as e:
                log_error(f"F_5_3: Ошибка экспорта {layer.name()} "
                          f"({doc_type_name}): {e}")
                success = False

            results[f"{layer.name()} ({doc_type_name})"] = success

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

        log_info(f"F_5_3: Экспорт завершён: {success_count} успешно, {error_count} ошибок")
