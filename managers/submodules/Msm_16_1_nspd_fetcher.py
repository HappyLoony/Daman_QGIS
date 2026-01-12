# -*- coding: utf-8 -*-
"""
Msm_16_1_NspdFetcher - Загрузка геометрии объектов из НСПД по кадастровому номеру

Использует API v2/search/geoportal для поиска объектов по КН.
Поддерживает ЗУ и ОКС (Здания, Сооружения, ОНС).
"""

import json
from typing import Optional, Dict, List, Tuple, Any
from dataclasses import dataclass

import requests
import urllib3

from qgis.core import (
    QgsProject, QgsVectorLayer, QgsFeature, QgsGeometry,
    QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsFields
)
from qgis.PyQt.QtCore import QVariant

from Daman_QGIS.utils import log_info, log_warning, log_error

# Отключаем предупреждения о SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


@dataclass
class NspdSearchResult:
    """Результат поиска в НСПД"""
    cadnum: str
    geometry: Optional[QgsGeometry]
    attributes: Dict[str, Any]
    object_type: str  # 'ZU', 'OKS_building', 'OKS_construction', 'OKS_ons', 'unknown'
    target_layer_name: str
    error: Optional[str] = None


class Msm_16_1_NspdFetcher:
    """Загрузчик геометрии объектов из НСПД API"""

    # API endpoint для поиска
    API_URL = "https://nspd.gov.ru/api/geoportal/v2/search/geoportal"
    
    # thematicSearchId для разных типов объектов
    THEMATIC_ID_REALTY = 1  # Объекты недвижимости (ЗУ + ОКС)
    
    # Заголовки запроса
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/119.0",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://nspd.gov.ru/map"
    }
    
    # Маппинг типов объектов на целевые слои
    LAYER_MAPPING = {
        'ZU': 'L_1_2_1_WFS_ЗУ',
        'OKS_building': 'L_1_2_4_WFS_ОКС_Здания',
        'OKS_construction': 'L_1_2_4_WFS_ОКС_Сооружения',
        'OKS_ons': 'L_1_2_4_WFS_ОКС_ОНС',
        'unknown': 'L_1_2_1_WFS_ЗУ'  # По умолчанию - ЗУ
    }
    
    # Ключевые слова для определения типа ОКС
    OKS_KEYWORDS = {
        'OKS_building': ['здание', 'жилой дом', 'многоквартирный', 'нежилое'],
        'OKS_construction': ['сооружение', 'линейный объект', 'трубопровод', 'дорога'],
        'OKS_ons': ['незавершенн', 'строительств']
    }
    
    # Таймаут запроса (секунды)
    TIMEOUT = 15
    MAX_RETRIES = 3

    def __init__(self):
        """Инициализация загрузчика"""
        log_info("Msm_16_1_NspdFetcher: Инициализация")

    def fetch_by_cadnum(self, cadnum: str) -> NspdSearchResult:
        """
        Загрузить геометрию объекта по кадастровому номеру
        
        Args:
            cadnum: Кадастровый номер (формат XX:XX:XXXXXXX:XXX)
            
        Returns:
            NspdSearchResult: Результат поиска
        """
        log_info(f"Msm_16_1_NspdFetcher: Поиск КН {cadnum}")
        
        # Убираем пробелы
        cadnum = cadnum.strip().replace(' ', '')
        
        # Формируем URL
        url = f"{self.API_URL}?query={cadnum}&thematicSearchId={self.THEMATIC_ID_REALTY}"
        
        # Пробуем запрос с retry
        for attempt in range(self.MAX_RETRIES):
            try:
                response = requests.get(
                    url,
                    headers=self.HEADERS,
                    timeout=self.TIMEOUT,
                    verify=False  # Сертификаты Минцифры
                )
                
                if response.status_code != 200:
                    log_warning(f"Msm_16_1_NspdFetcher: HTTP {response.status_code} для КН {cadnum}")
                    continue
                
                data = response.json()
                return self._parse_response(cadnum, data)
                
            except requests.exceptions.SSLError as e:
                log_warning(f"Msm_16_1_NspdFetcher: SSL ошибка (попытка {attempt + 1}): {str(e)}")
                continue
            except requests.exceptions.ConnectionError as e:
                log_warning(f"Msm_16_1_NspdFetcher: Ошибка соединения (попытка {attempt + 1}): {str(e)}")
                continue
            except requests.exceptions.Timeout:
                log_warning(f"Msm_16_1_NspdFetcher: Таймаут (попытка {attempt + 1})")
                continue
            except json.JSONDecodeError as e:
                log_error(f"Msm_16_1_NspdFetcher: Ошибка парсинга JSON: {str(e)}")
                return NspdSearchResult(
                    cadnum=cadnum,
                    geometry=None,
                    attributes={},
                    object_type='unknown',
                    target_layer_name='',
                    error="Ошибка парсинга ответа сервера"
                )
            except Exception as e:
                log_error(f"Msm_16_1_NspdFetcher: Неизвестная ошибка: {str(e)}")
                return NspdSearchResult(
                    cadnum=cadnum,
                    geometry=None,
                    attributes={},
                    object_type='unknown',
                    target_layer_name='',
                    error=f"Ошибка: {str(e)}"
                )
        
        # Все попытки исчерпаны
        return NspdSearchResult(
            cadnum=cadnum,
            geometry=None,
            attributes={},
            object_type='unknown',
            target_layer_name='',
            error="Превышено количество попыток подключения к НСПД"
        )

    def _parse_response(self, cadnum: str, data: dict) -> NspdSearchResult:
        """
        Парсинг ответа API
        
        Args:
            cadnum: Кадастровый номер
            data: JSON ответ API
            
        Returns:
            NspdSearchResult: Результат парсинга
        """
        # Проверяем структуру ответа
        if 'data' not in data:
            error_msg = data.get('message', 'Неизвестная ошибка')
            log_warning(f"Msm_16_1_NspdFetcher: Ошибка API для КН {cadnum}: {error_msg}")
            return NspdSearchResult(
                cadnum=cadnum,
                geometry=None,
                attributes={},
                object_type='unknown',
                target_layer_name='',
                error=f"Ошибка API: {error_msg}"
            )
        
        features = data.get('data', {}).get('features', [])
        
        if not features:
            log_info(f"Msm_16_1_NspdFetcher: Объект не найден в НСПД: {cadnum}")
            return NspdSearchResult(
                cadnum=cadnum,
                geometry=None,
                attributes={},
                object_type='unknown',
                target_layer_name='',
                error="Объект не найден в НСПД"
            )
        
        # Берём первый feature
        feature = features[0]
        geometry_data = feature.get('geometry', {})
        properties = feature.get('properties', {})
        
        # Проверяем тип геометрии
        geom_type = geometry_data.get('type', '')
        if geom_type == 'Point':
            log_warning(f"Msm_16_1_NspdFetcher: КН {cadnum} - только точка (без границ)")
            return NspdSearchResult(
                cadnum=cadnum,
                geometry=None,
                attributes=properties,
                object_type='unknown',
                target_layer_name='',
                error="Объект без координат границ (только точка)"
            )
        
        # Создаём геометрию QGIS из GeoJSON
        try:
            geom_json = json.dumps(geometry_data)
            geometry = QgsGeometry.fromJson(geom_json)
            
            if not geometry or geometry.isEmpty():
                log_warning(f"Msm_16_1_NspdFetcher: Пустая геометрия для КН {cadnum}")
                return NspdSearchResult(
                    cadnum=cadnum,
                    geometry=None,
                    attributes=properties,
                    object_type='unknown',
                    target_layer_name='',
                    error="Не удалось создать геометрию"
                )
        except Exception as e:
            log_error(f"Msm_16_1_NspdFetcher: Ошибка создания геометрии: {str(e)}")
            return NspdSearchResult(
                cadnum=cadnum,
                geometry=None,
                attributes=properties,
                object_type='unknown',
                target_layer_name='',
                error=f"Ошибка геометрии: {str(e)}"
            )
        
        # Определяем тип объекта
        object_type = self._determine_object_type(properties)
        target_layer = self.LAYER_MAPPING.get(object_type, self.LAYER_MAPPING['unknown'])
        
        log_info(f"Msm_16_1_NspdFetcher: КН {cadnum} - тип {object_type}, слой {target_layer}")
        
        return NspdSearchResult(
            cadnum=cadnum,
            geometry=geometry,
            attributes=properties,
            object_type=object_type,
            target_layer_name=target_layer,
            error=None
        )

    def _determine_object_type(self, properties: dict) -> str:
        """
        Определить тип объекта по атрибутам
        
        Args:
            properties: Атрибуты объекта
            
        Returns:
            str: Тип объекта ('ZU', 'OKS_building', 'OKS_construction', 'OKS_ons', 'unknown')
        """
        # Проверяем наличие характерных полей
        
        # Категория земель - признак ЗУ
        if properties.get('category') or properties.get('land_category'):
            return 'ZU'
        
        # Назначение/тип - признак ОКС
        oks_type = (
            properties.get('purpose', '') or 
            properties.get('type_oks', '') or 
            properties.get('name', '') or
            properties.get('type', '')
        ).lower()
        
        # Проверяем ключевые слова для типов ОКС
        for obj_type, keywords in self.OKS_KEYWORDS.items():
            for keyword in keywords:
                if keyword in oks_type:
                    return obj_type
        
        # Если есть любое из полей ОКС
        if properties.get('purpose') or properties.get('floors') or properties.get('year_built'):
            return 'OKS_building'  # По умолчанию - здание
        
        # По умолчанию считаем ЗУ
        return 'ZU'

    def fetch_multiple(self, cadnums: List[str]) -> List[NspdSearchResult]:
        """
        Загрузить геометрию для списка кадастровых номеров
        
        Args:
            cadnums: Список кадастровых номеров
            
        Returns:
            List[NspdSearchResult]: Список результатов
        """
        results = []
        for cadnum in cadnums:
            result = self.fetch_by_cadnum(cadnum)
            results.append(result)
        return results

    def add_to_layer(self, result: NspdSearchResult) -> Tuple[bool, str]:
        """
        Добавить объект в соответствующий слой проекта
        
        Args:
            result: Результат поиска из НСПД
            
        Returns:
            Tuple[bool, str]: (успех, сообщение)
        """
        if result.error or not result.geometry:
            return False, result.error or "Нет геометрии"
        
        # Ищем целевой слой
        target_layer = None
        for layer in QgsProject.instance().mapLayers().values():
            if isinstance(layer, QgsVectorLayer) and layer.name() == result.target_layer_name:
                target_layer = layer
                break
        
        if not target_layer:
            msg = f"Слой {result.target_layer_name} не найден в проекте"
            log_warning(f"Msm_16_1_NspdFetcher: {msg}")
            return False, msg
        
        # Проверяем, не дубликат ли
        field_name = self._get_cadnum_field(target_layer)
        if field_name:
            existing = list(target_layer.getFeatures(f'"{field_name}" = \'{result.cadnum}\''))
            if existing:
                msg = f"КН {result.cadnum} уже существует в слое"
                log_info(f"Msm_16_1_NspdFetcher: {msg}")
                return False, msg
        
        # Трансформируем геометрию из EPSG:3857 в CRS слоя
        geometry = QgsGeometry(result.geometry)  # Копия, чтобы не модифицировать оригинал
        source_crs = QgsCoordinateReferenceSystem("EPSG:3857")
        target_crs = target_layer.crs()
        
        if source_crs != target_crs:
            transform = QgsCoordinateTransform(source_crs, target_crs, QgsProject.instance())
            geometry.transform(transform)
            log_info(f"Msm_16_1_NspdFetcher: Трансформация из EPSG:3857 в {target_crs.authid()}")
        
        # Создаём feature
        feature = QgsFeature(target_layer.fields())
        feature.setGeometry(geometry)
        
        # Заполняем атрибуты
        self._populate_attributes(feature, result, target_layer)
        
        # Добавляем в слой
        try:
            target_layer.startEditing()
            success = target_layer.addFeature(feature)
            if success:
                target_layer.commitChanges()
                log_info(f"Msm_16_1_NspdFetcher: КН {result.cadnum} добавлен в {target_layer.name()}")
                return True, f"Добавлен в слой {target_layer.name()}"
            else:
                target_layer.rollBack()
                return False, "Ошибка добавления объекта"
        except Exception as e:
            target_layer.rollBack()
            log_error(f"Msm_16_1_NspdFetcher: Ошибка записи: {str(e)}")
            return False, f"Ошибка записи: {str(e)}"

    def _get_cadnum_field(self, layer: QgsVectorLayer) -> Optional[str]:
        """Получить имя поля кадастрового номера в слое"""
        if layer.fields().indexFromName('cad_num') >= 0:
            return 'cad_num'
        elif layer.fields().indexFromName('cad_number') >= 0:
            return 'cad_number'
        return None

    def _populate_attributes(self, feature: QgsFeature, result: NspdSearchResult, 
                            layer: QgsVectorLayer) -> None:
        """
        Заполнить атрибуты feature из результата НСПД
        
        Args:
            feature: QgsFeature для заполнения
            result: Результат поиска
            layer: Целевой слой
        """
        fields = layer.fields()
        props = result.attributes
        
        # Маппинг полей НСПД -> полей слоя
        field_mapping = {
            'cad_num': ['cadastralNumber', 'cadNumber', 'cad_number', 'cadnum'],
            'cad_number': ['cadastralNumber', 'cadNumber', 'cad_num', 'cadnum'],
            'address': ['address', 'addressNote'],
            'area': ['area', 'areaValue'],
            'category': ['category', 'land_category'],
            'permitted_use': ['permittedUse', 'permitted_use', 'utilizationCode'],
            'status': ['status', 'state'],
            'cost': ['cost', 'cadastralCost'],
            'name': ['name', 'objectName'],
            'purpose': ['purpose', 'assignation'],
            'floors': ['floors', 'floorsCount'],
            'year_built': ['yearBuilt', 'year_built', 'creationYear']
        }
        
        for field_idx in range(fields.count()):
            field_name = fields.field(field_idx).name()
            
            # Пробуем найти соответствующее поле в данных НСПД
            if field_name in field_mapping:
                for nspd_field in field_mapping[field_name]:
                    if nspd_field in props and props[nspd_field]:
                        feature.setAttribute(field_idx, props[nspd_field])
                        break
            elif field_name in props:
                feature.setAttribute(field_idx, props[field_name])
        
        # Обязательно устанавливаем кадастровый номер
        cadnum_field = self._get_cadnum_field(layer)
        if cadnum_field:
            idx = fields.indexFromName(cadnum_field)
            if idx >= 0:
                feature.setAttribute(idx, result.cadnum)
