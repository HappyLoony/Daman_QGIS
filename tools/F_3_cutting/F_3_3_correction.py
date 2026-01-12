# -*- coding: utf-8 -*-
"""
F_3_3_Корректировка - Пересчёт атрибутов и точек после ручного редактирования нарезки

Выполняется после того как пользователь вручную скорректировал геометрию
слоёв Раздел (убрал чересполосицы, подтянул точки и т.д.).

Функция:
1. Проверяет наличие слоёв нарезки в проекте
2. Пересчитывает геометрию НГС на основе изменённых Разделов:
   - НГС = НГС.difference(Раздел_union)
   - Если НГС полностью покрыт Разделом → удаляется
3. Пересчитывает атрибуты для всех слоёв:
   - ID (1, 2, 3...)
   - Услов_КН, Услов_ЕЗ (глобальная нумерация по всем слоям)
   - Площадь_ОЗУ (по текущей геометрии)
   - Точки (номера характерных точек)
4. Пересоздаёт точечные слои "Т_"
5. Сохраняет изменения в GPKG
"""

from typing import Optional, Dict, List, Any, Tuple, TYPE_CHECKING

from qgis.PyQt.QtWidgets import QMessageBox
from qgis.core import (
    QgsProject, Qgis, QgsVectorLayer, QgsFeature,
    QgsGeometry, QgsField, QgsFields
)
from qgis.PyQt.QtCore import QMetaType

from Daman_QGIS.core.base_tool import BaseTool
from Daman_QGIS.managers import get_project_structure_manager
from Daman_QGIS.constants import (
    PLUGIN_NAME, MESSAGE_SUCCESS_DURATION, MESSAGE_INFO_DURATION,
    COORDINATE_PRECISION,
    # Полигональные слои нарезки
    LAYER_CUTTING_OKS_RAZDEL, LAYER_CUTTING_OKS_NGS,
    LAYER_CUTTING_PO_RAZDEL, LAYER_CUTTING_PO_NGS,
    LAYER_CUTTING_VO_RAZDEL, LAYER_CUTTING_VO_NGS,
    # Слои Без_Меж (без точек)
    LAYER_CUTTING_OKS_BEZ_MEZH,
    LAYER_CUTTING_PO_BEZ_MEZH,
    LAYER_CUTTING_VO_BEZ_MEZH,
    # Точечные слои
    LAYER_CUTTING_POINTS_OKS_RAZDEL, LAYER_CUTTING_POINTS_OKS_NGS,
    LAYER_CUTTING_POINTS_PO_RAZDEL, LAYER_CUTTING_POINTS_PO_NGS,
    LAYER_CUTTING_POINTS_VO_RAZDEL, LAYER_CUTTING_POINTS_VO_NGS,
)
from Daman_QGIS.utils import log_info, log_warning, log_error

# Импорт менеджеров
from Daman_QGIS.managers import (
    PointNumberingManager, StyleManager, LabelManager,
    WorkTypeAssignmentManager, LayerType, VRIAssignmentManager
)

# Импорт субмодулей F_3_1 для переиспользования
from .submodules.Fsm_3_1_2_attribute_mapper import Fsm_3_1_2_AttributeMapper
from .submodules.Fsm_3_1_6_point_layer_creator import Fsm_3_1_6_PointLayerCreator

if TYPE_CHECKING:
    from Daman_QGIS.managers import LayerManager


