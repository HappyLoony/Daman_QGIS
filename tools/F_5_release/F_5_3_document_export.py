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
from Daman_QGIS.utils import log_info, log_error, log_warning, path_for_display

from .ui.document_export_dialog import DocumentExportDialog
from .submodules.Fsm_5_3_3_document_factory import DocumentFactory
from .submodules.Fsm_5_3_5_export_utils import ExportUtils
from .submodules.Fsm_5_3_10_product_registry import (
    ProductRegistry,
    _CUTTING_GROUPS,
    _STAGING_GROUPS,
)

# Маркеры 78-потока: при их наличии item НЕ группируется post-grouping
# (трасса маркеров §7 — двухступенчатая защита; группировка опознаёт 78-поток
# по этим ключам, не по продуктовым маркерам).
_REGION_78_MARKERS = (
    'split_by_feature',
    'spb_format',
    'merged_export',
    'summary_table',
    'explanatory_note',
)

# Карта group_key -> group_name для продуктовых перечней (coord_ozu/coord_ps):
# per-layer items несут только group_key, имя группы для filename_override/title
# берётся отсюда. Источник истины — определения групп в реестре продуктов
# (Fsm_5_3_10), реконструкция вручную запрещена (риск рассинхрона).
_GROUP_KEY_TO_NAME = {
    grp['group_key']: grp['group_name']
    for grp in (_CUTTING_GROUPS + _STAGING_GROUPS)
}

