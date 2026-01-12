# -*- coding: utf-8 -*-
"""
Fsm_1_3_0: AsyncTask для расчёта бюджета

Наследует от BaseAsyncTask (M_17) для унифицированной асинхронной обработки.
Выполняет последовательную цепочку задач F_1_3 в фоновом потоке.

IMPORTANT: Некоторые операции (показ диалога результатов) требуют main thread.
Этот Task выполняет только расчёты, финализация в finished() через callback.
"""

from typing import Any, Dict, Optional, TYPE_CHECKING
from qgis.core import QgsProject
from Daman_QGIS.managers.submodules.Msm_17_1_base_task import BaseAsyncTask
from Daman_QGIS.utils import log_info, log_error, log_warning

if TYPE_CHECKING:
    from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_3_1_boundaries_processor import BoundariesProcessor
    from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_3_2_vector_loader import VectorLoader
    from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_3_3_forest_loader import ForestLoader
    from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_3_4_spatial_analyzer import SpatialAnalyzer
    from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_3_7_intersections_calculator import IntersectionsCalculator


class Fsm_1_3_0_BudgetTask(BaseAsyncTask):
    """
    Task для асинхронного расчёта бюджета.

    Выполняет последовательно:
    1. Обработка границ (BoundariesProcessor)
    2. Проверка кадастровых кварталов (VectorLoader)
    3. Проверка ОКС (VectorLoader)
    4. Проверка населенных пунктов (VectorLoader)
    5. Проверка лесных кварталов (ForestLoader)
    6. Проверка лесоустроительных выделов (ForestLoader)
    7. Пространственный анализ (SpatialAnalyzer)
    8. Подсчёт пересечений линий (IntersectionsCalculator)

    ВАЖНО: Показ диалога результатов выполняется в main thread через on_completed callback.

    Использование:
        from Daman_QGIS.managers import get_async_manager

        task = Fsm_1_3_0_BudgetTask(
            boundaries_layer_id=boundaries_layer.id(),
            temp_folder=temp_folder,
            project_manager=project_manager,
            layer_manager=layer_manager
        )
        manager = get_async_manager(iface)
        manager.run(task, on_completed=show_results_dialog)
    """

    def __init__(self,
                 boundaries_layer_id: str,
                 temp_folder: str,
                 iface,
                 project_manager,
                 layer_manager):
        """
        Args:
            boundaries_layer_id: ID слоя границ работ (НЕ layer object!)
            temp_folder: Путь к папке для результатов
            iface: QgisInterface
            project_manager: ProjectManager instance
            layer_manager: LayerManager instance
        """
        super().__init__("Расчёт бюджета", can_cancel=True)

        self.boundaries_layer_id = boundaries_layer_id
        self.temp_folder = temp_folder
        self.iface = iface
        self.project_manager = project_manager
        self.layer_manager = layer_manager

        # Субмодули инициализируются в execute() (типизированы для Pylance)
        self.boundaries_processor: Optional['BoundariesProcessor'] = None
        self.vector_loader: Optional['VectorLoader'] = None
        self.forest_loader: Optional['ForestLoader'] = None
        self.spatial_analyzer: Optional['SpatialAnalyzer'] = None
        self.intersections_calculator: Optional['IntersectionsCalculator'] = None

    def execute(self) -> Dict[str, Any]:
        """
        Основная логика расчёта бюджета.

        Returns:
            dict: Результаты расчёта с ключами:
                - results: словарь с подсчитанными значениями
                - temp_folder: путь к папке результатов
                - success: флаг успеха
        """
        log_info("Fsm_1_3_0: Запуск расчёта бюджета")

        # Получаем слой границ по ID
        boundaries_layer = QgsProject.instance().mapLayer(self.boundaries_layer_id)
        if not boundaries_layer:
            raise ValueError(f"Слой границ не найден (id={self.boundaries_layer_id})")

        # Инициализируем субмодули
        self._init_submodules()

        # Type assertions для Pylance (гарантировано после _init_submodules)
        assert self.boundaries_processor is not None
        assert self.vector_loader is not None
        assert self.forest_loader is not None
        assert self.spatial_analyzer is not None
        assert self.intersections_calculator is not None

        results = {
            'cadastral_quarters': 0,
            'land_plots': 0,
            'land_plots_forest_fund': 0,
            'capital_objects': 0,
            'settlements': [],
            'municipal_districts': [],
            'forest_quarters': 0,
            'forest_subdivisions': 0,
            'road_road': 0,
            'road_railway': 0,
            'railway_railway': 0
        }

        total_steps = 8

        # Шаг 1: Обработка границ (10%)
        if self.is_cancelled():
            return {'results': results, 'temp_folder': self.temp_folder, 'success': False, 'cancelled': True}

        self.report_progress(5, "Обработка границ работ...")
        log_info("Fsm_1_3_0: Шаг 1 - Обработка границ")

        processed_boundaries = self.boundaries_processor.process_boundaries()
        if not processed_boundaries:
            raise ValueError("Не удалось обработать границы работ")

        boundaries_geometry = self.boundaries_processor.get_boundaries_geometry_for_api(processed_boundaries)

        # Шаг 2: Проверка кадастровых кварталов (20%)
        if self.is_cancelled():
            return {'results': results, 'temp_folder': self.temp_folder, 'success': False, 'cancelled': True}

        self.report_progress(15, "Проверка кадастровых кварталов...")
        log_info("Fsm_1_3_0: Шаг 2 - Проверка КК")
        self.vector_loader.load_single_layer('L_1_2_2_WFS_КК', boundaries_geometry)

        # Шаг 3: Проверка ОКС (35%)
        if self.is_cancelled():
            return {'results': results, 'temp_folder': self.temp_folder, 'success': False, 'cancelled': True}

        self.report_progress(30, "Проверка объектов капитального строительства...")
        log_info("Fsm_1_3_0: Шаг 3 - Проверка ОКС")
        self.vector_loader.load_capital_objects(boundaries_geometry)

        # Шаг 4: Проверка населенных пунктов (45%)
        if self.is_cancelled():
            return {'results': results, 'temp_folder': self.temp_folder, 'success': False, 'cancelled': True}

        self.report_progress(40, "Проверка населенных пунктов...")
        log_info("Fsm_1_3_0: Шаг 4 - Проверка НП")
        self.vector_loader.load_single_layer('Le_1_2_3_5_АТД_НП_poly', boundaries_geometry)

        # Шаг 5: Проверка лесных кварталов (55%)
        if self.is_cancelled():
            return {'results': results, 'temp_folder': self.temp_folder, 'success': False, 'cancelled': True}

        self.report_progress(50, "Проверка лесных кварталов...")
        log_info("Fsm_1_3_0: Шаг 5 - Проверка лесных кварталов")
        self.forest_loader.check_forest_quarters()

        # Шаг 6: Проверка лесоустроительных выделов (65%)
        if self.is_cancelled():
            return {'results': results, 'temp_folder': self.temp_folder, 'success': False, 'cancelled': True}

        self.report_progress(60, "Проверка лесоустроительных выделов...")
        log_info("Fsm_1_3_0: Шаг 6 - Проверка лесоустроительных выделов")
        self.forest_loader.check_forest_subdivisions()

        # Шаг 7: Пространственный анализ (80%)
        if self.is_cancelled():
            return {'results': results, 'temp_folder': self.temp_folder, 'success': False, 'cancelled': True}

        self.report_progress(75, "Выполнение пространственного анализа...")
        log_info("Fsm_1_3_0: Шаг 7 - Пространственный анализ")
        analysis_results = self.spatial_analyzer.analyze_intersections(processed_boundaries)
        results.update(analysis_results)

        # Шаг 8: Подсчёт пересечений линий (95%)
        if self.is_cancelled():
            return {'results': results, 'temp_folder': self.temp_folder, 'success': False, 'cancelled': True}

        self.report_progress(90, "Подсчёт пересечений линий АД и ЖД...")
        log_info("Fsm_1_3_0: Шаг 8 - Подсчёт пересечений")
        intersections = self.intersections_calculator.calculate_intersections(processed_boundaries)
        results.update(intersections)

        self.report_progress(100, "Расчёт завершён")
        log_info(f"Fsm_1_3_0: Расчёт бюджета завершён. Результаты: {results}")

        return {
            'results': results,
            'temp_folder': self.temp_folder,
            'success': True,
            'cancelled': False
        }

    def _init_submodules(self):
        """Инициализация субмодулей (lazy import внутри execute)"""
        from .Fsm_1_3_1_boundaries_processor import BoundariesProcessor
        from .Fsm_1_3_2_vector_loader import VectorLoader
        from .Fsm_1_3_3_forest_loader import ForestLoader
        from .Fsm_1_3_4_spatial_analyzer import SpatialAnalyzer
        from .Fsm_1_3_7_intersections_calculator import IntersectionsCalculator

        self.boundaries_processor = BoundariesProcessor(self.iface, self.project_manager, self.layer_manager)
        self.vector_loader = VectorLoader(self.iface, self.project_manager, self.layer_manager)
        self.forest_loader = ForestLoader(self.iface, self.project_manager, self.layer_manager)
        self.spatial_analyzer = SpatialAnalyzer(self.iface)
        self.intersections_calculator = IntersectionsCalculator(self.iface)
