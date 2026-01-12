# -*- coding: utf-8 -*-
"""
Координатор проверки топологии - native QGIS версия
Управляет всеми checker модулями и создает единый error layer

Поддерживает все типы геометрий: полигоны, линии, точки
"""

from typing import Dict, Any, Optional, List
from qgis.core import (
    QgsVectorLayer, QgsMessageLog, Qgis, QgsWkbTypes, QgsProject,
    QgsFeature, QgsGeometry, QgsField, QgsFields,
    QgsVectorFileWriter, QgsCoordinateReferenceSystem,
    QgsProcessingContext
)
from qgis.PyQt.QtCore import QMetaType
from qgis.PyQt.QtGui import QColor

from .Fsm_0_4_1_geometry_validity import Fsm_0_4_1_GeometryValidityChecker
from .Fsm_0_4_2_duplicates import Fsm_0_4_2_DuplicatesChecker
from .Fsm_0_4_3_topology_errors import Fsm_0_4_3_TopologyErrorsChecker
from .Fsm_0_4_4_precision import Fsm_0_4_4_PrecisionChecker
from .Fsm_0_4_8_line_checker import Fsm_0_4_8_LineChecker
from .Fsm_0_4_9_point_checker import Fsm_0_4_9_PointChecker
from .Fsm_0_4_10_cross_feature_checker import Fsm_0_4_10_CrossFeatureChecker
from .Fsm_0_4_12_sliver_checker import Fsm_0_4_12_SliverChecker
from .Fsm_0_4_13_sliver_native_checker import Fsm_0_4_13_SliverNativeChecker
from Daman_QGIS.constants import PLUGIN_NAME
from Daman_QGIS.utils import log_info, log_warning, log_error, log_success


