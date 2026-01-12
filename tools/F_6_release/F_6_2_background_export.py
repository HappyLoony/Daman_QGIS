# -*- coding: utf-8 -*-
"""
Инструмент 6_2: Экспорт подложек в DXF

Назначение:
    Экспорт векторных слоев в формат DXF по шаблонам подложек из Base_drawings_background.json.
    Подложка - это совокупность нескольких слоёв, объединённых в один DXF файл.

Описание:
    - Загрузка шаблонов подложек из Base_drawings_background.json
    - GUI для выбора подложек (множественный выбор, по умолчанию все выключены)
    - Экспорт каждой подложки в отдельный DXF файл с использованием имён из layer_name_autocad
    - Поддержка слоя Defpoints для непечатаемых буферных слоёв (цвет 8 - серый)
    - Поддержка флага not_print для слоёв
    - Автоматическое создание слоёв подписей {layer_name_autocad}_Номер
"""

from typing import List, Dict, Any, Optional, Tuple, Set
import os

from qgis.core import (
    QgsVectorLayer, QgsProject, QgsFeature, QgsFields, QgsField,
    QgsGeometry, QgsMemoryProviderUtils, QgsCoordinateReferenceSystem
)
from qgis.PyQt.QtWidgets import QMessageBox, QProgressDialog
from qgis.PyQt.QtCore import Qt

from Daman_QGIS.core.base_tool import BaseTool
from Daman_QGIS.tools.F_1_data.core.dxf_exporter import DxfExporter
from Daman_QGIS.managers import get_reference_managers, get_project_structure_manager, FolderType, LayerReplacementManager
from Daman_QGIS.utils import log_info, log_error, log_warning, log_success

from .ui.background_dialog import BackgroundExportDialog


# Константы для П_ОЗУ
# Примечание: слой "итог" НЕ имеет точек - точки формируются только на этапах 1 и 2
# В итоговом слое только атрибуты с перечислением характерных точек контура
POZU_STAGE_LAYERS = {
    '1_этап': {
        'polygons': 'Le_3_7_1_',
        'points': 'Le_3_8_1_'
    },
    '2_этап': {
        'polygons': 'Le_3_7_2_',
        'points': 'Le_3_8_2_'
    },
    'итог': {
        'polygons': 'Le_3_7_3_',
        'points': None  # Нет точечного слоя для итога
    }
}

POZU_DEFAULT_LAYERS = ['Le_3_1_', 'Le_3_2_', 'Le_3_5_', 'Le_3_6_']


