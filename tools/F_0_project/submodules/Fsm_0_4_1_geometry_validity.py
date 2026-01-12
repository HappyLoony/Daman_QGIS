# -*- coding: utf-8 -*-
"""
Модуль проверки валидности геометрии и самопересечений
Использует qgis:checkvalidity и QgsGeometry.validateGeometry()
"""

from typing import List, Dict, Any, Tuple
from qgis.core import (
    QgsVectorLayer, QgsGeometry, QgsPointXY
)
import processing
from Daman_QGIS.utils import log_info, log_warning

class Fsm_0_4_1_GeometryValidityChecker:
    """Проверка валидности геометрии и самопересечений"""

    def __init__(self):
        self.validity_errors_found = 0
        self.self_intersection_errors_found = 0

    def _safe_get_field(self, feature: Any, field_name: str, default: Any = None) -> Any:
        """
        Безопасное получение значения поля из feature

        Args:
            feature: QgsFeature объект
            field_name: Имя поля
            default: Значение по умолчанию

        Returns:
            Значение поля или default
        """
        try:
            if feature.fields().indexOf(field_name) >= 0:
                return feature.get(field_name, default)
            return default
        except (AttributeError, KeyError) as e:
            log_info(f"Fsm_0_4_1: Не удалось получить поле {field_name}: {e}")
            return default

    def check(self, layer: QgsVectorLayer) -> Tuple[List[Dict], List[Dict]]:
        """
        Комплексная проверка валидности

        Returns:
            Tuple из (validity_errors, self_intersection_errors)
        """
        validity_errors = self._check_validity(layer)
        self_int_errors = self._check_self_intersections(layer)

        return validity_errors, self_int_errors
    def _check_validity(self, layer: QgsVectorLayer) -> List[Dict[str, Any]]:
        """
        Проверка валидности через qgis:checkvalidity

        Returns:
            Список ошибок валидности
        """
        errors = []

        result = processing.run("qgis:checkvalidity", {
            'INPUT_LAYER': layer,
            'METHOD': 2,  # GEOS method
            'IGNORE_RING_SELF_INTERSECTION': False,
            'VALID_OUTPUT': 'memory:',
            'INVALID_OUTPUT': 'memory:',
            'ERROR_OUTPUT': 'memory:'
        })

        invalid_layer = result['INVALID_OUTPUT']
        error_layer = result['ERROR_OUTPUT']
        error_count = result['ERROR_COUNT']

        if error_count > 0:
            log_info(f"Fsm_0_4_1: checkvalidity нашел {error_count} ошибок валидности")

        # Парсим error layer (точки с описанием ошибок)
        for error_feat in error_layer.getFeatures():
            geom = error_feat.geometry()
            if not geom:
                continue

            message = self._safe_get_field(error_feat, 'message', 'Неизвестная ошибка валидности')
            translated_message = self._translate_validity_message(message)
            errors.append({
                'type': 'validity',
                'geometry': geom,
                'feature_id': self._safe_get_field(error_feat, 'FID', -1),
                'description': translated_message,
                'error_type': self._classify_error_type(message)
            })

        # Дополнительно парсим invalid layer для получения невалидных геометрий
        for invalid_feat in invalid_layer.getFeatures():
            geom = invalid_feat.geometry()
            if not geom:
                continue

            errors_field = self._safe_get_field(invalid_feat, '_errors', '')

            # Добавляем только если еще не добавлено
            if not any(e['feature_id'] == invalid_feat.id() for e in errors):
                # Безопасное получение точки для невалидной геометрии
                error_geom = geom.centroid()
                if not error_geom or error_geom.isEmpty():
                    # Fallback: используем центр bounding box
                    bbox = geom.boundingBox()
                    if not bbox.isEmpty():
                        error_geom = QgsGeometry.fromPointXY(bbox.center())
                    else:
                        # Последний fallback: используем исходную геометрию
                        error_geom = geom

                translated_errors = self._translate_validity_message(errors_field) if errors_field else ''
                errors.append({
                    'type': 'validity',
                    'geometry': error_geom,
                    'feature_id': invalid_feat.id(),
                    'description': f'Невалидная геометрия: {translated_errors}',
                    'error_type': 'invalid_geometry'
                })

        self.validity_errors_found = len(errors)
        return errors

    def _check_self_intersections(self, layer: QgsVectorLayer) -> List[Dict[str, Any]]:
        """
        Проверка самопересечений через QgsGeometry.validateGeometry()

        Returns:
            Список самопересечений
        """
        errors = []

        for feature in layer.getFeatures():
            geom = feature.geometry()
            if not geom or geom.isEmpty():
                continue

            # Используем validateGeometry для поиска самопересечений
            validation_errors = geom.validateGeometry()

            for val_error in validation_errors:
                error_msg = val_error.what().lower()

                # Фильтруем только самопересечения
                if 'self' in error_msg and 'intersection' in error_msg:
                    # Безопасное получение геометрии ошибки
                    error_geom = val_error.where() if val_error.where() else None
                    if not error_geom:
                        # Fallback 1: centroid
                        error_geom = geom.centroid()
                        if not error_geom or error_geom.isEmpty():
                            # Fallback 2: центр bounding box
                            bbox = geom.boundingBox()
                            if not bbox.isEmpty():
                                error_geom = QgsGeometry.fromPointXY(bbox.center())
                            else:
                                # Fallback 3: исходная геометрия
                                error_geom = geom

                    translated_error = self._translate_validity_message(val_error.what())
                    errors.append({
                        'type': 'self_intersection',
                        'geometry': error_geom,
                        'feature_id': feature.id(),
                        'description': f'Самопересечение: {translated_error}',
                        'error_detail': val_error.what()
                    })

        self.self_intersection_errors_found = len(errors)

        if self.self_intersection_errors_found > 0:
            log_info(f"Fsm_0_4_1: Найдено {self.self_intersection_errors_found} самопересечений")

        return errors

    def _classify_error_type(self, message: str) -> str:
        """Классификация типа ошибки по сообщению"""
        msg_lower = message.lower()

        if 'ring self' in msg_lower or 'self-intersection' in msg_lower:
            return 'ring_self_intersection'
        elif 'duplicate' in msg_lower and 'ring' in msg_lower:
            return 'duplicate_rings'
        elif 'hole' in msg_lower:
            return 'hole_error'
        elif 'segment' in msg_lower:
            return 'segment_error'
        else:
            return 'unknown_validity_error'

    def _translate_validity_message(self, message: str) -> str:
        """
        Перевод сообщений об ошибках валидности с английского на русский.

        Args:
            message: Исходное сообщение (обычно на английском от GEOS)

        Returns:
            Переведённое сообщение на русском
        """
        if not message:
            return message

        # Словарь переводов типичных сообщений GEOS
        translations = {
            # Самопересечения
            'ring self-intersection': 'самопересечение кольца',
            'self-intersection': 'самопересечение',
            'self intersection': 'самопересечение',
            # Кольца и дырки
            'duplicate rings': 'дублирующиеся кольца',
            'ring': 'кольцо',
            'hole': 'дырка (внутренний контур)',
            'hole lies outside shell': 'дырка находится за пределами внешнего контура',
            'holes are nested': 'вложенные дырки',
            # Сегменты
            'segment': 'сегмент',
            'too few points in geometry component': 'недостаточно точек в компоненте геометрии',
            # Общие
            'invalid': 'невалидный',
            'geometry': 'геометрия',
            'at or near point': 'в точке или около',
            'at point': 'в точке',
            'near point': 'около точки',
        }

        result = message.lower()

        # Заменяем известные фразы
        for eng, rus in translations.items():
            result = result.replace(eng, rus)

        return result

    def get_errors_count(self) -> Tuple[int, int]:
        """Возвращает (validity_errors, self_intersection_errors)"""
        return self.validity_errors_found, self.self_intersection_errors_found