class F_3_3_Correction(BaseTool):
    """Инструмент корректировки нарезки после ручного редактирования"""

    # Пары слоёв Раздел ↔ НГС для пересчёта геометрии
    # Формат: (razdel_layer, razdel_points, ngs_layer, ngs_points, zpr_type)
    LAYER_PAIRS = [
        # ОКС
        (LAYER_CUTTING_OKS_RAZDEL, LAYER_CUTTING_POINTS_OKS_RAZDEL,
         LAYER_CUTTING_OKS_NGS, LAYER_CUTTING_POINTS_OKS_NGS, 'ОКС'),
        # ПО
        (LAYER_CUTTING_PO_RAZDEL, LAYER_CUTTING_POINTS_PO_RAZDEL,
         LAYER_CUTTING_PO_NGS, LAYER_CUTTING_POINTS_PO_NGS, 'ПО'),
        # ВО
        (LAYER_CUTTING_VO_RAZDEL, LAYER_CUTTING_POINTS_VO_RAZDEL,
         LAYER_CUTTING_VO_NGS, LAYER_CUTTING_POINTS_VO_NGS, 'ВО'),
    ]

    # Порядок обработки слоёв для пересчёта атрибутов (соответствует приоритету)
    # Формат: (polygon_layer, points_layer, zpr_type)
    # Для Без_Меж: points_layer = None (нет нумерации точек)
    LAYER_ORDER = [
        # ОКС
        (LAYER_CUTTING_OKS_RAZDEL, LAYER_CUTTING_POINTS_OKS_RAZDEL, 'ОКС'),
        (LAYER_CUTTING_OKS_NGS, LAYER_CUTTING_POINTS_OKS_NGS, 'ОКС'),
        (LAYER_CUTTING_OKS_BEZ_MEZH, None, 'ОКС'),  # Без_Меж - без точек!
        # ПО
        (LAYER_CUTTING_PO_RAZDEL, LAYER_CUTTING_POINTS_PO_RAZDEL, 'ПО'),
        (LAYER_CUTTING_PO_NGS, LAYER_CUTTING_POINTS_PO_NGS, 'ПО'),
        (LAYER_CUTTING_PO_BEZ_MEZH, None, 'ПО'),  # Без_Меж - без точек!
        # ВО
        (LAYER_CUTTING_VO_RAZDEL, LAYER_CUTTING_POINTS_VO_RAZDEL, 'ВО'),
        (LAYER_CUTTING_VO_NGS, LAYER_CUTTING_POINTS_VO_NGS, 'ВО'),
        (LAYER_CUTTING_VO_BEZ_MEZH, None, 'ВО'),  # Без_Меж - без точек!
    ]

    # Маппинг типа ЗПР на имя слоя ЗПР
    ZPR_TYPE_TO_LAYER = {
        'ОКС': 'L_2_4_1_ЗПР_ОКС',
        'ПО': 'L_2_4_2_ЗПР_ПО',
        'ВО': 'L_2_4_3_ЗПР_ВО',
    }

    def __init__(self, iface: Any) -> None:
        """Инициализация инструмента

        Args:
            iface: Интерфейс QGIS
        """
        super().__init__(iface)
        self.layer_manager: Optional['LayerManager'] = None
        self.plugin_dir: Optional[str] = None
        self._attribute_mapper: Optional[Fsm_3_1_2_AttributeMapper] = None
        self._point_layer_creator: Optional[Fsm_3_1_6_PointLayerCreator] = None
        self._work_type_manager: Optional[WorkTypeAssignmentManager] = None
        self._vri_manager: Optional[VRIAssignmentManager] = None

    def set_plugin_dir(self, plugin_dir: str) -> None:
        """Установка пути к папке плагина"""
        self.plugin_dir = plugin_dir

    def set_layer_manager(self, layer_manager: 'LayerManager') -> None:
        """Установка менеджера слоёв"""
        self.layer_manager = layer_manager

    @staticmethod
    def get_name() -> str:
        """Имя инструмента для cleanup"""
        return "F_3_3_Корректировка"

    def run(self) -> None:
        """Основной метод запуска инструмента (без диалога)"""
        log_info("F_3_3: Запуск корректировки")

        # Проверка открытого проекта
        if not self.check_project_opened():
            return

        # Автоматическая очистка слоев перед выполнением
        self.auto_cleanup_layers()

        # Выполняем корректировку
        self._execute()

    def _execute(self) -> None:
        """Основная логика корректировки"""
        log_info("F_3_3: Запуск корректировки нарезки")

        # 1. Инициализация субмодулей
        if not self.plugin_dir:
            log_error("F_3_3: Не установлен путь к плагину (plugin_dir)")
            return
        self._attribute_mapper = Fsm_3_1_2_AttributeMapper(self.plugin_dir)
        self._work_type_manager = WorkTypeAssignmentManager(self.plugin_dir)
        # VRIAssignmentManager для пересчёта План_ВРИ и Общая_земля
        # при изменении ЗПР или перемещении контуров в другую зону ЗПР
        self._vri_manager = VRIAssignmentManager(self.plugin_dir)

        # Получаем путь к GPKG для PointLayerCreator
        structure_manager = get_project_structure_manager()
        gpkg_path = structure_manager.get_gpkg_path(create=False)
        if not gpkg_path:
            log_error("F_3_3: Не найден путь к project.gpkg")
            return
        self._point_layer_creator = Fsm_3_1_6_PointLayerCreator(gpkg_path)

        # 2. Поиск существующих слоёв нарезки
        existing_layers = self._find_existing_layers()

        if not existing_layers:
            log_warning("F_3_3: Не найдено ни одного слоя нарезки")
            QMessageBox.warning(
                None,
                PLUGIN_NAME,
                "Не найдено слоёв нарезки.\n\n"
                "Сначала выполните нарезку через 'F_3_1_Нарезка ЗПР'."
            )
            return

        log_info(f"F_3_3: Найдено {len(existing_layers)} слоёв нарезки")

        # 3. НОВЫЙ ЭТАП: Пересчёт геометрии НГС на основе изменённых Разделов
        ngs_removed_count = self._recalculate_all_ngs(existing_layers, gpkg_path)
        log_info(f"F_3_3: Пересчёт НГС завершён, удалено объектов: {ngs_removed_count}")

        # Обновляем список слоёв после пересчёта НГС
        existing_layers = self._find_existing_layers()

        # 4. Сброс глобальных счётчиков КН/ЕЗ
        self._attribute_mapper.reset_kn_counters()
        log_info("F_3_3: Сброс глобальных счётчиков КН/ЕЗ")

        # 5. Обработка слоёв в порядке приоритета
        total_features = 0
        total_points = 0
        processed_layers = 0
        removed_layers = []

        for poly_layer_name, points_layer_name, zpr_type in self.LAYER_ORDER:
            if poly_layer_name not in existing_layers:
                continue

            poly_layer = existing_layers[poly_layer_name]

            # Проверка на пустой слой - удаляем его из проекта и GPKG
            if poly_layer.featureCount() == 0:
                log_warning(f"F_3_3: Слой {poly_layer_name} пуст, удаляем")
                self._remove_empty_layer(poly_layer, poly_layer_name, points_layer_name, gpkg_path)
                removed_layers.append(poly_layer_name)
                continue

            # Обработка слоя
            result = self._process_layer(
                poly_layer, poly_layer_name, points_layer_name, zpr_type
            )

            if result:
                total_features += result['features']
                total_points += result['points']
                processed_layers += 1

        # 6. Применение стилей и подписей ко всем обработанным слоям
        self._apply_styles_and_labels(existing_layers)

        # 7. Сортировка слоёв
        if self.layer_manager:
            self.layer_manager.sort_all_layers()
            log_info("F_3_3: Слои отсортированы по order_layers")

        # 8. Валидация минимальных площадей
        self._validate_min_areas()

        # 9. Финализация
        log_info(f"F_3_3: Корректировка завершена. "
                f"Обработано слоёв: {processed_layers}, "
                f"объектов: {total_features}, точек: {total_points}")

        if removed_layers:
            log_warning(f"F_3_3: Удалённые пустые слои: {', '.join(removed_layers)}")

        self.iface.messageBar().pushMessage(
            PLUGIN_NAME,
            f"Корректировка завершена. Обработано: {processed_layers} слоёв, "
            f"{total_features} объектов, {total_points} точек",
            level=Qgis.Success,
            duration=MESSAGE_SUCCESS_DURATION
        )

    def _find_existing_layers(self) -> Dict[str, QgsVectorLayer]:
        """Поиск существующих слоёв нарезки в проекте

        Returns:
            Dict: {layer_name: QgsVectorLayer}
        """
        result = {}
        project = QgsProject.instance()

        for poly_layer_name, _, _ in self.LAYER_ORDER:
            layers = project.mapLayersByName(poly_layer_name)
            if layers and isinstance(layers[0], QgsVectorLayer) and layers[0].isValid():
                result[poly_layer_name] = layers[0]
                log_info(f"F_3_3: Найден слой {poly_layer_name} "
                        f"({layers[0].featureCount()} объектов)")

        return result

    def _process_layer(
        self,
        layer: QgsVectorLayer,
        layer_name: str,
        points_layer_name: Optional[str],
        zpr_type: str
    ) -> Optional[Dict[str, int]]:
        """Обработка одного слоя нарезки

        Args:
            layer: Слой для обработки
            layer_name: Имя слоя
            points_layer_name: Имя точечного слоя (None для Без_Меж)
            zpr_type: Тип ЗПР (ОКС, ЛО, ВО)

        Returns:
            Dict: {'features': int, 'points': int} или None при ошибке
        """
        # Определяем, это слой Без_Меж (без нумерации точек)
        is_bez_mezh = points_layer_name is None

        log_info(f"F_3_3: Обработка слоя {layer_name}"
                f"{' (Без_Меж - без точек)' if is_bez_mezh else ''}")

        # Сброс счётчика ID для этого слоя
        if self._attribute_mapper:
            self._attribute_mapper.reset_id_counter(layer_name)

        # Получаем объекты отсортированные по ID
        features_data = self._collect_features_sorted_by_id(layer)

        if not features_data:
            log_warning(f"F_3_3: Нет объектов в слое {layer_name}")
            return None

        if is_bez_mezh:
            # СПЕЦИАЛЬНАЯ ОБРАБОТКА ДЛЯ БЕЗ_МЕЖ
            # Только пересчёт ID, НЕ пересчитываем Услов_КН/ЕЗ и План_*
            # Эти атрибуты уже установлены в F_3_2
            updated_features = self._recalculate_bez_mezh_attributes(
                features_data, layer_name
            )

            # Поле "Точки" = "" (пустое)
            for item in updated_features:
                item['attributes']['Точки'] = ""

            # Обновление слоя в GPKG (без точечного слоя)
            self._update_layer_in_gpkg(layer, updated_features)

            log_info(f"F_3_3: Слой Без_Меж {layer_name} обработан: "
                    f"{len(updated_features)} объектов (без точек)")

            return {
                'features': len(updated_features),
                'points': 0  # Нет точек для Без_Меж
            }

        # СТАНДАРТНАЯ ОБРАБОТКА ДЛЯ РАЗДЕЛ/НГС
        # Пересчёт атрибутов
        updated_features = self._recalculate_attributes(
            features_data, layer_name, zpr_type
        )

        # Пересчёт ВРИ (План_ВРИ, Общая_земля) по геометрическому пересечению с ЗПР
        # При корректировке пользователь мог изменить ЗПР или переместить контуры
        updated_features = self._reassign_vri(updated_features, zpr_type)

        # Присвоение Вид_Работ
        if self._work_type_manager:
            # Определяем тип слоя по имени
            if 'Раздел' in layer_name:
                layer_type = LayerType.RAZDEL
            elif 'НГС' in layer_name:
                layer_type = LayerType.NGS
            else:
                layer_type = LayerType.RAZDEL  # fallback

            updated_features = self._work_type_manager.assign_work_type_basic(
                updated_features, layer_type
            )

        # Очистка дублей вершин в геометриях
        # После ручного редактирования могут появиться дубли (пользователь двигает вершины)
        updated_features = self._remove_duplicate_vertices(updated_features)

        # Нумерация точек
        point_numbering = PointNumberingManager()
        # process_polygon_layer возвращает (features_data, points_data)
        features_with_points, points_data = point_numbering.process_polygon_layer(
            updated_features,
            precision=2  # PRECISION_DECIMALS
        )

        # Обновление поля "Точки" в атрибутах
        for i, item in enumerate(updated_features):
            if i < len(features_with_points):
                item['attributes']['Точки'] = features_with_points[i].get('point_numbers_str', '-')

        # Обновление слоя в GPKG
        self._update_layer_in_gpkg(layer, updated_features)

        # Пересоздание точечного слоя
        points_count = self._recreate_points_layer(
            points_data, points_layer_name, layer.crs()
        )

        log_info(f"F_3_3: Слой {layer_name} обработан: "
                f"{len(updated_features)} объектов, {points_count} точек")

        return {
            'features': len(updated_features),
            'points': points_count
        }

    def _recalculate_bez_mezh_attributes(
        self,
        features_data: List[Dict[str, Any]],
        layer_name: str
    ) -> List[Dict[str, Any]]:
        """Пересчёт атрибутов для слоёв Без_Меж

        Для Без_Меж пересчитывается ТОЛЬКО ID.
        Услов_КН, Услов_ЕЗ, План_*, Площадь_ОЗУ уже установлены в F_3_2
        и не должны меняться.

        Args:
            features_data: Исходные данные объектов
            layer_name: Имя слоя

        Returns:
            List[Dict]: Обновлённые данные (только ID обновлён)
        """
        if not self._attribute_mapper:
            return features_data

        for item in features_data:
            attrs = item['attributes']

            # Только новый ID
            attrs['ID'] = self._attribute_mapper.generate_id(layer_name)

            # contour_id для совместимости (хотя точки не создаются)
            item['contour_id'] = attrs['ID']

        return features_data

    def _collect_features_sorted_by_id(
        self,
        layer: QgsVectorLayer
    ) -> List[Dict[str, Any]]:
        """Сбор объектов из слоя, отсортированных по ID

        Args:
            layer: Исходный слой

        Returns:
            List[Dict]: Список {'geometry': QgsGeometry, 'attributes': dict, 'old_id': int}
        """
        features_data = []

        for feature in layer.getFeatures():
            geom = feature.geometry()
            if not geom or geom.isEmpty():
                continue

            # Собираем все атрибуты
            attrs = {}
            for field in layer.fields():
                attrs[field.name()] = feature[field.name()]

            old_id = attrs.get('ID', 0)

            features_data.append({
                'geometry': QgsGeometry(geom),  # Копия геометрии
                'attributes': attrs,
                'old_id': old_id if old_id else 0
            })

        # Сортировка по старому ID
        features_data.sort(key=lambda x: x['old_id'])

        return features_data

    def _recalculate_attributes(
        self,
        features_data: List[Dict[str, Any]],
        layer_name: str,
        zpr_type: str
    ) -> List[Dict[str, Any]]:
        """Пересчёт атрибутов для всех объектов

        Пересчитываются:
        - ID (новый порядковый номер)
        - Услов_КН, Услов_ЕЗ (глобальная нумерация)
        - Площадь_ОЗУ (по текущей геометрии)

        Args:
            features_data: Исходные данные объектов
            layer_name: Имя слоя
            zpr_type: Тип ЗПР

        Returns:
            List[Dict]: Обновлённые данные
        """
        if not self._attribute_mapper:
            return features_data

        for item in features_data:
            attrs = item['attributes']
            geom = item['geometry']

            # Новый ID
            attrs['ID'] = self._attribute_mapper.generate_id(layer_name)

            # contour_id для PointNumberingManager (ID_Контура в точечном слое)
            item['contour_id'] = attrs['ID']

            # Услов_КН - используем базовый КН из атрибутов
            base_kn = attrs.get('КН')
            attrs['Услов_КН'] = self._attribute_mapper.generate_conditional_kn(base_kn)

            # Услов_ЕЗ
            base_ez = attrs.get('ЕЗ')
            attrs['Услов_ЕЗ'] = self._attribute_mapper.generate_conditional_ez(base_ez)

            # Площадь_ОЗУ - пересчёт по текущей геометрии
            attrs['Площадь_ОЗУ'] = self._attribute_mapper.calculate_area(geom)

        return features_data

    def _reassign_vri(
        self,
        features_data: List[Dict[str, Any]],
        zpr_type: str
    ) -> List[Dict[str, Any]]:
        """Пересчёт План_ВРИ и Общая_земля по геометрическому пересечению с ЗПР

        При корректировке пользователь мог:
        - Изменить границы или атрибуты ЗПР
        - Переместить контуры нарезки в другую зону ЗПР

        Args:
            features_data: Список данных объектов с геометрией
            zpr_type: Тип ЗПР (ОКС, ЛО, ВО)

        Returns:
            List[Dict]: Данные с обновлёнными План_ВРИ и Общая_земля
        """
        if not self._vri_manager:
            log_warning("F_3_3: VRIAssignmentManager не инициализирован")
            return features_data

        # Получаем слой ЗПР по типу
        zpr_layer_name = self.ZPR_TYPE_TO_LAYER.get(zpr_type)
        if not zpr_layer_name:
            log_warning(f"F_3_3: Неизвестный тип ЗПР: {zpr_type}")
            return features_data

        project = QgsProject.instance()
        layers = project.mapLayersByName(zpr_layer_name)
        if not layers or not layers[0].isValid():
            log_warning(f"F_3_3: Слой ЗПР {zpr_layer_name} не найден, ВРИ не пересчитывается")
            return features_data

        zpr_layer = layers[0]
        log_info(f"F_3_3: Пересчёт ВРИ по слою {zpr_layer_name}")

        # Вызываем reassign_vri_by_geometry из M_21
        updated_features = self._vri_manager.reassign_vri_by_geometry(
            features_data, zpr_layer
        )

        return updated_features

    def _remove_duplicate_vertices(
        self,
        features_data: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Удаление дублей вершин из геометрий

        После ручного редактирования пользователь может создать дубли вершин
        (например, переместив вершину на координаты соседней). Эта функция
        удаляет такие дубли с допуском COORDINATE_PRECISION (1 см).

        Args:
            features_data: Список данных объектов

        Returns:
            List[Dict]: Обновлённые данные с очищенными геометриями
        """
        removed_count = 0

        for item in features_data:
            geom = item.get('geometry')
            if not geom or geom.isEmpty():
                continue

            # Используем QgsGeometry.removeDuplicateNodes()
            # tolerance - расстояние в единицах слоя (метры для МСК)
            # useZValue=False - не учитываем Z координаты
            original_vertex_count = geom.constGet().nCoordinates() if geom.constGet() else 0

            # removeDuplicateNodes модифицирует геометрию in-place и возвращает True если были изменения
            if geom.removeDuplicateNodes(epsilon=COORDINATE_PRECISION, useZValues=False):
                new_vertex_count = geom.constGet().nCoordinates() if geom.constGet() else 0
                removed_count += (original_vertex_count - new_vertex_count)

        if removed_count > 0:
            log_info(f"F_3_3: Удалено {removed_count} дублей вершин")

        return features_data

    def _update_layer_in_gpkg(
        self,
        layer: QgsVectorLayer,
        features_data: List[Dict[str, Any]]
    ) -> bool:
        """Обновление слоя в GeoPackage

        Args:
            layer: Слой для обновления
            features_data: Новые данные объектов

        Returns:
            bool: Успех операции
        """
        try:
            # Начинаем редактирование
            if not layer.isEditable():
                layer.startEditing()

            # Удаляем все существующие объекты
            all_ids = [f.id() for f in layer.getFeatures()]
            layer.deleteFeatures(all_ids)

            # Добавляем объекты с обновлёнными атрибутами
            for item in features_data:
                feature = QgsFeature(layer.fields())
                feature.setGeometry(item['geometry'])

                for field_name, value in item['attributes'].items():
                    idx = layer.fields().indexFromName(field_name)
                    if idx >= 0:
                        feature.setAttribute(idx, value)

                layer.addFeature(feature)

            # Сохраняем изменения
            layer.commitChanges()
            log_info(f"F_3_3: Слой {layer.name()} обновлён в GPKG")
            return True

        except Exception as e:
            log_error(f"F_3_3: Ошибка обновления слоя {layer.name()}: {e}")
            if layer.isEditable():
                layer.rollBack()
            return False

    def _recreate_points_layer(
        self,
        points_data: List[Dict[str, Any]],
        points_layer_name: str,
        crs: Any
    ) -> int:
        """Пересоздание точечного слоя

        Args:
            points_data: Данные точек от PointNumberingManager
            points_layer_name: Имя точечного слоя
            crs: Система координат

        Returns:
            int: Количество созданных точек
        """
        if not self._point_layer_creator or not points_data:
            return 0

        # Удаляем старый слой если есть
        project = QgsProject.instance()
        old_layers = project.mapLayersByName(points_layer_name)
        for old_layer in old_layers:
            project.removeMapLayer(old_layer.id())

        # Создаём новый слой
        # Сигнатура: create_point_layer(layer_name, crs, points_data)
        points_layer = self._point_layer_creator.create_point_layer(
            points_layer_name,
            crs,
            points_data
        )

        if points_layer is not None and points_layer.isValid() and self.layer_manager:
            self.layer_manager.add_layer(
                points_layer,
                make_readonly=False,
                auto_number=False,
                check_precision=False
            )
            return points_layer.featureCount()

        return 0

    def _apply_styles_and_labels(
        self,
        existing_layers: Dict[str, QgsVectorLayer]
    ) -> None:
        """Применение стилей и подписей ко всем слоям нарезки

        Args:
            existing_layers: Словарь существующих слоёв {name: layer}
        """
        style_manager = StyleManager()
        label_manager = LabelManager()

        # Собираем все слои (полигональные + точечные)
        project = QgsProject.instance()
        all_layer_names = []

        for poly_name, points_name, _ in self.LAYER_ORDER:
            all_layer_names.append(poly_name)
            all_layer_names.append(points_name)

        for layer_name in all_layer_names:
            layers = project.mapLayersByName(layer_name)
            if not layers:
                continue

            layer = layers[0]
            if not layer.isValid():
                continue

            # Применяем стиль
            style_manager.apply_qgis_style(layer, layer_name)

            # Применяем подписи
            label_manager.apply_labels(layer, layer_name)

            # Обновляем отображение
            layer.triggerRepaint()

        log_info("F_3_3: Стили и подписи применены ко всем слоям")

    def _recalculate_all_ngs(
        self,
        existing_layers: Dict[str, QgsVectorLayer],
        gpkg_path: str
    ) -> int:
        """Пересчёт геометрии НГС на основе изменённых Разделов

        Для каждой пары (Раздел, НГС):
        1. Объединяем все объекты Раздел в один MultiPolygon
        2. Для каждого объекта НГС вычисляем difference с объединённым Разделом
        3. Если результат пустой → удаляем объект НГС
        4. Если результат не пустой → обновляем геометрию НГС

        Args:
            existing_layers: Словарь существующих слоёв {name: layer}
            gpkg_path: Путь к GeoPackage

        Returns:
            int: Количество удалённых объектов НГС
        """
        total_removed = 0

        for razdel_name, _, ngs_name, ngs_points_name, zpr_type in self.LAYER_PAIRS:
            # Проверяем наличие обоих слоёв
            if razdel_name not in existing_layers:
                continue
            if ngs_name not in existing_layers:
                continue

            razdel_layer = existing_layers[razdel_name]
            ngs_layer = existing_layers[ngs_name]

            if razdel_layer.featureCount() == 0:
                log_info(f"F_3_3: Слой Раздел {razdel_name} пуст, пропускаем пересчёт НГС")
                continue

            if ngs_layer.featureCount() == 0:
                log_info(f"F_3_3: Слой НГС {ngs_name} уже пуст")
                continue

            # Пересчитываем НГС для этой пары
            removed = self._recalculate_ngs_for_pair(
                razdel_layer, ngs_layer, ngs_name, zpr_type
            )
            total_removed += removed

        return total_removed

    def _recalculate_ngs_for_pair(
        self,
        razdel_layer: QgsVectorLayer,
        ngs_layer: QgsVectorLayer,
        ngs_name: str,
        zpr_type: str
    ) -> int:
        """Пересчёт геометрии НГС для одной пары Раздел-НГС

        Args:
            razdel_layer: Слой Раздел
            ngs_layer: Слой НГС
            ngs_name: Имя слоя НГС (для логирования)
            zpr_type: Тип ЗПР (ОКС, ЛО, ВО)

        Returns:
            int: Количество удалённых объектов НГС
        """
        log_info(f"F_3_3: Пересчёт НГС {ngs_name} на основе Раздела ({zpr_type})")

        # 1. Собираем все геометрии Раздел в список и объединяем через unaryUnion
        # unaryUnion значительно быстрее итеративного combine() для множества полигонов
        razdel_geometries = []
        for feature in razdel_layer.getFeatures():
            geom = feature.geometry()
            if geom and not geom.isEmpty():
                razdel_geometries.append(QgsGeometry(geom))

        if not razdel_geometries:
            log_warning(f"F_3_3: Нет геометрий Раздела для {zpr_type}")
            return 0

        # Используем статический метод unaryUnion для оптимального объединения
        razdel_union = QgsGeometry.unaryUnion(razdel_geometries)
        # Округляем координаты до стандартной точности после объединения
        razdel_union = razdel_union.snappedToGrid(COORDINATE_PRECISION, COORDINATE_PRECISION)

        if razdel_union.isEmpty():
            log_warning(f"F_3_3: Объединение Разделов пустое для {zpr_type}")
            return 0

        log_info(f"F_3_3: Объединено {len(razdel_geometries)} объектов Раздел через unaryUnion")

        # 2. Обрабатываем каждый объект НГС
        # Логика: НГС полностью покрыт если difference(Раздел_union) пуст
        # Один НГС может быть покрыт несколькими Разделами
        features_to_delete = []
        features_to_update = []  # (fid, new_geometry)

        for feature in ngs_layer.getFeatures():
            ngs_geom = feature.geometry()
            if not ngs_geom or ngs_geom.isEmpty():
                features_to_delete.append(feature.id())
                continue

            # Вычисляем разницу: НГС - Раздел_union
            new_geom = ngs_geom.difference(razdel_union)
            # Округляем координаты после difference для избежания микро-погрешностей
            new_geom = new_geom.snappedToGrid(COORDINATE_PRECISION, COORDINATE_PRECISION)

            if new_geom.isEmpty():
                # НГС полностью покрыт объединением Разделов → удаляем
                features_to_delete.append(feature.id())
                log_info(f"F_3_3: Объект НГС ID={feature.id()} полностью покрыт Разделами, удаляем")
            else:
                # НГС частично остался → обновляем геометрию
                features_to_update.append((feature.id(), new_geom))
                log_info(f"F_3_3: Объект НГС ID={feature.id()} обновлён, "
                        f"новая площадь: {new_geom.area():.2f} кв.м")

        # 3. Применяем изменения к слою НГС
        if features_to_delete or features_to_update:
            if not ngs_layer.isEditable():
                ngs_layer.startEditing()

            # Удаляем объекты
            if features_to_delete:
                ngs_layer.deleteFeatures(features_to_delete)
                log_info(f"F_3_3: Удалено {len(features_to_delete)} объектов НГС из {ngs_name}")

            # Обновляем геометрию
            for fid, new_geom in features_to_update:
                ngs_layer.changeGeometry(fid, new_geom)

            ngs_layer.commitChanges()

        return len(features_to_delete)

    def _extract_polygon_points(self, geom: QgsGeometry) -> List[Any]:
        """Извлечение всех точек из полигональной геометрии

        Обрабатывает как простые полигоны, так и мультиполигоны.

        Args:
            geom: Геометрия полигона

        Returns:
            List[QgsPointXY]: Список всех точек полигона
        """
        from qgis.core import QgsPointXY

        points = []

        if geom.isMultipart():
            polygons = geom.asMultiPolygon()
        else:
            polygons = [geom.asPolygon()]

        for polygon in polygons:
            for ring in polygon:
                for point in ring:
                    points.append(QgsPointXY(point))

        return points

    def _validate_min_areas(self) -> None:
        """Валидация минимальных площадей по ВРИ для всех типов ЗПР

        Вызывает M_27_MinAreaValidator для проверки контуров нарезки.
        """
        try:
            from Daman_QGIS.managers import MinAreaValidator

            validator = MinAreaValidator(self.plugin_dir)

            # Проверяем все типы ЗПР которые есть в LAYER_ORDER
            zpr_types_checked = set()
            for _, _, zpr_type in self.LAYER_ORDER:
                if zpr_type not in zpr_types_checked:
                    zpr_types_checked.add(zpr_type)
                    result = validator.validate_cutting_results(zpr_type, show_dialog=True)

                    if result.get('skipped_no_field'):
                        log_info(f"F_3_3: Валидация {zpr_type} пропущена (нет поля MIN_AREA_VRI)")
                    elif result.get('success'):
                        log_info(f"F_3_3: Валидация {zpr_type} успешна")
                    else:
                        log_warning(
                            f"F_3_3: Валидация {zpr_type} - найдено {result.get('problem_count', 0)} "
                            f"контуров с недостаточной площадью"
                        )
        except Exception as e:
            log_error(f"F_3_3: Ошибка валидации минимальных площадей: {e}")

    def _remove_empty_layer(
        self,
        poly_layer: QgsVectorLayer,
        poly_layer_name: str,
        points_layer_name: Optional[str],
        gpkg_path: str
    ) -> None:
        """Удаление пустого слоя из проекта и GeoPackage

        Args:
            poly_layer: Пустой полигональный слой
            poly_layer_name: Имя полигонального слоя
            points_layer_name: Имя соответствующего точечного слоя (None для Без_Меж)
            gpkg_path: Путь к GeoPackage
        """
        project = QgsProject.instance()

        # 1. Удаляем полигональный слой из проекта
        project.removeMapLayer(poly_layer.id())
        log_info(f"F_3_3: Слой {poly_layer_name} удалён из проекта")

        # 2. Удаляем соответствующий точечный слой если есть (не для Без_Меж)
        if points_layer_name:
            points_layers = project.mapLayersByName(points_layer_name)
            for points_layer in points_layers:
                project.removeMapLayer(points_layer.id())
                log_info(f"F_3_3: Точечный слой {points_layer_name} удалён из проекта")

        # 3. Удаляем слои из GeoPackage
        try:
            from osgeo import ogr
            ds = ogr.Open(gpkg_path, 1)  # 1 = update mode
            if ds:
                # Удаляем полигональный слой (ищем по имени)
                for i in range(ds.GetLayerCount()):
                    lyr = ds.GetLayerByIndex(i)
                    if lyr and lyr.GetName() == poly_layer_name:
                        ds.DeleteLayer(i)
                        log_info(f"F_3_3: Слой {poly_layer_name} удалён из GPKG")
                        break

                # Удаляем точечный слой только если указан (не для Без_Меж)
                if points_layer_name:
                    for i in range(ds.GetLayerCount()):
                        lyr = ds.GetLayerByIndex(i)
                        if lyr and lyr.GetName() == points_layer_name:
                            ds.DeleteLayer(i)
                            log_info(f"F_3_3: Слой {points_layer_name} удалён из GPKG")
                            break

                ds = None  # Закрываем соединение
        except Exception as e:
            log_warning(f"F_3_3: Не удалось удалить слои из GPKG: {e}")
