# -*- coding: utf-8 -*-
""" 
Инструмент F_1_3_Бюджет
Расчет количества попадания объектов кадастра и лесного фонда
"""

import os
from datetime import datetime
from typing import Dict, Any, Optional

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QMessageBox
from qgis.core import QgsProject, Qgis

from Daman_QGIS.core.base_tool import BaseTool
from Daman_QGIS.managers import LayerManager, get_reference_managers, get_async_manager, get_project_structure_manager, FolderType
from Daman_QGIS.constants import PLUGIN_NAME, MESSAGE_SUCCESS_DURATION, MESSAGE_INFO_DURATION, MESSAGE_WARNING_DURATION
from Daman_QGIS.utils import log_info, log_warning, log_error

# Async Task для M_17 (новая реализация)
from .submodules.Fsm_1_3_0_budget_task import Fsm_1_3_0_BudgetTask
from .submodules.Fsm_1_3_1_boundaries_processor import BoundariesProcessor
from .submodules.Fsm_1_3_2_vector_loader import VectorLoader
from .submodules.Fsm_1_3_3_forest_loader import ForestLoader
from .submodules.Fsm_1_3_4_spatial_analyzer import SpatialAnalyzer
from .submodules.Fsm_1_3_5_results_dialog import BudgetSelectionResultsDialog
from .submodules.Fsm_1_3_7_intersections_calculator import IntersectionsCalculator


