# -*- coding: utf-8 -*-
"""
Инструмент создания графики к запросу - координатор модулей
Генерирует PDF схему с OSM подложкой и выбранными слоями
"""

import os
from typing import List, Dict, Optional, Any, Union, Tuple

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QApplication
from qgis.core import QgsProject, Qgis

from Daman_QGIS.core.base_tool import BaseTool
from Daman_QGIS.constants import PLUGIN_NAME, MESSAGE_SUCCESS_DURATION, MESSAGE_INFO_DURATION, MESSAGE_WARNING_DURATION
from Daman_QGIS.utils import log_info, log_warning, log_error
from Daman_QGIS.managers import get_reference_managers, get_project_structure_manager, FolderType
from .submodules.Fsm_1_4_8_graphics_request_dialog import GraphicsRequestDialog
from .submodules.Fsm_1_4_9_graphics_progress_dialog import GraphicsProgressDialog

# Импортируем все подмодули
from .submodules.Fsm_1_4_2_excel_export import ExcelExporter
from .submodules.Fsm_1_4_3_dxf_export import DxfExportWrapper
from .submodules.Fsm_1_4_4_tab_export import TabExporter
from .submodules.Fsm_1_4_5_layout_manager import LayoutManager
from .submodules.Fsm_1_4_6_legend_layers import LegendLayersCreator
from .submodules.Fsm_1_4_7_style_manager import StyleManager


