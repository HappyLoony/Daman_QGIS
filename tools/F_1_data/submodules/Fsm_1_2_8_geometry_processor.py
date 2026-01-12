# -*- coding: utf-8 -*-
"""
Субмодуль F_1_2: Обработка геометрии
Преобразование геометрии и сохранение в GeoPackage
"""

import os
from typing import Optional
import processing

from qgis.core import (
    QgsVectorLayer, QgsProject, QgsWkbTypes,
    QgsFeature, QgsVectorFileWriter
)

from Daman_QGIS.utils import log_info, log_warning, log_error, log_success
from Daman_QGIS.constants import DRIVER_GPKG, PROVIDER_OGR


class Fsm_1_2_8_GeometryProcessor:
    """Обработчик геометрии для F_1_2"""

    def __init__(self, iface):
        """
        Инициализация обработчика геометрии

        Args:
            iface: Интерфейс QGIS
        """
        self.iface = iface

    def convert_polygon_to_line(self, polygon_layer: QgsVectorLayer, target_layer_name: str) -> Optional[QgsVectorLayer]:
        """Преобразует полигональный слой в линейный (границы полигонов)

        Использует алгоритм processing для извлечения границ полигонов.
        Временный слой автоматически удаляется после копирования данных.

        Args:
            polygon_layer: Полигональный слой для преобразования
            target_layer_name: Имя целевого линейного слоя

        Returns:
            QgsVectorLayer: Линейный слой с границами или None при ошибке
        """
        try:
            log_info(f"Fsm_1_2_8: Преобразование полигонов в линии для {target_layer_name}...")

            # Проверяем что это действительно полигональный слой
            if polygon_layer.geometryType() not in [QgsWkbTypes.PolygonGeometry]:
                log_error(f"Fsm_1_2_8: Слой {polygon_layer.name()} не является полигональным")
                return None

            # Используем processing.run для преобразования полигонов в линии
            result = processing.run("native:polygonstolines", {
                'INPUT': polygon_layer,
                'OUTPUT': 'memory:'  # Создаем временный memory слой
            })

            temp_line_layer = result['OUTPUT']

            if not temp_line_layer or temp_line_layer.featureCount() == 0:
                log_warning(f"Fsm_1_2_8: Не удалось преобразовать полигоны в линии для {target_layer_name}")
                return None

            # Создаем целевой линейный слой в памяти
            crs = polygon_layer.crs().authid()
            line_layer = QgsVectorLayer(f"LineString?crs={crs}", target_layer_name, "memory")
            line_provider = line_layer.dataProvider()

            # Копируем структуру полей из временного слоя
            line_provider.addAttributes(temp_line_layer.fields().toList())
            line_layer.updateFields()

            # Копируем фичи из временного слоя в целевой
            features_to_add = []
            for feature in temp_line_layer.getFeatures():
                new_feature = QgsFeature(line_layer.fields())
                new_feature.setGeometry(feature.geometry())
                new_feature.setAttributes(feature.attributes())
                features_to_add.append(new_feature)

            line_provider.addFeatures(features_to_add)
            line_layer.updateExtents()

            log_success(f"Fsm_1_2_8: Преобразовано {len(features_to_add)} полигонов в линии для {target_layer_name}")

            # Временный слой (temp_line_layer) будет автоматически удален Python GC
            # так как это memory слой и мы не добавляем его в проект

            return line_layer

        except Exception as e:
            log_error(f"Fsm_1_2_8: Ошибка при преобразовании полигонов в линии: {e}")
            return None

    def save_to_geopackage(self, layer: QgsVectorLayer, gpkg_path: str, layer_name: str) -> Optional[QgsVectorLayer]:
        """Сохранение временного слоя в GeoPackage

        Args:
            layer: Временный векторный слой
            gpkg_path: Путь к GeoPackage
            layer_name: Имя слоя

        Returns:
            QgsVectorLayer: Сохранённый слой или None
        """
        try:
            # ВАЖНО: Удаляем существующий слой из GeoPackage перед перезаписью
            # Это гарантирует, что старые данные с конфликтующими fid будут полностью удалены
            if os.path.exists(gpkg_path):
                try:
                    from osgeo import ogr
                    ds = ogr.Open(gpkg_path, 1)  # 1 = update mode
                    if ds:
                        # Ищем и удаляем слой по имени
                        for i in range(ds.GetLayerCount()):
                            lyr = ds.GetLayerByIndex(i)
                            if lyr and lyr.GetName() == layer_name:
                                ds.DeleteLayer(i)
                                break
                        ds = None  # Закрываем датасет
                except Exception as e:
                    log_warning(f"Fsm_1_2_8: Не удалось удалить существующий слой {layer_name}: {str(e)}")

            options = QgsVectorFileWriter.SaveVectorOptions()
            options.driverName = DRIVER_GPKG
            options.layerName = layer_name

            # ВАЖНО: Не сохраняем FID из исходного слоя!
            # Это предотвращает конфликты UNIQUE constraint при объединении подслоёв
            # GeoPackage автоматически создаст новые последовательные fid
            options.datasourceOptions = ['FID=']  # Пустое значение = не сохранять fid

            if os.path.exists(gpkg_path):
                options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer
            else:
                options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteFile

            error = QgsVectorFileWriter.writeAsVectorFormatV3(
                layer,
                gpkg_path,
                QgsProject.instance().transformContext(),
                options
            )

            if error[0] == QgsVectorFileWriter.NoError:
                saved_layer = QgsVectorLayer(
                    f"{gpkg_path}|layername={layer_name}",
                    layer_name,
                    PROVIDER_OGR
                )

                if saved_layer.isValid():
                    return saved_layer
                else:
                    log_warning(f"Fsm_1_2_8: Не удалось загрузить сохранённый слой {layer_name}")
            else:
                log_warning(f"Fsm_1_2_8: Ошибка сохранения слоя {layer_name}: {error[1]}")

        except Exception as e:
            log_warning(f"Fsm_1_2_8: Ошибка сохранения в GeoPackage: {str(e)}")

        return None
