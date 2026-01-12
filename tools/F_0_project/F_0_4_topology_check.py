# -*- coding: utf-8 -*-
"""
F_0_4 - Проверка топологии (Stage 1: Обнаружение ошибок)

Модульный инструмент комплексной проверки топологии и геометрии.
Использует native QGIS алгоритмы (без GRASS).

Рефакторен для работы в 2 стадии:
  Stage 1 (этот модуль): Обнаружение и визуализация ошибок
  Stage 2 (Fsm_0_4_6_fixer): Исправление ошибок

Поддерживает все типы геометрий:
  - Полигоны: валидность, самопересечения, дубли, наложения, spike, точность
  - Линии: самопересечения, наложения, висячие концы (dangles)
  - Точки: дубликаты, близость (proximity)

Создает единый слой ошибок для каждого проверяемого слоя,
содержащий точки всех типов ошибок для четкого понимания их расположения.

Версия: 4.0 (Multi-geometry support, асинхронная обработка через QgsTask)
"""

from typing import List, Dict, Optional

from qgis.core import (
    Qgis, QgsProject, QgsVectorLayer,
    QgsWkbTypes, QgsProcessingContext
)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QMessageBox, QPushButton, QApplication, QProgressBar

from Daman_QGIS.core.base_tool import BaseTool
from Daman_QGIS.managers import LayerReplacementManager, LayerManager, get_async_manager
from Daman_QGIS.database.project_db import ProjectDB
from .submodules.Fsm_0_4_5_coordinator import Fsm_0_4_5_TopologyCoordinator
from .submodules.Fsm_0_4_6_fixer import Fsm_0_4_6_TopologyFixer
from .submodules.Fsm_0_4_7_dialog import Fsm_0_4_7_TopologyCheckDialog
from .submodules.Fsm_0_4_10_async_task import Fsm_0_4_10_TopologyCheckTask
from Daman_QGIS.constants import PLUGIN_NAME
from Daman_QGIS.managers.M_19_project_structure_manager import get_project_structure_manager
from Daman_QGIS.utils import log_info, log_warning, log_error, log_success
import os


