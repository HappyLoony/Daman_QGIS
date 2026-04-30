# -*- coding: utf-8 -*-
"""
F_5_4: Мастер-план - Генерация комплекта PDF-схем мастер-плана на формате А3.

Координатор: загружает Base_drawings.json, фильтрует доступные схемы,
показывает GUI для выбора, генерирует макеты через M_34 и экспортирует PDF.
Результат: один объединённый PDF со всеми выбранными схемами.
"""

import os
import fnmatch
from typing import Optional, List, Dict, Any, Set, Tuple

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QMessageBox, QFileDialog, QApplication, QProgressDialog
)
from qgis.core import (
    QgsProject, QgsMapThemeCollection, QgsLayoutExporter,
    QgsLayoutItemMap, QgsLayoutItemLabel, QgsLayoutItemLegend,
    QgsLayoutRenderContext, QgsLayoutSize, QgsVectorLayer
)
from qgis.core import Qgis

from Daman_QGIS.core.base_tool import BaseTool
from Daman_QGIS.utils import log_info, log_error, log_warning, log_success
from Daman_QGIS.constants import EXPORT_DPI_ROSREESTR
from Daman_QGIS.managers import get_reference_managers, registry
from Daman_QGIS.managers.styling.submodules.Msm_46_utils import (
    filter_print_visible,
)

from .submodules.Fsm_5_4_1_dialog import Fsm_5_4_1_Dialog
from .submodules.Fsm_5_4_2_layout_manager import Fsm_5_4_2_LayoutManager
from .submodules.Fsm_5_4_3_pdf_assembler import Fsm_5_4_3_PdfAssembler


# Хардкод подложек
_MAIN_MAP_BASEMAP = 'L_1_3_2_NSPD_Ref'     # ЦОС справочный (cat=235) — главная карта
_OVERVIEW_MAP_BASEMAP = 'L_1_3_3_NSPD_Base'  # ЕЭКО основной (cat=849241) — обзорная карта
_BOUNDARIES_LAYER = 'L_1_1_1_Границы_работ'


def _expand_layer_patterns(
    patterns: List[str],
    project_layer_names: Set[str],
) -> Tuple[List[str], List[str]]:
    """
    Развернуть glob-паттерны в конкретные имена слоёв проекта.

    Поддерживает wildcards в именах: `*` (любые символы), `?` (один символ).
    Точные имена матчатся как есть.

    Args:
        patterns: Список паттернов или точных имён из Base_drawings.
        project_layer_names: Множество имён всех слоёв проекта.

    Returns:
        (resolved, unresolved):
          resolved — отсортированный список реальных имён слоёв
          unresolved — паттерны/имена без единого совпадения (для warning).
    """
    resolved: Set[str] = set()
    unresolved: List[str] = []
    for pattern in patterns:
        if '*' in pattern or '?' in pattern:
            matches = fnmatch.filter(project_layer_names, pattern)
            if matches:
                resolved.update(matches)
            else:
                unresolved.append(pattern)
        else:
            if pattern in project_layer_names:
                resolved.add(pattern)
            else:
                unresolved.append(pattern)
    resolved_sorted = sorted(resolved)
    # Фильтр not_print (Base_layers): скрытые от печати слои не должны
    # попадать в темы макетов и легенду
    visible, hidden = filter_print_visible(resolved_sorted)
    if hidden:
        log_info(
            f"F_5_4: Исключены not_print слои: {', '.join(hidden)}"
        )
    return visible, unresolved


