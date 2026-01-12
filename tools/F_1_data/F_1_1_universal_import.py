# -*- coding: utf-8 -*-
"""
F_1_1_Import - Универсальный контроллер импорта данных
Главный оркестратор, направляющий импорт в соответствующие сабмодули
"""

import os
import traceback
from typing import Optional, Dict, List, Any
from qgis.core import QgsProject, Qgis
from qgis.PyQt.QtWidgets import QMessageBox, QProgressDialog
from qgis.PyQt.QtCore import Qt

from Daman_QGIS.core.base_tool import BaseTool
from Daman_QGIS.constants import PLUGIN_NAME, MESSAGE_SUCCESS_DURATION, MESSAGE_INFO_DURATION, MESSAGE_WARNING_DURATION
from Daman_QGIS.utils import log_info, log_warning, log_error
from .ui.universal_import_dialog import UniversalImportDialog
from .submodules.Fsm_1_1_1_xml import XmlImportSubmodule
from .submodules.Fsm_1_1_1_dxf_importer import DxfImporter
from .submodules.Fsm_1_1_2_tab_importer import TabImporter
from .submodules.Fsm_1_1_4_vypiska_importer import Fsm_1_1_4_VypiskaImporter
from .submodules.Fsm_1_1_xml_detector import XmlTypeDetector


