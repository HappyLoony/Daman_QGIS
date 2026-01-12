# -*- coding: utf-8 -*-
"""
Модуль проверки точности округления координат до 0.01м (сантиметры)
Для кадастровых работ критична точность координат

ВАЖНО: При работе в background thread необходимо передавать QgsProcessingContext
созданный в main thread, так как processing.run() обращается к iface.mapCanvas()
"""

from typing import List, Dict, Any, Optional
from qgis.core import (
    QgsVectorLayer, QgsPointXY,
    QgsGeometry, QgsFeature, QgsWkbTypes,
    QgsProcessingContext, QgsProcessingFeedback
)
import processing
from Daman_QGIS.managers import CoordinatePrecisionManager as CPM
from Daman_QGIS.constants import COORDINATE_PRECISION, PRECISION_DECIMALS
from Daman_QGIS.utils import log_info

class Fsm_0_4_4_PrecisionChecker:
    """Проверка округления координат"""

    PRECISION = COORDINATE_PRECISION  # Точность в метрах (сантиметры)

    def __init__(self, processing_context: Optional[QgsProcessingContext] = None):
        """
        Args:
            processing_context: QgsProcessingContext созданный в main thread
                               для thread-safe вызовов processing.run()
        """
        self.errors_found = 0
        self.processing_context = processing_context
        self.feedback = QgsProcessingFeedback()

    def check(self, layer: QgsVectorLayer) -> List[Dict[str, Any]]:
        """
        Проверка округления координат до 0.01м

        Args:
            layer: Проверяемый слой

        Returns:
            Список словарей с информацией об ошибках:
            {
                'type': 'precision',
                'geometry': QgsGeometry (точка),
                'feature_id': int,
                'vertex_index': int,
                'description': str,
                'current_coords': (x, y),
                'rounded_coords': (x, y)
            }
        """
        errors = []
        self.errors_found = 0

        # Извлекаем все вершины через processing (с context для thread-safety)
        result = processing.run(
            "native:extractvertices",
            {'INPUT': layer, 'OUTPUT': 'memory:'},
            context=self.processing_context,
            feedback=self.feedback
        )

        vertices_layer = result['OUTPUT']
        field_names = vertices_layer.fields().names()

        for vertex_feat in vertices_layer.getFeatures():
            geom = vertex_feat.geometry()
            if not geom:
                continue

            point = geom.asPoint()
            x, y = point.x(), point.y()

            # Проверяем округление
            x_rounded, y_rounded = CPM.round_coordinates(x, y)

            # Если координаты не округлены до 0.01
            if abs(x - x_rounded) > 0.0001 or abs(y - y_rounded) > 0.0001:
                # Безопасное получение полей
                feature_id = vertex_feat['feature_id'] if 'feature_id' in field_names else vertex_feat.id()
                vertex_index = vertex_feat['vertex_index'] if 'vertex_index' in field_names else 0

                errors.append({
                    'type': 'precision',
                    'geometry': geom,
                    'feature_id': feature_id,
                    'vertex_index': vertex_index,
                    'description': f'Координаты не округлены до 0.01 м: X={x:.6f}, Y={y:.6f}',
                    'current_coords': (x, y),
                    'rounded_coords': (x_rounded, y_rounded)
                })

        self.errors_found = len(errors)

        log_info(f"Fsm_0_4_4: Найдено {self.errors_found} вершин с неокругленными координатами")

        return errors

    def get_errors_count(self) -> int:
        """
        Возвращает количество найденных ошибок точности.

        Returns:
            int: Количество вершин с неокругленными координатами
        """
        return self.errors_found