class F_5_4_MasterPlan(BaseTool):
    """Генерация комплекта PDF-схем мастер-плана."""

    def __init__(self, iface):
        super().__init__(iface)
        self._created_themes: List[str] = []

    def run(self) -> None:
        """Запуск функции.

        Использует QProgressDialog для информирования о текущем этапе
        (между этапами могут быть паузы 1-12 сек: создание макетов,
        DaData, M_46 plan_and_apply, M_34 adapt_legend). Без прогресса
        пользователь думает что плагин завис.
        """
        log_info("F_5_4: Запуск функции Мастер-план")

        # Проверка проекта
        if not self.check_project_opened():
            return

        # Создаём общий QProgressDialog (модальный к QGIS).
        # parent=iface.mainWindow() — обычно всегда доступен в QGIS plugin runtime.
        # Если по какой-то причине None — прогресс остаётся top-level окном.
        parent = self.iface.mainWindow() if self.iface else None
        progress = QProgressDialog(
            "Запуск...",
            None,  # cancel disabled — F_5_4 не отменяется частично
            0, 100,
            parent
        )
        progress.setWindowTitle("Мастер-план")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        # 0 = показать сразу (default 4000мс перекрывает большинство этапов)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)

        def _step(percent: int, label: str) -> None:
            """Обновить прогресс: лейбл + процент + processEvents."""
            progress.setLabelText(label)
            progress.setValue(percent)
            QApplication.processEvents()

        try:
            _step(0, "1/12: Загрузка справочника схем...")
            progress.show()
            QApplication.processEvents()

            # 1. Загрузить Base_drawings.json, отфильтровать по doc_type="Мастер-план"
            ref_managers = get_reference_managers()
            all_drawings = ref_managers.drawings.get_drawings()

            master_plan_drawings = [
                d for d in all_drawings
                if d.get('doc_type') == 'Мастер-план'
            ]

            if not master_plan_drawings:
                log_warning("F_5_4: Нет записей с doc_type='Мастер-план' в Base_drawings.json")
                progress.close()
                QMessageBox.warning(
                    self.iface.mainWindow(),
                    "Мастер-план",
                    "В справочнике чертежей нет записей для мастер-плана."
                )
                return

            _step(10, "2/12: Поиск доступных схем в проекте...")

            # 2. Фильтрация: visible_layers не null (слои могут отсутствовать — warning)
            available_drawings = self._filter_available_drawings(master_plan_drawings)

            if not available_drawings:
                log_warning("F_5_4: Нет схем с заполненными visible_layers")
                progress.close()
                QMessageBox.warning(
                    self.iface.mainWindow(),
                    "Мастер-план",
                    "Нет схем с заполненными слоями (visible_layers)."
                )
                return

            log_info(f"F_5_4: Доступно {len(available_drawings)} схем из {len(master_plan_drawings)}")

            _step(15, "3/12: Получение адреса территории (DaData)...")

            # 2.5. Получение адреса территории через M_39 DaData
            location_text = self._get_location_text()

            _step(20, "4/12: Ожидание выбора схем пользователем...")
            progress.hide()  # скрываем чтобы не перекрывать модальный диалог

            # 3. Диалог выбора схем и папки экспорта
            dialog = Fsm_5_4_1_Dialog(
                available_drawings, location_text, self.iface.mainWindow()
            )
            if dialog.exec() == 0:
                log_info("F_5_4: Отмена пользователем")
                return

            selected_drawings = dialog.get_selected_drawings()
            output_folder = dialog.get_output_folder()
            location_text = dialog.get_location_text()

            if not selected_drawings:
                log_warning("F_5_4: Не выбрано ни одной схемы")
                return

            if not output_folder:
                log_warning("F_5_4: Не указана папка экспорта")
                return

            os.makedirs(output_folder, exist_ok=True)

            log_info(
                f"F_5_4: Выбрано {len(selected_drawings)} схем, "
                f"папка: {output_folder}"
            )

            progress.show()
            _step(30, "5/12: Подготовка превью основной карты...")

            # 4. Layout manager (нужен раньше для main preview)
            layout_mgr = Fsm_5_4_2_LayoutManager(self.iface)

            _step(35, "6/12: Ожидание выбора масштаба основной карты...")
            # Превью-диалог сам показывает progress bar тайлов; общий progress
            # остаётся видимым с поясняющим текстом, чтобы UX не моргал.

            # 4a. Диалог масштаба основной карты (одноразовый по первой схеме)
            # Применяется глобально ко ВСЕМ схемам как множитель базового масштаба.
            main_scale_factor = self._get_main_scale_factor(
                selected_drawings[0], layout_mgr
            )
            if main_scale_factor is None:
                log_info("F_5_4: Отмена выбора масштаба основной карты")
                return

            _step(50, "7/12: Подготовка превью обзорной карты...")

            _step(55, "8/12: Ожидание выбора масштаба обзорной карты...")

            # 4b. Диалог масштаба обзорной карты (аналог Fsm_1_4_10)
            overview_scale_factor = self._get_overview_scale_factor(
                selected_drawings[0], layout_mgr
            )
            if overview_scale_factor is None:
                log_info("F_5_4: Отмена выбора масштаба обзорной карты")
                return

            _step(70, "9/12: Применение подписей через M_12...")

            # 4c. === ПРИМЕНЕНИЕ ПОДПИСЕЙ ===
            # ВАЖНО: Принудительно обновляем подписи для ВСЕХ слоёв
            # Причина: при отладке нужно гарантировать что настройки актуальные
            # из Base_labels.json. Также автоматически уважает флаг M_45 через
            # M_12.apply_labels (доминантный флаг видимости подписей).
            try:
                from Daman_QGIS.managers import LabelManager

                label_manager = LabelManager()

                # Настраиваем глобальный движок коллизий (ОДИН РАЗ)
                label_manager.configure_global_engine(self.iface)
                log_info("F_5_4: Глобальный движок коллизий подписей настроен")

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
                log_info(f"F_5_4: Подписи обновлены: {applied_count} слоёв, пропущено: {skipped_count}")

            except Exception as e:
                log_warning(f"F_5_4: Не удалось настроить движок подписей: {str(e)}")
                import traceback
                log_warning(f"F_5_4: {traceback.format_exc()}")

            # 5. Генерация PDF для каждой выбранной схемы
            pdf_paths: List[str] = []
            self._created_themes = []

            total = len(selected_drawings)
            for i, drawing in enumerate(selected_drawings):
                drawing_name = drawing.get('drawing_name', f'Схема_{i + 1}')
                log_info(f"F_5_4: Обработка схемы {i + 1}/{total}: {drawing_name}")

                # Этапы 10/12 — генерация: 75% + (i/total)*15% → 75-90%
                pct = 75 + int((i / max(total, 1)) * 15)
                _step(
                    pct,
                    f"10/12: Генерация схемы {i + 1}/{total}: {drawing_name}"
                )

                try:
                    pdf_path = self._generate_single_scheme(
                        drawing=drawing,
                        index=i,
                        output_folder=output_folder,
                        layout_mgr=layout_mgr,
                        overview_scale_factor=overview_scale_factor,
                        main_scale_factor=main_scale_factor,
                        location_text=location_text
                    )
                    if pdf_path:
                        pdf_paths.append(pdf_path)
                        log_info(f"F_5_4: Схема экспортирована: {pdf_path}")
                except Exception as e:
                    log_error(f"F_5_4: Ошибка при генерации схемы '{drawing_name}': {e}")
                    continue

            if not pdf_paths:
                log_error("F_5_4: Не удалось создать ни одного PDF")
                progress.close()
                QMessageBox.critical(
                    self.iface.mainWindow(),
                    "Мастер-план",
                    "Не удалось создать ни одного PDF."
                )
                return

            _step(95, "11/12: Склейка PDF в один файл...")

            # 6. Склейка PDF в один файл
            assembler = Fsm_5_4_3_PdfAssembler()
            merged_filename = "Мастер-план.pdf"
            merged_path = os.path.join(output_folder, merged_filename)

            merge_success = assembler.merge(pdf_paths, merged_path)

            # 7. Темы НЕ удаляются: они нужны сохранённым макетам для
            # корректного отображения при открытии в редакторе макетов.
            # При повторном запуске F_5_4 темы перезаписываются через
            # theme_collection.insert() (upsert-семантика QGIS).

            _step(100, "12/12: Готово.")

            # 8. Открытие результата
            if merge_success:
                log_success(f"F_5_4: Мастер-план создан: {merged_path}")
                self._open_result(merged_path)
            else:
                log_warning("F_5_4: Склейка не удалась, отдельные PDF сохранены")
                self.iface.messageBar().pushMessage(
                    "Мастер-план",
                    f"Создано {len(pdf_paths)} отдельных PDF в {output_folder}",
                    level=Qgis.MessageLevel.Warning,
                    duration=5
                )

        finally:
            # Гарантированное закрытие прогресса при любом сценарии
            # (отмена, ошибка, успех)
            try:
                progress.close()
            except Exception:
                pass

    def _filter_available_drawings(
        self, drawings: List[Dict]
    ) -> List[Dict]:
        """
        Фильтрация: оставить только схемы, где visible_layers не null.
        Отсутствующие слои — warning, но схема остаётся доступной.

        Args:
            drawings: Список чертежей из Base_drawings.json

        Returns:
            Отфильтрованный список (visible_layers заполнены)
        """
        project = QgsProject.instance()
        project_layer_names = {
            layer.name() for layer in project.mapLayers().values()
        }

        available = []
        for d in drawings:
            visible_layers = d.get('visible_layers')
            if not visible_layers:
                continue

            # Развернуть паттерны (поддержка `*`, `?`)
            resolved, unresolved = _expand_layer_patterns(
                visible_layers, project_layer_names
            )
            if unresolved:
                log_warning(
                    f"F_5_4: Схема '{d.get('drawing_name')}' — "
                    f"не найдены слои/паттерны: {', '.join(unresolved)}"
                )
            # Если ни один паттерн не дал совпадений — схема недоступна
            if not resolved:
                log_warning(
                    f"F_5_4: Схема '{d.get('drawing_name')}' — "
                    f"ни один слой не найден, пропускаем"
                )
                continue

            available.append(d)

        return available

    def _get_location_text(self) -> str:
        """
        Получить адрес территории через M_39 DaData по центроиду L_1_1_1.

        Returns:
            Отформатированный адрес или пустая строка
        """
        try:
            # Находим слой границ работ
            boundaries_layer = None
            for layer in QgsProject.instance().mapLayers().values():
                if layer.name() == _BOUNDARIES_LAYER:
                    boundaries_layer = layer
                    break

            if not boundaries_layer or not isinstance(boundaries_layer, QgsVectorLayer):
                log_warning("F_5_4: Слой границ работ не найден для геокодирования")
                return ''

            if boundaries_layer.featureCount() == 0:
                return ''

            from qgis.core import (
                QgsCoordinateReferenceSystem, QgsCoordinateTransform,
                QgsDistanceArea, QgsPointXY
            )
            feature = next(boundaries_layer.getFeatures())

            # Площадь в га
            da = QgsDistanceArea()
            da.setSourceCrs(boundaries_layer.crs(), QgsProject.instance().transformContext())
            da.setEllipsoid(QgsProject.instance().ellipsoid())
            area_m2 = da.measureArea(feature.geometry())
            area_ha = area_m2 / 10000.0
            centroid = feature.geometry().centroid().asPoint()

            transform = QgsCoordinateTransform(
                boundaries_layer.crs(),
                QgsCoordinateReferenceSystem('EPSG:4326'),
                QgsProject.instance()
            )

            # Multi-point геокодирование: центроид + 4 угла bbox.
            # На горных/приграничных территориях (Ингушетия, Алтай, ДВ)
            # центроид может попасть в "пустую" точку без адресов в ФИАС
            # (DaData возвращает результаты только из ФИАС в радиусе ≤1000м).
            # M_39 кэширует по округлённым lat/lon (~10м), повторы дёшевы.
            bbox = feature.geometry().boundingBox()
            corners = [
                QgsPointXY(bbox.xMinimum(), bbox.yMaximum()),  # NW
                QgsPointXY(bbox.xMaximum(), bbox.yMaximum()),  # NE
                QgsPointXY(bbox.xMinimum(), bbox.yMinimum()),  # SW
                QgsPointXY(bbox.xMaximum(), bbox.yMinimum()),  # SE
            ]
            points = [centroid] + corners  # центроид первым (приоритет)

            # Запрос к DaData
            geocoder = registry.get('M_39')
            if not geocoder:
                log_warning("F_5_4: M_39 не зарегистрирован")
                return ''
            geocoder.initialize()
            if not geocoder.is_configured():
                log_warning("F_5_4: M_39 DaData не настроен")
                return ''

            result = None
            for i, point in enumerate(points):
                wgs = transform.transform(point)
                result = geocoder.geolocate(
                    lat=wgs.y(), lon=wgs.x(), radius_meters=1000
                )
                if result:
                    if i > 0:
                        log_info(
                            f"F_5_4: DaData нашёл адрес по точке {i + 1}/{len(points)} "
                            f"(угол bbox), центроид пуст"
                        )
                    break

            if not result:
                # Нормальная ситуация для горных/приграничных территорий —
                # не баг, а отсутствие адреса в ФИАС. Уровень INFO.
                log_info(
                    f"F_5_4: DaData не нашёл адрес ни по одной из {len(points)} точек "
                    f"(центроид + 4 угла bbox, радиус 1000м)"
                )
                return ''

            # Собираем адрес (без street — для территории нужен уровень район)
            data = result.get('data', {})
            parts = []
            for field in ['region_with_type', 'area_with_type',
                          'city_with_type', 'city_district_with_type',
                          'settlement_with_type']:
                val = data.get(field)
                # Дедупликация (г Севастополь = регион и город одновременно)
                if val and val not in parts:
                    parts.append(val)

            address = ', '.join(parts)
            if address:
                area_str = f"{area_ha:.2f}".replace('.', ',')
                location = (
                    f"Территория разработки мастер-плана "
                    f"находится по адресу: {address}, "
                    f"площадью {area_str} га"
                )
                log_info(f"F_5_4: Адрес территории: {location}")
                return location

        except Exception as e:
            log_warning(f"F_5_4: Ошибка получения адреса: {e}")

        return ''

    def _get_overview_scale_factor(
        self,
        first_drawing: Dict,
        layout_mgr: 'Fsm_5_4_2_LayoutManager',
    ) -> Optional[float]:
        """
        Показать диалог выбора масштаба обзорной карты.
        Аналог Fsm_1_4_10, но без привязки к конкретному layout.

        Создаёт временный layout для получения overview_map,
        показывает OverviewPreviewDialog, возвращает scale_factor.

        Args:
            first_drawing: Первая выбранная схема (для заполнения легенды
                тем же visible_layers что будет в финале).
            layout_mgr: Менеджер макетов F_5_4 (для update_legend).

        Returns:
            float scale_factor или None при отмене
        """
        # Получаем масштаб проекта для базового масштаба обзорной карты
        overview_base_scale = self._get_project_overview_scale()
        if not overview_base_scale:
            # Fallback: масштаб 100000
            overview_base_scale = 100000.0

        # Создаём временный layout для превью
        layout_mgr_m34 = registry.get('M_34')
        temp_layout = layout_mgr_m34.build_layout(
            layout_name='_temp_overview_preview', page_format='A3', orientation='landscape',
            doc_type='Мастер-план'
        )
        if not temp_layout:
            log_warning("F_5_4: Не удалось создать временный макет для превью")
            return 1.0  # Fallback: базовый масштаб

        project = QgsProject.instance()
        layout_manager = project.layoutManager()
        layout_manager.addLayout(temp_layout)

        _temp_theme = '_F_5_4_temp_overview'

        # Развернуть visible_layers первой схемы для легенды (как в финале)
        visible_layers_first = first_drawing.get('visible_layers', []) or []
        project_layer_names = {
            layer.name() for layer in project.mapLayers().values()
        }
        visible_resolved, _ = _expand_layer_patterns(
            visible_layers_first, project_layer_names
        )
        main_layers_first = visible_resolved + [_MAIN_MAP_BASEMAP]

        try:
            # Находим overview_map
            overview_map = None
            for item in temp_layout.items():
                if isinstance(item, QgsLayoutItemMap) and item.id() == 'overview_map':
                    overview_map = item
                    break

            if not overview_map:
                log_warning("F_5_4: overview_map не найден во временном макете")
                return 1.0

            # Создаём временную тему с ЦОС + границы работ (как в F_1_4)
            self._create_map_theme(_temp_theme, [
                _BOUNDARIES_LAYER, _OVERVIEW_MAP_BASEMAP
            ])

            # Привязываем тему к overview_map
            overview_map.setFollowVisibilityPreset(True)
            overview_map.setFollowVisibilityPresetName(_temp_theme)

            # Заполняем легенду visible_layers первой схемы (как в финале):
            # без update_legend QgsLayoutItemLegend в режиме autoUpdateModel
            # собирает все видимые слои проекта → preview не соответствует
            # финальному PDF.
            layout_mgr.update_legend(temp_layout, main_layers_first)

            # Устанавливаем базовый масштаб
            overview_map.setScale(overview_base_scale)

            # Устанавливаем экстент по границам работ
            self._set_overview_extent(overview_map)

            from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_4_10_overview_preview_dialog import (
                OverviewPreviewDialog
            )
            preview_dialog = OverviewPreviewDialog(
                temp_layout, overview_base_scale, self.iface.mainWindow()
            )

            if preview_dialog.exec() == 1:  # Accepted
                _dpi, scale_factor = preview_dialog.get_selected_variant()
                log_info(f"F_5_4: Выбран масштаб обзорной карты: x{scale_factor}")
                return scale_factor
            else:
                return None

        finally:
            # Удаляем временный макет и тему
            layout_manager.removeLayout(temp_layout)
            theme_collection = project.mapThemeCollection()
            if theme_collection.hasMapTheme(_temp_theme):
                theme_collection.removeMapTheme(_temp_theme)

    def _get_main_scale_factor(
        self,
        first_drawing: Dict,
        layout_mgr: 'Fsm_5_4_2_LayoutManager',
    ) -> Optional[float]:
        """
        Показать диалог выбора масштаба основной карты (одноразовый).

        Симметричен _get_overview_scale_factor, но для main_map. Создаёт
        временный layout с темой первой выбранной схемы (как референс
        для подбора масштаба), показывает MainPreviewDialog, возвращает
        scale_factor. Этот factor затем применяется ко ВСЕМ схемам
        (умножается на main_map.scale() в _generate_single_scheme).

        Args:
            first_drawing: Запись первой выбранной схемы из Base_drawings
            layout_mgr: Менеджер макетов F_5_4 (для apply_main_map_extent)

        Returns:
            float scale_factor (1.0 если отмена или ошибка), None запрещает
            генерацию (пока не используется — fallback на 1.0).
        """
        from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_4_11_main_preview_dialog import (
            MainPreviewDialog
        )

        # Развернуть тему первой схемы
        drawing_name = first_drawing.get('drawing_name', 'Схема_1')
        visible_layers = first_drawing.get('visible_layers', []) or []
        project = QgsProject.instance()
        project_layer_names = {
            layer.name() for layer in project.mapLayers().values()
        }
        visible_resolved, _ = _expand_layer_patterns(
            visible_layers, project_layer_names
        )
        main_layers = visible_resolved + [_MAIN_MAP_BASEMAP]

        # Временный макет A3 MP
        layout_mgr_m34 = registry.get('M_34')
        temp_layout = layout_mgr_m34.build_layout(
            layout_name='_temp_main_preview',
            page_format='A3', orientation='landscape',
            doc_type='Мастер-план'
        )
        if not temp_layout:
            log_warning("F_5_4: Не удалось создать временный макет для main preview")
            return 1.0

        layout_manager = project.layoutManager()
        if not layout_mgr_m34.add_layout_to_project(temp_layout):
            log_warning("F_5_4: Не удалось добавить временный макет main preview в проект")
            return 1.0

        _temp_theme = '_F_5_4_temp_main'

        try:
            # Найти main_map во временном макете
            main_map = None
            for item in temp_layout.items():
                if isinstance(item, QgsLayoutItemMap) and item.id() == 'main_map':
                    main_map = item
                    break

            if not main_map:
                log_warning("F_5_4: main_map не найден во временном макете")
                return 1.0

            # Тема первой схемы (как референс)
            self._create_map_theme(_temp_theme, main_layers)
            main_map.setFollowVisibilityPreset(True)
            main_map.setFollowVisibilityPresetName(_temp_theme)

            # Заполнить легенду тем же visible_layers что будет в финале
            # (без update_legend QgsLayoutItemLegend в режиме autoUpdateModel
            # собирает все ~66 видимых слоёв проекта → не fits 128 мм →
            # M_46 даёт tight план → preview не соответствует финальному PDF).
            layout_mgr.update_legend(temp_layout, main_layers)

            # Применить экстент по границам работ + M_46 + adapt_legend
            # (та же цепочка что в _generate_single_scheme — даст реальный
            # базовый масштаб для preview)
            layout_mgr.apply_main_map_extent(temp_layout)

            legend_mgr = registry.get('M_46')
            legend_mgr.plan_and_apply(temp_layout, config_key='A3_landscape_MP')
            layout_mgr_m34.adapt_legend(temp_layout)

            current_scale = main_map.scale()
            if not current_scale:
                log_warning("F_5_4: main_map.scale() == 0 в preview")
                return 1.0

            log_info(
                f"F_5_4: Main preview по схеме '{drawing_name}', "
                f"базовый масштаб 1:{int(current_scale)}"
            )

            preview_dialog = MainPreviewDialog(
                temp_layout, current_scale, self.iface.mainWindow()
            )

            if preview_dialog.exec() == 1:
                _dpi, scale_factor = preview_dialog.get_selected_variant()
                log_info(f"F_5_4: Выбран масштаб основной карты: x{scale_factor}")
                return scale_factor

            log_info("F_5_4: Диалог main preview отменён, используется x1.0")
            return 1.0

        finally:
            # Cleanup
            layout_manager.removeLayout(temp_layout)
            theme_collection = project.mapThemeCollection()
            if theme_collection.hasMapTheme(_temp_theme):
                theme_collection.removeMapTheme(_temp_theme)

    def _get_project_overview_scale(self) -> Optional[float]:
        """
        Получить масштаб обзорной карты из метаданных проекта.
        Масштаб = масштаб проекта * 100.

        Returns:
            float масштаб или None
        """
        try:
            project_home = os.path.normpath(QgsProject.instance().homePath())
            structure_manager = registry.get('M_19')
            structure_manager.project_root = project_home
            gpkg_path = structure_manager.get_gpkg_path(create=False)

            if gpkg_path and os.path.exists(gpkg_path):
                from Daman_QGIS.database.project_db import ProjectDB
                project_db = ProjectDB(gpkg_path)
                scale_data = project_db.get_metadata('2_10_main_scale')

                if scale_data and scale_data.get('value'):
                    scale_value = scale_data['value']
                    if isinstance(scale_value, str) and ':' in scale_value:
                        scale_number = int(scale_value.split(':')[1])
                    else:
                        scale_number = int(scale_value)

                    overview_scale = scale_number * 100
                    log_info(f"F_5_4: Масштаб обзорной карты: 1:{overview_scale}")
                    return float(overview_scale)
        except Exception as e:
            log_warning(f"F_5_4: Не удалось получить масштаб проекта: {e}")

        return None

    def _set_overview_extent(self, overview_map: QgsLayoutItemMap) -> None:
        """
        Установить экстент обзорной карты по слою границ работ.

        Args:
            overview_map: Элемент карты
        """
        try:
            boundaries_layer = None
            for layer in QgsProject.instance().mapLayers().values():
                if layer.name() == _BOUNDARIES_LAYER:
                    boundaries_layer = layer
                    break

            if not boundaries_layer:
                log_warning("F_5_4: Слой границ работ не найден для обзорной карты")
                return

            extent_manager = registry.get('M_18')
            extent = extent_manager.calculate_extent(
                boundaries_layer, padding_percent=5.0, adaptive=True
            )
            width, height = extent_manager.fitter.get_map_item_dimensions(overview_map)
            extent = extent_manager.fit_to_ratio(extent, width, height)
            extent_manager.applier.apply_extent(overview_map, extent)
        except Exception as e:
            log_warning(f"F_5_4: Не удалось установить экстент обзорной карты: {e}")

    def _generate_single_scheme(
        self,
        drawing: Dict,
        index: int,
        output_folder: str,
        layout_mgr: 'Fsm_5_4_2_LayoutManager',
        overview_scale_factor: float,
        main_scale_factor: float = 1.0,
        location_text: str = ''
    ) -> Optional[str]:
        """
        Генерация одной схемы мастер-плана.

        Args:
            drawing: Запись из Base_drawings.json
            index: Порядковый номер (0-based)
            output_folder: Папка для PDF
            layout_mgr: Менеджер макетов
            overview_scale_factor: Множитель масштаба обзорной карты
            main_scale_factor: Множитель масштаба основной карты (глобально
                из MainPreviewDialog по первой схеме). 1.0 = базовый.
            location_text: Адрес территории для title_label

        Returns:
            Путь к PDF или None при ошибке
        """
        drawing_name = drawing.get('drawing_name', f'Схема_{index + 1}')
        visible_layers = drawing.get('visible_layers', []) or []
        overview_layers = drawing.get('overview_layers', []) or []

        # Развернуть glob-паттерны в реальные имена слоёв проекта
        project = QgsProject.instance()
        project_layer_names = {
            layer.name() for layer in project.mapLayers().values()
        }
        visible_resolved, _ = _expand_layer_patterns(
            visible_layers, project_layer_names
        )
        overview_resolved, _ = _expand_layer_patterns(
            overview_layers, project_layer_names
        )

        # a/b. Списки слоёв
        main_layers = visible_resolved + [_MAIN_MAP_BASEMAP]
        overview_layer_list = overview_resolved + [_OVERVIEW_MAP_BASEMAP]

        # c/d. Создать map themes
        main_theme_name = f'F_5_4_main_{index}'
        overview_theme_name = f'F_5_4_overview_{index}'

        self._create_map_theme(main_theme_name, main_layers)
        self._created_themes.append(main_theme_name)

        self._create_map_theme(overview_theme_name, overview_layer_list)
        self._created_themes.append(overview_theme_name)

        # e. Создать макет A3 через M_34
        layout_name = f'Мастер-план — {drawing_name}'
        layout = layout_mgr.create_layout(layout_name)
        if not layout:
            log_error(f"Fsm_5_4_2: Не удалось создать макет для '{drawing_name}'")
            return None

        # Добавить в проект через M_34 — корректно обрабатывает конфликт имён
        # (removeLayout(existing) + addLayout(new)). Прямой lm.addLayout() при
        # дубликате имени приводит к удалению C++ объекта нашего layout.
        project = QgsProject.instance()
        layout_mgr_m34 = registry.get('M_34')
        if not layout_mgr_m34.add_layout_to_project(layout):
            log_error(f"F_5_4: Не удалось добавить макет '{layout_name}' в проект")
            return None

        try:
            # f/g. Привязать темы к картам
            for item in layout.items():
                if isinstance(item, QgsLayoutItemMap):
                    if item.id() == 'main_map':
                        item.setFollowVisibilityPreset(True)
                        item.setFollowVisibilityPresetName(main_theme_name)
                    elif item.id() == 'overview_map':
                        item.setFollowVisibilityPreset(True)
                        item.setFollowVisibilityPresetName(overview_theme_name)

            # h. Заголовок (адрес территории) + название схемы
            layout_mgr.set_title(layout, location_text, drawing_name)

            # h2. Подпись организации (опционально, только если в макете
            # есть organization_label — для МП да, для DPT нет).
            layout_mgr.set_organization(layout)

            # i. Легенда (filter_by_map)
            layout_mgr.update_legend(layout, main_layers)

            # j. Экстент карты по границам работ L_1_1_1
            layout_mgr.apply_main_map_extent(layout)

            # j1. M_46: централизованный план/применение условников
            # (wrap/col/symbol) ПЕРЕД финальным measurement и сдвигом экстента.
            # F_5_4 всегда A3 landscape Мастер-план.
            legend_mgr = registry.get('M_46')
            legend_mgr.plan_and_apply(layout, config_key='A3_landscape_MP')

            # j2. Адаптация размера легенды (M_34)
            # Вызывается ПОСЛЕ экстента — легенда корректно измеряется
            # только когда карта имеет экстент и масштаб
            layout_mgr_m34 = registry.get('M_34')
            layout_mgr_m34.adapt_legend(layout)

            # j3. Применить глобальный множитель main_scale_factor
            # (выбран пользователем в MainPreviewDialog по первой схеме)
            if main_scale_factor and main_scale_factor != 1.0:
                for item in layout.items():
                    if isinstance(item, QgsLayoutItemMap) and item.id() == 'main_map':
                        new_scale = item.scale() * main_scale_factor
                        item.setScale(new_scale)
                        item.refresh()
                        log_info(
                            f"F_5_4: Применён main_scale_factor=x{main_scale_factor} "
                            f"→ 1:{int(new_scale)}"
                        )
                        break

            # k. Масштаб обзорной карты
            overview_base = self._get_project_overview_scale() or 100000.0
            target_scale = overview_base * overview_scale_factor
            layout_mgr.apply_overview_scale(layout, target_scale)

            # l. Экспорт PDF
            safe_name = drawing_name.replace('/', '_').replace('\\', '_')
            pdf_filename = f"{index + 1:02d}_{safe_name}.pdf"
            pdf_path = os.path.join(output_folder, pdf_filename)

            layout_mgr.export_to_pdf(layout, pdf_path)

        except Exception:
            # При ошибке макет всё равно остаётся в проекте для диагностики
            raise

        return pdf_path

    def _create_map_theme(
        self, theme_name: str, layer_names: List[str]
    ) -> None:
        """
        Создать map theme с указанными слоями.

        Args:
            theme_name: Имя темы
            layer_names: Список имён слоёв для включения
        """
        project = QgsProject.instance()
        theme_collection = project.mapThemeCollection()

        # Удаляем если существует
        if theme_collection.hasMapTheme(theme_name):
            theme_collection.removeMapTheme(theme_name)

        theme_record = QgsMapThemeCollection.MapThemeRecord()
        layer_records = []

        layer_names_set = set(layer_names)

        for layer_id, layer in project.mapLayers().items():
            if layer.name() in layer_names_set:
                record = QgsMapThemeCollection.MapThemeLayerRecord(layer)
                record.isVisible = True
                record.usingCurrentStyle = True
                record.currentStyle = layer.styleManager().currentStyle()
                layer_records.append(record)

        theme_record.setLayerRecords(layer_records)
        theme_collection.insert(theme_name, theme_record)

        log_info(f"F_5_4: Создана тема '{theme_name}' с {len(layer_records)} слоями")

    def _cleanup_themes(self) -> None:
        """Удалить все временные map themes, созданные при генерации."""
        theme_collection = QgsProject.instance().mapThemeCollection()
        for theme_name in self._created_themes:
            try:
                if theme_collection.hasMapTheme(theme_name):
                    theme_collection.removeMapTheme(theme_name)
            except Exception as e:
                log_warning(f"F_5_4: Не удалось удалить тему '{theme_name}': {e}")

        self._created_themes.clear()
        log_info("F_5_4: Временные темы очищены")

    def _open_result(self, pdf_path: str) -> None:
        """
        Открыть результат в системном просмотрщике.

        Args:
            pdf_path: Путь к PDF файлу
        """
        try:
            import subprocess
            import sys

            if sys.platform == 'win32':
                os.startfile(pdf_path)
            elif sys.platform == 'darwin':
                subprocess.run(['open', pdf_path])
            else:
                subprocess.run(['xdg-open', pdf_path])

            log_info(f"F_5_4: Открыт файл: {pdf_path}")
        except Exception as e:
            log_warning(f"F_5_4: Не удалось открыть файл: {e}")
            self.iface.messageBar().pushMessage(
                "Мастер-план",
                f"PDF создан: {pdf_path}",
                level=Qgis.MessageLevel.Info,
                duration=10
            )