class F_6_2_BackgroundExport(BaseTool):
    """Экспорт подложек в DXF по шаблонам"""

    @property
    def name(self) -> str:
        """Имя инструмента"""
        return "6_2 Подложки"

    @property
    def icon(self) -> str:
        """Иконка инструмента"""
        return "mActionFileSave.svg"

    def run(self) -> None:
        """Запуск экспорта с диалогом выбора подложек"""
        log_info("F_6_2: Запуск экспорта подложек")

        # Получаем reference managers
        ref_managers = get_reference_managers()

        # Определяем папку для сохранения (автоматически)
        output_folder = self._get_output_folder()
        if not output_folder:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Предупреждение",
                "Не удалось определить папку проекта.\n"
                "Убедитесь, что файл project.gpkg существует в папке проекта."
            )
            return

        # Создаём папку "Подложки" если её нет
        os.makedirs(output_folder, exist_ok=True)
        log_info(f"F_6_2: Папка для сохранения подложек: {output_folder}")

        # Загружаем шаблоны подложек из Base_drawings_background.json
        templates = self._load_background_templates()

        if not templates:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Предупреждение",
                "Не найдено ни одного шаблона подложек в Base_drawings_background.json"
            )
            return

        # Создаем диалог выбора подложек (с информацией о папке сохранения)
        dialog = BackgroundExportDialog(self.iface.mainWindow(), templates, output_folder)

        if dialog.exec_():
            selected_templates = dialog.get_selected_templates()

            if not selected_templates:
                QMessageBox.warning(
                    self.iface.mainWindow(),
                    "Предупреждение",
                    "Не выбрано ни одного шаблона для экспорта"
                )
                return

            # Экспортируем выбранные подложки
            self._export_backgrounds(selected_templates, output_folder, ref_managers)

    def _get_output_folder(self) -> Optional[str]:
        """
        Определить папку для сохранения подложек (автоматически)

        Использует M_19_ProjectStructureManager для получения пути к папке "Подложки".

        Returns:
            Путь к папке "Подложки" или None если не удалось определить
        """
        try:
            # Используем ProjectStructureManager
            structure_manager = get_project_structure_manager()

            # Если менеджер не инициализирован, пробуем установить project_root
            if not structure_manager.is_active():
                project = QgsProject.instance()
                project_path = project.homePath()
                if project_path:
                    structure_manager.project_root = project_path

            # Получаем папку через менеджер
            if structure_manager.is_active():
                output_folder = structure_manager.get_folder(FolderType.BACKGROUNDS)
                if output_folder:
                    log_info(f"F_6_2: Папка подложек через M_19: {output_folder}")
                    return os.path.normpath(output_folder)

            log_error("F_6_2: M_19 не активен, невозможно определить папку")
            return None

        except Exception as e:
            log_error(f"F_6_2: Ошибка определения папки для сохранения: {str(e)}")
            return None

    def _load_background_templates(self) -> List[Dict[str, Any]]:
        """
        Загрузка шаблонов подложек из Base_drawings_background.json через менеджер

        Returns:
            Список шаблонов подложек
        """
        try:
            ref_managers = get_reference_managers()
            templates = ref_managers.background.get_backgrounds()
            log_info(f"F_6_2: Загружено {len(templates)} шаблонов подложек")
            return templates

        except Exception as e:
            log_error(f"F_6_2: Ошибка загрузки шаблонов подложек: {str(e)}")
            return []

    def _export_backgrounds(self,
                           templates: List[Dict[str, Any]],
                           output_folder: str,
                           ref_managers) -> None:
        """
        Экспорт выбранных подложек в DXF

        Args:
            templates: Список выбранных шаблонов подложек
            output_folder: Папка для сохранения DXF файлов
            ref_managers: Reference managers для доступа к базам данных
        """
        log_info(f"F_6_2: Экспорт {len(templates)} подложек в {output_folder}")

        # Создаем прогресс-диалог
        progress = QProgressDialog(
            "Экспорт подложек...",
            "Отмена",
            0,
            len(templates),
            self.iface.mainWindow()
        )
        progress.setWindowModality(Qt.WindowModal)
        progress.setAutoClose(True)
        progress.show()

        results = {}
        current = 0

        for template in templates:
            if progress.wasCanceled():
                log_warning("F_6_2: Экспорт отменен пользователем")
                break

            current += 1
            template_name = template.get('name', 'Unknown')
            progress.setValue(current)
            progress.setLabelText(f"Экспорт подложки {template_name}...")

            # Экспортируем подложку
            success, detailed_results = self._export_single_background(template, output_folder, ref_managers)

            # Для П_ОЗУ добавляем все файлы в результаты
            if detailed_results:
                results.update(detailed_results)
            else:
                results[template_name] = success

        progress.close()

        # Показываем результаты
        self._show_results(results, output_folder)

    def _export_single_background(self,
                                  template: Dict[str, Any],
                                  output_folder: str,
                                  ref_managers) -> Tuple[bool, Dict[str, bool]]:
        """
        Экспорт одной подложки в DXF

        Для П_ОЗУ проверяет наличие этапности:
        - Если есть этапность: экспорт в 3 файла (П_ОЗУ_1_этап, П_ОЗУ_2_этап, П_ОЗУ_итог)
        - Если нет этапности: экспорт в 1 файл (П_ОЗУ)

        Args:
            template: Шаблон подложки из Base_drawings_background.json
            output_folder: Папка для сохранения
            ref_managers: Reference managers

        Returns:
            Tuple[bool, Dict[str, bool]]:
                - True если экспорт успешен (все файлы)
                - Словарь {filename: success} для отчёта
        """
        try:
            name = template.get('name')
            layer_names = template.get('layers', [])

            if not layer_names:
                log_warning(f"F_6_2: Шаблон {name} не содержит слоёв, пропускаем")
                return False, {}

            # Специальная обработка для П_ОЗУ
            if name == 'П_ОЗУ':
                return self._export_pozu_background(output_folder, ref_managers)

            # Получаем имя файла для экспорта через менеджер
            file_name = ref_managers.background.get_export_filename(template)

            if not file_name:
                log_warning(f"F_6_2: Шаблон {name} не содержит допустимого имени файла")
                return False, {}

            # Формируем полный путь к файлу
            output_path = os.path.join(output_folder, f"{file_name}.dxf")

            # Получаем слои QGIS по именам или префиксам через централизованный менеджер
            layer_finder = LayerReplacementManager()
            qgis_layers = []
            for layer_pattern in layer_names:
                found_layers = layer_finder.find_layers_by_pattern(layer_pattern, QgsVectorLayer)
                if found_layers:
                    qgis_layers.extend(found_layers)
                    # Логируем сколько слоёв найдено по паттерну
                    if layer_pattern.endswith('_'):
                        log_info(f"F_6_2: По префиксу '{layer_pattern}' найдено {len(found_layers)} слоёв")
                else:
                    log_warning(f"F_6_2: Слой/префикс '{layer_pattern}' не найден в проекте")

            if not qgis_layers:
                log_warning(f"F_6_2: Ни один слой из шаблона {name} не найден в проекте")
                return False, {}

            # Создаем DxfExporter с менеджером стилей
            from Daman_QGIS.managers import StyleManager
            style_manager = StyleManager()
            exporter = DxfExporter(self.iface, style_manager)

            log_info(f"F_6_2: Экспорт подложки в {output_path}")

            # Экспортируем слои
            export_results = exporter.export_layers(
                qgis_layers,
                output_path=output_path
            )

            # Проверяем результаты
            success = all(export_results.values())
            if success:
                log_success(f"F_6_2: Подложка {os.path.basename(output_path)} экспортирована успешно")
            else:
                log_error(f"F_6_2: Ошибка экспорта подложки {os.path.basename(output_path)}")

            return success, {name: success}

        except Exception as e:
            log_error(f"F_6_2: Ошибка экспорта подложки {template.get('name', 'Unknown')}: {str(e)}")
            return False, {}

    def _export_pozu_background(self, output_folder: str, ref_managers) -> Tuple[bool, Dict[str, bool]]:
        """
        Экспорт подложки П_ОЗУ с учётом этапности

        Args:
            output_folder: Папка для сохранения
            ref_managers: Reference managers

        Returns:
            Tuple[bool, Dict[str, bool]]:
                - True если все файлы экспортированы успешно
                - Словарь {filename: success} для детального отчёта
        """
        if self._has_stage_layers():
            log_info("F_6_2: П_ОЗУ - обнаружена этапность, экспорт в 3 файла")
            results = self._export_pozu_with_stages(output_folder, ref_managers)
        else:
            log_info("F_6_2: П_ОЗУ - этапность не обнаружена, экспорт в 1 файл")
            results = self._export_pozu_without_stages(output_folder, ref_managers)

        success = all(results.values()) if results else False
        return success, results

    def _show_results(self, results: Dict[str, bool], output_folder: str) -> None:
        """
        Показать результаты экспорта в диалоге

        Args:
            results: Словарь {template_name: success}
            output_folder: Папка сохранения
        """
        success_count = sum(1 for success in results.values() if success)
        error_count = len(results) - success_count

        message = "Экспорт подложек завершен!\n\n"
        message += f"Успешно: {success_count}\n"

        if error_count > 0:
            message += f"Ошибок: {error_count}\n\n"
            message += "Подложки с ошибками:\n"
            for template_name, success in results.items():
                if not success:
                    message += f"  • {template_name}\n"
            message += "\n"

        message += f"Файлы сохранены в:\n{output_folder}"

        if error_count > 0:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Экспорт подложек",
                message
            )
        else:
            QMessageBox.information(
                self.iface.mainWindow(),
                "Экспорт подложек",
                message
            )

        log_info(f"F_6_2: Экспорт завершен: {success_count} успешно, {error_count} ошибок")

    def _has_stage_layers(self) -> bool:
        """
        Проверить наличие слоёв этапности в проекте

        Этапность определяется по наличию слоёв с префиксами Le_3_7_ или Le_3_8_
        с непустыми объектами.

        Returns:
            True если есть слои этапности с данными
        """
        layer_finder = LayerReplacementManager()

        # Проверяем наличие слоёв этапности (полигоны или точки)
        for stage_info in POZU_STAGE_LAYERS.values():
            for prefix in [stage_info['polygons'], stage_info['points']]:
                found_layers = layer_finder.find_layers_by_pattern(prefix, QgsVectorLayer)
                for layer in found_layers:
                    if layer.featureCount() > 0:
                        log_info(f"F_6_2: Найден слой этапности {layer.name()} с {layer.featureCount()} объектами")
                        return True

        log_info("F_6_2: Слои этапности не найдены или пусты")
        return False

    def _get_temporary_zu_ids(self, stage2_layers: List[QgsVectorLayer]) -> Set[int]:
        """
        Получить ID временных ЗУ из поля Состав_контуров слоёв 2 этапа

        Временные ЗУ - это контуры 1 этапа, которые были объединены на 2 этапе.
        Их ID хранятся в поле Состав_контуров (например: "100, 101, 102").

        Args:
            stage2_layers: Слои 2 этапа (полигоны Le_3_7_2_*)

        Returns:
            Set[int]: Множество ID временных ЗУ
        """
        temporary_ids: Set[int] = set()

        for layer in stage2_layers:
            # Проверяем наличие поля Состав_контуров
            field_idx = layer.fields().indexFromName('Состав_контуров')
            if field_idx < 0:
                continue

            for feature in layer.getFeatures():
                contours_str = feature['Состав_контуров']
                if not contours_str or contours_str == '-':
                    continue

                # Парсим строку "100, 101, 102" в множество ID
                for id_str in str(contours_str).split(','):
                    id_str = id_str.strip()
                    if id_str.isdigit():
                        temporary_ids.add(int(id_str))

        if temporary_ids:
            log_info(f"F_6_2: Найдено {len(temporary_ids)} временных ЗУ для исключения из итога: {sorted(temporary_ids)}")

        return temporary_ids

    def _create_filtered_memory_layer(
        self,
        source_layer: QgsVectorLayer,
        exclude_ids: Set[int],
        id_field: str = 'ID'
    ) -> Optional[QgsVectorLayer]:
        """
        Создать memory-слой с фильтрацией по ID

        Args:
            source_layer: Исходный слой
            exclude_ids: Множество ID для исключения
            id_field: Имя поля с ID (по умолчанию 'ID')

        Returns:
            QgsVectorLayer: Memory-слой без исключённых объектов
        """
        if not exclude_ids:
            return source_layer  # Нет фильтрации - возвращаем исходный слой

        # Проверяем наличие поля ID
        id_idx = source_layer.fields().indexFromName(id_field)
        if id_idx < 0:
            log_warning(f"F_6_2: Поле '{id_field}' не найдено в слое {source_layer.name()}")
            return source_layer

        # Создаём memory-слой с той же структурой
        geom_type = source_layer.geometryType()
        geom_type_str = {0: 'Point', 1: 'LineString', 2: 'Polygon'}.get(geom_type, 'Polygon')
        crs = source_layer.crs()

        # ВАЖНО: Сохраняем оригинальное имя слоя для правильного поиска стилей в Base_layers.json
        # DxfExporter использует layer.name() для поиска стилей, поэтому имя должно совпадать
        memory_layer = QgsMemoryProviderUtils.createMemoryLayer(
            source_layer.name(),  # Оригинальное имя для корректного поиска стилей
            source_layer.fields(),
            source_layer.wkbType(),
            crs
        )

        if not memory_layer or not memory_layer.isValid():
            log_error(f"F_6_2: Не удалось создать memory-слой для {source_layer.name()}")
            return source_layer

        # Копируем объекты, исключая временные ЗУ
        memory_layer.startEditing()
        filtered_count = 0
        included_count = 0

        for feature in source_layer.getFeatures():
            feature_id = feature[id_field]
            # Проверяем ID (может быть int или str)
            try:
                feature_id_int = int(feature_id) if feature_id else None
            except (ValueError, TypeError):
                feature_id_int = None

            if feature_id_int in exclude_ids:
                filtered_count += 1
                continue  # Исключаем временный ЗУ

            # Копируем объект
            new_feature = QgsFeature(memory_layer.fields())
            new_feature.setGeometry(feature.geometry())
            for field in source_layer.fields():
                new_feature[field.name()] = feature[field.name()]
            memory_layer.addFeature(new_feature)
            included_count += 1

        memory_layer.commitChanges()

        log_info(f"F_6_2: Фильтрация слоя {source_layer.name()}: "
                f"включено {included_count}, отфильтровано {filtered_count} временных ЗУ")

        return memory_layer

    def _export_pozu_with_stages(self, output_folder: str, ref_managers) -> Dict[str, bool]:
        """
        Экспорт П_ОЗУ с этапностью - 3 отдельных файла

        Для слоя "итог" применяется фильтрация временных ЗУ:
        - Временные ЗУ (ID из Состав_контуров 2 этапа) исключаются из графики
        - Они остаются в таблице для ведомости, но не экспортируются на чертёж

        Args:
            output_folder: Папка для сохранения
            ref_managers: Reference managers

        Returns:
            dict: {filename: success}
        """
        results = {}
        layer_finder = LayerReplacementManager()

        from Daman_QGIS.managers import StyleManager
        style_manager = StyleManager()
        exporter = DxfExporter(self.iface, style_manager)

        # Получаем ID временных ЗУ из слоя "итог" (более надёжно, чем из 2 этапа)
        # Временные ЗУ - это ID контуров из поля Состав_контуров у записей 2 этапа
        itog_polygon_layers = layer_finder.find_layers_by_pattern(
            POZU_STAGE_LAYERS['итог']['polygons'], QgsVectorLayer
        )
        temporary_zu_ids = self._get_temporary_zu_ids(itog_polygon_layers)

        for stage_name, prefixes in POZU_STAGE_LAYERS.items():
            filename = f"П_ОЗУ_{stage_name}"
            output_path = os.path.join(output_folder, f"{filename}.dxf")

            qgis_layers = []
            # Собираем префиксы (points может быть None для итога)
            layer_prefixes = [
                (prefixes['polygons'], False),  # (prefix, is_point_layer)
            ]
            if prefixes['points']:  # Только если есть точечный слой
                layer_prefixes.append((prefixes['points'], True))

            for prefix, is_point_layer in layer_prefixes:
                found_layers = layer_finder.find_layers_by_pattern(prefix, QgsVectorLayer)

                # Для "итог" фильтруем временные ЗУ (только полигоны, точек нет)
                if stage_name == 'итог' and temporary_zu_ids:
                    filtered_layers = []
                    for layer in found_layers:
                        # Для точечных слоёв используем ID_Контура, для полигонов - ID
                        id_field = 'ID_Контура' if is_point_layer else 'ID'
                        filtered_layer = self._create_filtered_memory_layer(
                            layer, temporary_zu_ids, id_field=id_field
                        )
                        filtered_layers.append(filtered_layer)
                    qgis_layers.extend(filtered_layers)
                else:
                    qgis_layers.extend(found_layers)

            if not qgis_layers:
                log_warning(f"F_6_2: Не найдены слои для {filename}")
                results[filename] = False
                continue

            log_info(f"F_6_2: Экспорт {filename} ({len(qgis_layers)} слоёв) в {output_path}")

            try:
                export_results = exporter.export_layers(qgis_layers, output_path=output_path)
                success = all(export_results.values())
                results[filename] = success

                if success:
                    log_success(f"F_6_2: {filename} экспортирован успешно")
                else:
                    log_error(f"F_6_2: Ошибка экспорта {filename}")
            except Exception as e:
                log_error(f"F_6_2: Ошибка экспорта {filename}: {str(e)}")
                results[filename] = False

        return results

    def _export_pozu_without_stages(self, output_folder: str, ref_managers) -> Dict[str, bool]:
        """
        Экспорт П_ОЗУ без этапности - все нарезки в 1 файл

        Args:
            output_folder: Папка для сохранения
            ref_managers: Reference managers

        Returns:
            dict: {filename: success}
        """
        filename = "П_ОЗУ"
        output_path = os.path.join(output_folder, f"{filename}.dxf")

        layer_finder = LayerReplacementManager()
        qgis_layers = []

        for prefix in POZU_DEFAULT_LAYERS:
            found_layers = layer_finder.find_layers_by_pattern(prefix, QgsVectorLayer)
            qgis_layers.extend(found_layers)
            if found_layers:
                log_info(f"F_6_2: По префиксу '{prefix}' найдено {len(found_layers)} слоёв")

        if not qgis_layers:
            log_warning(f"F_6_2: Не найдены слои нарезки для {filename}")
            return {filename: False}

        log_info(f"F_6_2: Экспорт {filename} ({len(qgis_layers)} слоёв) в {output_path}")

        try:
            from Daman_QGIS.managers import StyleManager
            style_manager = StyleManager()
            exporter = DxfExporter(self.iface, style_manager)

            export_results = exporter.export_layers(qgis_layers, output_path=output_path)
            success = all(export_results.values())

            if success:
                log_success(f"F_6_2: {filename} экспортирован успешно")
            else:
                log_error(f"F_6_2: Ошибка экспорта {filename}")

            return {filename: success}
        except Exception as e:
            log_error(f"F_6_2: Ошибка экспорта {filename}: {str(e)}")
            return {filename: False}