class F_1_1_UniversalImport(BaseTool):
    """Универсальный контроллер импорта - точка входа для всех форматов"""
    
    # Маппинг форматов на сабмодули
    FORMAT_SUBMODULES = {
    'XML': XmlImportSubmodule,
    'DXF': DxfImporter,
    'TAB': TabImporter
    }
    
    def __init__(self, iface):
        """Инициализация инструмента"""
        super().__init__(iface)
        self.project_manager = None
        self.layer_manager = None
        self.plugin_dir: Optional[str] = None
    
    def set_plugin_dir(self, plugin_dir):
        """Установка директории плагина"""
        self.plugin_dir = plugin_dir
    
    def set_project_manager(self, project_manager):
        """Установка менеджера проектов"""
        self.project_manager = project_manager
    
    def set_layer_manager(self, layer_manager):
        """Установка менеджера слоев"""
        self.layer_manager = layer_manager
    
    @property
    def name(self):
        """Имя инструмента"""
        return "1_1_Импорт"

    def get_name(self):
        """Получить имя инструмента"""
        return "F_1_1_Импорт"
    def run(self):
        """Запуск инструмента с диалогом"""
        # DEPRECATED: 2025-10-28
        # Reason: Устаревшая реализация автоочистки слоев при универсальном импорте.
        # Удаляет все слои с creating_function="F_1_1_Импорт" без учета типа импорта.
        # Проблема: для накопительных операций (выписки, несколько КПТ) это неправильно.
        # TODO: Продумать грамотный механизм замены слоев:
        #   - Опция в диалоге "Заменить существующие слои" (чекбокс)
        #   - Или специфичная очистка по типу импорта (КПТ заменяет, выписки накапливаются)
        #   - Или очистка только целевого слоя, а не всех слоев функции
        # self.auto_cleanup_layers()

        # Проверяем открыт ли проект
        if not self._check_project():
            return

        # Проверяем что plugin_dir установлен
        if not self.plugin_dir:
            raise RuntimeError("plugin_dir не установлен")

        # Показываем универсальный диалог импорта
        assert self.plugin_dir is not None  # для type checker
        dialog = UniversalImportDialog(self.plugin_dir, self.iface.mainWindow())

        if dialog.exec_():
            options = dialog.get_import_options()
            if options:
                self.import_with_options(options)
    def import_with_options(self, options: Dict[str, Any]):
        """
        Импорт с заданными опциями

        Args:
            options: Опции импорта из диалога
        """
        format_name = options.get('format')
        files = options.get('files', [])
        layers = options.get('layers', {})
        import_options = options.get('options', {})
        layer_name = options.get('layer_name')  # Полное имя слоя

        # Логируем начало импорта
        log_info(f"F_1_1: Импорт {len(files)} файлов ({format_name}), слоёв: {len(layers)}")

        # Валидация формата
        if format_name not in self.FORMAT_SUBMODULES:
            raise ValueError(f"Неподдерживаемый формат: {format_name}")

        submodule_class = self.FORMAT_SUBMODULES[format_name]
        if not submodule_class:
            raise NotImplementedError(f"Сабмодуль для {format_name} еще не реализован")

        # Создаем прогресс-диалог
        progress = self._create_progress_dialog(len(files), format_name)

        # Результаты импорта
        all_results = {
            'success': True,
            'layers': [],
            'errors': []
        }

        try:
            # Для каждого файла вызываем соответствующий сабмодуль
            for idx, file_path in enumerate(files):
                if progress and progress.wasCanceled():
                    break

                # Обновляем прогресс
                if progress:
                    progress.setValue(idx + 1)
                    progress.setLabelText(
                        f"Импорт файла {idx + 1} из {len(files)}:\n"
                        f"{os.path.basename(file_path)}"
                    )

                # Импортируем через сабмодуль
                if format_name == 'XML':
                    # XML может импортировать сразу несколько файлов
                    result = self._import_xml(files, layers, import_options)
                    all_results = self._merge_results(all_results, result)
                    break  # XML обрабатывает все файлы сразу
                else:
                    # Остальные форматы - по одному файлу
                    result = self._import_single_file(
                        file_path, format_name, layers, import_options
                    )
                    all_results = self._merge_results(all_results, result)

        finally:
            if progress:
                progress.close()

        # Применяем сортировку слоёв по order_layers из Base_layers.json
        # ВАЖНО: Вызывается ОДИН РАЗ после импорта всех слоёв
        if self.layer_manager and all_results.get('layers'):
            self.layer_manager.sort_all_layers()
            log_info("F_1_1: Применена сортировка слоёв по order_layers")

        # Проверяем и логируем импортированные слои
        self._verify_imported_layers(all_results)

        # Показываем результаты
        self._show_results(all_results, format_name)
    def import_file_direct(self, file_path: str, format_name: str,
                          layer_id: Optional[str] = None, **params) -> Dict[str, Any]:
        """
        Прямой импорт файла без диалога (для вызова из других инструментов)

        Args:
            file_path: Путь к файлу
            format_name: Формат файла (XML, DXF, TAB, etc.)
            layer_id: ID целевого слоя
            **params: Дополнительные параметры

        Returns:
            Результаты импорта
        """
        # Проверяем проект
        if not self._check_project():
            return {'success': False, 'message': 'Проект не открыт'}

        # Определяем сабмодуль
        submodule_class = self.FORMAT_SUBMODULES.get(format_name.upper())
        if not submodule_class:
            return {
                'success': False,
                'message': f'Неподдерживаемый формат: {format_name}'
            }

        # Создаем экземпляр сабмодуля
        submodule = submodule_class(self.iface)
        submodule.set_project_manager(self.project_manager)
        submodule.set_layer_manager(self.layer_manager)

        # Добавляем layer_id в параметры если задан
        if layer_id:
            params['layer_id'] = layer_id
            params['layer_name'] = layer_id

        # Вызываем импорт
        result = submodule.import_file(file_path, **params)

        # Применяем сортировку слоёв после импорта
        if self.layer_manager and result.get('success'):
            self.layer_manager.sort_all_layers()
            log_info("F_1_1: Применена сортировка слоёв по order_layers (direct import)")

        return result
    
    def _check_project(self) -> bool:
        """Проверка открытого проекта"""
        if not self.project_manager or not self.project_manager.is_project_open():
            QMessageBox.warning(
                None,
                "Предупреждение",
                "Сначала откройте или создайте проект"
            )
            return False
        return True
    
    def _import_xml(self, files: List[str], layers: Dict, options: Dict) -> Dict:
        """
        Импорт XML файлов с автоопределением типа (КПТ vs Выписки)
        """
        # Классифицируем файлы
        classified = XmlTypeDetector.classify_files(files)

        kpt_files = classified.get('KPT', [])
        vypiska_files = classified.get('VYPISKA', [])
        unknown_files = classified.get('UNKNOWN', [])

        # Логируем сводку
        if kpt_files:
            log_info(f"F_1_1: Найдено КПТ файлов: {len(kpt_files)}")
        if vypiska_files:
            log_info(f"F_1_1: Найдено выписок: {len(vypiska_files)}")
        if unknown_files:
            log_warning(f"F_1_1: Неизвестных XML файлов: {len(unknown_files)}")

        # Результаты импорта
        combined_results = {
            'success': True,
            'layers': [],
            'errors': [],
            'message': ''
        }

        # Импортируем КПТ
        if kpt_files:
            kpt_submodule = XmlImportSubmodule(self.iface)
            kpt_submodule.set_project_manager(self.project_manager)
            kpt_submodule.set_layer_manager(self.layer_manager)

            kpt_result = kpt_submodule.import_file(kpt_files, **options)  # type: ignore[arg-type]
            combined_results = self._merge_results(combined_results, kpt_result)

        # Импортируем выписки
        if vypiska_files:
            vypiska_submodule = Fsm_1_1_4_VypiskaImporter(self.iface)
            vypiska_submodule.set_project_manager(self.project_manager)
            vypiska_submodule.set_layer_manager(self.layer_manager)

            vypiska_result = vypiska_submodule.import_file(vypiska_files, **options)  # type: ignore[arg-type]
            combined_results = self._merge_results(combined_results, vypiska_result)

            # После успешного импорта выписок - автоматическая синхронизация и анализ
            if vypiska_result.get('success'):
                self._run_auto_sync_and_analysis()

        # Предупреждаем о неизвестных файлах
        if unknown_files:
            combined_results['errors'].append(f"Пропущено неизвестных XML файлов: {len(unknown_files)}")

        return combined_results
    
    def _import_single_file(self, file_path: str, format_name: str,
                           layers: Dict, options: Dict) -> Dict:
        """Импорт одного файла"""
        # Определяем сабмодуль
        submodule_class = self.FORMAT_SUBMODULES[format_name]
        submodule = submodule_class(self.iface)
        submodule.set_project_manager(self.project_manager)
        submodule.set_layer_manager(self.layer_manager)
        
        # Для каждого выбранного слоя
        results = {
            'success': True,
            'layers': [],
            'message': '',
            'errors': []
        }
        
        for layer_id, layer_data in layers.items():
            # Формируем параметры для слоя
            layer_params = options.copy()
            layer_params['layer_id'] = layer_id
            layer_params['layer_name'] = layer_data.get('name', layer_id)  # Используем полное имя
            layer_params['group_name'] = layer_data.get('group')

            # Импортируем
            result = submodule.import_file(file_path, **layer_params)

            # Объединяем результаты
            if result.get('success'):
                results['layers'].extend(result.get('layers', []))
            else:
                results['success'] = False
                results['errors'].extend(result.get('errors', []))
                log_warning(f"F_1_1: Ошибки импорта: {result.get('errors', [])}")
        
        return results
    
    def _create_progress_dialog(self, total_files: int, format_name: str) -> Optional[QProgressDialog]:
        """Создание диалога прогресса"""
        if total_files <= 1:
            return None
        
        progress = QProgressDialog(
            f"Импорт {format_name} файлов...",
            "Отмена",
            0,
            total_files,
            self.iface.mainWindow()
        )
        progress.setWindowModality(Qt.WindowModal)
        progress.setAutoClose(True)
        progress.show()
        return progress
    
    def _merge_results(self, total: Dict, new: Dict) -> Dict:
        """Объединение результатов импорта"""
        total['success'] = total['success'] and new.get('success', False)
        total['layers'].extend(new.get('layers', []))
        total['errors'].extend(new.get('errors', []))
        # Если хотя бы один импорт асинхронный, помечаем весь результат как асинхронный
        if new.get('async', False):
            total['async'] = True
        return total
    
    def _show_results(self, results: Dict, format_name: str):
        """Показ результатов импорта"""
        # Если импорт асинхронный, результаты покажет сам субмодуль
        if results.get('async', False):
            return

        if results['success']:
            layer_count = len(results['layers'])

            # Информационное сообщение
            self.iface.messageBar().pushMessage(
                "Успешно",
                f"Импортировано {layer_count} слоев из {format_name}",
                level=Qgis.Success,
                duration=MESSAGE_INFO_DURATION
            )
            
            # Масштабируем к первому слою
            if results['layers']:
                first_layer = results['layers'][0]
                self.iface.setActiveLayer(first_layer)
                self.iface.zoomToActiveLayer()
        else:
            # Сообщение об ошибках
            error_msg = "Ошибки при импорте:\n"
            for error in results['errors'][:5]:  # Показываем первые 5 ошибок
                error_msg += f"• {error}\n"
            
            if len(results['errors']) > 5:
                error_msg += f"... и еще {len(results['errors']) - 5} ошибок"
            
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Ошибки импорта",
                error_msg
            )
    
    def _verify_imported_layers(self, results: Dict[str, Any]):
        """
        Проверка и логирование импортированных слоёв

        Args:
            results: Результаты импорта
        """
        # Если импорт асинхронный, не логируем предупреждение
        if results.get('async', False):
            log_info(f"F_1_1: Импорт запущен асинхронно, слои будут добавлены по завершении")
            return

        imported_count = len(results.get('layers', []))

        if imported_count == 0:
            log_warning(f"F_1_1: Слои не были импортированы!")
            return

        log_info(f"F_1_1: Импортировано слоёв: {imported_count}")

        # Проверяем наличие слоёв в проекте
        project = QgsProject.instance()

        for layer in results.get('layers', []):
            layer_name = layer.name() if hasattr(layer, 'name') else str(layer)
            layer_id = layer.id() if hasattr(layer, 'id') else None

            layer_found = project.mapLayer(layer_id) if layer_id else None

            if not layer_found:
                log_error(f"F_1_1: Слой '{layer_name}' НЕ НАЙДЕН в проекте!")
                continue

            # ВАЖНО: Плоская структура - все слои в корне, группы не используются
            # Проверка на группы убрана, так как теперь используется плоская структура слоёв

    def _run_auto_sync_and_analysis(self) -> None:
        """
        Автоматическая синхронизация и анализ после импорта выписок

        Вызывает:
        1. M_24 SyncManager - синхронизация выписок с выборкой
        2. M_23 OksZuAnalysisManager - анализ связей ОКС-ЗУ
        3. M_25 FillsManager - распределение по категориям и правам
        """
        try:
            # ШАГ 1: Синхронизация выписок с выборкой (M_24)
            from Daman_QGIS.managers import SyncManager
            sync_manager = SyncManager(self.iface)
            sync_manager.set_layer_manager(self.layer_manager)
            sync_result = sync_manager.auto_sync()

            if sync_result.get('updated_features', 0) > 0:
                log_info(
                    f"F_1_1: Автосинхронизация: обновлено {sync_result['updated_features']} объектов, "
                    f"заменено {sync_result.get('fields_updated', 0)} полей"
                )

            # ШАГ 2: Анализ ОКС-ЗУ (M_23)
            from Daman_QGIS.managers import OksZuAnalysisManager
            oks_zu_manager = OksZuAnalysisManager(self.iface)
            oks_zu_result = oks_zu_manager.auto_analyze()

            if oks_zu_result.get('oks_updated', 0) > 0 or oks_zu_result.get('zu_updated', 0) > 0:
                log_info(
                    f"F_1_1: Анализ ОКС-ЗУ: обновлено {oks_zu_result.get('oks_updated', 0)} ОКС, "
                    f"{oks_zu_result.get('zu_updated', 0)} ЗУ"
                )

            # ШАГ 3: Распределение по категориям и правам (M_25)
            from Daman_QGIS.managers import get_fills_manager
            fills_manager = get_fills_manager(self.iface, self.layer_manager)
            fills_result = fills_manager.auto_fill()

            if fills_result:
                cat_layers = len(fills_result.get('categories', {}).get('layers_created', []))
                rights_layers = len(fills_result.get('rights', {}).get('layers_created', []))
                if cat_layers > 0 or rights_layers > 0:
                    log_info(
                        f"F_1_1: Распределение: категории - {cat_layers} слоёв, "
                        f"права - {rights_layers} слоёв"
                    )

        except Exception as e:
            log_warning(f"F_1_1: Ошибка автоматической синхронизации/анализа: {e}")

    def _handle_error(self, exception: Exception, context: str):
        """Обработка ошибок"""
        log_error(f"F_1_1: {context}: {str(exception)}\n{traceback.format_exc()}")
        QMessageBox.critical(
            None,
            "Ошибка",
            f"{context}:\n{str(exception)}"
        )