class F_0_4_TopologyCheck(BaseTool):
    """
    Модульный оркестратор проверки топологии (Stage 1)

    Архитектура:
    - Использует координатор (Fsm_0_4_5) с checker модулями:
      Полигоны:
      * Fsm_0_4_1: Проверка валидности и самопересечений
      * Fsm_0_4_2: Проверка дублей геометрий и вершин
      * Fsm_0_4_3: Проверка наложений и острых углов
      * Fsm_0_4_4: Проверка точности координат
      Линии:
      * Fsm_0_4_8: Самопересечения, наложения, висячие концы
      Точки:
      * Fsm_0_4_9: Дубликаты, близость
      Cross-layer:
      * Fsm_0_4_11: Наложения между слоями
    - Создает единый слой ошибок для каждого исходного слоя
    - Слой ошибок содержит точки всех типов ошибок с атрибутами
    - Не изменяет исходные данные
    - Сохраняет контекст для Stage 2 (Fsm_0_4_6_fixer)
    - Поддерживает все типы геометрий (полигоны, линии, точки)
    """

    def __init__(self, iface):
        super().__init__(iface)

        # Инициализируем менеджер замены слоев
        self.replacement_manager = LayerReplacementManager()

        # Инициализируем координатор (native QGIS версия)
        self.coordinator = Fsm_0_4_5_TopologyCoordinator()

        # Инициализируем fixer для Stage 2
        self.fixer = Fsm_0_4_6_TopologyFixer()

        # Менеджеры для сохранения в GPKG и стилизации
        # plugin_dir - 2 уровня вверх от tools/F_0_project/
        plugin_dir = os.path.dirname(os.path.dirname(__file__))
        self.layer_manager = LayerManager(iface, plugin_dir)
        self.project_db = None  # Инициализируется при проверке проекта

        # Диалог
        self.dialog = None

        # Данные проверки
        self.check_cancelled = False
        self.check_context = []  # Контекст для Stage 2
        self.last_check_results = None  # Результаты последней проверки

        # QgsMessageBar прогресс
        self.progress_bar = None
        self.progress_message_bar_item = None

        # Async task manager (M_17)
        self.async_manager = None
        self.async_pending_layers = []  # Слои ожидающие обработки в async режиме
        self.async_results = {}  # Результаты async проверок по layer_id
        self._layer_id_map = {}  # Маппинг task description -> layer_id для sequential mode

    def get_name(self):
        """Возвращает название инструмента для меню"""
        return "F_0_4_Проверка топологии"

    def run(self):
        """Главный метод - показ диалога с двумя этапами"""
        # Создаем и показываем диалог
        self.dialog = Fsm_0_4_7_TopologyCheckDialog(self.iface.mainWindow())

        # Подключаем сигналы (check_requested всегда async через M_17)
        self.dialog.check_requested.connect(self._run_stage1)
        self.dialog.fix_requested.connect(self._run_stage2)

        # Показываем диалог
        self.dialog.show()

    def _run_stage1(self):
        """
        Stage 1: Обнаружение ошибок

        Всегда использует асинхронную обработку через M_17 AsyncTaskManager.
        """
        # Проверка что dialog инициализирован (создается в run())
        if self.dialog is None:
            raise RuntimeError("F_0_4: Диалог не инициализирован. Вызовите run() перед _run_stage1()")

        # Сбрасываем флаг отмены и контекст
        self.check_cancelled = False
        self.check_context = []

        log_info("F_0_4: Stage 1 - Обнаружение ошибок (async via M_17)")

        try:
            # Очищаем старые слои ошибок
            self._cleanup_old_error_layers()

            # Получаем векторные слои
            layers = self._get_vector_layers()
            if not layers:
                self.dialog.on_error("В проекте нет векторных слоев для проверки")
                return

            log_info(f"F_0_4: Найдено слоев для проверки: {len(layers)}")

            # Всегда async через M_17
            self._run_stage1_async(layers)

        except Exception as e:
            log_error(f"F_0_4: Ошибка при проверке: {str(e)}")
            self.dialog.on_error(f"Ошибка при проверке: {str(e)}")

    def _run_stage1_async(self, layers: List[QgsVectorLayer]):
        """
        Асинхронная проверка через QgsTask (не блокирует UI)

        Использует M_17 AsyncTaskManager для ПОСЛЕДОВАТЕЛЬНОЙ фоновой обработки.

        ВАЖНО: Задачи запускаются ПОСЛЕДОВАТЕЛЬНО (одна за другой), так как
        processing.run() не является thread-safe. Параллельный запуск вызывает
        access violation crash.

        ВАЖНО: QgsProcessingContext создаётся здесь (в main thread) и передаётся
        в каждый task, так как processing.run() внутри себя обращается к
        iface.mapCanvas() что вызывает access violation из background thread.

        Args:
            layers: Список слоёв для проверки
        """
        # Инициализируем async manager (M_17)
        if self.async_manager is None:
            self.async_manager = get_async_manager(self.iface)

        # Отменяем предыдущие задачи если есть
        self.async_manager.cancel_all()
        self.async_manager.clear_sequential_queue()

        # Сбрасываем результаты
        self.async_results = {}
        self.async_pending_layers = [layer.id() for layer in layers]

        # КРИТИЧЕСКИ ВАЖНО: Создаём QgsProcessingContext в main thread!
        # processing.run() обращается к iface.mapCanvas() для создания контекста,
        # что вызывает access violation при вызове из background thread.
        # Создаём один контекст и передаём его во все tasks.
        processing_context = QgsProcessingContext()
        processing_context.setProject(QgsProject.instance())

        log_info(f"F_0_4: Запуск ПОСЛЕДОВАТЕЛЬНОЙ асинхронной проверки для {len(layers)} слоёв")

        # Создаём список задач
        tasks = []
        layer_id_map = {}  # Маппинг task description -> layer_id

        for layer in layers:
            # Создаём task для этого слоя (передаём layer_id, НЕ layer!)
            # Также передаём processing_context созданный в main thread
            task = Fsm_0_4_10_TopologyCheckTask(
                layer_id=layer.id(),
                layer_name=layer.name(),
                processing_context=processing_context
            )
            tasks.append(task)
            # Сохраняем маппинг для callbacks
            layer_id_map[f"Проверка топологии: {layer.name()}"] = layer.id()

        # Сохраняем маппинг для использования в callbacks
        self._layer_id_map = layer_id_map

        # Запускаем ПОСЛЕДОВАТЕЛЬНО через run_sequential()
        # Это предотвращает access violation от параллельных processing.run()
        self.async_manager.run_sequential(
            tasks,
            show_progress=True,
            silent_completion=True,
            on_each_completed=self._on_sequential_layer_completed,
            on_each_failed=self._on_sequential_layer_failed,
            on_each_cancelled=self._on_sequential_layer_cancelled,
            on_all_completed=self._check_async_completion
        )

    def _on_sequential_layer_completed(self, task_desc: str, result: dict):
        """
        Callback при завершении проверки слоя (sequential mode).

        Args:
            task_desc: Описание задачи (содержит имя слоя)
            result: Результат проверки
        """
        # Получаем layer_id из маппинга
        layer_id = self._layer_id_map.get(task_desc)
        if layer_id:
            self._on_async_layer_completed(layer_id, result)

    def _on_sequential_layer_failed(self, task_desc: str, error: str):
        """
        Callback при ошибке проверки слоя (sequential mode).

        Args:
            task_desc: Описание задачи
            error: Сообщение об ошибке
        """
        layer_id = self._layer_id_map.get(task_desc)
        if layer_id:
            self._on_async_layer_failed(layer_id, error)

    def _on_sequential_layer_cancelled(self, task_desc: str):
        """
        Callback при отмене проверки слоя (sequential mode).

        Args:
            task_desc: Описание задачи
        """
        layer_id = self._layer_id_map.get(task_desc)
        if layer_id:
            self._on_async_layer_cancelled(layer_id)

    def _on_async_layer_cancelled(self, layer_id: str):
        """
        Callback при отмене проверки слоя

        Args:
            layer_id: ID слоя
        """
        log_info(f"F_0_4: Проверка слоя {layer_id} отменена")

        # Сохраняем как отменённую
        self.async_results[layer_id] = {'cancelled': True, 'error_count': 0}

        # НЕ вызываем _check_async_completion() здесь!
        # При sequential mode он вызывается через on_all_completed callback

    def _on_async_layer_completed(self, layer_id: str, result: dict):
        """
        Callback при завершении проверки одного слоя

        Args:
            layer_id: ID слоя
            result: Результат проверки от координатора
        """
        log_info(f"F_0_4: Async проверка слоя завершена, ошибок: {result.get('error_count', 0)}")

        # Сохраняем результат
        self.async_results[layer_id] = result

        # Обрабатываем error layer если есть ошибки
        if result['error_count'] > 0 and result.get('error_layer'):
            error_layer = result['error_layer']

            # Применяем стиль в main thread (безопасно для GUI)
            # Стиль не был применён в background thread
            if error_layer.customProperty("NeedsStyle") == "true":
                self._apply_error_style_safe(error_layer)
                error_layer.removeCustomProperty("NeedsStyle")

            # Добавляем слой ошибок в проект
            error_layer = self.replacement_manager.replace_or_add_layer(
                error_layer,
                error_layer.name(),
                preserve_order=True
            )
            self.replacement_manager.move_layer_to_top(error_layer)

        # НЕ вызываем _check_async_completion() здесь!
        # При sequential mode он вызывается через on_all_completed callback

    def _on_async_layer_failed(self, layer_id: str, error: str):
        """
        Callback при ошибке проверки слоя

        Args:
            layer_id: ID слоя
            error: Сообщение об ошибке
        """
        log_warning(f"F_0_4: Async проверка слоя {layer_id} завершилась ошибкой: {error}")

        # Сохраняем как ошибку
        self.async_results[layer_id] = {'error': error, 'error_count': 0}

        # НЕ вызываем _check_async_completion() здесь!
        # При sequential mode он вызывается через on_all_completed callback

    def _check_async_completion(self):
        """
        Обработка завершения всех async задач.

        При sequential mode вызывается через on_all_completed callback
        когда ВСЕ задачи завершены (успешно, с ошибкой или отменены).
        """
        log_info("F_0_4: Все async задачи завершены")

        # Собираем результаты
        total_errors = 0
        errors_by_layer = {}
        fixable_errors = 0

        for layer_id, result in self.async_results.items():
            # Пропускаем слои с ошибками выполнения или отменённые
            if 'error' in result or result.get('cancelled'):
                continue

            layer = QgsProject.instance().mapLayer(layer_id)
            if not layer:
                continue

            layer_name = layer.name()

            if result['error_count'] > 0:
                # Формируем информацию об ошибках для диалога
                layer_errors = []
                for error_type, error_list in result.get('errors_by_type', {}).items():
                    if error_list and isinstance(error_list, list):
                        error_info = {
                            'error_type': error_type,
                            'error_count': len(error_list),
                            'can_auto_fix': error_type in self.coordinator.FIXABLE_ERROR_TYPES
                        }
                        layer_errors.append(error_info)
                        self.check_context.append(error_info)

                        total_errors += len(error_list)
                        if error_info['can_auto_fix']:
                            fixable_errors += len(error_list)

                if layer_errors:
                    errors_by_layer[layer_name] = layer_errors

        # Сохраняем результаты
        self.last_check_results = errors_by_layer

        # Показываем одно общее сообщение о завершении в MessageBar
        self._show_completion_message(total_errors, len(self.async_pending_layers))

        # Отправляем результаты в диалог
        if self.dialog:
            self.dialog.on_check_completed(errors_by_layer, total_errors, fixable_errors)

        log_info(f"F_0_4: Async проверка завершена. Всего: {total_errors}, исправляемых: {fixable_errors}")

    def _run_stage2(self):
        """Stage 2: Исправление ошибок"""
        # Проверка что dialog инициализирован (создается в run())
        if self.dialog is None:
            raise RuntimeError("F_0_4: Диалог не инициализирован. Вызовите run() перед _run_stage2()")

        log_info("F_0_4: Stage 2 - Исправление ошибок")

        try:
            if not self.last_check_results:
                self.dialog.on_error("Сначала выполните проверку (Stage 1)")
                return

            # Создаём прогресс-бар в QgsMessageBar
            self._create_progress_bar("Исправление ошибок...")

            total_fixes = 0
            fixes_by_type = {}

            total_layers = len(self.last_check_results)
            layer_idx = 0

            # Исправляем ошибки для каждого слоя
            for layer_name, layer_errors in self.last_check_results.items():
                layer_idx += 1

                # Обновляем прогресс
                progress = int((layer_idx / total_layers) * 100)
                self._update_progress(progress)

                QApplication.processEvents()

                # Находим исходный слой
                layer = self._find_layer_by_name(layer_name)
                if not layer:
                    log_warning(f"F_0_4: Слой '{layer_name}' не найден, пропускаем")
                    continue

                # Проверяем что слой валиден (не был удалён)
                try:
                    if not layer.isValid():
                        log_warning(f"F_0_4: Слой '{layer_name}' невалиден, пропускаем")
                        continue
                except RuntimeError:
                    log_warning(f"F_0_4: Слой '{layer_name}' был удалён, пропускаем")
                    continue

                # Собираем errors_by_type для этого слоя
                errors_by_type = {}
                for error_info in layer_errors:
                    if error_info.get('can_auto_fix', False):
                        error_type = error_info['error_type']
                        # Для Fixer нужны сами ошибки, но мы их не сохранили
                        # Поэтому передаём пустой список (Fixer использует алгоритмы)
                        errors_by_type[error_type] = []

                if not errors_by_type:
                    continue

                # Обработка слоя в отдельном try/except
                try:
                    # Исправляем (получаем memory: слой)
                    result = self.fixer.fix_errors(layer, errors_by_type)
                    fixed_layer = result['fixed_layer']

                    # Сохраняем статистику ДО операций с GPKG (слой может быть удалён)
                    layer_fixes = result['fixes_applied']
                    layer_fixes_by_type = result['fixes_by_type'].copy()

                    # ВАЖНО: Сохраняем memory: слой в GPKG для постоянного хранения
                    if not self.project_db:
                        # Инициализируем ProjectDB при первом использовании
                        project_path = QgsProject.instance().absolutePath()
                        structure_manager = get_project_structure_manager()
                        structure_manager.project_root = project_path
                        gpkg_path = structure_manager.get_gpkg_path(create=False)
                        if gpkg_path:
                            self.project_db = ProjectDB(gpkg_path)

                    # Сохраняем исправленный слой в GPKG
                    if self.project_db is None:
                        log_warning(f"F_0_4: ProjectDB не инициализирован, слой '{layer_name}' не сохранён")
                        continue

                    self.project_db.add_layer(fixed_layer, layer_name)
                    log_info(f"F_0_4: Слой '{layer_name}' сохранён в GPKG")

                    # Загружаем слой из GPKG (теперь он постоянный, не memory:)
                    gpkg_layer = self.project_db.get_layer(layer_name)

                    if gpkg_layer:
                        # Применяем стиль через StyleManager
                        self.layer_manager.style_manager.apply_qgis_style(gpkg_layer, layer_name)
                        log_info(f"F_0_4: Стиль применён к слою '{layer_name}'")

                        # Заменяем слой постоянной версией из GPKG
                        self.replacement_manager.replace_or_add_layer(
                            gpkg_layer,
                            layer_name,
                            preserve_order=True
                        )
                    else:
                        log_warning(f"F_0_4: Не удалось загрузить слой '{layer_name}' из GPKG")
                        # Fallback: используем memory: слой
                        self.replacement_manager.replace_or_add_layer(
                            fixed_layer,
                            layer_name,
                            preserve_order=True
                        )

                    # Собираем статистику (используем сохранённые значения)
                    total_fixes += layer_fixes
                    for fix_type, count in layer_fixes_by_type.items():
                        fixes_by_type[fix_type] = fixes_by_type.get(fix_type, 0) + count

                except RuntimeError as e:
                    log_error(f"F_0_4: Слой '{layer_name}' был удалён во время обработки: {str(e)}")
                    continue
                except Exception as e:
                    log_error(f"F_0_4: Ошибка обработки слоя '{layer_name}': {str(e)}")
                    continue

            # Завершаем прогресс
            self._update_progress(100)

            # Удаляем прогресс-бар
            self._clear_progress_bar()

            # Обновляем слои ошибок (запускаем проверку заново автоматически)
            # Нет, лучше просто сообщить пользователю

            # Отправляем результаты в диалог
            self.dialog.on_fix_completed(total_fixes, fixes_by_type)

            log_info(f"F_0_4: Исправление завершено. Применено: {total_fixes}")

        except Exception as e:
            log_error(f"F_0_4: Ошибка при исправлении: {str(e)}")
            self._clear_progress_bar()
            self.dialog.on_error(f"Ошибка при исправлении: {str(e)}")

    def _check_layer(self, layer: QgsVectorLayer) -> List[Dict]:
        """
        Проверяет один слой через координатор (поддержка всех типов геометрий)

        Returns:
            Список найденных ошибок с метаданными
        """
        errors = []
        geom_type = layer.geometryType()

        # Проверяем поддерживаемые типы геометрий
        supported_types = [
            QgsWkbTypes.PolygonGeometry,
            QgsWkbTypes.LineGeometry,
            QgsWkbTypes.PointGeometry
        ]

        if geom_type not in supported_types:
            log_info(
                f"F_0_4: Слой '{layer.name()}' имеет неподдерживаемый тип геометрии, пропускаем"
            )
            return errors

        # Проверяем что слой не пустой
        if layer.featureCount() == 0:
            log_info(
                f"F_0_4: Слой '{layer.name()}' пустой, пропускаем"
            )
            return errors

        # Определяем тип геометрии для логирования
        geom_type_name = {
            QgsWkbTypes.PolygonGeometry: 'полигоны',
            QgsWkbTypes.LineGeometry: 'линии',
            QgsWkbTypes.PointGeometry: 'точки'
        }.get(geom_type, 'unknown')

        log_info(f"F_0_4: Проверка слоя '{layer.name()}' ({geom_type_name})")

        try:
            # Запускаем проверку через координатор
            result = self.coordinator.check_layer(layer)
        except Exception as e:
            log_warning(f"F_0_4: Ошибка при проверке слоя '{layer.name()}': {str(e)}")
            return errors

        if result['error_count'] > 0:
            error_layer = result['error_layer']

            # Заменяем существующий error layer с сохранением позиции
            # ВАЖНО: replace_or_add_layer добавляет temporary layer в проект
            # (QgsProject берет ownership), поэтому утечки памяти не происходит
            error_layer = self.replacement_manager.replace_or_add_layer(
                error_layer,
                error_layer.name(),
                preserve_order=True
            )

            # ВАЖНО: Слои ошибок должны быть всегда сверху для видимости
            # Перемещаем в топ дерева слоёв (позиция 0)
            self.replacement_manager.move_layer_to_top(error_layer)

            # Сохраняем информацию для каждого типа ошибок
            for error_type, error_list in result['errors_by_type'].items():
                # Проверяем что error_list это список, а не bool (может быть False при ошибке)
                if error_list and isinstance(error_list, list):
                    error_info = {
                        'error_type': error_type,
                        'error_count': len(error_list),
                        'error_layer_id': error_layer.id(),
                        'error_layer_name': error_layer.name(),
                        'source_layer_id': layer.id(),
                        'source_layer_name': layer.name(),
                        'can_auto_fix': error_type in self.coordinator.FIXABLE_ERROR_TYPES,
                        'fix_params': {}
                    }

                    errors.append(error_info)
                    self.check_context.append(error_info)

                    log_warning(
                        f"F_0_4: [{error_type}] Найдено ошибок: {len(error_list)}"
                    )

        return errors

    def _cleanup_old_error_layers(self):
        """
        Удаляет все слои ошибок из предыдущих проверок.
        Вызывается перед каждым запуском проверки для обеспечения актуальности данных.
        """
        removed_count = 0
        layers_to_remove = []

        # Префикс слоев ошибок из координатора
        error_prefix = f"{self.coordinator.PREFIX_ERRORS}_"

        # Собираем все слои ошибок
        for layer in QgsProject.instance().mapLayers().values():
            if isinstance(layer, QgsVectorLayer) and layer.name().startswith(error_prefix):
                layers_to_remove.append(layer)

        # Удаляем их
        for layer in layers_to_remove:
            QgsProject.instance().removeMapLayer(layer.id())
            removed_count += 1

        if removed_count > 0:
            log_info(
                f"F_0_4: Удалено {removed_count} старых слоев ошибок"
            )

    def _get_vector_layers(self) -> List[QgsVectorLayer]:
        """
        Возвращает слои для проверки топологии на основе Base_layers.json.

        Фильтрация по полю topology_check:
        - 1: проверять топологию
        - 0 или отсутствует: не проверять

        Returns:
            List[QgsVectorLayer]: Слои с topology_check=1
        """
        from Daman_QGIS.managers import get_reference_managers

        layers = []
        ref_manager = get_reference_managers()

        # Получаем данные из Base_layers.json
        layers_data = ref_manager.layer.get_base_layers()

        # Создаём set слоёв которые нужно проверять
        layers_to_check = set()
        for layer_data in layers_data:
            topology_check = layer_data.get('topology_check', 0)
            if topology_check == 1:
                full_name = layer_data.get('full_name')
                if full_name:
                    layers_to_check.add(full_name)

        log_info(f"F_0_4: Слоёв с topology_check=1: {len(layers_to_check)}")

        # DEBUG: Логируем слои этапности из списка для проверки
        staging_layers_in_check = [l for l in layers_to_check if 'Le_3_7' in l]
        if staging_layers_in_check:
            log_info(f"F_0_4: Слои этапности в списке для проверки: {staging_layers_in_check[:5]}...")

        # Фильтруем слои проекта
        project_layer_names = []
        for layer in QgsProject.instance().mapLayers().values():
            if isinstance(layer, QgsVectorLayer) and layer.isValid():
                layer_name = layer.name()
                project_layer_names.append(layer_name)
                if layer_name in layers_to_check:
                    layers.append(layer)
                    log_info(f"F_0_4: Добавлен для проверки: {layer_name}")

        # DEBUG: Логируем слои этапности в проекте
        staging_in_project = [l for l in project_layer_names if 'Le_3_7' in l]
        if staging_in_project:
            log_info(f"F_0_4: Слои этапности в проекте: {staging_in_project}")
        else:
            log_info(f"F_0_4: Слоёв этапности (Le_3_7) в проекте не найдено")

        return layers
    def _find_layer_by_name(self, layer_name: str) -> Optional[QgsVectorLayer]:
        """
        Находит слой по имени

        Args:
            layer_name: Имя слоя

        Returns:
            QgsVectorLayer или None
        """
        for layer_id, layer in QgsProject.instance().mapLayers().items():
            if isinstance(layer, QgsVectorLayer) and layer.name() == layer_name:
                return layer
        return None

    def _create_progress_bar(self, message: str):
        """
        Создаёт прогресс-бар в QgsMessageBar (область уведомлений QGIS)

        Args:
            message: Начальное сообщение

        Notes:
            QgsMessageBar отображается над обзорным окном и не блокирует интерфейс
        """
        # Удаляем предыдущий прогресс-бар если есть
        self._clear_progress_bar()

        # Создаём виджет прогресс-бара
        self.progress_bar = QProgressBar()
        self.progress_bar.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)

        # Добавляем в message bar QGIS
        self.progress_message_bar_item = self.iface.messageBar().createMessage(
            "Проверка топологии",
            message
        )
        self.progress_message_bar_item.layout().addWidget(self.progress_bar)
        self.iface.messageBar().pushWidget(
            self.progress_message_bar_item,
            Qgis.Info
        )

        log_info(f"F_0_4: Прогресс-бар создан: {message}")

    def _update_progress(self, value: int):
        """
        Обновляет значение прогресс-бара БЕЗ изменения текста

        ВАЖНО: Текст сообщения статичен ("Проверка топологии..." или "Исправление ошибок..."),
        обновляется только прогресс 0-100%. Это решение основано на официальной документации
        QGIS PyQGIS и предотвращает reparenting виджетов между layouts.

        Args:
            value: Значение прогресса (0-100)
        """
        if self.progress_bar:
            self.progress_bar.setValue(value)

    def _clear_progress_bar(self):
        """
        Удаляет прогресс-бар из QgsMessageBar

        ВАЖНО: Использует popWidget() вместо clearWidgets() чтобы удалить только
        наш виджет, не затрагивая сообщения других плагинов или QGIS.
        """
        if self.progress_message_bar_item:
            self.iface.messageBar().popWidget(self.progress_message_bar_item)
            self.progress_message_bar_item = None
            self.progress_bar = None
            log_info("F_0_4: Прогресс-бар удалён")

    def _apply_error_style_safe(self, layer: QgsVectorLayer):
        """
        Применение стиля к слою ошибок (красные точки).

        ВАЖНО: Этот метод ДОЛЖЕН вызываться только из main thread!
        Вызывается из callback после завершения async задачи.

        Args:
            layer: Слой ошибок для стилизации
        """
        from qgis.PyQt.QtGui import QColor
        from Daman_QGIS.managers import StyleManager

        try:
            style_manager = StyleManager()
            style_manager.create_simple_marker_style(
                layer,
                QColor(255, 0, 0, 200),  # Красный цвет с прозрачностью
                4.0  # Размер 4 мм
            )
            log_info(f"F_0_4: Стиль применён к слою '{layer.name()}'")
        except Exception as e:
            log_warning(f"F_0_4: Не удалось применить стиль к '{layer.name()}': {e}")

    def _show_completion_message(self, total_errors: int, layers_checked: int):
        """
        Показывает одно общее сообщение о завершении проверки в MessageBar.

        Args:
            total_errors: Общее количество найденных ошибок
            layers_checked: Количество проверенных слоёв
        """
        if total_errors == 0:
            message = f"Проверка топологии: {layers_checked} слоёв проверено, ошибок не найдено"
            level = Qgis.Success
        else:
            message = f"Проверка топологии: {layers_checked} слоёв проверено, найдено {total_errors} ошибок"
            level = Qgis.Warning

        self.iface.messageBar().pushMessage("", message, level, duration=5)