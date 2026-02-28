# -*- coding: utf-8 -*-
"""
M_35_ZprGpmtManager - Формирование ГПМТ из слоёв ЗПР

ГПМТ (Граница проекта межевания территории) - единый MultiPolygon,
объединяющий все слои ЗПР в проекте.

Слои-источники:
- L_2_4_* - стандартные ЗПР (ОКС, ПО, ВО)
- L_2_5_* - рекреационные ЗПР (РЕК_АД, СЕТИ_ПО, СЕТИ_ВО, НЭ)

Результат:
- L_2_6_1_ГПМТ - 1 объект MultiPolygon с атрибутом area_sqm
- L_2_6_3_Т_ГПМТ - точечный слой с нумерацией вершин ГПМТ

Логика:
- При каждом импорте ЗПР вызывается rebuild_gpmt()
- Удаляется старый ГПМТ и точечный слой нумерации
- Собираются ВСЕ геометрии из ВСЕХ слоёв ЗПР в проекте
- Объединяются через unaryUnion в один MultiPolygon
- Площадь вычисляется от объединённой геометрии (учитывает перекрытия)
- Создаётся точечный слой с нумерацией всех вершин (M_20)
"""

import os
from typing import List, Optional, Dict, Any

from qgis.PyQt.QtCore import QMetaType
from qgis.core import (
    Qgis, QgsProject, QgsVectorLayer, QgsFeature, QgsGeometry,
    QgsField, QgsWkbTypes, QgsVectorFileWriter,
    QgsMemoryProviderUtils, QgsFields, QgsPointXY
)

from Daman_QGIS.utils import log_info, log_warning, log_error, log_success
from Daman_QGIS.constants import PRECISION_DECIMALS, COORDINATE_PRECISION

__all__ = ['ZprGpmtManager']