class F_1_3_BudgetSelection(BaseTool):
    """Инструмент выборки объектов для бюджета

    Использует async режим (M_17): Фоновая обработка через QgsTask, не блокирует UI.
    """

    def __init__(self, iface) -> None:
        """Инициализация инструмента"""
        super().__init__(iface)
        self.project_manager: Optional[Any] = None
        self.layer_manager: Optional[Any] = None
        self.boundaries_processor: Optional[BoundariesProcessor] = None
        self.vector_loader: Optional[VectorLoader] = None
        self.forest_loader: Optional[ForestLoader] = None
        self.spatial_analyzer: Optional[SpatialAnalyzer] = None
        self.intersections_calculator: Optional[IntersectionsCalculator] = None

        # Async manager (M_17)
        self.async_manager = None
        self.temp_folder: Optional[str] = None
    
    def set_project_manager(self, project_manager) -> None:
        """Установка менеджера проектов"""
        self.project_manager = project_manager
    
    def set_layer_manager(self, layer_manager) -> None:
        """Установка менеджера слоев"""
        self.layer_manager = layer_manager

        # Инициализируем субмодули с менеджерами
        if self.project_manager and self.layer_manager:
            self.boundaries_processor = BoundariesProcessor(self.iface, self.project_manager, self.layer_manager)
            self.vector_loader = VectorLoader(self.iface, self.project_manager, self.layer_manager)
            self.forest_loader = ForestLoader(self.iface, self.project_manager, self.layer_manager)
            self.spatial_analyzer = SpatialAnalyzer(self.iface)
            self.intersections_calculator = IntersectionsCalculator(self.iface)

    def _get_required_layers_from_database(self) -> Dict[str, str]:
        """УСТАРЕВШИЙ МЕТОД: Получение списка required слоёв из Base_layers.json

        ВАЖНО: Этот метод не используется в текущей реализации.
        Для земельных участков используется округленный слой Le_2_1_1_1_Выборка_ЗУ из F_2_1.

        Returns:
            Dict[str, str]: Словарь {описание: имя_слоя} для слоёв групп L_1_2 и Le_1_2
        """
        ref_managers = get_reference_managers()
        base_layers_manager = ref_managers.get('base_layers')

        if not base_layers_manager:
            log_error("F_1_3_Бюджет: Не удалось получить base_layers_manager")
            return {}

        layers_dict = {}
        all_layers = base_layers_manager.get_all()

        # Собираем слои из групп L_1_2 и Le_1_2
        for layer in all_layers:
            full_name = layer.get('full_name', '')
            description = layer.get('description', '')

            # Проверяем что слой принадлежит группам L_1_2 или Le_1_2
            if full_name.startswith('L_1_2_') or full_name.startswith('Le_1_2_'):
                # Создаем понятное описание
                if 'ЗУ' in full_name:
                    # УСТАРЕЛО: Используется Le_2_1_1_1_Выборка_ЗУ вместо L_1_2_1_WFS_ЗУ
                    layers_dict["Загрузка земельных участков..."] = 'Le_2_1_1_1_Выборка_ЗУ'
                elif 'КК' in full_name:
                    layers_dict["Загрузка кадастровых кварталов..."] = 'L_1_2_2_WFS_КК'
                elif 'НП' in full_name:
                    layers_dict["Загрузка населенных пунктов..."] = 'Le_1_2_3_5_АТД_НП_poly'

        log_info(f"F_1_3_Бюджет: Загружено {len(layers_dict)} слоёв из БД")
        return layers_dict

    def get_name(self) -> str:
        """Получить имя инструмента"""
        return "F_1_3_Бюджет"

    def _get_budget_folder(self) -> Optional[str]:
        """
        Определить папку для сохранения результатов бюджета

        Использует M_19_ProjectStructureManager.
        Fallback: создает папку "Бюджет" в корне проекта.

        Returns:
            Путь к папке или None если не удалось определить
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

            # Получаем папку через менеджер (TABLES для ведомостей/бюджета)
            if structure_manager.is_active():
                output_folder = structure_manager.get_folder(FolderType.TABLES)
                if output_folder:
                    # Добавляем подпапку "Бюджет"
                    budget_folder = os.path.join(output_folder, "Бюджет")
                    log_info(f"F_1_3: Папка бюджета через M_19: {budget_folder}")
                    return os.path.normpath(budget_folder)

            # Fallback для старых проектов
            log_warning("F_1_3: M_19 не активен, используем fallback")
            project = QgsProject.instance()
            project_path = project.homePath()

            if not project_path:
                log_warning("F_1_3: Проект QGIS не сохранён, не удалось определить папку")
                return None

            # Создаём путь к папке "Бюджет" (старое название в корне)
            output_folder = os.path.join(project_path, "Бюджет")
            return os.path.normpath(output_folder)

        except Exception as e:
            log_error(f"F_1_3: Ошибка определения папки для сохранения: {str(e)}")
            return None

    def run(self) -> None:
        """Основной метод запуска инструмента через M_17 AsyncTaskManager"""
        # Автоматическая очистка слоев перед выполнением
        self.auto_cleanup_layers()

        # Проверяем что проект открыт и менеджеры инициализированы
        if not self.project_manager or not self.project_manager.project_db:
            QMessageBox.critical(
                self.iface.mainWindow(),
                "Ошибка",
                "Проект не открыт!\n\nОткройте или создайте проект через инструменты F_0_1 или F_0_2."
            )
            return

        if not self.layer_manager:
            QMessageBox.critical(
                self.iface.mainWindow(),
                "Ошибка",
                "Менеджер слоев не инициализирован!"
            )
            return

        # Type narrowing для Pylance - после проверок менеджеры точно установлены
        assert self.intersections_calculator is not None
        assert self.spatial_analyzer is not None
        assert self.boundaries_processor is not None
        assert self.vector_loader is not None
        assert self.forest_loader is not None

        # Проверяем наличие слоя границ работ
        project = QgsProject.instance()
        boundaries_layer = None
        for layer in project.mapLayers().values():
            if layer.name() == "L_1_1_1_Границы_работ":
                boundaries_layer = layer
                break

        if not boundaries_layer:
            QMessageBox.critical(
                self.iface.mainWindow(),
                "Ошибка",
                "Не найден слой 'L_1_1_1_Границы_работ'.\nСначала импортируйте границы работ через F_1_1_Импорт."
            )
            return

        log_info("F_1_3_Бюджет: Запуск через M_17 AsyncTaskManager")

        # Получаем папку для результатов через M_19
        self.temp_folder = self._get_budget_folder()
        if not self.temp_folder:
            QMessageBox.critical(
                self.iface.mainWindow(),
                "Ошибка",
                "Не удалось определить папку для сохранения результатов бюджета."
            )
            return

        # Если папка существует, удаляем её содержимое
        if os.path.exists(self.temp_folder):
            import shutil
            shutil.rmtree(self.temp_folder)
            log_info(f"F_1_3: Удалена существующая папка: {self.temp_folder}")

        os.makedirs(self.temp_folder, exist_ok=True)
        # Инициализируем async manager
        if self.async_manager is None:
            self.async_manager = get_async_manager(self.iface)

        # Type assertion для Pylance (temp_folder установлен в run() перед вызовом)
        assert self.temp_folder is not None

        # Создаём task (передаём layer_id, НЕ layer!)
        task = Fsm_1_3_0_BudgetTask(
            boundaries_layer_id=boundaries_layer.id(),
            temp_folder=self.temp_folder,
            iface=self.iface,
            project_manager=self.project_manager,
            layer_manager=self.layer_manager
        )

        # Запускаем через AsyncTaskManager
        self.async_manager.run(
            task,
            show_progress=True,
            on_completed=self._on_budget_completed,
            on_failed=self._on_budget_failed,
            on_cancelled=self._on_budget_cancelled
        )

    def _on_budget_completed(self, result: Dict[str, Any]) -> None:
        """Callback при успешном завершении расчёта бюджета (main thread)"""
        log_info("F_1_3_Бюджет: Async расчёт завершён успешно")

        if result.get('cancelled'):
            log_info("F_1_3_Бюджет: Операция была отменена")
            return

        results = result.get('results', {})
        temp_folder = result.get('temp_folder', self.temp_folder)

        # Сохраняем результаты в txt
        self._save_results_to_txt(results, temp_folder)

        # Организуем слои в группы
        self._organize_layers_in_groups()

        # Показываем диалог с результатами (только в main thread!)
        results_dialog = BudgetSelectionResultsDialog(
            self.iface.mainWindow(),
            results,
            temp_folder
        )
        results_dialog.exec_()

        log_info("F_1_3_Бюджет: Выборка для бюджета успешно завершена")

    def _on_budget_failed(self, error: str) -> None:
        """Callback при ошибке расчёта бюджета (main thread)"""
        log_error(f"F_1_3_Бюджет: Async ошибка - {error}")
        QMessageBox.critical(
            self.iface.mainWindow(),
            "Ошибка выполнения бюджета",
            f"Произошла ошибка при расчете бюджета:\n\n{error}"
        )

    def _on_budget_cancelled(self) -> None:
        """Callback при отмене расчёта бюджета (main thread)"""
        log_info("F_1_3_Бюджет: Операция отменена пользователем")
        self.iface.messageBar().pushMessage(
            "F_1_3_Бюджет",
            "Расчёт бюджета отменён",
            level=Qgis.Warning,
            duration=5
        )

    def _save_results_to_txt(self, results: Dict[str, Any], temp_folder: str) -> None:
        """Сохранение результатов в текстовый файл"""

        try:
            filename = "Выборка_для_бюджета.txt"
            filepath = os.path.join(temp_folder, filename)
            
            # Форматируем список населенных пунктов
            settlements_text = ""
            if results['settlements']:
                for settlement in results['settlements']:
                    settlements_text += f"   - {settlement}\n"
            else:
                settlements_text = "   - Нет данных\n"

            # Форматируем список муниципальных образований
            municipal_districts_text = ""
            if results['municipal_districts']:
                for district in results['municipal_districts']:
                    municipal_districts_text += f"   - {district}\n"
            else:
                municipal_districts_text = "   - Нет данных\n"
            
            # Пересечения линий
            road_road = results.get('road_road', 0)
            road_railway = results.get('road_railway', 0)
            railway_railway = results.get('railway_railway', 0)

            # ЗУ в лесном фонде (показываем всегда, даже если 0)
            forest_fund_count = results.get('land_plots_forest_fund', 0)
            forest_fund_text = f"   в том числе ЗУ в лесном фонде: {forest_fund_count}\n"

            content = f"""=== ВЫБОРКА ДЛЯ БЮДЖЕТА ===
