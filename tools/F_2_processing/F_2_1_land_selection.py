# -*- coding: utf-8 -*-
"""
Инструмент 2_1_Выборка ЗУ
Создание выборки земельных участков и ОКС, пересекающих границы работ
"""

import os
from typing import Optional, TYPE_CHECKING

from qgis.PyQt.QtWidgets import QMessageBox
from qgis.core import QgsProject, Qgis, QgsVectorLayer

from Daman_QGIS.core.base_tool import BaseTool

if TYPE_CHECKING:
    from Daman_QGIS.core.layer_manager import LayerManager

from Daman_QGIS.constants import (
    PLUGIN_NAME, MESSAGE_SUCCESS_DURATION, MESSAGE_INFO_DURATION,
    LAYER_BOUNDARIES_EXACT, LAYER_BOUNDARIES_10M, LAYER_BOUNDARIES_MINUS2CM,
    LAYER_WFS_ZU, LAYER_WFS_KK, LAYER_WFS_OKS, LAYER_WFS_NP, LAYER_MANUAL_ZU,
    LAYER_SELECTION_ZU, LAYER_SELECTION_ZU_10M, LAYER_SELECTION_OKS, LAYER_SELECTION_KK,
    LAYER_SELECTION_NP, LAYER_SELECTION_TERZONY, LAYER_SELECTION_VODA
)
from Daman_QGIS.utils import log_info, log_warning, log_error, log_success
from Daman_QGIS.managers import FeatureSortManager, OksZuAnalysisManager

# Импорт субмодулей
from .submodules.Fsm_2_1_8_selection_engine import Fsm_2_1_8_SelectionEngine


def pluralize_plots(count: int) -> str:
    """Склонение слова 'участок' в зависимости от количества

    Args:
        count: Количество участков

    Returns:
        str: Правильная форма слова (участок/участка/участков)
    """
    if count % 10 == 1 and count % 100 != 11:
        return "участок"
    elif count % 10 in [2, 3, 4] and count % 100 not in [12, 13, 14]:
        return "участка"
    else:
        return "участков"