class F_1_4_GraphicsRequest(BaseTool):
    """Инструмент создания графики к запросу - главный координатор"""
    
    def __init__(self, iface) -> None:
        """Инициализация инструмента и всех подмодулей"""
        super().__init__(iface)

        # Инициализируем все модули
        self.excel_exporter = ExcelExporter(iface)
        self.dxf_exporter = DxfExportWrapper(iface)
        self.tab_exporter = TabExporter(iface)
        self.layout_manager = LayoutManager(iface)
        self.legend_creator = LegendLayersCreator(iface)
        self.style_manager = StyleManager(iface)
        
    def get_name(self) -> str:
        """Получить имя инструмента"""
        return "F_1_4_Запрос"
    def run(self) -> None:
        """Основной метод запуска инструмента"""
        # Проверяем наличие проекта
        project = QgsProject.instance()
        if not project.fileName():
            self.iface.messageBar().pushMessage(
                "Ошибка",
                "Сначала откройте или создайте проект",
                level=Qgis.Critical,
                duration=MESSAGE_INFO_DURATION
            )
            return

        # Проверяем наличие необходимых WMS слоев (только логирование, без GUI)
        missing_layers = self._check_required_wms_layers()
        if missing_layers:
            # Логируем отсутствующие слои без показа пользователю
            # Если F_1_2 не загрузила слои - значит их просто нет в области
            log_info(f"F_1_4: Отсутствует {len(missing_layers)} слоёв (возможно нет данных в области)")
            log_info(f"F_1_4: Отсутствующие слои: {', '.join(missing_layers[:5])}...")  # Первые 5 для краткости

        # Показываем диалог выбора слоев
        dialog = GraphicsRequestDialog(self.iface.mainWindow())
        if dialog.exec_() != 1:
            return

        selected_layers = dialog.selected_layers  # Будет пустой список, но это нормально
        nspd_layers = dialog.nspd_layers  # Получаем выбранные слои НСПД
        use_satellite = dialog.use_satellite  # Получаем настройку спутниковой подложки

        # Для совместимости проверяем выбранные векторные слои
        if not nspd_layers or not any(nspd_layers.values()):
            self.iface.messageBar().pushMessage(
                "Предупреждение",
                "Не выбрано ни одного векторного слоя",
                level=Qgis.Warning,
                duration=MESSAGE_SUCCESS_DURATION
            )
            # Но все равно продолжаем - будет только слой границ работ

        # Создаем схему с передачей слоев НСПД и настройки спутника
        self.create_graphics(selected_layers, nspd_layers, use_satellite)
            
    def create_graphics(self, selected_layer_ids: List[str], nspd_layers: Optional[Dict[str, bool]] = None, use_satellite: bool = False) -> None:
        """Создание графики с выбранными слоями - координация всех модулей

        Args:
            selected_layer_ids: Список ID выбранных слоев проекта
            nspd_layers: Словарь с выбранными слоями НСПД
            use_satellite: Использовать спутниковый снимок вместо ЦОС
        """
        
        # Создаем и показываем диалог прогресса
        progress_dialog = GraphicsProgressDialog(self.iface.mainWindow())
        progress_dialog.show()
        QApplication.processEvents()  # Обновляем GUI
        
        try:
            # Удаляем существующие служебные слои перед загрузкой новых
            self._remove_existing_service_layers()
            
            # Автоматически добавляем слой границ работ в список выбранных
            boundaries_layer_id = self._get_boundaries_layer_id()
            if boundaries_layer_id:
                if boundaries_layer_id not in selected_layer_ids:
                    selected_layer_ids.append(boundaries_layer_id)
            
            self._execute_graphics_creation(progress_dialog, selected_layer_ids, nspd_layers, use_satellite)
        except Exception as e:
            progress_dialog.update_progress(0, f"Ошибка: {str(e)}")
            progress_dialog.enable_close()
            log_error(f"F_1_4: Критическая ошибка - {str(e)}")
            raise
    
    def _remove_existing_service_layers(self) -> None:
        """Удаление существующих служебных слоев с префиксом Le_1_4"""
        project = QgsProject.instance()
        layers_to_remove = []
        
        # Собираем слои для удаления
        for layer_id, layer in project.mapLayers().items():
            layer_name = layer.name()
            # Удаляем слои с префиксом Le_1_4 (служебные слои для графики)
            if layer_name.startswith('Le_1_4'):
                layers_to_remove.append(layer_id)
                log_info(f"F_1_4: Удаляем служебный слой: {layer_name}")

        # Удаляем найденные слои
        for layer_id in layers_to_remove:
            project.removeMapLayer(layer_id)

        if layers_to_remove:
            log_info(f"F_1_4: Удалено {len(layers_to_remove)} служебных слоев Le_1_4")
    
    def _get_boundaries_layer_id(self) -> Optional[str]:
        """Получение ID слоя границ работ L_1_1_1_Границы_работ

        Returns:
            str: ID слоя или None
        """
        project = QgsProject.instance()
        for layer_id, layer in project.mapLayers().items():
            if layer.name() == "L_1_1_1_Границы_работ":
                return layer_id
        return None

    @staticmethod
    def _normalize_result(result: Union[bool, Tuple[bool, Optional[str]]], default_error: str) -> Tuple[bool, Optional[str]]:
        """
        Нормализует результат выполнения модуля к единому формату (success, error)

        Args:
            result: Результат выполнения модуля (bool или tuple)
            default_error: Сообщение об ошибке по умолчанию

        Returns:
            Tuple[bool, Optional[str]]: (success, error_message)
        """
        if isinstance(result, bool):
            return result, None
        elif len(result) == 2:
            return result  # type: ignore
        else:
            return False, default_error

    def _check_required_wms_layers(self) -> List[str]:
        """Проверка наличия необходимых Web слоев в проекте из Base_layers.json

        ВАЖНО: Учитывает родительские слои созданные через F_1_2
        Например, если есть L_1_2_4_WFS_ОКС, то подслои Le_1_2_4_X считаются загруженными

        Returns:
            list: Список отсутствующих слоев (пустой если все на месте)
        """
        # Получаем список required слоёв из Base_layers.json
        ref_managers = get_reference_managers()
        layer_manager = ref_managers.layer

        required_wms_layers = []
        parent_mapping = {}  # Маппинг подслоёв на родительские

        if layer_manager:
            all_layers = layer_manager.get_base_layers()

            # Собираем слои из групп L_1_2, Le_1_2, L_1_3 (Web слои)
            for layer in all_layers:
                full_name = layer.get('full_name', '')
                # Проверяем что слой принадлежит группам L_1_2, Le_1_2 или L_1_3
                if (full_name.startswith('L_1_2_') or
                    full_name.startswith('Le_1_2_') or
                    full_name.startswith('L_1_3_')):
                    required_wms_layers.append(full_name)

                    # Создаём маппинг подслоёв на родительские слои
                    # Например: Le_1_2_4_1_WFS_Здание → L_1_2_4_WFS_ОКС
                    if full_name.startswith('Le_1_2_4_'):
                        parent_mapping[full_name] = 'L_1_2_4_WFS_ОКС'
                    # Остальные слои могут использовать себя как родительские
                    elif full_name.startswith('L_1_2_'):
                        parent_mapping[full_name] = full_name

        project = QgsProject.instance()
        existing_layers = set(layer.name() for layer in project.mapLayers().values())

        missing_layers = []
        for layer_name in required_wms_layers:
            # Проверяем наличие самого слоя
            if layer_name in existing_layers:
                continue

            # Проверяем наличие родительского слоя
            parent_layer = parent_mapping.get(layer_name)
            if parent_layer and parent_layer in existing_layers:
                continue

            # Если ни слой, ни родительский слой не найдены
            missing_layers.append(layer_name)

        return missing_layers

    def _get_graphics_folder(self) -> Optional[str]:
        """
        Определить папку для сохранения графики к запросам

        Использует M_19_ProjectStructureManager для получения пути к папке "Графика".
        Fallback: создает папку "Графика к запросам" в корне проекта.

        Returns:
            Путь к папке "Графика" или None если не удалось определить
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
                output_folder = structure_manager.get_folder(FolderType.GRAPHICS)
                if output_folder:
                    log_info(f"F_1_4: Папка графики через M_19: {output_folder}")
                    return os.path.normpath(output_folder)

            # Fallback для старых проектов
            log_warning("F_1_4: M_19 не активен, используем fallback")
            project = QgsProject.instance()
            project_path = project.homePath()

            if not project_path:
                log_warning("F_1_4: Проект QGIS не сохранён, не удалось определить папку")
                return None

            # Создаём путь к папке "Графика к запросам" (старое название)
            output_folder = os.path.join(project_path, "Графика к запросам")
            return os.path.normpath(output_folder)

        except Exception as e:
            log_error(f"F_1_4: Ошибка определения папки для сохранения: {str(e)}")
            return None

    def _execute_graphics_creation(self, progress_dialog, selected_layer_ids: List[str], nspd_layers: Optional[Dict[str, bool]], use_satellite: bool = False) -> None:
        """Выполнение создания графики"""
        
        # Флаг создания макета
        layout_created = False
        
        # Получаем путь к папке графики через M_19
        graphics_folder = self._get_graphics_folder()
        if not graphics_folder:
            progress_dialog.update_progress(0, "Ошибка: не удалось определить путь к проекту")
            progress_dialog.enable_close()
            raise Exception("Не удалось определить путь к проекту")

        # Если папка существует, удаляем её содержимое
        if os.path.exists(graphics_folder):
            import shutil
            shutil.rmtree(graphics_folder)
            log_info(f"F_1_4: Удалена существующая папка: {graphics_folder}")

        os.makedirs(graphics_folder, exist_ok=True)
        
        # Сохраняем путь к папке результатов
        progress_dialog.set_result_folder(graphics_folder)
        
        # Словарь для сбора результатов выполнения модулей
        results = {}

        # Счетчик шагов для прогресса
        total_steps = 8
        current_step = 0

        # 1. Настраиваем правила подписей для избегания перекрытий (ВСЕГДА применяем)
        current_step += 1
        progress_dialog.update_progress(int(current_step * 100 / total_steps), "Настройка правил подписей...")
        QApplication.processEvents()

        # ВСЕГДА применяем правила подписей при создании графического запроса
        # Причина: слои могли быть перезагружены через F_1_2, и подписи могли быть потеряны

        # === ПРИМЕНЕНИЕ ПОДПИСЕЙ ===
        # ВАЖНО: Принудительно обновляем подписи для ВСЕХ слоёв
        # Причина: при отладке нужно гарантировать что настройки актуальные из Base_labels.json
        try:
            from Daman_QGIS.managers import LabelManager

            label_manager = LabelManager()

            # Настраиваем глобальный движок коллизий (ОДИН РАЗ)
            label_manager.configure_global_engine(self.iface)
            log_info("F_1_4: Глобальный движок коллизий подписей настроен")

            # Принудительно применяем подписи ко ВСЕМ векторным слоям
            project = QgsProject.instance()
            applied_count = 0
            skipped_count = 0
            for layer_id, layer in project.mapLayers().items():
                if layer.type() == 0:  # Векторный слой
                    layer_name = layer.name()
                    if label_manager.apply_labels(layer, layer_name):
                        applied_count += 1
                    else:
                        skipped_count += 1
            log_info(f"F_1_4: Подписи обновлены: {applied_count} слоёв, пропущено: {skipped_count}")

        except Exception as e:
            log_warning(f"F_1_4: Не удалось настроить движок подписей: {str(e)}")
            import traceback
            log_warning(f"F_1_4: {traceback.format_exc()}")

        # 2. Создаем компоновку из шаблона
        current_step += 1
        progress_dialog.update_progress(int(current_step * 100 / total_steps), "Создание компоновки...")
        QApplication.processEvents()
        log_info("F_1_4: Запуск модуля Fsm_1_4_5_layout_manager")
        
        try:
            result = self.layout_manager.create_layout_from_template(selected_layer_ids, nspd_layers, use_satellite)
            success, error = self._normalize_result(result, "Ошибка создания макета")
        except Exception as e:
            success, error = False, str(e)
            
        results['layout'] = (success, error)
        layout_created = success
        if success:
            log_info("F_1_4: Fsm_1_4_5_layout_manager: успех")
        else:
            log_error(f"F_1_4: Fsm_1_4_5_layout_manager: ошибка - {error}")

        # 3. Создаем векторные слои для легенды если создан макет
        if layout_created:
            current_step += 1
            progress_dialog.update_progress(int(current_step * 100 / total_steps), "Создание слоев легенды...")
            QApplication.processEvents()
            log_info("F_1_4: Запуск модуля Fsm_1_4_6_legend_layers")
            
            try:
                result = self.legend_creator.create_legend_layers()
                success, error = self._normalize_result(result, "Ошибка создания слоев легенды")
            except Exception as e:
                success, error = False, str(e)
                
            results['legend_layers'] = (success, error)
            if success:
                log_info("F_1_4: Fsm_1_4_6_legend_layers: успех")
            else:
                log_error(f"F_1_4: Fsm_1_4_6_legend_layers: ошибка - {error}")
        else:
            current_step += 1

        # 4. Настраиваем фильтры для карт если создан макет
        if layout_created:
            current_step += 1
            progress_dialog.update_progress(int(current_step * 100 / total_steps), "Настройка фильтров карт...")
            QApplication.processEvents()
            log_info("F_1_4: Настройка фильтров карт")
            if self.layout_manager.configure_map_filters(nspd_layers, use_satellite):
                log_info("F_1_4: Fsm_1_4_5_layout_manager.configure_filters: успех")
            else:
                log_warning("F_1_4: Fsm_1_4_5_layout_manager.configure_filters: предупреждение")
        else:
            current_step += 1

        # 5. Экспортируем в PDF если создан макет
        if layout_created:
            current_step += 1
            progress_dialog.update_progress(int(current_step * 100 / total_steps), "Экспорт в PDF...")
            QApplication.processEvents()
            pdf_path = os.path.join(graphics_folder, "Приложение_1_Схема.pdf")
            log_info("F_1_4: Экспорт в PDF")
            
            try:
                result = self.layout_manager.export_to_pdf(pdf_path)
                success, error = self._normalize_result(result, "Ошибка экспорта PDF")
            except Exception as e:
                success, error = False, str(e)
                
            results['pdf'] = (success, error)
            if success:
                log_info("F_1_4: Fsm_1_4_5_layout_manager.export_pdf: успех")
            else:
                log_error(f"F_1_4: Fsm_1_4_5_layout_manager.export_pdf: ошибка - {error}")
        else:
            current_step += 1
            log_error("F_1_4: PDF не создан - макет не был создан")
            results['pdf'] = (False, "Макет не создан")
        
        # 6. Проверяем наличие слоя границ работ и экспортируем координаты
        boundaries_layer = None
        for layer in QgsProject.instance().mapLayers().values():
            if layer.name() == "L_1_1_1_Границы_работ":
                boundaries_layer = layer
                break

        if boundaries_layer:
            # 7. Экспортируем координаты в Excel
            current_step += 1
            progress_dialog.update_progress(int(current_step * 100 / total_steps), "Экспорт координат в Excel...")
            QApplication.processEvents()
            log_info("F_1_4: Запуск модуля Fsm_1_4_2_excel_export")
            
            try:
                result = self.excel_exporter.export_coordinates_to_excel(boundaries_layer, graphics_folder)
                success, error = self._normalize_result(result, "Ошибка экспорта Excel")
            except Exception as e:
                success, error = False, str(e)
                
            results['excel'] = (success, error)
            if success:
                log_info("F_1_4: Fsm_1_4_2_excel_export: успех")
            else:
                log_error(f"F_1_4: Fsm_1_4_2_excel_export: ошибка - {error}")

            # 8. Экспортируем в DXF
            current_step += 1
            progress_dialog.update_progress(int(current_step * 100 / total_steps), "Экспорт в DXF...")
            QApplication.processEvents()
            log_info("F_1_4: Запуск модуля Fsm_1_4_3_dxf_export")
            
            try:
                result = self.dxf_exporter.export_to_dxf(boundaries_layer, graphics_folder)
                success, error = self._normalize_result(result, "Ошибка экспорта DXF")
            except Exception as e:
                success, error = False, str(e)
                
            results['dxf'] = (success, error)
            if success:
                log_info("F_1_4: Fsm_1_4_3_dxf_export: успех")
            else:
                log_error(f"F_1_4: Fsm_1_4_3_dxf_export: ошибка - {error}")

            # 9. Экспортируем в TAB
            current_step += 1
            progress_dialog.update_progress(int(current_step * 100 / total_steps), "Экспорт в MapInfo TAB...")
            QApplication.processEvents()
            log_info("F_1_4: Запуск модуля Fsm_1_4_4_tab_export")
            
            try:
                result = self.tab_exporter.export_to_tab(boundaries_layer, graphics_folder)
                success, error = self._normalize_result(result, "Ошибка экспорта TAB")
            except Exception as e:
                success, error = False, str(e)
                
            results['tab'] = (success, error)
            if success:
                log_info("F_1_4: Fsm_1_4_4_tab_export: успех")
            else:
                log_error(f"F_1_4: Fsm_1_4_4_tab_export: ошибка - {error}")
        else:
            # Пропускаем 3 шага (Excel, DXF, TAB)
            current_step += 3
            log_warning("F_1_4: Слой 'L_1_1_1_Границы_работ' не найден. Excel, DXF и TAB файлы не созданы.")
        
        # Подводим итоги
        errors_count = sum(1 for success, error in results.values() if not success and error)
        
        # Обновляем прогресс до 100%
        progress_dialog.update_progress(100, "Успех!")
        
        # Определяем сообщение в зависимости от результата
        if errors_count == 0:
            self.iface.messageBar().pushMessage(
                "Успех",
                f"Все файлы успешно созданы в {graphics_folder}",
                level=Qgis.Success,
                duration=MESSAGE_INFO_DURATION
            )
        else:
            self.iface.messageBar().pushMessage(
                "Частичный успех",
                f"Файлы сохранены в {graphics_folder}, но были ошибки ({errors_count}). См. журнал сообщений.",
                level=Qgis.Warning,
                duration=MESSAGE_WARNING_DURATION
            )
        
        # Итоговое сообщение в лог
        log_info(f"F_1_4: Завершение. Успешно: {len(results) - errors_count}, Ошибок: {errors_count}")
        
        # Отображаем диалог для пользователя
        progress_dialog.exec_()