# ПС-специфичный титул merged-перечня публичных сервитутов (§4.1):
# generic merged-ПС item НЕ наследует титул первого члена (он по типу работы),
# а получает этот ПС-специфичный титул.
_PS_MERGED_TITLE = (
    'Перечень координат характерных точек контуров публичных сервитутов'
)


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
            product_ids = dialog.get_selected_product_ids()
            create_wgs84 = dialog.get_create_wgs84()

            if not product_ids:
                QMessageBox.warning(
                    self.iface.mainWindow(),
                    "Предупреждение",
                    "Не выбрано ни одного документа для экспорта"
                )
                return

            # Раскрываем выбранные продукты в items через ProductRegistry.expand().
            # Порядок раскрытия фиксирован независимо от порядка выбора в GUI
            # (§5: детерминизм нумерации приложений). Перечни координат идут до
            # ведомостей: coord_ozu -> coord_ps -> coord_gpmt (счётчик приложений
            # инкрементится только на coordinate_list), затем vedomost_ozu
            # (ведомости не нумеруются приложениями).
            expand_order = ('coord_ozu', 'coord_ps', 'coord_gpmt', 'vedomost_ozu')
            selected_set = set(product_ids)

            selected_items: List[Dict[str, Any]] = []
            for product_id in expand_order:
                if product_id in selected_set:
                    selected_items.extend(ProductRegistry.expand(product_id))

            if not selected_items:
                QMessageBox.warning(
                    self.iface.mainWindow(),
                    "Предупреждение",
                    "Для выбранных документов не найдено непустых слоёв"
                )
                return

            log_info(
                f"F_5_3: выбрано продуктов {len(product_ids)}, "
                f"раскрыто items {len(selected_items)}"
            )

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
                project_path = os.path.normpath(project.homePath())
                if project_path:
                    structure_manager.project_root = project_path

            if structure_manager.is_active():
                folder = structure_manager.get_folder(FolderType.EXPORT)
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

                # Регион 78: именование ПС по закону — «сервитут, публичный сервитут»
                if (regional_mgr.is_region('78', metadata)
                        and self._has_ps_items(selected_items)):
                    metadata['extended_servitude_name'] = True

                original_count = len(selected_items)
                selected_items = regional_mgr.apply_export_modifiers(
                    selected_items, metadata
                )
                if len(selected_items) != original_count:
                    log_info(
                        f"F_5_3: Региональные модификаторы: "
                        f"{original_count} -> {len(selected_items)} задач"
                    )
            except Exception as e:
                log_warning(f"F_5_3: Ошибка региональных модификаторов, "
                            f"экспорт без модификаций: {e}")

        # Post-grouping продуктовых items (§7, вариант B): слияние per-layer
        # coord_ozu/coord_ps в merged-перечни «один файл на ЗПР». Выполняется
        # ПОСЛЕ региональных модификаторов и ДО назначения appendix-номеров.
        # Старые items (без product_id) проходят шаг прозрачно.
        selected_items = self._group_product_items(selected_items)

        # Создаём прогресс-диалог
        progress = QProgressDialog(
            "Экспорт документов...",
            "Отмена",
            0,
            len(selected_items),
            self.iface.mainWindow()
        )
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        # setAutoClose/setAutoReset = False: диалог не закрывается автоматически
        # при value==max. Это нужно чтобы sub-progress callback (например, для
        # пояснительной записки на последнем item) мог обновлять setLabelText
        # после progress.setValue(current). Закрываем явно через progress.close()
        # после цикла.
        progress.setAutoClose(False)
        progress.setAutoReset(False)
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
            extra_context = item.get('extra_context', {})

            # Имя для лога/прогресса: для слоевого item — layer.name();
            # для merged-item с group_name (продуктовый перечень) —
            # "Перечень {group_name}"; иначе filename_override.
            group_name = extra_context.get('group_name')
            if layer is not None:
                display_name = layer.name()
            elif group_name:
                display_name = f"Перечень {group_name}"
            else:
                display_name = extra_context.get('filename_override', 'merged')

            doc_type_name = DocumentFactory.get_doc_type_name(template.doc_type)
            progress.setValue(current)

            # Фаза экспорта для информативного label
            total = len(selected_items)
            if extra_context.get('summary_table'):
                base_label = f"[{current}/{total}] Сводная таблица: {display_name}"
            elif extra_context.get('merged_export'):
                base_label = f"[{current}/{total}] Сводный перечень: {display_name}"
            elif template.doc_type == 'explanatory_note':
                base_label = f"[{current}/{total}] Пояснительная записка"
            else:
                base_label = f"[{current}/{total}] {display_name} ({doc_type_name})"
            progress.setLabelText(base_label)

            # Sub-progress callback для долгих экспортёров (например Fsm_5_3_9).
            # Передаётся через extra_context — экспортёр сам решает использовать или нет.
            if template.doc_type == 'explanatory_note':
                from qgis.PyQt.QtWidgets import QApplication

                def _stage_progress(msg, percent, _label=base_label, _prog=progress):
                    if _prog.wasCanceled():
                        return
                    _prog.setLabelText(f"{_label}: {msg}")
                    _prog.repaint()
                    QApplication.processEvents()

                extra_context = {**extra_context, 'progress_callback': _stage_progress}
                log_info(
                    f"F_5_3: progress_callback подключён для item {current}/{total} "
                    f"(пояснительная записка)"
                )

            # Автонумерация приложений для перечней координат
            appendix_num = str(appendix_counter)
            if template.doc_type == 'coordinate_list':
                appendix_counter += 1

            # Экспорт через фабрику
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
                log_error(
                    f"F_5_3: Ошибка экспорта {display_name} "
                    f"({doc_type_name}): {e}"
                )
                success = False

            # Уникальный ключ: для split items используем счётчик
            result_key = f"{current}_{display_name} ({doc_type_name})"
            results[result_key] = success

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

        message += f"Файлы сохранены в:\n{path_for_display(output_folder)}"

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

    @staticmethod
    def _has_ps_items(items: List[Dict[str, Any]]) -> bool:
        """Проверить наличие слоёв публичных сервитутов среди items."""
        for item in items:
            template = item.get('template')
            if template and getattr(template, 'template_id', '') == 'coord_cutting_oks_ps':
                return True
            layer = item.get('layer')
            if layer is not None:
                name = layer.name()
                if '_ПС' in name or name.endswith('_ПС'):
                    return True
        return False

    @staticmethod
    def _group_product_items(
        items: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Post-grouping (§7, вариант B): слить per-layer продуктовые items
        coord_ozu/coord_ps в merged-items «один файл на ЗПР».

        Группируются ТОЛЬКО items, у которых extra_context имеет product_id из
        ('coord_ozu', 'coord_ps') И group_key И НЕТ маркеров 78-потока
        (split_by_feature / spb_format / merged_export / summary_table /
        explanatory_note). Остальные items проходят прозрачно в исходном порядке.

        Группы — по first-seen group_key (порядок сохраняется). Каждая группа из
        N members -> ОДИН merged-item на позиции первого члена; позиции остальных
        членов удаляются. merged-item:
            {layer: None, template: <шаблон первого члена>,
             extra_context: {ozu_merged: True,
                             merged_layers: [item['layer'] каждого члена],
                             group_name, product_id, group_key, filename_override}}.
        Группа из одного члена тоже становится merged-item (единый формат на ЗПР).

        filename_override (§5/§7):
        - coord_ozu -> 'Приложение_{appendix}_координаты_' + group_name
          (для этапных group_key вида oks_stage_N имя группы 'ОКС_Этап_N' уже
          содержит этап — group_name используется как есть);
        - coord_ps  -> 'Приложение_{appendix}_координаты_ПС_' + group_name.
        Литерал '{appendix}' остаётся в строке — резолвится экспортёром через
        format_template_text (номер приложения здесь ещё неизвестен).

        coord_ps merged-item дополнительно получает title_override
        (ПС-специфичный титул, §4.1) — не наследует титул первого члена.

        vedomost_ozu items НЕ группируются (уже merged из expander).

        Args:
            items: items любого источника (продукт или старый GUI).

        Returns:
            Список items с post-grouping. Не-группируемые items — без изменений.
        """
        # Группы по first-seen group_key. group_order хранит ключи в порядке
        # первого появления; группа merged-item ставится на позицию первого члена.
        # result_slots — выходной список с плейсхолдером (None) для позиций членов
        # группы; merged-item подставляется на позицию первого члена группы.
        result_slots: List[Optional[Dict[str, Any]]] = []
        group_order: List[str] = []
        group_members: Dict[str, List[Dict[str, Any]]] = {}
        group_first_slot: Dict[str, int] = {}

        for item in items:
            extra_context = item.get('extra_context') or {}
            product_id = extra_context.get('product_id')
            group_key = extra_context.get('group_key')

            groupable = (
                product_id in ('coord_ozu', 'coord_ps')
                and bool(group_key)
                and not any(extra_context.get(m) for m in _REGION_78_MARKERS)
            )

            if not groupable:
                result_slots.append(item)
                continue

            slot_index = len(result_slots)
            if group_key not in group_members:
                group_members[group_key] = []
                group_order.append(group_key)
                group_first_slot[group_key] = slot_index
                # Резерв позиции под merged-item (на месте первого члена).
                result_slots.append(None)
            group_members[group_key].append(item)

        if not group_order:
            # Нет групп — вернуть исходный список без изменений.
            return list(items)

        # Построить merged-item для каждой группы, поставить на зарезервированную
        # позицию первого члена.
        for group_key in group_order:
            members = group_members[group_key]
            first_member = members[0]
            first_ctx = first_member.get('extra_context') or {}
            product_id = first_ctx.get('product_id')
            group_name = _GROUP_KEY_TO_NAME.get(group_key, group_key)

            merged_layers = [m['layer'] for m in members]

            # Этапные группы (ОКС_Этап_N / ОКС_Итог): в имени файла — суффикс
            # этапа БЕЗ префикса "ОКС_" (план §5: ..._Этап_1 / _Этап_2 / _Итог;
            # этапность существует только для ОКС, префикс избыточен).
            filename_part = group_name
            if filename_part.startswith('ОКС_'):
                filename_part = filename_part[4:]

            if product_id == 'coord_ps':
                filename_override = (
                    'Приложение_{appendix}_координаты_ПС_' + filename_part
                )
            else:  # coord_ozu
                filename_override = (
                    'Приложение_{appendix}_координаты_' + filename_part
                )

            merged_extra: Dict[str, Any] = {
                'ozu_merged': True,
                'merged_layers': merged_layers,
                'group_name': group_name,
                'product_id': product_id,
                'group_key': group_key,
                'filename_override': filename_override,
            }
            if product_id == 'coord_ps':
                merged_extra['title_override'] = _PS_MERGED_TITLE

            merged_item = {
                'layer': None,
                'template': first_member['template'],
                'extra_context': merged_extra,
            }
            result_slots[group_first_slot[group_key]] = merged_item

        # Удалить плейсхолдеры позиций членов группы (кроме первого, заменённого
        # merged-item). Здесь None остаётся только если merged-item не подставлен,
        # что невозможно (каждый group_key получает merged-item выше).
        grouped = [slot for slot in result_slots if slot is not None]

        log_info(
            f"F_5_3: Post-grouping продуктовых items: {len(items)} -> "
            f"{len(grouped)} ({len(group_order)} merged-групп)"
        )
        return grouped