class Fsm_0_4_5_TopologyCoordinator:
    """
    Координатор проверки топологии через native QGIS алгоритмы

    Поддерживает:
    - Полигоны: валидность, самопересечения, дубли, наложения, spike, точность
    - Линии: самопересечения, наложения, висячие концы (dangles)
    - Точки: дубликаты, близость (proximity)

    Этап 1: ПРОВЕРКА - только анализ без изменения исходных данных
    Этап 2: Передача результатов в Fixer для исправления
    """

    # Префикс для временных слоев
    PREFIX_ERRORS = "Ошибки_топологии"

    # Типы ошибок (расширенный список)
    ERROR_TYPES = {
        # Полигоны
        'validity': 'Ошибка валидности',
        'self_intersection': 'Самопересечение',
        'duplicate_geometry': 'Дубль полигона',
        'duplicate_vertex': 'Дубль вершины',
        'close_points': 'Близкие точки (< 1см)',
        'cross_feature_close_points': 'Близкие точки между объектами',
        'overlap': 'Наложение',
        'spike': 'Острый угол',
        'precision': 'Неокругленные координаты',
        'sliver_polsby_popper': 'Sliver-полигон (Polsby-Popper)',
        'sliver_qgis_native': 'Sliver-полигон (QGIS thinness)',
        # Линии
        'line_self_intersection': 'Самопересечение линии',
        'line_overlap': 'Наложение линий',
        'dangle': 'Висячий конец',
        # Точки
        'duplicate_point': 'Дубликат точки',
        'point_proximity': 'Близкие точки',
        # Cross-layer
        'cross_layer_overlap': 'Наложение между слоями'
    }

    # Типы ошибок, которые могут быть автоматически исправлены
    FIXABLE_ERROR_TYPES = {
        'validity',
        'self_intersection',
        'duplicate_vertex',
        'close_points',  # Близкие точки - через native:removeduplicatevertices
        'cross_feature_close_points',  # Близкие точки между объектами - через snap
        'precision',
        'duplicate_point'
    }

    def __init__(self, processing_context: Optional[QgsProcessingContext] = None):
        """
        Инициализация координатора

        Args:
            processing_context: QgsProcessingContext созданный в main thread.
                               ОБЯЗАТЕЛЬНО передавать при работе в background thread,
                               так как processing.run() обращается к iface.mapCanvas()
                               что вызывает access violation из background thread.
        """
        self.report = []
        self.statistics = {}
        self.last_check_result = None
        self.processing_context = processing_context

        # Инициализируем checker'ы для полигонов с processing_context
        self.validity_checker = Fsm_0_4_1_GeometryValidityChecker()
        self.duplicates_checker = Fsm_0_4_2_DuplicatesChecker(processing_context)
        self.topology_checker = Fsm_0_4_3_TopologyErrorsChecker()
        self.precision_checker = Fsm_0_4_4_PrecisionChecker(processing_context)
        self.cross_feature_checker = Fsm_0_4_10_CrossFeatureChecker()

        # Инициализируем sliver checker'ы
        self.sliver_checker = Fsm_0_4_12_SliverChecker()
        self.sliver_native_checker = Fsm_0_4_13_SliverNativeChecker(
            processing_context=processing_context
        )

        # Инициализируем checker'ы для линий и точек
        self.line_checker = Fsm_0_4_8_LineChecker()
        self.point_checker = Fsm_0_4_9_PointChecker()

        log_info(
            "Fsm_0_4_5: TopologyCoordinator инициализирован (multi-geometry версия)"
        )

    def check_layer(self,
                   layer: QgsVectorLayer,
                   check_types: Optional[List[str]] = None,
                   progress_callback=None) -> Dict[str, Any]:
        """
        Проверка топологии слоя (полигоны, линии или точки)

        Args:
            layer: Проверяемый слой
            check_types: Список типов проверок. По умолчанию - все для данного типа геометрии.
                Полигоны: ['validity', 'self_intersection', 'duplicate_geometries',
                          'duplicate_vertices', 'overlaps', 'spikes', 'precision']
                Линии: ['line_self_intersections', 'line_overlaps', 'dangles']
                Точки: ['duplicate_points', 'point_proximity']
            progress_callback: Функция обратного вызова для прогресса (0-100)

        Returns:
            Словарь с результатами:
            {
                'error_layer': QgsVectorLayer - слой с ошибками,
                'error_count': int - общее количество ошибок,
                'errors_by_type': dict - ошибки по типам,
                'statistics': dict - статистика,
                'original_layer': QgsVectorLayer - исходный слой,
                'geometry_type': str - тип геометрии ('polygon', 'line', 'point')
            }
        """
        # Очищаем предыдущие результаты
        self.clear_report()

        # Определяем тип геометрии
        geom_type = layer.geometryType()

        if geom_type == QgsWkbTypes.PolygonGeometry:
            return self._check_polygon_layer(layer, check_types, progress_callback)
        elif geom_type == QgsWkbTypes.LineGeometry:
            return self._check_line_layer(layer, check_types, progress_callback)
        elif geom_type == QgsWkbTypes.PointGeometry:
            return self._check_point_layer(layer, check_types, progress_callback)
        else:
            log_warning(
                f"Fsm_0_4_5: Слой '{layer.name()}' имеет неподдерживаемый тип геометрии"
            )
            return {
                'error_layer': None,
                'error_count': 0,
                'errors_by_type': {},
                'statistics': {
                    'total_features': layer.featureCount(),
                    'check_types': [],
                    'errors_found': 0
                },
                'original_layer': layer,
                'geometry_type': 'unknown'
            }

    def _check_polygon_layer(self,
                            layer: QgsVectorLayer,
                            check_types: Optional[List[str]] = None,
                            progress_callback=None) -> Dict[str, Any]:
        """Проверка полигонального слоя"""

        # Определяем типы проверок по умолчанию для полигонов
        if check_types is None:
            check_types = [
                'validity', 'self_intersection',
                'duplicate_geometries', 'duplicate_vertices', 'close_points',
                'cross_feature_close_points',  # Близкие точки между объектами
                'overlaps', 'spikes', 'precision',
                'slivers_polsby_popper', 'slivers_qgis_native'  # Sliver detection
            ]

        # Инициализация статистики
        self.statistics[layer.name()] = {
            'total_features': layer.featureCount(),
            'check_types': check_types,
            'errors_found': 0,
            'geometry_type': 'polygon'
        }

        # Отчет
        self.report.append(f"=== ПРОВЕРКА ТОПОЛОГИИ (ПОЛИГОНЫ): {layer.name()} ===")
        self.report.append(f"Объектов в слое: {layer.featureCount()}")
        self.report.append(f"Типы проверок: {', '.join(check_types)}")
        self.report.append("")

        if progress_callback:
            progress_callback(5)

        # Собираем все ошибки
        all_errors = []
        errors_by_type = {}

        # 1. Проверка валидности и самопересечений
        if 'validity' in check_types or 'self_intersection' in check_types:
            log_info("Fsm_0_4_5: Проверка валидности геометрии...")

            try:
                validity_errors, self_int_errors = self.validity_checker.check(layer)

                if 'validity' in check_types:
                    errors_by_type['validity'] = validity_errors
                    all_errors.extend(validity_errors)

                if 'self_intersection' in check_types:
                    errors_by_type['self_intersection'] = self_int_errors
                    all_errors.extend(self_int_errors)
            except Exception as e:
                log_error(f"Fsm_0_4_5: Ошибка проверки валидности: {e}")

            if progress_callback:
                progress_callback(25)

        # 2. Проверка дублей и близких точек
        if ('duplicate_geometries' in check_types or
            'duplicate_vertices' in check_types or
            'close_points' in check_types):

            try:
                geom_duplicates, vertex_duplicates, close_points = self.duplicates_checker.check(layer)

                if 'duplicate_geometries' in check_types:
                    errors_by_type['duplicate_geometry'] = geom_duplicates
                    all_errors.extend(geom_duplicates)

                if 'duplicate_vertices' in check_types:
                    errors_by_type['duplicate_vertex'] = vertex_duplicates
                    all_errors.extend(vertex_duplicates)

                if 'close_points' in check_types:
                    errors_by_type['close_points'] = close_points
                    all_errors.extend(close_points)
            except Exception as e:
                log_error(f"Fsm_0_4_5: Ошибка проверки дублей: {e}")

            if progress_callback:
                progress_callback(50)

        # 3. Проверка топологических ошибок
        if 'overlaps' in check_types or 'spikes' in check_types:
            try:
                overlaps, spikes = self.topology_checker.check(layer)

                if 'overlaps' in check_types:
                    errors_by_type['overlap'] = overlaps
                    all_errors.extend(overlaps)

                if 'spikes' in check_types:
                    errors_by_type['spike'] = spikes
                    all_errors.extend(spikes)
            except Exception as e:
                log_error(f"Fsm_0_4_5: Ошибка проверки топологии: {e}")

            if progress_callback:
                progress_callback(75)

        # 4. Проверка точности
        if 'precision' in check_types:
            log_info("Fsm_0_4_5: Проверка точности координат...")

            try:
                precision_errors = self.precision_checker.check(layer)

                errors_by_type['precision'] = precision_errors
                all_errors.extend(precision_errors)
            except Exception as e:
                log_error(f"Fsm_0_4_5: Ошибка проверки точности: {e}")

            if progress_callback:
                progress_callback(80)

        # 5. Проверка близких точек между объектами (cross-feature)
        if 'cross_feature_close_points' in check_types:
            log_info("Fsm_0_4_5: Проверка близких точек между объектами...")

            try:
                cross_feature_errors = self.cross_feature_checker.check(layer)

                errors_by_type['cross_feature_close_points'] = cross_feature_errors
                all_errors.extend(cross_feature_errors)
            except Exception as e:
                log_error(f"Fsm_0_4_5: Ошибка проверки cross-feature: {e}")

            if progress_callback:
                progress_callback(85)

        # 6. Проверка sliver-полигонов (Polsby-Popper)
        if 'slivers_polsby_popper' in check_types:
            log_info("Fsm_0_4_5: Проверка sliver-полигонов (Polsby-Popper)...")

            try:
                sliver_pp_errors = self.sliver_checker.check(layer)

                errors_by_type['sliver_polsby_popper'] = sliver_pp_errors
                all_errors.extend(sliver_pp_errors)
            except Exception as e:
                log_error(f"Fsm_0_4_5: Ошибка проверки slivers (Polsby-Popper): {e}")

            if progress_callback:
                progress_callback(90)

        # 7. Проверка sliver-полигонов (QGIS native thinness)
        if 'slivers_qgis_native' in check_types:
            log_info("Fsm_0_4_5: Проверка sliver-полигонов (QGIS native)...")

            try:
                sliver_native_errors = self.sliver_native_checker.check(layer)

                errors_by_type['sliver_qgis_native'] = sliver_native_errors
                all_errors.extend(sliver_native_errors)
            except Exception as e:
                log_error(f"Fsm_0_4_5: Ошибка проверки slivers (QGIS native): {e}")

            if progress_callback:
                progress_callback(95)

        return self._finalize_check(layer, all_errors, errors_by_type, 'polygon', progress_callback)

    def _check_line_layer(self,
                         layer: QgsVectorLayer,
                         check_types: Optional[List[str]] = None,
                         progress_callback=None) -> Dict[str, Any]:
        """Проверка линейного слоя"""

        # Определяем типы проверок по умолчанию для линий
        if check_types is None:
            check_types = ['line_self_intersections', 'line_overlaps', 'dangles']

        # Инициализация статистики
        self.statistics[layer.name()] = {
            'total_features': layer.featureCount(),
            'check_types': check_types,
            'errors_found': 0,
            'geometry_type': 'line'
        }

        # Отчет
        self.report.append(f"=== ПРОВЕРКА ТОПОЛОГИИ (ЛИНИИ): {layer.name()} ===")
        self.report.append(f"Объектов в слое: {layer.featureCount()}")
        self.report.append(f"Типы проверок: {', '.join(check_types)}")
        self.report.append("")

        if progress_callback:
            progress_callback(5)

        # Собираем все ошибки
        all_errors = []
        errors_by_type = {}

        # Выполняем проверку линий
        log_info("Fsm_0_4_5: Проверка линейной топологии...")

        self_ints, overlaps, dangles = self.line_checker.check(layer)

        if 'line_self_intersections' in check_types:
            errors_by_type['line_self_intersection'] = self_ints
            all_errors.extend(self_ints)

        if progress_callback:
            progress_callback(35)

        if 'line_overlaps' in check_types:
            errors_by_type['line_overlap'] = overlaps
            all_errors.extend(overlaps)

        if progress_callback:
            progress_callback(65)

        if 'dangles' in check_types:
            errors_by_type['dangle'] = dangles
            all_errors.extend(dangles)

        if progress_callback:
            progress_callback(85)

        return self._finalize_check(layer, all_errors, errors_by_type, 'line', progress_callback)

    def _check_point_layer(self,
                          layer: QgsVectorLayer,
                          check_types: Optional[List[str]] = None,
                          progress_callback=None) -> Dict[str, Any]:
        """Проверка точечного слоя"""

        # Определяем типы проверок по умолчанию для точек
        if check_types is None:
            check_types = ['duplicate_points', 'point_proximity']

        # Инициализация статистики
        self.statistics[layer.name()] = {
            'total_features': layer.featureCount(),
            'check_types': check_types,
            'errors_found': 0,
            'geometry_type': 'point'
        }

        # Отчет
        self.report.append(f"=== ПРОВЕРКА ТОПОЛОГИИ (ТОЧКИ): {layer.name()} ===")
        self.report.append(f"Объектов в слое: {layer.featureCount()}")
        self.report.append(f"Типы проверок: {', '.join(check_types)}")
        self.report.append("")

        if progress_callback:
            progress_callback(5)

        # Собираем все ошибки
        all_errors = []
        errors_by_type = {}

        # Выполняем проверку точек
        log_info("Fsm_0_4_5: Проверка точечной топологии...")

        duplicates, proximity = self.point_checker.check(layer)

        if 'duplicate_points' in check_types:
            errors_by_type['duplicate_point'] = duplicates
            all_errors.extend(duplicates)

        if progress_callback:
            progress_callback(50)

        if 'point_proximity' in check_types:
            errors_by_type['point_proximity'] = proximity
            all_errors.extend(proximity)

        if progress_callback:
            progress_callback(85)

        return self._finalize_check(layer, all_errors, errors_by_type, 'point', progress_callback)

    def _finalize_check(self,
                       layer: QgsVectorLayer,
                       all_errors: List[Dict],
                       errors_by_type: Dict[str, List[Dict]],
                       geometry_type: str,
                       progress_callback=None) -> Dict[str, Any]:
        """Завершение проверки: создание слоя ошибок и формирование результата"""

        # Создаем единый слой с ошибками
        final_error_layer = None
        total_errors = len(all_errors)

        if total_errors > 0:
            layer_prefix = self._extract_layer_prefix(layer.name())
            final_error_layer = self._create_error_layer(
                all_errors, layer, f"{self.PREFIX_ERRORS}_{layer_prefix}"
            )

        # Обновляем статистику
        self.statistics[layer.name()]['errors_found'] = total_errors

        # Формируем отчет
        self.report.append("\n=== РЕЗУЛЬТАТЫ ПРОВЕРКИ ===")
        if total_errors == 0:
            self.report.append("Топологических ошибок не обнаружено")
        else:
            self.report.append(f"Всего найдено ошибок: {total_errors}")
            self.report.append("\nПо типам:")
            for error_type, errors in errors_by_type.items():
                if errors:
                    type_name = self.ERROR_TYPES.get(error_type, error_type)
                    self.report.append(f"  - {type_name}: {len(errors)}")

        if progress_callback:
            progress_callback(100)

        # Сохраняем результат
        self.last_check_result = {
            'error_layer': final_error_layer,
            'error_count': total_errors,
            'errors_by_type': errors_by_type,
            'statistics': self.statistics[layer.name()],
            'original_layer': layer,
            'geometry_type': geometry_type
        }

        if total_errors == 0:
            log_info(f"Fsm_0_4_5: Проверка завершена. Найдено {total_errors} ошибок")
        else:
            log_warning(f"Fsm_0_4_5: Проверка завершена. Найдено {total_errors} ошибок")

        return self.last_check_result

    def _create_error_layer(self, errors: List[Dict],
                           original_layer: QgsVectorLayer,
                           layer_name: str) -> QgsVectorLayer:
        """
        Создание слоя с ошибками

        Args:
            errors: Список ошибок
            original_layer: Исходный слой
            layer_name: Имя создаваемого слоя

        Returns:
            Слой с ошибками
        """
        crs = original_layer.crs()

        # Создаем точечный слой (точки или центроиды)
        error_layer = QgsVectorLayer(
            f"Point?crs={crs.authid()}",
            layer_name,
            "memory"
        )

        # Добавляем атрибуты (на русском для пользователя)
        provider = error_layer.dataProvider()
        provider.addAttributes([
            QgsField("Тип_ошибки", QMetaType.Type.QString),
            QgsField("ID_объекта", QMetaType.Type.Int),
            QgsField("Описание", QMetaType.Type.QString),
            QgsField("Название_типа", QMetaType.Type.QString)
        ])
        error_layer.updateFields()

        # Добавляем объекты
        features = []
        for error in errors:
            feat = QgsFeature()

            geom = error['geometry']

            # Преобразуем в точку если нужно
            if geom.type() != QgsWkbTypes.PointGeometry:
                geom = geom.centroid()

            feat.setGeometry(geom)
            feat.setAttributes([
                error['type'],
                error.get('feature_id', -1),
                error.get('description', ''),
                self.ERROR_TYPES.get(error['type'], error['type'])
            ])
            features.append(feat)

        provider.addFeatures(features)
        error_layer.updateExtents()

        # ВАЖНО: Стиль НЕ применяем здесь - это может выполняться в background thread!
        # Стиль будет применён в main thread в F_0_4._on_async_layer_completed()

        # Пометка как временный (для внутренней логики плагина)
        error_layer.setCustomProperty("TopologyCheck", "temporary")
        # Пометка что стиль не применён
        error_layer.setCustomProperty("NeedsStyle", "true")
        # Пометка что memory слой не должен сохраняться в проекте
        # НЕ используем QgsMapLayer.Private - он скрывает слой из панели слоёв!
        error_layer.setCustomProperty("skipMemoryLayersCheck", "true")

        log_info(
            f"Fsm_0_4_5: Создан слой ошибок: {layer_name} ({len(features)} объектов)"
        )

        return error_layer

    def _apply_error_style(self, layer: QgsVectorLayer):
        """Применение стиля к слою ошибок (красные точки)"""
        from Daman_QGIS.managers import StyleManager

        style_manager = StyleManager()
        style_manager.create_simple_marker_style(
            layer,
            QColor(255, 0, 0, 200),  # Красный цвет с прозрачностью
            4.0  # Размер 4 мм
        )
        # ВАЖНО: triggerRepaint() не вызываем - может вызвать краш

    def _extract_layer_prefix(self, layer_name: str) -> str:
        """
        Извлекает префикс слоя (L_X_Y_Z или Le_X_Y_Z_A)

        Args:
            layer_name: Полное имя слоя

        Returns:
            Префикс слоя

        Examples:
            "L_1_1_3_Границы_работ_500_м" -> "L_1_1_3"
            "Le_1_1_3_1_Буфер" -> "Le_1_1_3_1"
        """
        parts = layer_name.split('_')

        # Определяем количество частей для префикса
        if parts[0] == 'L':
            # L_X_Y_Z = 4 части
            prefix_parts = parts[:4]
        elif parts[0] == 'Le':
            # Le_X_Y_Z_A = 5 частей
            prefix_parts = parts[:5]
        else:
            # Неизвестный формат, возвращаем исходное имя
            return layer_name

        return '_'.join(prefix_parts)

    def get_last_check_result(self) -> Optional[Dict]:
        """Получение результата последней проверки"""
        return self.last_check_result

    def get_report(self) -> str:
        """Получение текстового отчета"""
        return "\n".join(self.report)

    def clear_report(self):
        """Очистка отчета и статистики"""
        self.report = []
        self.statistics = {}

    def get_statistics(self) -> Dict[str, Any]:
        """Получение статистики проверок"""
        return self.statistics