class ZprGpmtManager:
    """
    Менеджер формирования ГПМТ из слоёв ЗПР.

    ГПМТ всегда содержит 1 объект MultiPolygon - объединённую границу
    всех ЗПР в проекте. Пересоздаётся при каждом импорте ЗПР.
    """

    # Префиксы слоёв ЗПР (источники для ГПМТ)
    ZPR_PREFIXES = ['L_2_4_', 'L_2_5_']

    # Имя результирующего слоя ГПМТ
    GPMT_LAYER_NAME = 'L_2_6_1_ГПМТ'

    # Имя точечного слоя нумерации ГПМТ
    GPMT_POINTS_LAYER_NAME = 'L_2_6_3_Т_ГПМТ'

    def __init__(self, iface, layer_manager=None):
        """
        Инициализация менеджера.

        Args:
            iface: Интерфейс QGIS
            layer_manager: Менеджер слоёв (опционально)
        """
        self.iface = iface
        self.layer_manager = layer_manager

    def get_zpr_layers(self) -> List[QgsVectorLayer]:
        """
        Получить все слои ЗПР в проекте.

        Returns:
            Список валидных слоёв ЗПР с объектами
        """
        zpr_layers = []
        project = QgsProject.instance()

        for layer_id, layer in project.mapLayers().items():
            if not isinstance(layer, QgsVectorLayer) or not layer.isValid():
                continue

            layer_name = layer.name()

            for prefix in self.ZPR_PREFIXES:
                if layer_name.startswith(prefix):
                    if layer.featureCount() > 0:
                        zpr_layers.append(layer)
                        log_info(f"M_35: Найден слой ЗПР: {layer_name} ({layer.featureCount()} объектов)")
                    break

        return zpr_layers

    def get_gpmt_layer(self) -> Optional[QgsVectorLayer]:
        """Получить текущий слой ГПМТ или None."""
        project = QgsProject.instance()

        for layer_id, layer in project.mapLayers().items():
            if isinstance(layer, QgsVectorLayer) and layer.name() == self.GPMT_LAYER_NAME:
                return layer

        return None

    def get_gpmt_points_layer(self) -> Optional[QgsVectorLayer]:
        """Получить текущий точечный слой нумерации ГПМТ или None."""
        project = QgsProject.instance()

        for layer_id, layer in project.mapLayers().items():
            if isinstance(layer, QgsVectorLayer) and layer.name() == self.GPMT_POINTS_LAYER_NAME:
                return layer

        return None

    def clear_gpmt(self) -> None:
        """Удалить существующий слой ГПМТ и точечный слой нумерации."""
        gpmt_layer = self.get_gpmt_layer()
        if gpmt_layer:
            log_info(f"M_35: Удаление существующего слоя {self.GPMT_LAYER_NAME}")
            QgsProject.instance().removeMapLayer(gpmt_layer.id())

        points_layer = self.get_gpmt_points_layer()
        if points_layer:
            log_info(f"M_35: Удаление существующего слоя {self.GPMT_POINTS_LAYER_NAME}")
            QgsProject.instance().removeMapLayer(points_layer.id())

    def rebuild_gpmt(self) -> Dict[str, Any]:
        """
        Пересоздать ГПМТ из всех текущих слоёв ЗПР.

        Процесс:
        1. Удаляет существующий ГПМТ и точечный слой нумерации
        2. Находит все слои ЗПР (L_2_4_*, L_2_5_*) в проекте
        3. Собирает все геометрии и объединяет через unaryUnion
        4. Создаёт 1 объект MultiPolygon с area_sqm
        5. Сохраняет в GeoPackage и добавляет в проект
        6. Создаёт точечный слой с нумерацией вершин (M_20)

        Returns:
            Dict с результатом:
            - success: bool
            - layer: QgsVectorLayer или None
            - points_layer: QgsVectorLayer или None (точечный слой)
            - area_sqm: int (площадь объединённой геометрии)
            - zpr_count: int (количество слоёв ЗПР)
            - points_count: int (количество точек нумерации)
            - error: str (если ошибка)
        """
        result = {
            'success': False,
            'layer': None,
            'points_layer': None,
            'area_sqm': 0,
            'zpr_count': 0,
            'points_count': 0,
            'error': None
        }

        try:
            # 1. Удаляем существующий ГПМТ и точечный слой
            self.clear_gpmt()

            # 2. Находим все слои ЗПР
            zpr_layers = self.get_zpr_layers()
            result['zpr_count'] = len(zpr_layers)

            if not zpr_layers:
                result['error'] = "Не найдено слоёв ЗПР для объединения"
                log_warning(f"M_35: {result['error']}")
                return result

            log_info(f"M_35: Формирование ГПМТ из {len(zpr_layers)} слоёв ЗПР")

            # 3. Собираем все геометрии и объединяем
            united_geometry, crs = self._collect_and_unite_geometries(zpr_layers)

            if not united_geometry or united_geometry.isEmpty():
                result['error'] = "Не удалось объединить геометрии ЗПР"
                log_error(f"M_35: {result['error']}")
                return result

            # Вычисляем площадь объединённой геометрии
            area_sqm = int(round(united_geometry.area()))
            result['area_sqm'] = area_sqm

            log_info(f"M_35: Объединённая геометрия: площадь {area_sqm} кв.м")

            # 4. Создаём слой с 1 объектом
            gpmt_layer = self._create_gpmt_layer(united_geometry, area_sqm, crs)

            if not gpmt_layer:
                result['error'] = "Не удалось создать слой ГПМТ"
                return result

            # 5. Сохраняем в GeoPackage
            saved_layer = self._save_to_gpkg(gpmt_layer, self.GPMT_LAYER_NAME)

            if not saved_layer:
                result['error'] = "Не удалось сохранить ГПМТ в GeoPackage"
                return result

            # 6. Добавляем в проект
            QgsProject.instance().addMapLayer(saved_layer)
            log_info(f"M_35: Слой {self.GPMT_LAYER_NAME} добавлен в проект")

            # 7. Применяем стиль
            self._apply_style(saved_layer)

            # 8. Применяем видимость из Base_layers.json
            self._apply_layer_visibility(saved_layer)

            result['success'] = True
            result['layer'] = saved_layer

            # 9. Создаём точечный слой нумерации
            points_result = self._create_gpmt_points_layer(united_geometry, crs)
            if points_result['success']:
                result['points_layer'] = points_result['layer']
                result['points_count'] = points_result['points_count']
                log_info(f"M_35: Создан слой нумерации {self.GPMT_POINTS_LAYER_NAME} "
                        f"({result['points_count']} точек)")

            log_success(f"M_35: ГПМТ создан. Площадь: {area_sqm} кв.м "
                       f"(из {len(zpr_layers)} слоёв ЗПР, {result['points_count']} точек)")

        except Exception as e:
            result['error'] = str(e)
            log_error(f"M_35: Ошибка при создании ГПМТ: {e}")

        return result

    def is_zpr_layer(self, layer_name: str) -> bool:
        """Проверить, является ли слой слоем ЗПР."""
        for prefix in self.ZPR_PREFIXES:
            if layer_name.startswith(prefix):
                return True
        return False

    def _collect_and_unite_geometries(self, layers: List[QgsVectorLayer]):
        """
        Собрать все геометрии из слоёв и объединить в один MultiPolygon.

        Args:
            layers: Список слоёв ЗПР

        Returns:
            Tuple (объединённая геометрия, CRS) или (None, None)
        """
        all_geometries = []
        crs = layers[0].crs() if layers else None

        for layer in layers:
            for feature in layer.getFeatures():
                geom = feature.geometry()
                if geom and not geom.isEmpty():
                    all_geometries.append(geom)

        if not all_geometries:
            log_warning("M_35: Нет геометрий для объединения")
            return None, None

        log_info(f"M_35: Объединение {len(all_geometries)} геометрий")

        # Объединяем все геометрии в одну
        united = QgsGeometry.unaryUnion(all_geometries)

        if not united or united.isEmpty():
            log_error("M_35: unaryUnion вернул пустую геометрию")
            return None, None

        # Преобразуем в MultiPolygon если нужно
        if united.type() == Qgis.GeometryType.Polygon:
            if QgsWkbTypes.isSingleType(united.wkbType()):
                united = QgsGeometry.fromMultiPolygonXY([united.asPolygon()])

        return united, crs

    def _create_gpmt_layer(
        self,
        geometry: QgsGeometry,
        area_sqm: int,
        crs
    ) -> Optional[QgsVectorLayer]:
        """
        Создать слой ГПМТ с одним объектом.

        Args:
            geometry: Объединённая геометрия (MultiPolygon)
            area_sqm: Площадь в кв.м
            crs: Система координат

        Returns:
            Слой ГПМТ или None
        """
        # Создаём поля
        fields = QgsFields()
        fields.append(QgsField("area_sqm", QMetaType.Type.Int))
        fields.append(QgsField("area_ga", QMetaType.Type.QString, len=20))

        # Вычисляем площадь в гектарах (формат "0,0000")
        area_ga = area_sqm / 10000.0
        area_ga_str = f"{area_ga:.4f}".replace('.', ',')

        # Создаём слой
        layer = QgsMemoryProviderUtils.createMemoryLayer(
            self.GPMT_LAYER_NAME,
            fields,
            Qgis.WkbType.MultiPolygon,
            crs
        )

        if not layer or not layer.isValid():
            log_error("M_35: Не удалось создать memory layer для ГПМТ")
            return None

        # Добавляем единственный объект
        layer.startEditing()

        feature = QgsFeature()
        feature.setFields(fields)
        feature.initAttributes(fields.count())
        feature.setGeometry(geometry)
        feature.setAttribute(0, area_sqm)
        feature.setAttribute(1, area_ga_str)

        layer.addFeature(feature)
        layer.commitChanges()

        return layer

    def _save_to_gpkg(
        self,
        layer: QgsVectorLayer,
        layer_name: str
    ) -> Optional[QgsVectorLayer]:
        """
        Сохранить слой в GeoPackage проекта.

        Args:
            layer: Слой для сохранения
            layer_name: Имя слоя в GeoPackage

        Returns:
            Слой из GeoPackage или None
        """
        from Daman_QGIS.managers import registry

        project = QgsProject.instance()
        project_path = project.homePath()

        structure_manager = registry.get('M_19')
        structure_manager.project_root = project_path
        gpkg_path = structure_manager.get_gpkg_path(create=False)

        if not gpkg_path or not os.path.exists(gpkg_path):
            log_error("M_35: GeoPackage не найден")
            return None

        # Сохраняем
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GPKG"
        options.layerName = layer_name
        options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer

        error = QgsVectorFileWriter.writeAsVectorFormatV3(
            layer,
            gpkg_path,
            project.transformContext(),
            options
        )

        if error[0] != QgsVectorFileWriter.NoError:
            log_error(f"M_35: Ошибка сохранения в GeoPackage: {error[1]}")
            return None

        log_info(f"M_35: Слой сохранён в GeoPackage: {layer_name}")

        # Загружаем из GeoPackage
        gpkg_layer = QgsVectorLayer(
            f"{gpkg_path}|layername={layer_name}",
            layer_name,
            "ogr"
        )

        if not gpkg_layer.isValid():
            log_error(f"M_35: Не удалось загрузить слой {layer_name} из GeoPackage")
            return None

        return gpkg_layer

    def _apply_style(self, layer: QgsVectorLayer) -> None:
        """Применить стиль к слою из Base_layers.json."""
        try:
            from Daman_QGIS.managers import StyleManager

            style_manager = StyleManager()
            style_manager.apply_qgis_style(layer, layer.name())

            log_info(f"M_35: Применён стиль к слою {layer.name()}")
        except Exception as e:
            log_warning(f"M_35: Не удалось применить стиль: {e}")

    def _apply_layer_visibility(self, layer: QgsVectorLayer) -> None:
        """
        Применяет видимость слоя на основе поля 'hidden' из Base_layers.json.

        Args:
            layer: Слой QGIS
        """
        from Daman_QGIS.managers import get_reference_managers

        layer_name = layer.name()
        ref_managers = get_reference_managers()

        # Получаем информацию о слое из базы
        layer_info = ref_managers.layer.get_layer_by_full_name(layer_name)

        if not layer_info:
            return

        hidden = layer_info.get('hidden', 0)

        # hidden == 1 означает скрытый слой
        if hidden == 1 or hidden == "1":
            root = QgsProject.instance().layerTreeRoot()
            layer_node = root.findLayer(layer.id())
            if layer_node:
                layer_node.setItemVisibilityChecked(False)
                log_info(f"M_35: Слой {layer_name} скрыт (hidden=1)")

    def _create_gpmt_points_layer(
        self,
        geometry: QgsGeometry,
        crs
    ) -> Dict[str, Any]:
        """
        Создать точечный слой с нумерацией вершин ГПМТ.

        Использует PointNumberingManager (M_20) для:
        - Сортировки контуров от СЗ к ЮВ
        - Приведения к обходу по часовой стрелке
        - Уникальной нумерации точек

        Args:
            geometry: Геометрия ГПМТ (MultiPolygon)
            crs: Система координат

        Returns:
            Dict с результатом:
            - success: bool
            - layer: QgsVectorLayer или None
            - points_count: int
            - error: str (если ошибка)
        """
        from Daman_QGIS.managers import PointNumberingManager

        result = {
            'success': False,
            'layer': None,
            'points_count': 0,
            'error': None
        }

        try:
            # Подготавливаем данные для M_20
            # ГПМТ - это всегда 1 объект (MultiPolygon), но может иметь
            # несколько частей (внешних контуров) и внутренние контуры (дырки)
            features_data = [{
                'geometry': geometry,
                'contour_id': 1,  # Единственный ГПМТ
                'attributes': {
                    'Услов_КН': 'ГПМТ',
                    'КН': ''
                }
            }]

            # Нумеруем точки через M_20
            manager = PointNumberingManager()
            processed_data, points_data = manager.process_polygon_layer(
                features_data,
                precision=PRECISION_DECIMALS,
                auto_reset=True,
                sort_northwest=True
            )

            if not points_data:
                result['error'] = "Нет точек для нумерации"
                log_warning(f"M_35: {result['error']}")
                return result

            result['points_count'] = len(points_data)

            # Создаём точечный слой
            points_layer = self._create_points_memory_layer(points_data, crs)

            if not points_layer:
                result['error'] = "Не удалось создать memory layer для точек"
                return result

            # Сохраняем в GeoPackage
            saved_layer = self._save_to_gpkg(points_layer, self.GPMT_POINTS_LAYER_NAME)

            if not saved_layer:
                result['error'] = "Не удалось сохранить точечный слой в GeoPackage"
                return result

            # Добавляем в проект
            QgsProject.instance().addMapLayer(saved_layer)

            # Применяем стиль
            self._apply_style(saved_layer)

            # Применяем видимость из Base_layers.json (hidden=1 для L_2_6_3_Т_ГПМТ)
            self._apply_layer_visibility(saved_layer)

            result['success'] = True
            result['layer'] = saved_layer

        except Exception as e:
            result['error'] = str(e)
            log_error(f"M_35: Ошибка создания точечного слоя: {e}")

        return result

    def _create_points_memory_layer(
        self,
        points_data: List[Dict[str, Any]],
        crs
    ) -> Optional[QgsVectorLayer]:
        """
        Создать memory layer с точками нумерации.

        Структура полей:
        - ID: номер точки (глобальный)
        - ID_Точки_контура: номер точки внутри контура
        - Тип_контура: Внешний/Внутренний
        - Номер_контура: параллельная нумерация контуров
        - X, Y: геодезические координаты

        Args:
            points_data: Данные точек от M_20
            crs: Система координат

        Returns:
            QgsVectorLayer или None
        """
        # Создаём поля
        fields = QgsFields()
        fields.append(QgsField("ID", QMetaType.Type.Int))
        fields.append(QgsField("ID_Точки_контура", QMetaType.Type.Int))
        fields.append(QgsField("Тип_контура", QMetaType.Type.QString, len=20))
        fields.append(QgsField("Номер_контура", QMetaType.Type.Int))
        fields.append(QgsField("X", QMetaType.Type.Double))
        fields.append(QgsField("Y", QMetaType.Type.Double))

        # Создаём слой
        layer = QgsMemoryProviderUtils.createMemoryLayer(
            self.GPMT_POINTS_LAYER_NAME,
            fields,
            Qgis.WkbType.MultiPoint,
            crs
        )

        if not layer or not layer.isValid():
            log_error("M_35: Не удалось создать memory layer для точек ГПМТ")
            return None

        # Добавляем точки
        layer.startEditing()

        for data in points_data:
            point = data.get('point')
            if not point:
                continue

            feature = QgsFeature(fields)

            # Геометрия с округлением координат
            geom = QgsGeometry.fromPointXY(point)
            geom = geom.snappedToGrid(COORDINATE_PRECISION, COORDINATE_PRECISION)
            feature.setGeometry(geom)

            # Атрибуты
            feature.setAttributes([
                data.get('id', 0),
                data.get('contour_point_index', 0),
                data.get('contour_type', 'Внешний'),
                data.get('contour_number', 1),
                data.get('x_geodetic', 0.0),
                data.get('y_geodetic', 0.0),
            ])

            layer.addFeature(feature)

        layer.commitChanges()

        log_info(f"M_35: Создан memory layer с {layer.featureCount()} точками")
        return layer