Дата: {datetime.now().strftime('%Y-%m-%d')}

РЕЗУЛЬТАТЫ:
1. Кадастровые кварталы: {results['cadastral_quarters']}
2. Земельные участки: {results['land_plots']}
{forest_fund_text}3. Объекты капитального строительства: {results['capital_objects']}
4. Населенные пункты:
{settlements_text}5. Муниципальные образования:
{municipal_districts_text}6. Лесные кварталы: {results['forest_quarters']}
7. Лесоустроительные выделы: {results['forest_subdivisions']}
8. Пересечения линий:
   • АД и АД: {road_road}
   • АД и ЖД: {road_railway}
   • ЖД и ЖД: {railway_railway}
"""
            
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)

            log_info(f"F_1_3_Бюджет: Результаты сохранены в {filepath}")

        except Exception as e:
            log_warning(f"F_1_3_Бюджет: Ошибка сохранения результатов - {str(e)}")
    
    def _organize_layers_in_groups(self) -> None:
        """Организация созданных слоев в группы согласно Base_layers.json"""
        try:
            # КРИТИЧЕСКИ ВАЖНО: Принудительно сортируем все слои по order_layers
            if self.layer_manager:
                self.layer_manager.sort_all_layers()
                log_info("F_1_3_Бюджет: Порядок слоев отсортирован согласно Base_layers.json")
        except Exception as e:
            log_warning(f"F_1_3_Бюджет: Ошибка организации слоев - {str(e)}")