class F_2_1_LandSelection(BaseTool):
    """Инструмент выборки земельных участков и ОКС (координатор)"""

    def __init__(self, iface) -> None:
        """Инициализация инструмента"""
        super().__init__(iface)
        self.layer_manager: Optional['LayerManager'] = None
        self.plugin_dir: Optional[str] = None

        # Инициализируем движок выборки (будет настроен после set_project_manager)
        self.selection_engine = None

        # Инициализируем менеджер сортировки по "КН"
        self.feature_sort_manager = FeatureSortManager()

    def set_plugin_dir(self, plugin_dir: str) -> None:
        """Установка пути к папке плагина"""
        self.plugin_dir = plugin_dir

    def set_layer_manager(self, layer_manager: 'LayerManager') -> None:
        """Установка менеджера слоев"""
        self.layer_manager = layer_manager

    def set_project_manager(self, project_manager) -> None:
        """Установка менеджера проектов"""
        self.project_manager = project_manager

    def _get_gpkg_path(self) -> Optional[str]:
        """Получить путь к GeoPackage проекта через M_19"""
        if not self.project_manager or not self.project_manager.current_project:
            return None
        from Daman_QGIS.managers.M_19_project_structure_manager import get_project_structure_manager
        structure_manager = get_project_structure_manager()
        structure_manager.project_root = self.project_manager.current_project
        return structure_manager.get_gpkg_path(create=False)

    def get_name(self) -> str:
        """Получить имя инструмента"""
        return "F_2_1_Выборка"

    def run(self) -> None:
        """Основной метод запуска инструмента"""
        # Автоматическая очистка слоев перед выполнением
        self.auto_cleanup_layers()

        # Выполняем выборку для всех доступных слоёв
        self._perform_selection_workflow_all()

    def _perform_selection_workflow_all(self) -> None:
        """Выполнение процесса выборки для всех доступных объектов (ЗУ и ОКС)"""
        log_info("F_2_1: Запуск универсальной выборки объектов")

        # Ленивая инициализация движка выборки
        if not self.selection_engine:
            if not self.plugin_dir:
                log_error("F_2_1: Не удалось инициализировать Selection engine - plugin_dir не установлен")
                return
            gpkg_path = self._get_gpkg_path()
            if gpkg_path and os.path.exists(gpkg_path):
                self.selection_engine = Fsm_2_1_8_SelectionEngine(
                    self.iface,
                    self.plugin_dir,
                    gpkg_path
                )
                log_info(f"F_2_1: Selection engine инициализирован: {gpkg_path}")
            else:
                log_error("F_2_1: Не удалось инициализировать Selection engine - проект не открыт")
                return

        # Проверяем наличие слоёв границ
        boundaries_layer_exact = self._get_layer_by_name(LAYER_BOUNDARIES_EXACT)
        boundaries_layer_10m = self._get_layer_by_name(LAYER_BOUNDARIES_10M)
        boundaries_layer_minus2cm = self._get_layer_by_name(LAYER_BOUNDARIES_MINUS2CM)

        # Список отсутствующих границ
        missing_boundaries = []
        if not boundaries_layer_exact:
            missing_boundaries.append(LAYER_BOUNDARIES_EXACT)
        if not boundaries_layer_10m:
            missing_boundaries.append(LAYER_BOUNDARIES_10M)
        if not boundaries_layer_minus2cm:
            missing_boundaries.append(LAYER_BOUNDARIES_MINUS2CM)

        if missing_boundaries:
            reply = QMessageBox.warning(
                self.iface.mainWindow(),
                "Отсутствуют слои границ",
                f"Не найдены слои границ:\n" + "\n".join(f"• {layer}" for layer in missing_boundaries) +
                "\n\nСначала выполните импорт границ через 'F_1_1_Импорт'.\n\nПродолжить со всеми доступными границами?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return

        # Определяем какие слои доступны для выборки
        available_source_layers = []

        # Проверяем ЗУ
        zu_wfs = self._get_layer_by_name(LAYER_WFS_ZU)
        zu_manual = self._get_layer_by_name(LAYER_MANUAL_ZU)

        if zu_wfs:
            available_source_layers.append(('ZU', LAYER_WFS_ZU, zu_wfs))
        if zu_manual:
            available_source_layers.append(('ZU', LAYER_MANUAL_ZU, zu_manual))

        # Проверяем КК (кадастровые кварталы)
        kk_wfs = self._get_layer_by_name(LAYER_WFS_KK)
        if kk_wfs:
            available_source_layers.append(('KK', LAYER_WFS_KK, kk_wfs))

        # Проверяем ОКС
        oks_wfs = self._get_layer_by_name(LAYER_WFS_OKS)
        if oks_wfs:
            available_source_layers.append(('OKS', LAYER_WFS_OKS, oks_wfs))

        # Проверяем НП (населённые пункты)
        np_wfs = self._get_layer_by_name(LAYER_WFS_NP)
        if np_wfs:
            available_source_layers.append(('NP', LAYER_WFS_NP, np_wfs))

        # TODO: Добавить WFS слои для ТерЗоны и Вода когда будет найден API
        # Проверяем ТерЗоны (заглушка - WFS API не найден)
        # terzony_wfs = self._get_layer_by_name(LAYER_WFS_TERZONY)
        # if terzony_wfs:
        #     available_source_layers.append(('TERZONY', LAYER_WFS_TERZONY, terzony_wfs))

        # Проверяем Вода (заглушка - WFS API не найден)
        # voda_wfs = self._get_layer_by_name(LAYER_WFS_VODA)
        # if voda_wfs:
        #     available_source_layers.append(('VODA', LAYER_WFS_VODA, voda_wfs))

        # Если нет исходных слоёв - показываем диалог
        if not available_source_layers:
            missing_sources = [LAYER_WFS_ZU, LAYER_WFS_KK, LAYER_MANUAL_ZU, LAYER_WFS_OKS, LAYER_WFS_NP]
            reply = QMessageBox.warning(
                self.iface.mainWindow(),
                "Отсутствуют исходные слои",
                f"Не найдены исходные слои для выборки:\n" +
                "\n".join(f"• {layer}" for layer in missing_sources) +
                "\n\nСначала загрузите данные через 'F_1_2_Загрузка Web карт' или 'F_1_3_Импорт'.",
                QMessageBox.Ok
            )
            return

        log_info(f"F_2_1: Найдено {len(available_source_layers)} исходных слоёв для выборки")

        # Выполняем выборку для каждого доступного слоя
        for obj_type, layer_name, source_layer in available_source_layers:

            if obj_type == 'ZU':
                # Выборка для ЗУ (требует все 3 слоя границ)
                if boundaries_layer_exact and boundaries_layer_10m and boundaries_layer_minus2cm:
                    self._perform_selection_workflow_zu(
                        layer_name, source_layer,
                        boundaries_layer_exact, boundaries_layer_10m, boundaries_layer_minus2cm
                    )
                else:
                    log_warning(f"F_2_1: Пропущена выборка ЗУ из {layer_name} - не все слои границ доступны")

            elif obj_type == 'KK':
                # Выборка для КК (кадастровые кварталы) - требует только точные границы
                if boundaries_layer_exact:
                    self._reload_boundaries_if_needed(boundaries_layer_exact)
                    self._perform_selection_workflow_generic(
                        layer_name, source_layer, boundaries_layer_exact,
                        LAYER_SELECTION_KK, "КК"
                    )
                else:
                    log_warning(f"F_2_1: Пропущена выборка КК из {layer_name} - слой точных границ недоступен")

            elif obj_type == 'OKS':
                # Выборка для ОКС (требует только точные границы)
                if boundaries_layer_exact:
                    # КРИТИЧНО: После сохранения слоя ЗУ в project.gpkg слой границ из того же GPKG
                    # становится недоступным для итерации (getFeatures() не работает).
                    # Решение: reload() слоя для обновления кэша GDAL
                    self._reload_boundaries_if_needed(boundaries_layer_exact)

                    self._perform_selection_workflow_oks(layer_name, source_layer, boundaries_layer_exact)
                else:
                    log_warning(f"F_2_1: Пропущена выборка ОКС из {layer_name} - слой точных границ недоступен")

            elif obj_type == 'NP':
                # Выборка для НП (населённые пункты) - требует только точные границы
                if boundaries_layer_exact:
                    self._reload_boundaries_if_needed(boundaries_layer_exact)
                    self._perform_selection_workflow_generic(
                        layer_name, source_layer, boundaries_layer_exact,
                        LAYER_SELECTION_NP, "НП"
                    )
                else:
                    log_warning(f"F_2_1: Пропущена выборка НП из {layer_name} - слой точных границ недоступен")

            elif obj_type == 'TERZONY':
                # TODO: Выборка для ТерЗоны - WFS API не найден
                if boundaries_layer_exact:
                    self._reload_boundaries_if_needed(boundaries_layer_exact)
                    self._perform_selection_workflow_generic(
                        layer_name, source_layer, boundaries_layer_exact,
                        LAYER_SELECTION_TERZONY, "ТерЗоны"
                    )
                else:
                    log_warning(f"F_2_1: Пропущена выборка ТерЗоны из {layer_name} - слой точных границ недоступен")

            elif obj_type == 'VODA':
                # TODO: Выборка для Вода - WFS API не найден
                if boundaries_layer_exact:
                    self._reload_boundaries_if_needed(boundaries_layer_exact)
                    self._perform_selection_workflow_generic(
                        layer_name, source_layer, boundaries_layer_exact,
                        LAYER_SELECTION_VODA, "Вода"
                    )
                else:
                    log_warning(f"F_2_1: Пропущена выборка Вода из {layer_name} - слой точных границ недоступен")

        log_info(f"F_2_1: Выборка завершена успешно. Обработано слоёв: {len(available_source_layers)}")

        # Автоматический анализ ОКС-ЗУ (M_23)
        # Заполняет поля ОКС_на_ЗУ_факт и ОКС_на_ЗУ_выписка (если выписки уже загружены)
        self._run_oks_zu_analysis()

    def _perform_selection_workflow_zu(self, source_layer_name: str, source_layer: QgsVectorLayer,
                                       boundaries_layer_exact: QgsVectorLayer,
                                       boundaries_layer_10m: QgsVectorLayer,
                                       boundaries_layer_minus2cm: QgsVectorLayer) -> None:
        """Выполнение процесса выборки для ЗУ

        Args:
            source_layer_name: Имя исходного слоя
            source_layer: Исходный слой
            boundaries_layer_exact: Слой точных границ
            boundaries_layer_10m: Слой границ с буфером 10м
            boundaries_layer_minus2cm: Слой границ с буфером -2см
        """
        # Проверяем существование слоев выборки и предупреждаем о замене
        existing_layers_to_check = [LAYER_SELECTION_ZU, LAYER_SELECTION_ZU_10M]
        existing_layers = []

        for layer_name in existing_layers_to_check:
            layer = self._get_layer_by_name(layer_name)
            if layer:
                existing_layers.append(layer)

        if existing_layers:
            reply = QMessageBox.warning(
                self.iface.mainWindow(),
                "Подтверждение замены",
                f"Следующие слои уже существуют и будут заменены:\n" +
                "\n".join(f"• {layer.name()}" for layer in existing_layers) +
                "\n\nПродолжить?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                log_info(f"F_2_1: Пропущена выборка ЗУ из {source_layer_name}")
                return

            # Удаляем существующие слои
            for layer in existing_layers:
                QgsProject.instance().removeMapLayer(layer.id())
                log_info(f"F_2_1: Удален существующий слой {layer.name()}")

        # Проверяем что движок выборки инициализирован
        if not self.selection_engine:
            log_error("F_2_1: Selection engine не инициализирован")
            return

        # Выполняем выборку через движок
        log_info(f"F_2_1: Запуск выборки ЗУ из {source_layer_name}")
        final_layer_1, final_layer_2 = self.selection_engine.perform_selection_zu(
            boundaries_layer_exact, boundaries_layer_10m, boundaries_layer_minus2cm,
            source_layer, object_type='ZU'
        )

        # Сортируем слои по полю "КН" (если поле присутствует)
        # ВАЖНО: Сортировка ПЕРЕД добавлением в проект для корректной последовательности FID
        # КРИТИЧНО: M_15 возвращает memory layer - нужно пересохранить в GeoPackage
        if final_layer_1:
            sorted_layer_1 = self.feature_sort_manager.sort_layer(final_layer_1)
            # Если слой был отсортирован (новый memory layer), пересохраняем в GeoPackage
            if sorted_layer_1 != final_layer_1:
                from .submodules.Fsm_2_1_6_layer_builder import Fsm_2_1_6_LayerBuilder
                assert self.plugin_dir is not None  # Type narrowing для Pylance
                gpkg_path = self._get_gpkg_path()
                if gpkg_path:
                    builder = Fsm_2_1_6_LayerBuilder(self.plugin_dir)
                    final_layer_1 = builder.save_layer_to_gpkg(sorted_layer_1, LAYER_SELECTION_ZU, gpkg_path)
            else:
                final_layer_1 = sorted_layer_1

        if final_layer_2:
            sorted_layer_2 = self.feature_sort_manager.sort_layer(final_layer_2)
            # Если слой был отсортирован (новый memory layer), пересохраняем в GeoPackage
            if sorted_layer_2 != final_layer_2:
                from .submodules.Fsm_2_1_6_layer_builder import Fsm_2_1_6_LayerBuilder
                assert self.plugin_dir is not None  # Type narrowing для Pylance
                gpkg_path = self._get_gpkg_path()
                if gpkg_path:
                    builder = Fsm_2_1_6_LayerBuilder(self.plugin_dir)
                    final_layer_2 = builder.save_layer_to_gpkg(sorted_layer_2, LAYER_SELECTION_ZU_10M, gpkg_path)
            else:
                final_layer_2 = sorted_layer_2

        # Добавляем только непустые слои
        layers_to_add = []
        if final_layer_1:
            layers_to_add.append(final_layer_1)
        if final_layer_2:
            layers_to_add.append(final_layer_2)

        if not layers_to_add:
            log_info("F_2_1: Нет слоёв для добавления (все слои пусты)")
        elif self.layer_manager:
            for layer in layers_to_add:
                self.layer_manager.add_layer(layer, make_readonly=False, auto_number=False, check_precision=False)
            log_info(f"F_2_1: Добавлено слоёв: {len(layers_to_add)}")

            # Сортируем все слои
            log_info("F_2_1: Сортировка всех слоёв по order_layers из Base_layers.json")
            self.layer_manager.sort_all_layers()
            log_info("F_2_1: Слои отсортированы по order_layers")

        # Показываем результат
        count_1 = final_layer_1.featureCount() if final_layer_1 else 0
        count_2 = final_layer_2.featureCount() if final_layer_2 else 0

        log_info(f"F_2_1: ИТОГОВЫЕ РЕЗУЛЬТАТЫ ВЫБОРКИ ЗУ из {source_layer_name}:")
        log_info(f"F_2_1:   {LAYER_SELECTION_ZU}: {count_1} {pluralize_plots(count_1)}")
        log_info(f"F_2_1:   {LAYER_SELECTION_ZU_10M}: {count_2} {pluralize_plots(count_2)}")

        self.iface.messageBar().pushMessage(
            PLUGIN_NAME,
            f"Выборка ЗУ из {source_layer_name} завершена:\n"
            f"{LAYER_SELECTION_ZU}: {count_1} {pluralize_plots(count_1)}\n"
            f"{LAYER_SELECTION_ZU_10M}: {count_2} {pluralize_plots(count_2)}",
            level=Qgis.Success,
            duration=MESSAGE_INFO_DURATION
        )

    def _perform_selection_workflow_oks(self, source_layer_name: str, source_layer: QgsVectorLayer,
                                        boundaries_layer_exact: QgsVectorLayer) -> None:
        """Выполнение процесса выборки для ОКС (упрощённая версия без буфера 10м)

        Args:
            source_layer_name: Имя исходного слоя
            source_layer: Исходный слой
            boundaries_layer_exact: Слой точных границ
        """
        # Проверяем существование слоя выборки
        existing_layer = self._get_layer_by_name(LAYER_SELECTION_OKS)

        if existing_layer:
            reply = QMessageBox.warning(
                self.iface.mainWindow(),
                "Подтверждение замены",
                f"Слой '{LAYER_SELECTION_OKS}' уже существует и будет заменён.\n\nПродолжить?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                log_info(f"F_2_1: Пропущена выборка ОКС из {source_layer_name}")
                return

            # Удаляем существующий слой
            QgsProject.instance().removeMapLayer(existing_layer.id())
            log_info(f"F_2_1: Удален существующий слой {LAYER_SELECTION_OKS}")

        # Проверяем что движок выборки инициализирован
        if not self.selection_engine:
            log_error("F_2_1: Selection engine не инициализирован")
            return

        # Выполняем выборку ОКС через движок
        log_info(f"F_2_1: Запуск выборки ОКС из {source_layer_name}")
        final_layer = self.selection_engine.perform_selection_oks(boundaries_layer_exact, source_layer)

        if not final_layer:
            log_info("F_2_1: Слой ОКС пуст - нет объектов для добавления")
            return

        # Сортируем слой по полю "КН" (если поле присутствует)
        # ВАЖНО: Сортировка ПЕРЕД добавлением в проект для корректной последовательности FID
        # КРИТИЧНО: M_15 возвращает memory layer - нужно пересохранить в GeoPackage
        sorted_layer = self.feature_sort_manager.sort_layer(final_layer)
        # Если слой был отсортирован (новый memory layer), пересохраняем в GeoPackage
        if sorted_layer != final_layer:
            from .submodules.Fsm_2_1_6_layer_builder import Fsm_2_1_6_LayerBuilder
            assert self.plugin_dir is not None  # Type narrowing для Pylance
            gpkg_path = self._get_gpkg_path()
            if gpkg_path:
                builder = Fsm_2_1_6_LayerBuilder(self.plugin_dir)
                final_layer = builder.save_layer_to_gpkg(sorted_layer, LAYER_SELECTION_OKS, gpkg_path)
        else:
            final_layer = sorted_layer

        assert final_layer is not None  # Type narrowing для Pylance

        # Добавляем слой через layer_manager
        if not self.layer_manager:
            raise ValueError("layer_manager не инициализирован")

        self.layer_manager.add_layer(final_layer, make_readonly=False, auto_number=False, check_precision=False)
        log_info("F_2_1: Слой добавлен через layer_manager")

        # Сортируем все слои
        log_info("F_2_1: Сортировка всех слоёв по order_layers из Base_layers.json")
        self.layer_manager.sort_all_layers()
        log_info("F_2_1: Слои отсортированы по order_layers")

        # Показываем результат
        count = final_layer.featureCount()
        log_info(f"F_2_1: ИТОГОВЫЕ РЕЗУЛЬТАТЫ ВЫБОРКИ ОКС из {source_layer_name}:")
        log_info(f"F_2_1:   {LAYER_SELECTION_OKS}: {count} объектов")

        self.iface.messageBar().pushMessage(
            PLUGIN_NAME,
            f"Выборка ОКС из {source_layer_name} завершена:\n{count} объектов",
            level=Qgis.Success,
            duration=MESSAGE_INFO_DURATION
        )

        # Масштабируем к слою
        self.iface.setActiveLayer(final_layer)
        self.iface.zoomToActiveLayer()

    def _get_layer_by_name(self, layer_name: str) -> Optional[QgsVectorLayer]:
        """Поиск слоя по имени

        Args:
            layer_name: Имя слоя

        Returns:
            QgsVectorLayer: Найденный слой или None
        """
        for layer in QgsProject.instance().mapLayers().values():
            if layer.name() == layer_name:
                return layer
        return None

    def _reload_boundaries_if_needed(self, boundaries_layer: QgsVectorLayer) -> None:
        """Перезагрузка слоя границ если он из GPKG

        КРИТИЧНО: После сохранения слоя в project.gpkg слой границ из того же GPKG
        становится недоступным для итерации (getFeatures() не работает).
        Решение: reload() слоя для обновления кэша GDAL

        Args:
            boundaries_layer: Слой границ для проверки и перезагрузки
        """
        if boundaries_layer.providerType() == 'ogr' and 'project.gpkg' in boundaries_layer.source():
            log_info("F_2_1: Обновление слоя границ после записи в GPKG...")
            boundaries_layer.reload()
            log_info(f"F_2_1: Слой обновлён. featureCount: {boundaries_layer.featureCount()}")

    def _perform_selection_workflow_generic(self, source_layer_name: str, source_layer: QgsVectorLayer,
                                             boundaries_layer_exact: QgsVectorLayer,
                                             target_layer_name: str, display_name: str) -> None:
        """Выполнение generic выборки (НП, ТерЗоны, Вода и др.)

        Упрощённая выборка без буфера 10м и без специальной обработки атрибутов.
        Поля копируются напрямую из исходного WFS слоя.

        TODO: Создать Base_selection_NP.json, Base_selection_TerZony.json,
              Base_selection_Voda.json для более точного маппинга полей

        Args:
            source_layer_name: Имя исходного слоя
            source_layer: Исходный WFS слой
            boundaries_layer_exact: Слой точных границ
            target_layer_name: Имя целевого слоя выборки (константа)
            display_name: Отображаемое имя для логов и сообщений
        """
        # Проверяем существование слоя выборки
        existing_layer = self._get_layer_by_name(target_layer_name)

        if existing_layer:
            reply = QMessageBox.warning(
                self.iface.mainWindow(),
                "Подтверждение замены",
                f"Слой '{target_layer_name}' уже существует и будет заменён.\n\nПродолжить?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                log_info(f"F_2_1: Пропущена выборка {display_name} из {source_layer_name}")
                return

            # Удаляем существующий слой
            QgsProject.instance().removeMapLayer(existing_layer.id())
            log_info(f"F_2_1: Удален существующий слой {target_layer_name}")

        # Проверяем что движок выборки инициализирован
        if not self.selection_engine:
            log_error("F_2_1: Selection engine не инициализирован")
            return

        # Выполняем generic выборку через движок
        log_info(f"F_2_1: Запуск выборки {display_name} из {source_layer_name}")
        final_layer = self.selection_engine.perform_selection_generic(
            boundaries_layer_exact, source_layer, target_layer_name
        )

        if not final_layer:
            log_info(f"F_2_1: Слой {display_name} пуст - нет объектов для добавления")
            return

        # Добавляем слой через layer_manager
        if not self.layer_manager:
            raise ValueError("layer_manager не инициализирован")

        self.layer_manager.add_layer(final_layer, make_readonly=False, auto_number=False, check_precision=False)
        log_info(f"F_2_1: Слой {display_name} добавлен через layer_manager")

        # Сортируем все слои
        log_info("F_2_1: Сортировка всех слоёв по order_layers из Base_layers.json")
        self.layer_manager.sort_all_layers()
        log_info("F_2_1: Слои отсортированы по order_layers")

        # Показываем результат
        count = final_layer.featureCount()
        log_info(f"F_2_1: ИТОГОВЫЕ РЕЗУЛЬТАТЫ ВЫБОРКИ {display_name} из {source_layer_name}:")
        log_info(f"F_2_1:   {target_layer_name}: {count} объектов")

        self.iface.messageBar().pushMessage(
            PLUGIN_NAME,
            f"Выборка {display_name} из {source_layer_name} завершена:\n{count} объектов",
            level=Qgis.Success,
            duration=MESSAGE_INFO_DURATION
        )

    def _run_oks_zu_analysis(self) -> None:
        """Автоматический анализ связей ОКС-ЗУ через M_23

        Вызывается в конце выборки. M_23 автоматически определяет:
        - Есть ли слои выборки (куда записывать)
        - Есть ли выписки (ОКС_на_ЗУ_выписка)
        - Заполняет ОКС_на_ЗУ_факт по геометрии
        """
        try:
            oks_zu_manager = OksZuAnalysisManager(self.iface)
            result = oks_zu_manager.auto_analyze()

            # Логируем результаты
            if result.get('geometry_filled'):
                oks_count = result.get('oks_updated', 0)
                zu_count = result.get('zu_updated', 0)
                log_success(f"F_2_1: Заполнено ОКС_на_ЗУ_факт ({oks_count} ОКС, {zu_count} ЗУ)")

            if result.get('vypiska_filled'):
                log_success("F_2_1: Заполнено ОКС_на_ЗУ_выписка (выписки уже загружены)")

            if result.get('cutting_synced', 0) > 0:
                log_info(f"F_2_1: Синхронизировано {result['cutting_synced']} слоёв нарезки")

        except Exception as e:
            log_warning(f"F_2_1: Ошибка автоматического анализа ОКС-ЗУ: {e}")
