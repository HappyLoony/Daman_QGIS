# -*- coding: utf-8 -*-
"""
F_2_4_GPMT - Формирование границ проекта межевания территории

Объединение всех слоев ЗПР в единый полигон ГПМТ
"""

import os
from typing import List, Optional
from qgis.PyQt.QtWidgets import QMessageBox
from qgis.PyQt.QtCore import QMetaType
from qgis.core import (
    QgsProject, Qgis,
    QgsVectorLayer, QgsFeature, QgsGeometry,
    QgsField, QgsWkbTypes, QgsVectorFileWriter,
    QgsLayerTreeGroup, QgsCoordinateReferenceSystem,
    QgsPointXY, QgsMemoryProviderUtils, QgsFields
)
from qgis import processing

from Daman_QGIS.core.base_tool import BaseTool
from Daman_QGIS.utils import log_info, log_warning, log_error, log_success


class F_2_4_GPMT(BaseTool):
    """Инструмент формирования границ проекта межевания территории"""

    def __init__(self, iface):
        """
        Инициализация инструмента

        Args:
            iface: Интерфейс QGIS
        """
        super().__init__(iface)

    @property
    def name(self):
        """Имя инструмента"""
        return "2_4_ГПМТ"

    def get_name(self):
        """Получить имя инструмента"""
        return "F_2_4_ГПМТ"
    def run(self):
        """Запуск инструмента"""
        # Автоматическая очистка слоев перед выполнением
        self.auto_cleanup_layers()

        # Проверяем наличие проекта
        if not self.check_project_opened():
            return

        # Находим все слои ЗПР
        zpr_layers = self._find_zpr_layers()

        if not zpr_layers:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Предупреждение",
                "Нужен импорт ЗПР.\nНе найдено ни одного слоя ЗПР в проекте."
            )
            return

        log_info(f"F_2_4_GPMT: Найдено слоев ЗПР: {len(zpr_layers)}")

        # Объединяем слои
        merged_layer = self._merge_zpr_layers(zpr_layers)

        if not merged_layer:
            QMessageBox.critical(
                self.iface.mainWindow(),
                "Ошибка",
                "Не удалось объединить слои ЗПР"
            )
            return

        # Создаем финальный слой с атрибутами
        final_layer = self._create_gpmt_layer(merged_layer)

        if not final_layer:
            QMessageBox.critical(
                self.iface.mainWindow(),
                "Ошибка",
                "Не удалось создать слой ГПМТ"
            )
            return

        # Сохраняем в GeoPackage
        saved_layer = self._save_to_gpkg(final_layer)

        if not saved_layer:
            QMessageBox.critical(
                self.iface.mainWindow(),
                "Ошибка",
                "Не удалось сохранить слой в GeoPackage"
            )
            return

        # Организуем в группы
        self._organize_in_groups(saved_layer)

        # Применяем стиль
        self._apply_style(saved_layer)

        # КРИТИЧЕСКИ ВАЖНО: Сортируем ВСЕ слои после добавления нового слоя
        if hasattr(self, 'layer_manager') and self.layer_manager:
            log_info("F_2_4: Сортировка всех слоёв по order_layers из Base_layers.json")
            self.layer_manager.sort_all_layers()
            log_info("F_2_4: Слои отсортированы по order_layers")

        # Масштабируем к слою
        self.iface.setActiveLayer(saved_layer)
        self.iface.zoomToActiveLayer()

        # Показываем результат
        area_sqm = 0
        for feature in saved_layer.getFeatures():
            area_sqm = feature["area_sqm"]
            break

        area_ha = area_sqm / 10000.0 if area_sqm else 0

        QMessageBox.information(
            self.iface.mainWindow(),
            "Успешно",
            f"Создан слой ГПМТ\n"
            f"Площадь: {area_sqm} кв.м ({area_ha:.2f} га)"
        )

        log_success(f"F_2_4_GPMT: Успешно создан слой L_2_5_1_ГПМТ, площадь {area_sqm} кв.м")
    
    
    def _find_zpr_layers(self) -> List[QgsVectorLayer]:
        """
        Поиск всех слоев ЗПР в проекте
        
        Returns:
            Список слоев ЗПР
        """
        zpr_layers = []
        project = QgsProject.instance()
        
        # Ищем все слои, начинающиеся с 2_3_1_ или 2_3_2_
        for layer_id, layer in project.mapLayers().items():
            if isinstance(layer, QgsVectorLayer) and layer.isValid():
                layer_name = layer.name()
                
                # Проверяем префиксы
                if layer_name.startswith("L_2_3_") or layer_name.startswith("L_2_4_"):
                    # Проверяем что слой не пустой
                    if layer.featureCount() > 0:
                        zpr_layers.append(layer)
                        log_info(f"F_2_4_GPMT: Найден слой ЗПР: {layer_name} ({layer.featureCount()} объектов)")
        
        return zpr_layers
    
    def _merge_zpr_layers(self, layers: List[QgsVectorLayer]) -> Optional[QgsVectorLayer]:
        """
        Объединение слоев ЗПР в один с сохранением внутренних контуров (дырок)

        Args:
            layers: Список слоев для объединения

        Returns:
            Объединенный слой или None
        """
        log_info(f"F_2_4_GPMT: Объединение {len(layers)} слоев ЗПР с сохранением внутренних контуров")

        try:
            # Сначала проверим наличие внутренних контуров в исходных данных
            source_rings_count = 0
            for layer in layers:
                for feature in layer.getFeatures():
                    geom = feature.geometry()
                    if geom and not geom.isEmpty():
                        # МИГРАЦИЯ POLYGON → MULTIPOLYGON: упрощённый паттерн
                        parts = geom.asMultiPolygon() if geom.isMultipart() else [geom.asPolygon()]

                        for part in parts:
                            if len(part) > 1:
                                source_rings_count += len(part) - 1

            log_info(f"F_2_4_GPMT: В исходных слоях найдено {source_rings_count} внутренних контуров")

            # Используем алгоритм union, который сохраняет внутренние контуры
            if len(layers) == 1:
                # Для одного слоя просто копируем его
                merged_layer = layers[0]
            else:
                # Объединяем слои попарно через union
                current_layer = layers[0]

                for i in range(1, len(layers)):
                    # Union двух слоев
                    result = processing.run(
                        "native:union",
                        {
                            'INPUT': current_layer,
                            'OVERLAY': layers[i],
                            'OVERLAY_FIELDS_PREFIX': '',
                            'OUTPUT': 'TEMPORARY_OUTPUT'
                        }
                    )
                    current_layer = result['OUTPUT']

                merged_layer = current_layer

            # Теперь применяем dissolve БЕЗ удаления внутренних контуров
            # Используем параметр SEPARATE_DISJOINT для сохранения отдельных частей
            result = processing.run(
                "native:dissolve",
                {
                    'INPUT': merged_layer,
                    'FIELD': [],  # Не группируем по полям
                    'SEPARATE_DISJOINT': False,  # Объединяем смежные части
                    'OUTPUT': 'TEMPORARY_OUTPUT'
                }
            )
            final_layer = result['OUTPUT']

        except Exception as e:
            log_warning(f"Ошибка при объединении через processing: {str(e)}")
            log_info("Используем ручное объединение геометрий")

            # Создаем новый слой вручную
            from qgis.core import QgsVectorLayer, QgsFeature, QgsGeometry

            # МИГРАЦИЯ POLYGON → MULTIPOLYGON: временный слой
            final_layer = QgsVectorLayer("MultiPolygon?crs=" + layers[0].crs().authid(), "merged", "memory")
            provider = final_layer.dataProvider()

            # Собираем все геометрии
            all_geoms = []
            for layer in layers:
                for feature in layer.getFeatures():
                    geom = feature.geometry()
                    if geom and not geom.isEmpty():
                        all_geoms.append(geom)

            # Объединяем геометрии
            if all_geoms:
                combined = QgsGeometry.unaryUnion(all_geoms)
                feat = QgsFeature()
                feat.setGeometry(combined)
                provider.addFeatures([feat])
                final_layer.updateExtents()

        if not final_layer or not final_layer.isValid():
            raise ValueError("Не удалось объединить слои")

        # Логируем информацию о результате
        feature_count = final_layer.featureCount()
        if feature_count > 0:
            for feature in final_layer.getFeatures():
                geometry = feature.geometry()
                if geometry and not geometry.isEmpty():
                    parts_count = 0
                    rings_count = 0

                    # Проверяем тип геометрии и считаем внутренние контуры
                    # МИГРАЦИЯ POLYGON → MULTIPOLYGON: упрощённый паттерн
                    multi_polygon = geometry.asMultiPolygon() if geometry.isMultipart() else [geometry.asPolygon()]
                    parts_count = len(multi_polygon)

                    for polygon_part in multi_polygon:
                        # Каждая часть - это список колец
                        # Первое кольцо - внешний контур, остальные - внутренние
                        if len(polygon_part) > 1:
                            rings_count += len(polygon_part) - 1

                    log_info(f"F_2_4_GPMT: Результат объединения: {parts_count} частей, {rings_count} внутренних контуров")
                    break

        return final_layer
    def _create_gpmt_layer(self, source_layer: QgsVectorLayer) -> Optional[QgsVectorLayer]:
        """
        Создание финального слоя ГПМТ с правильными атрибутами

        Args:
            source_layer: Исходный объединенный слой

        Returns:
            Финальный слой или None
        """
        # Создаем новый слой с нужными атрибутами
        fields = QgsFields()
        fields.append(QgsField("contour_num", QMetaType.Type.Int))
        fields.append(QgsField("area_sqm", QMetaType.Type.Int))

        # Определяем тип геометрии
        wkb_type = source_layer.wkbType()
        if QgsWkbTypes.isSingleType(wkb_type):
            # Преобразуем в Multi тип для совместимости
            if QgsWkbTypes.geometryType(wkb_type) == QgsWkbTypes.PolygonGeometry:
                wkb_type = QgsWkbTypes.MultiPolygon

        # Создаем слой
        crs = source_layer.crs()
        final_layer = QgsMemoryProviderUtils.createMemoryLayer(
            "L_2_5_1_ГПМТ",
            fields,
            wkb_type,
            crs
        )

        if not final_layer or not final_layer.isValid():
            raise ValueError("Не удалось создать финальный слой")

        # Добавляем объект с атрибутами
        final_layer.startEditing()

        # Обычно после dissolve получается один объект
        # Но может быть MultiPolygon с несвязанными частями
        for feature in source_layer.getFeatures():
            geometry = feature.geometry()

            if not geometry or geometry.isEmpty():
                continue

            # Создаем новый объект БЕЗ старых атрибутов
            # Важно: используем конструктор без аргументов и затем устанавливаем поля
            new_feature = QgsFeature()
            new_feature.setFields(fields)
            new_feature.initAttributes(fields.count())  # Инициализируем атрибуты

            # Копируем ТОЛЬКО геометрию, без атрибутов
            new_feature.setGeometry(QgsGeometry(geometry))  # Создаем копию геометрии

            # Устанавливаем ТОЛЬКО наши атрибуты
            new_feature.setAttribute(0, 1)  # contour_num = 1

            # Вычисляем площадь на плоскости
            area = geometry.area()
            new_feature.setAttribute(1, int(round(area)))  # area_sqm

            final_layer.addFeature(new_feature)

            log_info(f"F_2_4_GPMT: Площадь ГПМТ: {int(round(area))} кв.м")

            # Обычно только один объект после dissolve
            break

        final_layer.commitChanges()

        return final_layer
    def _save_to_gpkg(self, layer: QgsVectorLayer) -> Optional[QgsVectorLayer]:
        """
        Сохранение слоя в GeoPackage проекта

        Args:
            layer: Слой для сохранения

        Returns:
            Сохраненный слой из GeoPackage или None
        """
        from Daman_QGIS.managers.M_19_project_structure_manager import get_project_structure_manager
        project = QgsProject.instance()
        project_path = project.homePath()
        structure_manager = get_project_structure_manager()
        structure_manager.project_root = project_path
        gpkg_path = structure_manager.get_gpkg_path(create=False)

        if not gpkg_path or not os.path.exists(gpkg_path):
            log_error("F_2_4: GeoPackage не найден")
            return None

        layer_name = "L_2_5_1_ГПМТ"

        # Сохраняем в GeoPackage
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GPKG"
        options.layerName = layer_name
        # Заменяем существующий слой
        options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer

        error = QgsVectorFileWriter.writeAsVectorFormatV3(
            layer,
            gpkg_path,
            project.transformContext(),
            options
        )

        if error[0] == QgsVectorFileWriter.NoError:
            log_info(f"F_2_4_GPMT: Слой сохранен в GeoPackage: {layer_name}")

            # Загружаем слой из GeoPackage
            gpkg_layer = QgsVectorLayer(
                f"{gpkg_path}|layername={layer_name}",
                layer_name,
                "ogr"
            )

            if gpkg_layer.isValid():
                return gpkg_layer
            else:
                raise ValueError("Не удалось загрузить слой из GeoPackage")
        else:
            raise ValueError(f"Ошибка сохранения в GeoPackage: {error[1]}")
    def _organize_in_groups(self, layer: QgsVectorLayer):
        """
        Организация слоя в группы дерева слоев

        Args:
            layer: Слой для добавления
        """
        project = QgsProject.instance()
        root = project.layerTreeRoot()

        # Находим или создаем группу "L_2_Обработка"
        main_group = None
        for child in root.children():
            if isinstance(child, QgsLayerTreeGroup) and child.name() == "L_2_Обработка":
                main_group = child
                break

        if not main_group:
            main_group = root.addGroup("L_2_Обработка")
            log_info("F_2_4_GPMT: Создана группа L_2_Обработка")

        # Находим или создаем подгруппу "L_2_5_ГПМТ"
        sub_group = None
        for child in main_group.children():
            if isinstance(child, QgsLayerTreeGroup) and child.name() == "L_2_5_ГПМТ":
                sub_group = child
                break

        if not sub_group:
            sub_group = main_group.addGroup("L_2_5_ГПМТ")
            log_info("F_2_4_GPMT: Создана подгруппа L_2_5_ГПМТ")

        # Добавляем слой в подгруппу
        project.addMapLayer(layer, False)
        sub_group.addLayer(layer)

        log_info("F_2_4_GPMT: Слой добавлен в группу L_2_5_ГПМТ")
    def _apply_style(self, layer: QgsVectorLayer):
        """
        Применение стиля к слою из базы данных Base_layers.json

        Args:
            layer: Слой для стилизации
        """
        # Стиль применяется из базы данных Base_layers.json
        from Daman_QGIS.managers import StyleManager, LayerManager
        from Daman_QGIS.constants import PLUGIN_NAME

        style_manager = StyleManager()
        style_manager.apply_qgis_style(layer, layer.name())

        log_info("F_2_4_GPMT: Применен стиль из Base_layers.json")
