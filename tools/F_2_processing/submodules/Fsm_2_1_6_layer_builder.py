# -*- coding: utf-8 -*-
"""
Fsm_2_1_6: Построитель слоёв результата выборки
Создание слоёв, сохранение в GeoPackage, применение стилей
"""

import os
import json
from typing import Optional

from qgis.PyQt.QtCore import QMetaType
from qgis.core import (
    QgsVectorLayer, QgsField, QgsWkbTypes,
    QgsVectorFileWriter, QgsProject
)

from Daman_QGIS.constants import MAX_FIELD_LEN, PROVIDER_OGR, DRIVER_GPKG
from Daman_QGIS.utils import log_info, log_warning, log_error


class Fsm_2_1_6_LayerBuilder:
    """Построитель слоёв результата выборки"""

    def __init__(self, plugin_dir: str):
        """Инициализация

        Args:
            plugin_dir: Путь к директории плагина
        """
        # Используем централизованный путь к справочникам
        from Daman_QGIS.constants import DATA_REFERENCE_PATH
        self.reference_dir = DATA_REFERENCE_PATH

    def create_result_layer(self, source_layer: QgsVectorLayer, layer_name: str,
                           object_type: str = 'ZU', target_crs=None) -> Optional[QgsVectorLayer]:
        """Создание слоя с новой структурой на основе JSON справочника

        Args:
            source_layer: Исходный слой земельных участков или ОКС
            layer_name: Имя создаваемого слоя
            object_type: Тип объекта ('ZU', 'OKS' или 'GENERIC')
            target_crs: Целевая СК для результирующего слоя (если None, берется из source_layer)

        Returns:
            QgsVectorLayer: Созданный слой или None при ошибке
        """
        # Для GENERIC типа используем прямое копирование полей из исходного слоя
        if object_type == 'GENERIC':
            return self._create_generic_result_layer(source_layer, layer_name, target_crs)

        # Выбираем правильный JSON справочник
        if object_type == 'ZU':
            json_filename = 'Base_selection_ZU.json'
        else:
            json_filename = 'Base_selection_OKS.json'

        # Загружаем структуру из JSON (через BaseReferenceLoader для remote)
        try:
            from Daman_QGIS.database.base_reference_loader import BaseReferenceLoader

            loader = BaseReferenceLoader()
            field_definitions = loader._load_json(json_filename)

            if field_definitions is None:
                raise FileNotFoundError(f"{json_filename} не найден ни на remote ни локально")
        except Exception as e:
            log_error(f"Fsm_2_1_6: Не удалось загрузить {json_filename}: {str(e)}")
            raise ValueError(f"Не удалось загрузить структуру полей из {json_filename}")

        # Создаём временный memory слой с геометрией MultiPolygon
        # ВАЖНО: Всегда используем MultiPolygon, так как в selection_engine
        # все геометрии конвертируются в MultiPolygon для совместимости
        # Используем целевую СК (проектную), а не СК исходного слоя
        if target_crs:
            crs_string = target_crs.authid()
        else:
            crs_string = source_layer.crs().authid()

        result_layer = QgsVectorLayer(
            f"MultiPolygon?crs={crs_string}",
            layer_name,
            "memory"
        )

        if not result_layer.isValid():
            log_error(f"Fsm_2_1_6: Не удалось создать memory слой {layer_name}")
            return None

        # Создаем новую структуру полей
        result_layer.startEditing()

        # Добавляем поля из JSON
        for field_def in field_definitions:
            field_name = field_def.get('working_name', '')

            # Пропускаем строку заголовка
            if field_name == 'Имя':
                continue

            # Определяем тип поля из mapinfo_format в JSON
            mapinfo_format = field_def.get('mapinfo_format', '')
            if '(Целое)' in mapinfo_format:
                # Целочисленное поле (Integer)
                result_layer.addAttribute(QgsField(field_name, QMetaType.Type.Int))
            else:
                # Текстовое поле (QString) - по умолчанию для всех остальных
                result_layer.addAttribute(QgsField(field_name, QMetaType.Type.QString, len=MAX_FIELD_LEN))

        result_layer.commitChanges()

        field_count = len([f for f in field_definitions if f.get('working_name') != 'Имя'])
        log_info(f"Fsm_2_1_6: Слой {layer_name} создан с {field_count} полями")

        return result_layer

    def save_layer_to_gpkg(self, layer: QgsVectorLayer, layer_name: str,
                          gpkg_path: str) -> Optional[QgsVectorLayer]:
        """Сохранение слоя в GeoPackage

        Args:
            layer: Слой для сохранения
            layer_name: Имя слоя в GeoPackage
            gpkg_path: Путь к файлу GeoPackage

        Returns:
            QgsVectorLayer: Загруженный из GeoPackage слой или None при ошибке
        """
        if not layer or layer.featureCount() == 0:
            log_info(f"Fsm_2_1_6: Слой {layer_name} пуст - пропускаем сохранение в GeoPackage")
            return None

        log_info(f"Fsm_2_1_6: Сохранение слоя {layer_name} в GeoPackage...")

        # Настройки для сохранения в GeoPackage
        save_options = QgsVectorFileWriter.SaveVectorOptions()
        save_options.driverName = DRIVER_GPKG
        save_options.layerName = layer_name
        save_options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer

        # Сохраняем слой
        error = QgsVectorFileWriter.writeAsVectorFormatV3(
            layer,
            gpkg_path,
            QgsProject.instance().transformContext(),
            save_options
        )

        if error[0] != QgsVectorFileWriter.NoError:
            log_error(f"Fsm_2_1_6: Ошибка сохранения {layer_name} в GeoPackage: {error}")
            # Диагностика проблемы блокировки файла
            import os
            log_error(f"Fsm_2_1_6: Путь к GPKG: {gpkg_path}")
            log_error(f"Fsm_2_1_6: Файл существует: {os.path.exists(gpkg_path)}")
            if os.path.exists(gpkg_path):
                log_error(f"Fsm_2_1_6: Файл доступен для записи: {os.access(gpkg_path, os.W_OK)}")
            log_error(f"Fsm_2_1_6: Возможные причины: файл открыт в другой программе, "
                     "сетевой диск с блокировкой, незакрытое соединение QGIS")
            return None

        log_info(f"Fsm_2_1_6: Слой {layer_name} успешно сохранён в GeoPackage")

        # Загружаем слой из GeoPackage
        uri = f"{gpkg_path}|layername={layer_name}"
        saved_layer = QgsVectorLayer(uri, layer_name, PROVIDER_OGR)

        if not saved_layer.isValid():
            log_error(f"Fsm_2_1_6: Не удалось загрузить слой {layer_name} из GeoPackage")
            return None

        return saved_layer

    def _create_generic_result_layer(self, source_layer: QgsVectorLayer, layer_name: str,
                                      target_crs=None) -> Optional[QgsVectorLayer]:
        """Создание слоя с прямым копированием полей из исходного слоя (без JSON маппинга)

        Используется для слоёв НП, ТерЗоны, Вода где структура полей
        копируется напрямую из WFS источника.

        TODO: Создать Base_selection_NP.json, Base_selection_TerZony.json,
              Base_selection_Voda.json для более точного маппинга полей

        Args:
            source_layer: Исходный WFS слой
            layer_name: Имя создаваемого слоя
            target_crs: Целевая СК для результирующего слоя

        Returns:
            QgsVectorLayer: Созданный слой или None при ошибке
        """
        # Используем целевую СК (проектную), а не СК исходного слоя
        if target_crs:
            crs_string = target_crs.authid()
        else:
            crs_string = source_layer.crs().authid()

        # Создаём временный memory слой с геометрией MultiPolygon
        result_layer = QgsVectorLayer(
            f"MultiPolygon?crs={crs_string}",
            layer_name,
            "memory"
        )

        if not result_layer.isValid():
            log_error(f"Fsm_2_1_6: Не удалось создать memory слой {layer_name}")
            return None

        # Копируем структуру полей из исходного слоя
        result_layer.startEditing()

        for field in source_layer.fields():
            # Копируем поле как есть
            result_layer.addAttribute(QgsField(field))

        result_layer.commitChanges()

        field_count = source_layer.fields().count()
        log_info(f"Fsm_2_1_6: GENERIC слой {layer_name} создан с {field_count} полями (копия из {source_layer.name()})")

        return result_layer
