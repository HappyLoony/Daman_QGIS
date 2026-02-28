# -*- coding: utf-8 -*-
"""
Менеджер управления коллизиями и приоритетами подписей слоёв

Отвечает за:
- Настройку приоритетов подписей
- Управление препятствиями (obstacles)
- Автоматический выбор типа препятствия по стилю слоя
- Настройку Z-Index (порядок отрисовки)
- Конфигурацию глобального движка подписей QGIS

Типы препятствий для полигонов:
- PolygonBoundary: избегать ГРАНИЦ (подписи могут быть внутри)
- PolygonInterior: избегать ВНУТРЕННЕЙ ЧАСТИ (подписи снаружи)
- PolygonWhole: избегать ВСЕГО полигона

Автоматика: если слой без заливки -> PolygonBoundary (кадастровые номера внутри ЗУ)
"""

from typing import Optional
from qgis.core import (
    QgsProject,
    QgsPalLayerSettings,
    QgsLabelObstacleSettings,
    QgsLabelingEngineSettings,
    QgsPropertyCollection,
    QgsProperty,
    QgsVectorLayer,
    Qgis
)
from qgis.PyQt.QtCore import Qt
from Daman_QGIS.utils import log_error, log_info


class CollisionManager:
    """Управление коллизиями и приоритетами подписей"""

    def apply_collision_rules(self, settings: QgsPalLayerSettings,
                              config: dict,
                              layer: Optional[QgsVectorLayer] = None) -> QgsPalLayerSettings:
        """
        Применить правила коллизий к настройкам подписей

        Логика выбора типа препятствия:
        1. Для не-полигонов: стандартные настройки
        2. Для полигонов БЕЗ заливки: PolygonBoundary (подписи могут быть внутри)
        3. Для полигонов С заливкой: PolygonInterior (подписи избегают interior)

        Args:
            settings: Настройки подписей QGIS
            config: Конфигурация из Base_labels.json
            layer: Векторный слой (опционально, для определения стиля)

        Returns:
            Обновлённые настройки подписей

        Example:
            >>> settings = QgsPalLayerSettings()
            >>> config = {'label_priority': 10, 'label_is_obstacle': True}
            >>> settings = collision_manager.apply_collision_rules(settings, config, layer)
        """
        # 1. Приоритет подписей (0-10, где 10=максимальный)
        if 'label_priority' in config:
            properties = settings.dataDefinedProperties()
            if not properties:
                properties = QgsPropertyCollection()

            properties.setProperty(
                QgsPalLayerSettings.Priority,
                QgsProperty.fromValue(config['label_priority'])
            )
            settings.setDataDefinedProperties(properties)

        # 2. Z-Index (порядок отрисовки, выше = рисуется позже)
        if 'label_z_index' in config:
            settings.zIndex = config['label_z_index']

        # 3. Препятствия с автоматическим выбором типа по стилю
        obstacle = QgsLabelObstacleSettings()
        obstacle.setIsObstacle(True)

        is_obstacle = config.get('label_is_obstacle', False)
        is_polygon = self._is_polygon_layer(layer)
        has_fill = self._layer_has_fill(layer) if is_polygon else False

        if is_polygon:
            # Автоматический выбор типа препятствия для полигонов
            obstacle_type, factor = self._get_polygon_obstacle_settings(
                is_obstacle=is_obstacle,
                has_fill=has_fill
            )
            obstacle.setType(obstacle_type)
            obstacle.setFactor(factor)
        else:
            # Для линий и точек - стандартное поведение
            if is_obstacle:
                obstacle.setFactor(2.0)
            else:
                obstacle.setFactor(0.1)

        settings.setObstacleSettings(obstacle)

        return settings

    def _is_polygon_layer(self, layer: Optional[QgsVectorLayer]) -> bool:
        """Проверить является ли слой полигональным"""
        if not layer or not isinstance(layer, QgsVectorLayer):
            return False
        return layer.geometryType() == Qgis.GeometryType.Polygon

    def _layer_has_fill(self, layer: Optional[QgsVectorLayer]) -> bool:
        """
        Определить есть ли у полигонального слоя заливка

        Проверяет фактический стиль рендерера слоя.
        Если brushStyle != NoBrush -> есть заливка/штриховка.

        Args:
            layer: Векторный слой

        Returns:
            True если слой имеет заливку или штриховку
        """
        if not layer:
            return False

        try:
            renderer = layer.renderer()
            if not renderer:
                return False

            symbol = renderer.symbol()
            if not symbol:
                return False

            # Проверяем все symbol layers
            for i in range(symbol.symbolLayerCount()):
                sl = symbol.symbolLayer(i)
                # Проверяем brushStyle для fill symbol layers
                if hasattr(sl, 'brushStyle'):
                    brush_style = sl.brushStyle()
                    if brush_style != Qt.BrushStyle.NoBrush:
                        return True

            return False

        except Exception as e:
            log_error(f"Msm_12_1: Ошибка определения заливки: {str(e)}")
            return False

    def _get_polygon_obstacle_settings(self, is_obstacle: bool,
                                        has_fill: bool) -> tuple:
        """
        Получить тип препятствия и factor для полигона

        Матрица решений:
        | is_obstacle | has_fill | Тип             | Factor | Описание                    |
        |-------------|----------|-----------------|--------|-----------------------------|
        | False       | False    | PolygonBoundary | 0.1    | Минимальный штраф на границы|
        | False       | True     | PolygonInterior | 0.3    | Слабый штраф на interior    |
        | True        | False    | PolygonBoundary | 0.5    | Умеренный штраф на границы  |
        | True        | True     | PolygonInterior | 2.0    | Сильный штраф на interior   |

        Args:
            is_obstacle: Флаг label_is_obstacle из конфига
            has_fill: Есть ли заливка у слоя

        Returns:
            Tuple (obstacle_type, factor)
        """
        if has_fill:
            # С заливкой -> избегать внутренней части
            obstacle_type = QgsLabelObstacleSettings.PolygonInterior
            factor = 2.0 if is_obstacle else 0.3
        else:
            # Без заливки -> избегать только границ (подписи могут быть внутри)
            obstacle_type = QgsLabelObstacleSettings.PolygonBoundary
            factor = 0.5 if is_obstacle else 0.1

        return obstacle_type, factor

    def configure_global_engine(self, iface=None) -> bool:
        """
        Настроить глобальный движок подписей QGIS

        ВАЖНО: Вызывается ОДИН РАЗ при загрузке проекта!
        Эти настройки влияют на ВСЕ подписи в проекте.

        Args:
            iface: Интерфейс QGIS (опционально, не используется сейчас)

        Returns:
            True если настройки успешно применены

        Example:
            >>> collision_manager = CollisionManager()
            >>> collision_manager.configure_global_engine(iface)
        """
        try:
            project = QgsProject.instance()
            engine_settings = QgsLabelingEngineSettings()

            # 1. Улучшенный алгоритм размещения (Version2)
            if hasattr(Qgis, 'LabelPlacementEngineVersion'):
                engine_settings.setPlacementVersion(
                    Qgis.LabelPlacementEngineVersion.Version2
                )

            # 2. Оптимизация размещения
            # Не использовать частичные кандидаты (лучше пропустить чем показать плохо)
            engine_settings.setFlag(
                QgsLabelingEngineSettings.UsePartialCandidates,
                False
            )

            # Не показывать неразмещённые подписи (иначе будут накладываться)
            engine_settings.setFlag(
                QgsLabelingEngineSettings.DrawUnplacedLabels,
                False
            )

            # 3. Увеличиваем количество кандидатов для лучшего размещения
            engine_settings.setMaximumLineCandidatesPerCm(8.0)
            engine_settings.setMaximumPolygonCandidatesPerCmSquared(7.0)

            # Применяем к проекту
            project.setLabelingEngineSettings(engine_settings)
            return True

        except Exception as e:
            log_error(f"Msm_12_1: Ошибка настройки движка коллизий: {str(e)}")
            return False

    def get_collision_info(self, settings: QgsPalLayerSettings) -> dict:
        """
        Получить информацию о настройках коллизий слоя

        Args:
            settings: Настройки подписей

        Returns:
            Словарь с информацией о коллизиях

        Example:
            >>> info = collision_manager.get_collision_info(settings)
            >>> print(f"Приоритет: {info['priority']}")
            >>> print(f"Препятствие: {info['is_obstacle']}")
        """
        # Получаем приоритет
        priority = None
        properties = settings.dataDefinedProperties()
        if properties:
            priority_prop = properties.property(QgsPalLayerSettings.Priority)
            if priority_prop and priority_prop.isActive():
                priority = priority_prop.staticValue()

        # Получаем настройки препятствий
        obstacle_settings = settings.obstacleSettings()
        is_obstacle = obstacle_settings.isObstacle() if obstacle_settings else False
        obstacle_factor = obstacle_settings.factor() if obstacle_settings else 1.0

        return {
            'priority': priority,
            'z_index': settings.zIndex,
            'is_obstacle': is_obstacle,
            'obstacle_factor': obstacle_factor
        }
